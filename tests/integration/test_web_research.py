"""Web research + owner settings against a real migrated database."""

import hashlib
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.service import BriefInput, BriefService
from app.core.config import Environment, Settings
from app.db.session import Database
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.domain import SourceType
from app.knowledge.file_import import FileImportError, import_web_resource
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.knowledge.structure.domain import StructureNodeType
from app.knowledge.structure.models import SourceStructureNode
from app.knowledge.units.domain import KnowledgeUnitType
from app.knowledge.units.models import KnowledgeUnit
from app.ops.settings.service import StudioSettingsService
from app.topics.service import TopicService
from app.web_research.domain import IngestedWebSource, WebResearchReport
from app.web_research.gap_fill import GapAssessment, GapFillService
from app.web_research.service import GapResearchOutcome

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


@pytest.fixture
def web_db(tmp_path: Path) -> Iterator[tuple[Database, Settings]]:
    """Disposable migrated database plus matching Settings object."""

    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = (
        make_url(base_url.replace("postgresql+psycopg://", "postgresql://", 1))
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(url),
        storage_root=tmp_path / "storage",
    )
    database = Database(url)
    try:
        yield database, settings
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


_PAGE_TEXT = " ".join(["Substantial paragraph of research content."] * 30)


class TestSettingsService:
    async def test_env_defaults_when_no_overrides(self, web_db) -> None:
        database, settings = web_db
        service = StudioSettingsService(database, settings)
        effective = await service.effective()
        assert effective["web_research_enabled"] is False
        # Retrieval defaults to a real URL backend; the APIMaster LLM
        # answer path was demoted — it cannot supply verifiable URLs.
        assert effective["web_research_provider"] == "tavily"
        assert effective["target_duration_default_minutes"] == 27.5
        assert effective["units_per_video_minute"] == 1.5

    async def test_set_many_coerces_and_overrides(self, web_db) -> None:
        database, settings = web_db
        service = StudioSettingsService(database, settings)
        await service.set_many(
            {
                "web_research_enabled": "on",
                "web_research_max_results": "7",
                "units_per_video_minute": "2.5",
                "web_research_api_key": "sk-secret-1234",
            }
        )
        effective = await service.effective()
        assert effective["web_research_enabled"] is True
        assert effective["web_research_max_results"] == 7
        assert effective["units_per_video_minute"] == 2.5
        assert effective["web_research_api_key"] == "sk-secret-1234"

    async def test_none_removes_override(self, web_db) -> None:
        database, settings = web_db
        service = StudioSettingsService(database, settings)
        await service.set_many({"web_research_max_results": 9})
        await service.set_many({"web_research_max_results": None})
        effective = await service.effective()
        assert effective["web_research_max_results"] == 5

    async def test_unknown_key_rejected(self, web_db) -> None:
        database, settings = web_db
        service = StudioSettingsService(database, settings)
        with pytest.raises(ValueError, match="Unknown setting"):
            await service.set_many({"llm_provider": "openai"})


class TestImportWebResource:
    async def test_creates_webpage_source_with_real_segments(self, web_db) -> None:
        database, _ = web_db
        source_id, created = await import_web_resource(
            database,
            url="https://example.com/article",
            title="Example article",
            text=_PAGE_TEXT,
            provider="apimaster",
            query="test query",
            answer_text="synthesized answer must not be evidence",
            schedule=False,
        )
        assert created is True
        async with database.transaction() as session:
            source = await session.get(Source, source_id)
            assert source is not None
            assert source.source_type == SourceType.WEBPAGE
            assert source.platform == "web"
            assert source.canonical_url == "https://example.com/article"
            assert source.raw_metadata["research_query"] == "test query"
            version = await session.scalar(
                select(SourceVersion).where(SourceVersion.source_id == source_id)
            )
            assert version is not None
            assert version.provider_metadata["fetched_url"] == (
                "https://example.com/article"
            )
            segments = list(
                (
                    await session.scalars(
                        select(SourceSegment).where(
                            SourceSegment.source_version_id == version.id
                        )
                    )
                ).all()
            )
            assert segments
            combined = " ".join(seg.raw_text for seg in segments)
            assert "Substantial paragraph" in combined
            # The synthesized answer stays in metadata, never in segments.
            assert "synthesized answer must not be evidence" not in combined

    async def test_dedupes_on_canonical_url(self, web_db) -> None:
        database, _ = web_db
        first_id, created = await import_web_resource(
            database,
            url="https://example.com/dup",
            title="A",
            text=_PAGE_TEXT,
            provider="tavily",
            schedule=False,
        )
        second_id, created_again = await import_web_resource(
            database,
            url="https://example.com/dup",
            title="A again",
            text=_PAGE_TEXT,
            provider="tavily",
            schedule=False,
        )
        assert created is True
        assert created_again is False
        assert first_id == second_id

    async def test_rejects_non_http_url(self, web_db) -> None:
        database, _ = web_db
        with pytest.raises(FileImportError):
            await import_web_resource(
                database,
                url="file:///etc/passwd",
                title="x",
                text=_PAGE_TEXT,
                provider="custom",
                schedule=False,
            )


class _StubResearch:
    """Records queries and returns a prepared outcome per call."""

    def __init__(self, outcome: GapResearchOutcome, *, enabled: bool = True) -> None:
        self.outcome = outcome
        self._enabled = enabled
        self.queries: list[str] = []
        self.kinds: list[tuple[object, str]] = []

    async def enabled(self) -> bool:
        return self._enabled

    async def research_and_ingest(
        self,
        query: str,
        *,
        context: str = "",
        channel_ids=(),
        language: str = "en",
        schedule: bool = True,
        content_brief_id=None,
        trigger: str = "manual",
        round_number=None,
        query_kind: str = "",
    ) -> GapResearchOutcome:
        self.queries.append(query)
        self.kinds.append((round_number, query_kind))
        return self.outcome


async def _candidate_and_brief(database: Database, *, duration: int = 22):
    channels = await EditorialChannelService(database).seed_channels()
    channel = channels[0]
    strategies = await EditorialChannelService(database).list_strategies(channel.id)
    active = next(s for s in strategies if s.status.value == "ACTIVE")
    candidate = await TopicService(database).create_manual(
        channel.id,
        active.id,
        question="Why do humans procrastinate?",
        thesis="Procrastination is emotion regulation failure.",
    )
    brief = await BriefService(database).create_for_candidate(
        candidate.id,
        BriefInput(
            question="Why do humans procrastinate?",
            thesis="Procrastination is emotion regulation failure.",
            target_duration_minutes=duration,
        ),
    )
    return channel, candidate, brief


async def _units_for_source(
    database: Database, source_id: UUID, count: int
) -> list[UUID]:
    """Create minimal units so gap/link logic has material to count."""

    async with database.transaction() as session:
        version = await session.scalar(
            select(SourceVersion).where(SourceVersion.source_id == source_id)
        )
        segments = list(
            (
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.source_version_id == version.id)
                    .order_by(SourceSegment.sequence)
                )
            ).all()
        )
        node = SourceStructureNode(
            source_version_id=version.id,
            level=1,
            ordinal=1,
            node_type=StructureNodeType.TOPIC,
            title="fixture node",
            summary="fixture",
            start_segment_id=segments[0].id,
            end_segment_id=segments[-1].id,
            start_seconds=Decimal(0),
            end_seconds=Decimal(1),
        )
        session.add(node)
        await session.flush()
        unit_ids: list[UUID] = []
        for index in range(count):
            unit = KnowledgeUnit(
                source_version_id=version.id,
                structure_node_id=node.id,
                unit_type=KnowledgeUnitType.CLAIM,
                title=f"unit {index}",
                summary=f"summary {index}",
                full_text=f"full text {index}",
                start_segment_id=segments[0].id,
                end_segment_id=segments[-1].id,
                content_hash=hashlib.sha256(f"u{index}{uuid4()}".encode()).hexdigest(),
                extraction_version="fixture",
            )
            session.add(unit)
            await session.flush()
            unit_ids.append(unit.id)
        return unit_ids


class TestGapFill:
    async def test_assess_reports_gap_without_units(self, web_db) -> None:
        database, _ = web_db
        _, _, brief = await _candidate_and_brief(database)
        assessment = await GapFillService(database).assess(brief.id)
        assert assessment.units_available == 0
        assert assessment.units_required == 33  # ceil(22 * 1.5)
        assert assessment.has_gap is True

    async def test_disabled_research_skips_with_reason(self, web_db) -> None:
        database, _ = web_db
        _, _, brief = await _candidate_and_brief(database)
        stub = _StubResearch(GapResearchOutcome(), enabled=False)
        outcome = await GapFillService(database, research=stub).fill_gap(brief.id)
        assert outcome.ran is False
        assert outcome.skipped_reason == "web_research_disabled"
        assert stub.queries == []

    async def test_sufficient_material_skips_research(self, web_db) -> None:
        database, _ = web_db
        _, candidate, brief = await _candidate_and_brief(database, duration=1)
        source_id, _ = await import_web_resource(
            database,
            url="https://research.example/enough",
            title="Enough material",
            text=_PAGE_TEXT,
            provider="custom",
            schedule=False,
        )
        await _units_for_source(database, source_id, 3)
        await GapFillService(database)._link_units(candidate.id, [source_id])
        stub = _StubResearch(GapResearchOutcome(), enabled=True)
        outcome = await GapFillService(database, research=stub).fill_gap(brief.id)
        # duration=1 → ceil(1 * 1.5) = 2 required; 3 linked → no gap.
        assert outcome.skipped_reason == "material_sufficient"
        assert outcome.ran is False
        assert stub.queries == []

    async def test_fill_runs_queries_and_ingests(self, web_db) -> None:
        database, _ = web_db
        _, candidate, brief = await _candidate_and_brief(database)
        source_id, _ = await import_web_resource(
            database,
            url="https://research.example/procrastination",
            title="Procrastination study",
            text=_PAGE_TEXT,
            provider="custom",
            schedule=False,
        )
        stub_outcome = GapResearchOutcome(
            report=WebResearchReport(provider="custom", query="q", findings=[]),
            ingested=[
                IngestedWebSource(
                    url="https://research.example/procrastination",
                    source_id=str(source_id),
                    status="ingested",
                )
            ],
        )
        stub = _StubResearch(stub_outcome, enabled=True)
        outcome = await GapFillService(database, research=stub).fill_gap(
            brief.id, process_inline=False
        )
        assert outcome.ran is True
        assert stub.queries[0] == "Why do humans procrastinate?"
        assert any("counterevidence" in q.lower() for q in stub.queries)
        assert outcome.ingested[0].source_id == str(source_id)
        # §28/29: the plan covers falsification + alternative explanations,
        # not only confirming phrasing; rounds are numbered for provenance.
        kinds = {kind for _round, kind in stub.kinds}
        assert "falsification" in kinds
        assert "alternative_explanation" in kinds
        assert stub.kinds[0][0] == 1
        # Without inline processing no units link → the gap never closes
        # and the loop runs the full 3-round cap, then persists the gap.
        assert outcome.rounds_completed == 3
        assert outcome.remaining_gaps

    async def test_coverage_loop_stops_when_gap_closes(self, web_db) -> None:
        """§33: once grounding suffices, later rounds never fire."""

        database, _ = web_db
        _, _, brief = await _candidate_and_brief(database, duration=1)

        class _ClosingService(GapFillService):
            """Gap open on entry, closed after round 1."""

            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.assess_calls = 0

            async def assess(self, brief_id) -> GapAssessment:
                self.assess_calls += 1
                if self.assess_calls == 1:
                    return GapAssessment(0, 2, 1.0)
                return GapAssessment(5, 2, 1.0)

        stub = _StubResearch(
            GapResearchOutcome(
                report=WebResearchReport(provider="custom", query="q", findings=[])
            ),
            enabled=True,
        )
        service = _ClosingService(database, research=stub)
        outcome = await service.fill_gap(brief.id, process_inline=False)
        assert outcome.ran is True
        assert outcome.rounds_completed == 1
        assert outcome.remaining_gaps == []
        assert {round_ for round_, _kind in stub.kinds} == {1}

    async def test_link_units_grounds_candidate_on_new_sources(self, web_db) -> None:
        database, _ = web_db
        _, candidate, brief = await _candidate_and_brief(database)
        source_id, _ = await import_web_resource(
            database,
            url="https://research.example/units",
            title="Units source",
            text=_PAGE_TEXT,
            provider="custom",
            schedule=False,
        )
        await _units_for_source(database, source_id, 3)
        linked = await GapFillService(database)._link_units(candidate.id, [source_id])
        assert linked == 3
        # Idempotent: second call links nothing new.
        assert (
            await GapFillService(database)._link_units(candidate.id, [source_id]) == 0
        )

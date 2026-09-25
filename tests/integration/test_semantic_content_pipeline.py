"""Database integration for transcript -> semantic tree -> long-form generation."""

import json
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url

from alembic import command
from app.db.session import Database
from app.knowledge.adapters.base import ExternalSourceSnapshot, TranscriptEntry
from app.knowledge.domain import SourceType
from app.knowledge.extraction_schema import WindowExtraction
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.models import SourceSegment
from app.retrieval.domain import QueryLanguage
from app.semantic_content.generation import AutomatedContentService
from app.semantic_content.ingestion import SemanticKnowledgePipeline
from app.semantic_content.models import (
    GeneratedContentProject,
    SemanticNode,
    SemanticStructureRun,
)
from app.semantic_content.schemas import (
    CoherenceReportSpec,
    ContentOutlineSpec,
    EvidenceReference,
    GenerateContentRequest,
    GenerationPlanSpec,
    GlobalOutline,
    GlobalOutlineNode,
    LocalOutline,
    LocalOutlineNode,
    OutlineSectionSpec,
    ResearchQuerySpec,
    SectionDraftSpec,
    SynthesisCluster,
    SynthesisSpec,
)

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _url_for_database(url: str, database: str) -> str:
    parsed: URL = make_url(url)
    return parsed.set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def semantic_database_url() -> Iterator[str]:
    base_url = _database_url()
    database_name = f"emtedad_semantic_{uuid4().hex}"
    admin_url = _sync_url(_url_for_database(base_url, "postgres"))
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    test_url = _url_for_database(base_url, database_name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


class _Adapter:
    async def acquire(self, _locator: str) -> ExternalSourceSnapshot:
        texts = (
            "آگاهی با دریافت تفاوت در محیط آغاز می‌شود.",
            "تجربه فقط دریافت نیست و در حافظه باقی می‌ماند.",
            "وقتی موجود به وضعیت خود توجه می‌کند پرسش خودآگاهی پدیدار می‌شود.",
            "دیگری می‌تواند آینه‌ای برای دیدن خود باشد.",
            "زبان تجربه را به روایت تبدیل می‌کند.",
            "روایت شخصی همیشه با خود تجربه یکسان نیست.",
            "گذشته بر شیوه تفسیر اکنون اثر می‌گذارد.",
            "پس خودآگاهی فرایندی باز و وابسته به رابطه و تجربه است.",
        )
        return ExternalSourceSnapshot(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id="semantic-pilot",
            canonical_url="https://www.youtube.com/watch?v=semantic-pilot",
            title="Semantic Pilot",
            description="integration fixture",
            language="fa",
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            duration_seconds=80,
            channel_external_id="semantic-channel",
            channel_title="Semantic Channel",
            channel_url="https://youtube.com/channel/semantic-channel",
            creator_name="Fixture Speaker",
            transcript_kind="manual",
            metadata={"fixture": True},
            transcript=tuple(
                TranscriptEntry(index, (index - 1) * 10.0, 9.0, text)
                for index, text in enumerate(texts, start=1)
            ),
            thumbnail_url=None,
        )


class _FailOnceProvider(_Provider):
    """Fail the first global merge to verify a persisted failed run can retry."""

    def __init__(self) -> None:
        self.failed_once = False

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        if (
            request.task == "semantic-transcript-global-tree"
            and not self.failed_once
        ):
            self.failed_once = True
            raise RuntimeError("fixture semantic merge failure")
        return await super().extract(request)


class _EmbeddingProvider:
    provider_name = "fixture"
    model_name = "fixture-e5"
    revision = "1"
    dimensions = 3

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        size = max(len(text), 1)
        return [
            min(text.count("آگاهی") / size + 0.2, 1.0),
            min(text.count("تجربه") / size + 0.3, 1.0),
            0.5,
        ]


class _Provider:
    name = "fixture-llm"

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        if request.task == "external-knowledge-extraction":
            return WindowExtraction(mentions=[], claims=[])
        if request.task == "semantic-transcript-window":
            return LocalOutline(
                nodes=[
                    LocalOutlineNode(
                        title="آگاهی و تجربه",
                        summary="حرکت از دریافت محیط به تجربه.",
                        main_idea="آگاهی در تجربه و حافظه گسترش می‌یابد.",
                        start_sequence=1,
                        end_sequence=4,
                    ),
                    LocalOutlineNode(
                        title="روایت و خودآگاهی",
                        summary="نقش زبان، گذشته و رابطه.",
                        main_idea="خودآگاهی از رابطه و روایت جدا نیست.",
                        start_sequence=5,
                        end_sequence=8,
                    ),
                ]
            )
        if request.task == "semantic-transcript-global-tree":
            return GlobalOutline(
                title="ساختار سخنرانی آزمایشی",
                sections=[
                    GlobalOutlineNode(
                        title="آگاهی",
                        summary="از دریافت تا توجه به خود.",
                        main_idea="تجربه و دیگری به خودآگاهی شکل می‌دهند.",
                        start_sequence=1,
                        end_sequence=4,
                        children=[
                            GlobalOutlineNode(
                                title="تجربه",
                                summary="تجربه در حافظه می‌ماند.",
                                main_idea="دریافت صرف با تجربه یکی نیست.",
                                start_sequence=1,
                                end_sequence=2,
                            ),
                            GlobalOutlineNode(
                                title="دیگری",
                                summary="دیگری امکان دیدن خود را فراهم می‌کند.",
                                main_idea="خودآگاهی رابطه‌ای است.",
                                start_sequence=3,
                                end_sequence=4,
                            ),
                        ],
                    ),
                    GlobalOutlineNode(
                        title="روایت",
                        summary="زبان و گذشته در روایت خود وارد می‌شوند.",
                        main_idea="روایت، تجربه را تفسیر می‌کند.",
                        start_sequence=5,
                        end_sequence=8,
                        children=[
                            GlobalOutlineNode(
                                title="زبان",
                                summary="زبان تجربه را روایت می‌کند.",
                                main_idea="روایت عین تجربه نیست.",
                                start_sequence=5,
                                end_sequence=6,
                            ),
                            GlobalOutlineNode(
                                title="گذشته",
                                summary="گذشته در تفسیر اکنون حضور دارد.",
                                main_idea="خودآگاهی فرایندی باز است.",
                                start_sequence=7,
                                end_sequence=8,
                            ),
                        ],
                    ),
                ],
            )
        if request.task == "long-form-content-research-plan":
            return GenerationPlanSpec(
                central_question="خودآگاهی چگونه در تجربه و رابطه شکل می‌گیرد؟",
                thesis_direction="از آگاهی ساده به روایت خود حرکت کن.",
                research_queries=[
                    ResearchQuerySpec(query="آگاهی تجربه", purpose="تعریف آغاز"),
                    ResearchQuerySpec(query="دیگری خودآگاهی", purpose="نقش رابطه"),
                    ResearchQuerySpec(query="زبان روایت گذشته", purpose="نقش روایت"),
                ],
                must_cover=["آگاهی", "دیگری", "روایت"],
            )
        if request.task == "long-form-content-knowledge-synthesis":
            payload = json.loads(request.input_text)
            candidates = payload["evidence_candidates"]
            first = candidates[0]
            reference = EvidenceReference(
                candidate_id=first["candidate_id"],
                source_id=first["source_id"],
                source_version_id=first["source_version_id"],
                source_title=first["source_title"],
                source_url=first["source_url"],
                timestamp_start=first["timestamp_start"],
                timestamp_end=first["timestamp_end"],
                chunk_id=first["chunk_id"],
                semantic_root_path=first["semantic_root_path"],
                semantic_hit_path=first["semantic_hit_path"],
            )
            return SynthesisSpec(
                clusters=[
                    SynthesisCluster(
                        cluster_id="C1",
                        title="آگاهی، رابطه و روایت",
                        core_idea="خودآگاهی در پیوند تجربه، دیگری و روایت فهم می‌شود.",
                        supporting_points=[
                            "تجربه در حافظه می‌ماند.",
                            "دیگری در دیدن خود نقش دارد.",
                            "روایت عین تجربه نیست.",
                        ],
                        references=[reference],
                    )
                ],
                repeated_ideas_removed=["تکرار تعریف آگاهی"],
            )
        if request.task == "long-form-content-architecture":
            return ContentOutlineSpec(
                title="خودآگاهی در امتداد تجربه",
                opening_intent="از تفاوت آگاهی و خودآگاهی شروع کن.",
                sections=[
                    OutlineSectionSpec(
                        title="از آگاهی تا تجربه",
                        purpose="مبنای بحث را روشن کن.",
                        cluster_ids=["C1"],
                        target_word_count=330,
                    ),
                    OutlineSectionSpec(
                        title="دیگری و دیدن خود",
                        purpose="بعد رابطه‌ای را توضیح بده.",
                        transition_from_previous="از تجربه به رابطه برو.",
                        cluster_ids=["C1"],
                        target_word_count=330,
                    ),
                    OutlineSectionSpec(
                        title="زبان، گذشته و روایت",
                        purpose="نشان بده روایت چگونه شکل می‌گیرد.",
                        transition_from_previous="از رابطه به روایت برو.",
                        cluster_ids=["C1"],
                        target_word_count=340,
                    ),
                ],
                conclusion_intent="پرسش را باز اما روشن جمع‌بندی کن.",
            )
        if request.task == "long-form-content-section-writer":
            payload = json.loads(request.input_text)
            title = payload["section"]["title"]
            return SectionDraftSpec(
                text=f"{title}: این بخش بر اساس شواهد بازیابی‌شده توضیح داده می‌شود.",
                claims_used=[title],
                concepts_defined=[title],
            )
        if request.task == "long-form-content-coherence-audit":
            return CoherenceReportSpec(
                issues=[],
                strengths_to_preserve=["پیوستگی سه بخش"],
            )
        raise AssertionError(f"unexpected task: {request.task}")


@pytest.mark.asyncio
async def test_failed_semantic_run_is_retried_in_place(
    semantic_database_url: str,
) -> None:
    database = Database(semantic_database_url)
    provider = _FailOnceProvider()
    embedding = _EmbeddingProvider()
    pipeline = SemanticKnowledgePipeline(
        database,
        _Adapter(),
        provider,
        embedding,
        extraction_window_size=8,
        extraction_overlap=0,
        semantic_overlap_segments=0,
    )
    try:
        with pytest.raises(RuntimeError, match="fixture semantic merge failure"):
            await pipeline.ingest("semantic-pilot")

        prepared = await pipeline.ingest("semantic-pilot")
        assert prepared.semantic_node_count == 6

        async with database.transaction() as session:
            run_count = int(
                await session.scalar(select(func.count(SemanticStructureRun.id))) or 0
            )
            run = await session.scalar(select(SemanticStructureRun))
            node_count = int(
                await session.scalar(select(func.count(SemanticNode.id))) or 0
            )
        assert run_count == 1
        assert run is not None
        assert run.status == "SUCCEEDED"
        assert node_count == 6
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_semantic_ingestion_and_generation_preserve_source_data(
    semantic_database_url: str,
) -> None:
    database = Database(semantic_database_url)
    provider = _Provider()
    embedding = _EmbeddingProvider()
    try:
        pipeline = SemanticKnowledgePipeline(
            database,
            _Adapter(),
            provider,
            embedding,
            extraction_window_size=8,
            extraction_overlap=0,
            semantic_overlap_segments=0,
        )
        prepared = await pipeline.ingest("semantic-pilot")
        backfilled = await pipeline.backfill_existing()

        assert backfilled.attempted_source_versions == 1
        assert backfilled.succeeded_source_versions == 1
        assert backfilled.failed_source_version_ids == ()
        assert backfilled.chunking_run_id == prepared.chunking_run_id
        assert backfilled.embedding_model_id == prepared.embedding_model_id

        async with database.transaction() as session:
            source_segment_count_before = int(
                await session.scalar(select(func.count(SourceSegment.id))) or 0
            )
            semantic_node_count = int(
                await session.scalar(select(func.count(SemanticNode.id))) or 0
            )
        assert source_segment_count_before == 8
        assert semantic_node_count == 6
        assert prepared.semantic_node_count == 6

        generated = await AutomatedContentService(
            database,
            embedding,
            provider,
        ).generate(
            GenerateContentRequest(
                topic="خودآگاهی چگونه شکل می‌گیرد؟",
                language=QueryLanguage.FA,
                chunking_run_id=prepared.chunking_run_id,
                embedding_model_id=prepared.embedding_model_id,
                target_duration_seconds=600,
                words_per_minute=100,
            )
        )

        assert generated.status == "READY"
        assert generated.provenance_complete is True
        assert len(generated.sections) == 3
        assert generated.final_script is not None
        async with database.transaction() as session:
            stored = await session.get(GeneratedContentProject, generated.id)
            assert stored is not None
            evidence = stored.retrieval_snapshot["evidence"]
            assert isinstance(evidence, list) and evidence
            first_evidence = evidence[0]
            assert isinstance(first_evidence, dict)
            semantic_family = first_evidence["semantic_family"]
            assert isinstance(semantic_family, list)
            assert len(semantic_family) >= 3
            assert first_evidence["semantic_hit_path"] is not None
            assert first_evidence["semantic_root_path"] in {"1", "2"}
            source_segment_count_after = int(
                await session.scalar(select(func.count(SourceSegment.id))) or 0
            )
        assert source_segment_count_after == source_segment_count_before
    finally:
        await database.dispose()

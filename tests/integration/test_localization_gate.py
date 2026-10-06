"""Owner-approval gate + semantic package + native pipeline integration.

Proves: localization cannot start from a READY master alone, the shared
semantic package only derives from the owner-approved Persian primary
draft, source changes stale dependent runs, and the native pipeline
persists truthful stages to a READY_FOR_VOICE localized draft.
"""

import json
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.models import ContentBrief
from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
from app.content_engine.review import ScriptService
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.lecture.domain import PublicationLanguage
from app.lecture.generic_service import GenericMasterService
from app.localization.domain import LocalizationPipelineStage
from app.localization.gate import require_approved_persian_draft
from app.localization.models import LocalizationPipelineRun
from app.localization.native_pipeline import NativeLocalizationPipeline
from app.localization.semantic_package import SemanticPackageService
from app.localization.service import LocalizationService
from tests.integration.test_final_duration_gate import (
    _draft_with_completed_review,
)
from tests.integration.test_stage_truth import _draft_pipeline
from tests.integration.test_studio_ui import _database_url
from tests.integration.test_topics import _Provider

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
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
    try:
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


async def _approved_fa_draft(
    database: Database, brief: ContentBrief, words: int = 2992, chain: int = 2
) -> ScriptDraft:
    draft = await _draft_with_completed_review(
        database, brief, language="fa", words=words, version=chain, chain=chain
    )
    return await ScriptService(database, provider=_Provider()).approve_draft(
        draft.id, approved_by="owner"
    )


@pytest.mark.asyncio
async def test_localization_requires_approved_persian_draft(
    migrated_database_url: str,
) -> None:
    """A READY master alone is NOT sufficient — §26 gate."""

    database = Database(migrated_database_url)
    try:
        brief, _scripts, _draft = await _draft_pipeline(database, _Provider())
        master = await GenericMasterService(database).latest_ready_for_brief(brief.id)
        assert master is not None
        with pytest.raises(GateBlockedError, match="LOCALIZATION_GATE"):
            await LocalizationService(database).create(
                master.id, PublicationLanguage.EN
            )
        with pytest.raises(GateBlockedError, match="LOCALIZATION_GATE"):
            await require_approved_persian_draft(database, brief.id)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_semantic_package_only_from_approved_persian(
    migrated_database_url: str,
) -> None:
    """Package creation rejects unapproved, non-Persian, and stale drafts."""

    database = Database(migrated_database_url)
    try:
        brief, _scripts, _draft = await _draft_pipeline(database, _Provider())
        service = SemanticPackageService(database, provider=_Provider())
        # Unapproved Persian draft → blocked.
        unapproved = await _draft_with_completed_review(
            database, brief, language="fa", words=100, version=2, chain=2
        )
        with pytest.raises(GateBlockedError, match="LOCALIZATION_GATE"):
            await service.create_for_draft(unapproved.id)
        # English draft → blocked regardless of status.
        with pytest.raises(GateBlockedError, match="primary"):
            await service.create_for_draft(_draft.id)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_package_and_native_pipeline_end_to_end(
    migrated_database_url: str,
) -> None:
    """Approved fa → package → DE run through every persisted stage."""

    database = Database(migrated_database_url)
    try:
        provider = _PipelineProvider()
        brief, _scripts, _draft = await _draft_pipeline(database, provider)
        fa = await _approved_fa_draft(database, brief)
        package = await SemanticPackageService(
            database, provider=provider
        ).create_for_draft(fa.id)
        assert package.source_draft_hash == fa.content_hash

        pipeline = NativeLocalizationPipeline(
            database, provider_for=lambda role: provider
        )
        run = await pipeline.start(package.id, PublicationLanguage.DE)
        run = await pipeline.coverage_translate(run.id)
        assert run.stage is LocalizationPipelineStage.COVERAGE_TRANSLATED
        run = await pipeline.native_draft(run.id)
        assert run.stage is LocalizationPipelineStage.NATIVE_DRAFTED
        assert run.script_draft_id is not None
        await pipeline.review(run.id)
        run = await pipeline.premium_final(run.id)
        assert run.stage is LocalizationPipelineStage.FINAL_FIDELITY
        run = await pipeline.finalize(run.id)
        assert run.stage is LocalizationPipelineStage.READY_FOR_VOICE
        assert run.fidelity_status == "PASSED"

        async with database.transaction() as session:
            localized = await session.get(ScriptDraft, run.script_draft_id)
            assert localized is not None
            assert localized.language == "de"
            assert localized.lineage == "localized"
            assert localized.status is DraftStatus.DRAFT
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_staleness_invalidates_runs(
    migrated_database_url: str,
) -> None:
    """Approving a newer Persian draft makes the package stale."""

    database = Database(migrated_database_url)
    try:
        provider = _PipelineProvider()
        brief, _scripts, _draft = await _draft_pipeline(database, provider)
        fa_v1 = await _approved_fa_draft(database, brief)
        service = SemanticPackageService(database, provider=provider)
        package = await service.create_for_draft(fa_v1.id)
        pipeline = NativeLocalizationPipeline(
            database, provider_for=lambda role: provider
        )
        run = await pipeline.start(package.id, PublicationLanguage.EN)
        # A newer Persian approval makes v1's package stale.
        await _approved_fa_draft(database, brief, chain=3)
        swept = await service.staleness_sweep(package.id)
        assert swept == 1
        async with database.transaction() as session:
            refreshed = await session.get(LocalizationPipelineRun, run.id)
            assert refreshed is not None
            assert refreshed.stage is LocalizationPipelineStage.STALE_SOURCE
        # Package creation from the stale draft is also refused.
        with pytest.raises(GateBlockedError, match="STALE_SOURCE"):
            await service.create_for_draft(fa_v1.id)
    finally:
        await database.dispose()


class _PipelineProvider(_Provider):
    """Stub provider covering every pipeline task deterministically."""

    async def extract(self, request):  # type: ignore[no-untyped-def]
        task = request.task
        if task == "localization_semantic_package":
            payload = json.loads(request.input_text)
            claims = (payload.get("master_export") or {}).get("claims") or []
            return request.output_model.model_validate(
                {
                    "thesis": "Thesis.",
                    "conclusion": "Conclusion.",
                    "claim_ledger": [
                        {
                            "claim_id": c["id"],
                            "semantic_proposition": "p",
                            "epistemic_status": c.get("epistemic_status")
                            or "SUPPORTED",
                            "argument_role": "main",
                        }
                        for c in claims
                    ],
                }
            )
        if task in (
            "localization_coverage_translation",
            "localization_final_edit",
            "localization_targeted_correction",
        ):
            # DE contract: 25–30 min at 130 wpm → 3250–3900 words; every
            # stage draft must sit in-band or the deterministic duration
            # finding inside review() honestly blocks the run.
            words = 3650
            sentence = " ".join(
                f"Ein deutSCHER Satz Nummer {i} mit Varianz."
                for i in range(max(1, words // 7))
            )
            return request.output_model.model_validate({"text": sentence})
        if task in (
            "localization_native_reconstruction",
            "localization_narrative_edit",
        ):
            # Sectioned writer contract (§13): exactly one entry per
            # section_id the caller's section_budgets demand — the total
            # must sit inside the DE 25–30 min band (3250–3900 words).
            payload = json.loads(request.input_text)
            budgets = payload.get("section_budgets") or [
                {"section_id": "s01", "target_words": 3650}
            ]
            per = max(40, 3650 // len(budgets))
            sentence = " ".join(
                f"Ein deutscher Satz Nummer {i} mit Varianz."
                for i in range(max(1, per // 7))
            )
            return request.output_model.model_validate(
                {
                    "sections": [
                        {"section_id": b["section_id"], "text": sentence}
                        for b in budgets
                    ]
                }
            )
        if task.startswith(
            (
                "localization_section_patch",
                "localization_global_patch",
                "localization_length_",
            )
        ):
            return request.output_model.model_validate({"patches": []})
        if task in (
            "localization_native_critic",
            "localization_audience_critic",
            "localization_fidelity_critic",
            "localization_final_fidelity",
        ):
            return request.output_model.model_validate({"findings": []})
        return await super().extract(request)  # type: ignore[no-untyped-call]

"""Phase 21 gates: the 100-lesson production path is retired, history stays."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select, text

from app.content_engine.writing.memory import PublishedMemoryReader
from app.content_strategy.lesson_canon import LessonContentPackage
from app.content_strategy.lesson_workflow import (
    lesson_project_snapshot,
    lesson_research_summary,
)
from app.content_strategy.models import (
    ChannelLedgerEntry,
    EditorialProject,
    PersianDraft,
)
from app.content_strategy.persian_service import PersianEditorialService
from app.core.config import Environment, Settings
from app.db.session import Database
from app.lecture.domain import (
    LectureType,
    MasterOriginType,
    MasterStatus,
)
from app.lecture.models import LectureMasterVersion, LectureProject
from app.main import create_app
from app.research.domain import PackageStatus, ResearchPlanStatus
from app.research.models import ResearchPackage, ResearchPlan, ResearchProject
from app.retrieval.models import RetrievalConfiguration


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-lesson-retirement-test"),
    )


def _fixture_package() -> LessonContentPackage:
    return LessonContentPackage(
        lesson_canon_hash="legacy-hash",
        lesson_id="3.1",
        lesson_number=11,
        chapter=3,
        chapter_title_fa="فصل",
        order_in_chapter=1,
        level=1,
        canonical_lesson_title="بُن",
        is_core_concept=True,
        central_question="بُن چیست؟",
        canonical_lesson_explanation="توضیح کانونیک درس تاریخی.",
        core_concepts=["بُن"],
        required_distinctions=[],
        conceptual_boundaries=[],
        prerequisites=[],
        lesson_relations=[],
        canonical_relations_section_fa="",
        what_this_lesson_develops=[],
        what_should_remain_open=[],
        ayin_provenance=None,
        provenance_complete=True,
        review_items=[],
        core_concept_registry=[],
    )


@pytest.mark.integration
def test_lesson_catalog_and_creation_are_retired() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = _settings(database_url)

    with TestClient(create_app(settings)) as client:
        catalog = client.get("/lessons", follow_redirects=False)
        assert catalog.status_code == 303
        assert catalog.headers["location"] == "/studio"
        assert "data-lesson-id=" not in catalog.text

        nested = client.get("/lessons/3.1", follow_redirects=False)
        assert nested.status_code == 303
        assert nested.headers["location"] == "/studio"

        concepts = client.get("/lessons/concepts", follow_redirects=False)
        assert concepts.status_code == 303

        # No creation route: the catch-all only answers GET.
        created = client.post("/lessons/3.1/projects", follow_redirects=False)
        assert created.status_code in {404, 405}

        home = client.get("/")
        assert home.status_code == 200
        assert "Lektionen" not in home.text
        assert "100-Lektionen" not in home.text
        assert 'href="/lessons"' not in home.text
        assert "/studio" in home.text


@pytest.mark.integration
def test_historical_lesson_project_remains_readable_and_maintainable() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = _settings(database_url)
    database = Database(database_url)
    project_id = asyncio.run(_add_historical_project(database))

    with TestClient(create_app(settings)) as client:
        workspace = client.get(f"/workspace/{project_id}")
        assert workspace.status_code == 200
        assert "Historische Lektion 11 / 100" in workspace.text
        assert "historische Provenienz" in workspace.text
        # Retired production actions are gone; maintenance actions remain.
        assert 'name="lesson_id"' not in workspace.text
        assert 'name="semantic_master_id"' not in workspace.text
        assert f"/workspace/{project_id}/research" not in workspace.text
        assert "/edit" in workspace.text
        assert "/approve" in workspace.text

        texts = client.get("/texts")
        assert texts.status_code == 200
        assert "Historische Lektion 11 / 100" in texts.text

    asyncio.run(_assert_edit_gate_preserved(database, project_id))
    asyncio.run(_cleanup(database, project_id))
    asyncio.run(database.dispose())


@pytest.mark.integration
def test_historical_research_chain_and_published_memory_remain_readable() -> None:
    """Lesson-origin plan/package/master rows and lesson-tagged published
    memory stay readable after the canon path is retired."""

    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = _settings(database_url)
    database = Database(database_url)
    project_id = asyncio.run(_add_historical_chain(database))

    with TestClient(create_app(settings)) as client:
        workspace = client.get(f"/workspace/{project_id}")
        assert workspace.status_code == 200
        # The pinned lesson package + READY legacy master render as
        # "ready for writing" historical provenance.
        assert "Bereit für den Entwurf" in workspace.text
        assert "Historische Quelle" in workspace.text

    asyncio.run(_assert_historical_reads(database, project_id))
    asyncio.run(_cleanup_chain(database, project_id))
    asyncio.run(database.dispose())


_HASH = "a" * 64


async def _add_historical_chain(database: Database) -> UUID:
    package = _fixture_package()
    async with database.transaction() as session:
        retrieval_config = RetrievalConfiguration(
            name=f"phase21-retirement-{uuid4().hex[:12]}",
            version="1",
            parameters={},
            configuration_hash=uuid4().hex + uuid4().hex,
        )
        research_project = ResearchProject(
            human_question="Was ist بُن؟",
            created_by="phase21-test",
        )
        session.add_all([retrieval_config, research_project])
        await session.flush()

        plan = ResearchPlan(
            lesson_id="3.1",
            lesson_canon_hash="legacy-hash",
            lesson_content_package_snapshot=package.model_dump(mode="json"),
            human_question="Was ist بُن؟",
            version_number=1,
            prohibited_conflations=[],
            retrieval_configuration={},
            input_hash=_HASH,
            status=ResearchPlanStatus.READY,
            created_by="phase21-test",
        )
        session.add(plan)
        await session.flush()

        research_package = ResearchPackage(
            research_project_id=research_project.id,
            research_plan_id=plan.id,
            lesson_id="3.1",
            lesson_canon_hash="legacy-hash",
            lesson_content_package_version=package.package_version,
            lesson_content_package_snapshot=package.model_dump(mode="json"),
            retrieval_configuration_id=retrieval_config.id,
            package_version=1,
            status=PackageStatus.FROZEN,
            retrieval_snapshot={
                "queries": [
                    {
                        "label": "Empirischer Kontext",
                        "kind": "EMPIRICAL",
                        "results": [
                            {
                                "chunk_id": "chunk-1",
                                "text": "Historischer Befund.",
                                "source_role": "EMPIRICAL_CONTEXT",
                                "provenance": {"source_title": "Historische Quelle"},
                            }
                        ],
                    }
                ],
                "rejected_candidates": [],
            },
            unresolved_issues=[],
            input_hash=_HASH,
            content_hash=_HASH,
            created_by="phase21-test",
        )
        session.add(research_package)
        await session.flush()

        lecture_project = LectureProject(
            research_package_id=research_package.id,
            lecture_type=LectureType.FOUNDATION,
            working_title="Historischer Master",
            created_by="phase21-test",
        )
        session.add(lecture_project)
        await session.flush()

        master = LectureMasterVersion(
            lecture_project_id=lecture_project.id,
            version_number=1,
            research_package_id=research_package.id,
            research_package_version=1,
            research_package_content_hash=_HASH,
            origin_type=MasterOriginType.LEGACY_LESSON,
            central_human_question="Was ist بُن؟",
            status=MasterStatus.READY,
            input_hash=_HASH,
            created_by="phase21-test",
        )
        session.add(master)
        await session.flush()

        project = EditorialProject(
            title="Historisches Lektionsprojekt",
            human_question="Was ist بُن؟",
            target_duration_minutes=15,
            status="PUBLISHED",
            strategy_topic_snapshot=lesson_project_snapshot(
                package, lesson_number=11, lesson_count=100
            ),
            research_package_id=research_package.id,
            semantic_master_id=master.id,
        )
        session.add(project)
        await session.flush()

        draft = PersianDraft(
            editorial_project_id=project.id,
            semantic_master_id=master.id,
            version_number=1,
            variant_index=1,
            text="متن تاریخی منتشرشده برای حافظه انتشار.",
            status="PERSIAN_APPROVED",
            owner_prompt=None,
            target_duration_minutes=5,
            target_word_count_min=1,
            target_word_count_max=1000,
            actual_word_count=6,
            estimated_duration_seconds=15,
            provenance={"fixture": "phase21-retirement"},
        )
        session.add(draft)
        await session.flush()

        session.add(
            ChannelLedgerEntry(
                editorial_project_id=project.id,
                published_draft_id=draft.id,
                lesson_id="3.1",
                published_title="Historischer Titel",
                concept_keys=["bun"],
                content_hash=_HASH,
                published_at=datetime.now(UTC),
            )
        )
        return project.id


async def _assert_historical_reads(database: Database, project_id: UUID) -> None:
    async with database.transaction() as session:
        project = await session.get(EditorialProject, project_id)
        assert project is not None

        # Lesson-origin research package renders through the read-only helper.
        summary = await lesson_research_summary(session, project)
        assert summary is not None
        assert summary.ready_for_writing is True
        assert summary.result_count == 1
        assert "Historische Quelle" in summary.sources

        # The LEGACY_LESSON master stays deserializable with provenance intact.
        master = await session.get(LectureMasterVersion, project.semantic_master_id)
        assert master is not None
        assert master.origin_type is MasterOriginType.LEGACY_LESSON
        assert master.research_package_id == project.research_package_id

        # Published memory keeps historical lesson provenance readable.
        memory, ledger_count = await PublishedMemoryReader.load(session)
        item = next(entry for entry in memory if entry.project_id == project_id)
        assert item.lesson_id == "3.1"
        assert item.title == "Historischer Titel"
        assert ledger_count >= 1


async def _cleanup_chain(database: Database, project_id: UUID) -> None:
    async with database.transaction() as session:
        # The fixture intentionally seeds immutable historical states
        # (READY master, FROZEN package); cleanup bypasses those triggers
        # and re-enables them before commit.
        await session.execute(
            text(
                "ALTER TABLE content.lecture_master_versions "
                "DISABLE TRIGGER lecture_master_ready_immutable"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE content.research_packages "
                "DISABLE TRIGGER research_packages_frozen_immutable"
            )
        )
        project = await session.get(EditorialProject, project_id)
        assert project is not None
        package_id = project.research_package_id
        master_id = project.semantic_master_id
        package = await session.get(ResearchPackage, package_id)
        await session.execute(
            delete(ChannelLedgerEntry).where(
                ChannelLedgerEntry.editorial_project_id == project_id
            )
        )
        await session.execute(
            delete(PersianDraft).where(PersianDraft.editorial_project_id == project_id)
        )
        await session.delete(project)
        master = await session.get(LectureMasterVersion, master_id)
        if master is not None:
            lecture_project_id = master.lecture_project_id
            await session.delete(master)
            lecture_project = await session.get(LectureProject, lecture_project_id)
            if lecture_project is not None:
                await session.delete(lecture_project)
        if package is not None:
            plan_id = package.research_plan_id
            config_id = package.retrieval_configuration_id
            research_project_id = package.research_project_id
            await session.delete(package)
            plan = await session.get(ResearchPlan, plan_id)
            if plan is not None:
                await session.delete(plan)
            research_project = await session.get(ResearchProject, research_project_id)
            if research_project is not None:
                await session.delete(research_project)
            config = await session.get(RetrievalConfiguration, config_id)
            if config is not None:
                await session.delete(config)
        await session.execute(
            text(
                "ALTER TABLE content.lecture_master_versions "
                "ENABLE TRIGGER lecture_master_ready_immutable"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE content.research_packages "
                "ENABLE TRIGGER research_packages_frozen_immutable"
            )
        )


async def _add_historical_project(database: Database) -> UUID:
    async with database.transaction() as session:
        project = EditorialProject(
            title="Historisches Lektionsprojekt",
            human_question="Was ist بُن؟",
            target_duration_minutes=15,
            strategy_topic_snapshot=lesson_project_snapshot(
                _fixture_package(), lesson_number=11, lesson_count=100
            ),
        )
        session.add(project)
        await session.flush()
        master = await session.scalar(select(LectureMasterVersion).limit(1))
        session.add(
            PersianDraft(
                editorial_project_id=project.id,
                semantic_master_id=master.id if master is not None else None,
                version_number=1,
                variant_index=1,
                text="متن تاریخی برای خوانایی لطفاً بررسی شود.",
                status="PERSIAN_APPROVED",
                owner_prompt=None,
                target_duration_minutes=5,
                target_word_count_min=1,
                target_word_count_max=1000,
                actual_word_count=6,
                estimated_duration_seconds=15,
                provenance={"fixture": "phase21-retirement"},
            )
        )
        return project.id


async def _assert_edit_gate_preserved(database: Database, project_id: UUID) -> None:
    """Historical drafts still version on edit and require review before approve."""

    async with database.transaction() as session:
        approved = await session.scalar(
            select(PersianDraft).where(
                PersianDraft.editorial_project_id == project_id,
                PersianDraft.status == "PERSIAN_APPROVED",
            )
        )
        assert approved is not None
        approved_id = approved.id
        original_text = approved.text
    edited_id = await PersianEditorialService(database).edit(
        approved_id, original_text + " ویرایش صاحب اثر."
    )
    with pytest.raises(ValueError, match="review must be completed"):
        await PersianEditorialService(database).approve(edited_id)
    async with database.transaction() as session:
        original = await session.get(PersianDraft, approved_id)
        edited = await session.get(PersianDraft, edited_id)
        assert original is not None and original.status == "PERSIAN_APPROVED"
        assert edited is not None and edited.parent_draft_id == approved_id
        assert edited.version_number == original.version_number + 1
        assert edited.provenance["review_completed"] is False


async def _cleanup(database: Database, project_id: UUID) -> None:
    async with database.transaction() as session:
        await session.execute(
            delete(ChannelLedgerEntry).where(
                ChannelLedgerEntry.editorial_project_id == project_id
            )
        )
        await session.execute(
            delete(PersianDraft).where(PersianDraft.editorial_project_id == project_id)
        )
        project = await session.get(EditorialProject, project_id)
        if project is not None:
            await session.delete(project)

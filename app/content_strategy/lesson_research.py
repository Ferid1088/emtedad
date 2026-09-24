"""External-only research orchestration for canonical lesson projects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.lesson_canon import LessonContentPackage
from app.content_strategy.lesson_workflow import lesson_package_from_project
from app.content_strategy.models import EditorialProject
from app.db.session import Database
from app.knowledge.models import ExternalClaim
from app.lecture.domain import LectureType, MasterStatus
from app.lecture.schemas import LectureProjectCreate
from app.lecture.service import LectureMasterService
from app.research.domain import (
    EvidenceSelectionRole,
    PackageStatus,
    ResearchPlanStatus,
    ResearchProjectStatus,
    ResearchQuestionKind,
)
from app.research.models import (
    ResearchPackage,
    ResearchPackageExternalChunk,
    ResearchPackageExternalClaim,
    ResearchPackageExternalPerson,
    ResearchPackageExternalWork,
    ResearchPlan,
    ResearchPlanQuestion,
    ResearchProject,
)
from app.retrieval.chunking import ChunkBuilder
from app.retrieval.domain import QueryLanguage, RetrievalLane
from app.retrieval.embeddings import EmbeddingProvider, EmbeddingService
from app.retrieval.models import (
    Chunk,
    ChunkExternalEntity,
    ChunkExternalSegment,
    RetrievalResult,
)
from app.retrieval.normalization import search_tokens
from app.retrieval.schemas import SearchResponse, SearchResult
from app.retrieval.service import HybridRetrievalService


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


_FOCUS_STOP_WORDS = {
    "است",
    "نیست",
    "چیست",
    "چه",
    "یک",
    "این",
    "آن",
    "برای",
    "بدون",
    "قابل",
    "درس",
    "آیین",
    "امتداد",
}


def _focus_tokens(lesson: LessonContentPackage) -> set[str]:
    question = lesson.central_question or lesson.canonical_lesson_title
    return {
        token
        for token in search_tokens(f"{question} {_external_themes(lesson)}")
        if len(token) >= 3 and token not in _FOCUS_STOP_WORDS
    }


def _external_themes(lesson: LessonContentPackage) -> str:
    """Map lesson areas to human-world vocabulary, never new Ayin doctrine."""

    themes = {
        1: "تفکر انتقادی زبان مفهوم ابهام پرسشگری",
        2: "حافظه بین نسلی میراث اثر آینده معنا",
        3: "هویت فردی شخصیت فردیت روایت خود",
        4: "آگاهی خودآگاهی شناخت ذهن تجربه اول شخص",
        5: "محدودیت توانایی کنترل آسیب پذیری مرز قدرت",
        6: "شرایط محیط عوامل اجتماعی علیت زمینه تجربه",
        7: "عادت واکنش خودکار یادگیری تغییر رفتار محیط خودآگاهی",
        8: "تصمیم اختیار مسئولیت فرصت عمل تغییر شرایط",
        9: "سوگ فقدان تاب آوری حمایت اجتماعی تنظیم هیجان رنج ثانویه",
        10: "رابطه اخلاق قدرت مرز رضایت تعارض همکاری",
        11: "هوش مصنوعی یادگیری ماشین شناخت زبان آگاهی سامانه محاسباتی",
        12: "مرگ معنویت طبیعت گرایی ندانم گرایی معنا سوگ",
        13: "آیین جمعی تجربه نمادین رضایت ایمنی خروج",
        14: "خود مشاهده گری روایت شخصی بازاندیشی تمرین",
        15: "خانواده کار مهاجرت فقر فناوری بیماری جامعه",
        16: "یکپارچگی کاربرد خطای مفهومی مسئولیت جمعی",
    }
    return themes.get(lesson.chapter, "تجربه انسانی رفتار رابطه تاریخ نقد")


def _matches_human_question(
    item: SearchResult, lesson: LessonContentPackage, focus: set[str]
) -> bool:
    if not focus:
        return True
    candidate_text = " ".join(
        [
            item.normalized_text,
            item.provenance.source_title,
            *item.matched_entities,
        ]
    )
    candidate_tokens = set(search_tokens(candidate_text))
    matches = {
        token
        for token in focus
        if token in candidate_tokens
        or any(
            len(token) >= 4
            and len(candidate) >= 4
            and (candidate.startswith(token) or token.startswith(candidate))
            for candidate in candidate_tokens
        )
    }
    normalized = " ".join(search_tokens(candidate_text))
    if lesson.chapter == 7:
        return any(
            phrase in normalized
            for phrase in ("عادت", "واکنش خودکار", "الگوی رفتاری")
        ) or len(matches & {"موقعیت", "محرک", "پاسخ", "پیامد"}) >= 2
    if lesson.chapter == 9:
        return any(
            phrase in normalized
            for phrase in ("سوگ", "فقدان", "عزیز", "تروما", "تاب آوری")
        )
    if lesson.chapter == 11:
        return any(
            phrase in normalized
            for phrase in (
                "هوش مصنوعی",
                "یادگیری ماشین",
                "سامانه هوشمند",
                "مدل زبانی",
            )
        )
    required = 2 if len(focus) >= 3 else 1
    return len(matches) >= required


@dataclass(frozen=True, slots=True)
class LessonResearchQuery:
    """One deterministic external question derived from an approved lesson."""

    kind: str
    label: str
    text: str
    selection_role: EvidenceSelectionRole


@dataclass(frozen=True, slots=True)
class LessonResearchResult:
    """Result of one reproducible lesson research run."""

    package_id: UUID
    master_id: UUID | None
    result_count: int
    source_count: int
    counterevidence_count: int
    ready_for_writing: bool


@dataclass(frozen=True, slots=True)
class LessonRetrievalPins:
    """One current corpus-wide chunk and embedding snapshot."""

    chunking_run_id: UUID
    embedding_model_id: UUID


@dataclass(frozen=True, slots=True)
class LessonResearchSummary:
    """Owner-facing state without exposing raw package records."""

    status_label: str
    badge_class: str
    result_count: int
    source_count: int
    counterevidence_count: int
    sources: tuple[str, ...]
    query_labels: tuple[str, ...]
    issues: tuple[str, ...]
    ready_for_writing: bool
    selected_sources: tuple[SelectedExternalSource, ...]
    rejected_count: int


@dataclass(frozen=True, slots=True)
class SelectedExternalSource:
    """Owner-facing reason for including one external item."""

    title: str
    role: str
    relevant_claim: str
    inclusion_reason: str


class LessonResearchService:
    """Build a frozen external ResearchPackage for one lesson project."""

    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.database = database
        self.chunking = ChunkBuilder(database)
        self.embedding = EmbeddingService(database, embedding_provider)
        self.retrieval = HybridRetrievalService(database, embedding_provider)
        self.masters = LectureMasterService(database)

    async def run(
        self,
        editorial_project_id: UUID,
        *,
        owner_focus: str | None = None,
        max_results_per_question: int = 5,
    ) -> LessonResearchResult:
        """Retrieve external evidence only and bind it to the editorial project."""

        if not 1 <= max_results_per_question <= 20:
            raise ValueError("max_results_per_question must be between 1 and 20")
        async with self.database.transaction() as session:
            project = await session.get(EditorialProject, editorial_project_id)
            if project is None:
                raise ValueError("editorial project not found")
            package = lesson_package_from_project(project)
            if package is None:
                raise ValueError(
                    "external lesson research requires a canonical lesson project"
                )
            research_project = await self._research_project(session, project, package)
            research_project_id = research_project.id
            queries = self.build_queries(package, owner_focus=owner_focus)
            research_plan = await self._research_plan(
                session, package, queries, created_by="owner-ui"
            )
            research_plan_id = research_plan.id

        pins = await self._ensure_retrieval_index()

        responses: list[tuple[LessonResearchQuery, SearchResponse]] = []
        for query in queries:
            response = await self.retrieval.search(
                query.text,
                QueryLanguage.FA,
                chunking_run_id=pins.chunking_run_id,
                embedding_model_id=pins.embedding_model_id,
                lanes=[RetrievalLane.EXTERNAL],
                parameters={"lane_top_n": max_results_per_question},
            )
            responses.append((query, response))

        (
            package_id,
            result_count,
            source_count,
            counter_count,
        ) = await self._persist_package(
            research_project_id,
            research_plan_id,
            package,
            responses,
            pins,
        )
        master_id: UUID | None = None
        ready = False
        if result_count:
            lecture_project = await self.masters.create_project(
                LectureProjectCreate(
                    research_package_id=package_id,
                    lecture_type=LectureType.HUMAN_QUESTION,
                    working_title=package.canonical_lesson_title,
                    created_by="owner-ui",
                )
            )
            master = await self.masters.architect(
                lecture_project.id, created_by="owner-ui"
            )
            validated = await self.masters.validate(master.id)
            if validated.master.status is MasterStatus.READY:
                frozen = await self.masters.freeze(master.id)
                master_id = frozen.id
                ready = True
            else:
                master_id = master.id

        async with self.database.transaction() as session:
            project = await session.get(EditorialProject, editorial_project_id)
            loaded_research_project = await session.get(
                ResearchProject, research_project_id
            )
            if project is None or loaded_research_project is None:
                raise RuntimeError("lesson research project disappeared")
            project.research_project_id = loaded_research_project.id
            project.research_package_id = package_id
            project.semantic_master_id = master_id
            project.status = "RESEARCH_READY" if ready else "RESEARCH_REVIEW"
            loaded_research_project.status = ResearchProjectStatus.READY

        return LessonResearchResult(
            package_id=package_id,
            master_id=master_id,
            result_count=result_count,
            source_count=source_count,
            counterevidence_count=counter_count,
            ready_for_writing=ready,
        )

    @staticmethod
    def build_queries(
        package: LessonContentPackage,
        *,
        owner_focus: str | None = None,
    ) -> tuple[LessonResearchQuery, ...]:
        """Create narrow external-only questions without regenerating an Ayin seed."""

        question = package.central_question or package.canonical_lesson_title
        context = question.strip()
        themes = _external_themes(package)
        queries = [
            LessonResearchQuery(
                kind=ResearchQuestionKind.EMPIRICAL.value,
                label="Empirischer Kontext",
                text=(
                    f"{context}؛ {themes}؛ پژوهش روان‌شناسی، یادگیری، رفتار، روابط و "
                    "تأثیر محیط چه توضیحی می‌دهد؟"
                ),
                selection_role=EvidenceSelectionRole.EMPIRICAL_CONTEXT,
            ),
            LessonResearchQuery(
                kind=ResearchQuestionKind.EXTERNAL_CONCEPT.value,
                label="Konzeptuelle Parallele",
                text=(
                    f"{context}؛ {themes}؛ کدام دیدگاه‌های معاصر فلسفی، روان‌شناختی یا "
                    "اجتماعی فقط شباهت یا تفاوت روشنگر دارند؟"
                ),
                selection_role=EvidenceSelectionRole.CONCEPTUAL_PARALLEL,
            ),
            LessonResearchQuery(
                kind=ResearchQuestionKind.PHILOSOPHICAL.value,
                label="Historischer Kontext",
                text=(
                    f"{context}؛ {themes}؛ زمینهٔ تاریخی و تحول نگاه انسان "
                    "به این مسئله چیست؟"
                ),
                selection_role=EvidenceSelectionRole.HISTORICAL_CONTEXT,
            ),
            LessonResearchQuery(
                kind=ResearchQuestionKind.EMPIRICAL.value,
                label="Beispiele und Anwendungen",
                text=(
                    f"{context}؛ {themes}؛ نمونهٔ عینی، مطالعهٔ موردی و موقعیت روزمرهٔ "
                    "روشنگر چیست؟"
                ),
                selection_role=EvidenceSelectionRole.EXAMPLE,
            ),
            LessonResearchQuery(
                kind=ResearchQuestionKind.PHILOSOPHICAL.value,
                label="Alternative Erklärung",
                text=(
                    f"{context}؛ {themes}؛ چه توضیح‌های جایگزین یا "
                    "چارچوب‌های رقیبی وجود دارد؟"
                ),
                selection_role=EvidenceSelectionRole.ALTERNATIVE_EXPLANATION,
            ),
            LessonResearchQuery(
                kind=ResearchQuestionKind.COUNTEREVIDENCE.value,
                label="Kritik und Gegenargumente",
                text=(
                    "نقد، شواهد مخالف، محدودیت‌ها و استدلال‌های جایگزین "
                    f"دربارهٔ {context}؛ {themes}"
                ),
                selection_role=EvidenceSelectionRole.COUNTERARGUMENT,
            ),
            LessonResearchQuery(
                kind=ResearchQuestionKind.COUNTEREVIDENCE.value,
                label="Offene Frage",
                text=(
                    f"{context}؛ {themes}؛ کدام ابهام‌ها، مرزهای دانسته‌ها "
                    "و پرسش‌های باز باقی است؟"
                ),
                selection_role=EvidenceSelectionRole.OPEN_QUESTION,
            ),
        ]
        if owner_focus and owner_focus.strip():
            queries.append(
                LessonResearchQuery(
                    kind="OWNER_FOCUS",
                    label="Eigener Recherchefokus",
                    text=owner_focus.strip(),
                    selection_role=EvidenceSelectionRole.EXTERNAL_EVIDENCE,
                )
            )
        return tuple(queries)

    @staticmethod
    async def _research_project(
        session: AsyncSession,
        project: EditorialProject,
        package: LessonContentPackage,
    ) -> ResearchProject:
        research_project = (
            await session.get(ResearchProject, project.research_project_id)
            if project.research_project_id is not None
            else None
        )
        if research_project is None:
            research_project = ResearchProject(
                human_question=(
                    package.central_question or package.canonical_lesson_title
                ),
                status=ResearchProjectStatus.DRAFT,
                created_by="owner-ui",
            )
            session.add(research_project)
            await session.flush()
            project.research_project_id = research_project.id
        return research_project

    @staticmethod
    async def _research_plan(
        session: AsyncSession,
        package: LessonContentPackage,
        queries: tuple[LessonResearchQuery, ...],
        *,
        created_by: str,
    ) -> ResearchPlan:
        """Persist the human-question-derived external plan and provenance."""

        version = int(
            await session.scalar(
                select(func.coalesce(func.max(ResearchPlan.version_number), 0) + 1)
                .where(
                    ResearchPlan.lesson_id == package.lesson_id,
                    ResearchPlan.lesson_canon_hash == package.lesson_canon_hash,
                )
            )
            or 1
        )
        human_question = package.central_question or package.canonical_lesson_title
        plan = ResearchPlan(
            ayin_spine_id=None,
            lesson_id=package.lesson_id,
            lesson_canon_hash=package.lesson_canon_hash,
            lesson_content_package_snapshot=package.model_dump(mode="json"),
            human_question=human_question,
            query_provenance={
                "planner": "lesson-human-question-external-v1",
                "derived_from": "HUMAN_QUESTION",
                "human_question": human_question,
                "generative_lanes": [RetrievalLane.EXTERNAL.value],
                "excluded_generation_sources": [
                    "AYIN_BOOK_RAG",
                    "PUBLISHED_SCRIPT_ARCHIVE",
                    "CHANNEL_LEDGER",
                ],
            },
            version_number=version,
            manasek_relevant=False,
            manasek_reason=None,
            prohibited_conflations=[
                "External knowledge may not redefine the canonical lesson",
                "Conceptual similarity is not identity",
                "Empirical material does not prove Ayin doctrine",
            ],
            retrieval_configuration={
                "lanes": [RetrievalLane.EXTERNAL.value],
                "query_count": len(queries),
                "counterevidence_required": True,
            },
            input_hash=_hash(
                {
                    "lesson_id": package.lesson_id,
                    "lesson_canon_hash": package.lesson_canon_hash,
                    "human_question": human_question,
                    "queries": [query.text for query in queries],
                }
            ),
            status=ResearchPlanStatus.READY,
            created_by=created_by,
        )
        session.add(plan)
        await session.flush()
        known_kinds = {item.value for item in ResearchQuestionKind}
        for ordinal, query in enumerate(queries, start=1):
            kind = (
                ResearchQuestionKind(query.kind)
                if query.kind in known_kinds
                else ResearchQuestionKind.EXTERNAL_CONCEPT
            )
            session.add(
                ResearchPlanQuestion(
                    research_plan_id=plan.id,
                    ordinal=ordinal,
                    kind=kind,
                    question=f"{query.label}: {human_question}",
                    retrieval_text=query.text,
                    requires_counterevidence=(
                        query.selection_role
                        in {
                            EvidenceSelectionRole.COUNTERARGUMENT,
                            EvidenceSelectionRole.OPEN_QUESTION,
                        }
                    ),
                )
            )
        return plan

    async def _ensure_retrieval_index(self) -> LessonRetrievalPins:
        """Refresh stale source snapshots before ordinary lesson retrieval."""

        chunking = await self.chunking.build()
        async with self.database.transaction() as session:
            external_chunk = await session.scalar(
                select(Chunk.id)
                .where(
                    Chunk.chunking_run_id == chunking.run_id,
                    Chunk.lane == RetrievalLane.EXTERNAL,
                )
                .limit(1)
            )
        if external_chunk is None:
            raise ValueError(
                "Keine externen Quellen im aktuellen Wissensindex gefunden."
            )
        embedding = await self.embedding.build(chunking.run_id)
        return LessonRetrievalPins(
            chunking_run_id=chunking.run_id,
            embedding_model_id=embedding.model_id,
        )

    async def _persist_package(
        self,
        research_project_id: UUID,
        research_plan_id: UUID,
        lesson: LessonContentPackage,
        responses: list[tuple[LessonResearchQuery, SearchResponse]],
        pins: LessonRetrievalPins,
    ) -> tuple[UUID, int, int, int]:
        retrieval_run_ids = [response.retrieval_run_id for _, response in responses]
        configuration_id = responses[0][1].retrieval_configuration_id
        external_chunks: dict[UUID, tuple[SearchResult, EvidenceSelectionRole]] = {}
        queries_snapshot: list[dict[str, object]] = []
        sources: set[UUID] = set()
        counter_chunks: set[UUID] = set()
        selected_hashes: set[str] = set()
        source_counts: dict[UUID, int] = {}
        rejected: list[dict[str, object]] = []
        focus = _focus_tokens(lesson)
        for query, response in responses:
            results: list[dict[str, object]] = []
            for item in response.results:
                if item.provenance.lane is not RetrievalLane.EXTERNAL:
                    raise ValueError("lesson research returned a non-external result")
                rejection_reason: str | None = None
                if item.chunk_id in external_chunks:
                    rejection_reason = "DUPLICATE_RETRIEVAL"
                elif item.chunk_content_hash in selected_hashes:
                    rejection_reason = "DUPLICATE_MATERIAL"
                elif source_counts.get(item.provenance.source_version_id, 0) >= 2:
                    rejection_reason = "SOURCE_CONCENTRATION"
                elif len(external_chunks) >= 18:
                    rejection_reason = "PACKAGE_SELECTION_LIMIT"
                elif not _matches_human_question(item, lesson, focus):
                    rejection_reason = "WEAK_HUMAN_QUESTION_RELEVANCE"
                elif (
                    item.lexical_rank is None
                    and item.entity_rank is None
                    and (item.dense_score or 0.0) < 0.2
                ):
                    rejection_reason = "WEAK_RELEVANCE"
                selected = rejection_reason is None
                if selected:
                    external_chunks[item.chunk_id] = (item, query.selection_role)
                    selected_hashes.add(item.chunk_content_hash)
                    source_id = item.provenance.source_version_id
                    source_counts[source_id] = source_counts.get(source_id, 0) + 1
                    sources.add(source_id)
                    if query.selection_role in {
                        EvidenceSelectionRole.COUNTERARGUMENT,
                        EvidenceSelectionRole.CHALLENGE,
                        EvidenceSelectionRole.TENSION,
                    }:
                        counter_chunks.add(item.chunk_id)
                else:
                    rejected.append(
                        {
                            "chunk_id": str(item.chunk_id),
                            "source_title": item.provenance.source_title,
                            "reason": rejection_reason,
                            "query_kind": query.kind,
                        }
                    )
                results.append(
                    {
                        "chunk_id": str(item.chunk_id),
                        "rank": item.final_rank,
                        "text": item.text,
                        "language": item.language,
                        "fusion_score": item.fusion_score,
                        "reranker_score": item.reranker_score,
                        "content_hash": item.chunk_content_hash,
                        "selected": selected,
                        "source_role": query.selection_role.value,
                        "inclusion_reason": (
                            f"Relevant für den Recherchebereich „{query.label}“ "
                            "der menschlichen Leitfrage."
                            if selected
                            else None
                        ),
                        "rejection_reason": rejection_reason,
                        "provenance": item.provenance.model_dump(mode="json"),
                    }
                )
            queries_snapshot.append(
                {
                    "kind": query.kind,
                    "label": query.label,
                    "query": query.text,
                    "retrieval_run_id": str(response.retrieval_run_id),
                    "results": results,
                }
            )

        retrieval_snapshot: dict[str, object] = {
            "mode": "LESSON_EXTERNAL_ONLY",
            "human_question": (
                lesson.central_question or lesson.canonical_lesson_title
            ),
            "chunking_run_id": str(pins.chunking_run_id),
            "embedding_model_id": str(pins.embedding_model_id),
            "lanes": [RetrievalLane.EXTERNAL.value],
            "queries": queries_snapshot,
            "rejected_candidates": rejected,
            "generation_roles": [
                "CANONICAL_LESSON_CONTENT",
                "CORE_CONCEPT_REGISTRY",
                "EXTERNAL_RESEARCH",
            ],
            "review_only_roles": [
                "CHANNEL_LEDGER",
                "PUBLISHED_SCRIPT_ARCHIVE",
                "LESSON_RELATIONS",
            ],
        }
        input_hash = _hash(
            {
                "lesson_id": lesson.lesson_id,
                "lesson_canon_hash": lesson.lesson_canon_hash,
                "queries": [query.text for query, _ in responses],
                "retrieval_runs": retrieval_run_ids,
            }
        )
        content_hash = _hash(
            {
                "lesson": lesson.model_dump(mode="json"),
                "retrieval_snapshot": retrieval_snapshot,
            }
        )
        issues = [
            {
                "code": item,
                "severity": "WARNING",
                "message": item,
                "resolved": False,
            }
            for item in lesson.review_items
        ]
        if not external_chunks:
            issues.append(
                {
                    "code": "NO_EXTERNAL_EVIDENCE_FOUND",
                    "severity": "WARNING",
                    "message": (
                        "Die externe Wissensbasis lieferte für diese Recherche "
                        "keine passenden Ergebnisse."
                    ),
                    "resolved": False,
                }
            )

        async with self.database.transaction() as session:
            version = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(ResearchPackage.package_version), 0) + 1
                    ).where(ResearchPackage.research_project_id == research_project_id)
                )
                or 1
            )
            package = ResearchPackage(
                research_project_id=research_project_id,
                ayin_spine_id=None,
                research_plan_id=research_plan_id,
                canon_version_id=None,
                lesson_id=lesson.lesson_id,
                lesson_canon_hash=lesson.lesson_canon_hash,
                lesson_content_package_version=lesson.package_version,
                lesson_content_package_snapshot=lesson.model_dump(mode="json"),
                retrieval_configuration_id=configuration_id,
                package_version=version,
                status=PackageStatus.BUILDING,
                retrieval_snapshot=retrieval_snapshot,
                unresolved_issues=issues,
                input_hash=input_hash,
                content_hash=content_hash,
                created_by="owner-ui",
            )
            session.add(package)
            await session.flush()
            await self._persist_external_links(
                session, package.id, external_chunks, retrieval_run_ids
            )
            package.status = PackageStatus.FROZEN
            package.frozen_at = datetime.now(UTC)
            await session.flush()
            return (
                package.id,
                len(external_chunks),
                len(sources),
                len(counter_chunks),
            )

    @staticmethod
    async def _persist_external_links(
        session: AsyncSession,
        package_id: UUID,
        external_chunks: dict[UUID, tuple[SearchResult, EvidenceSelectionRole]],
        retrieval_run_ids: list[UUID],
    ) -> None:
        for result, role in external_chunks.values():
            retrieval_result_id = await session.scalar(
                select(RetrievalResult.id)
                .where(
                    RetrievalResult.chunk_id == result.chunk_id,
                    RetrievalResult.retrieval_run_id.in_(retrieval_run_ids),
                )
                .order_by(RetrievalResult.final_rank)
                .limit(1)
            )
            session.add(
                ResearchPackageExternalChunk(
                    package_id=package_id,
                    chunk_id=result.chunk_id,
                    source_version_id=result.provenance.source_version_id,
                    content_hash=result.chunk_content_hash,
                    selection_role=role,
                    retrieval_result_id=retrieval_result_id,
                )
            )
        if not external_chunks:
            return
        chunk_ids = list(external_chunks)
        segment_rows = list(
            await session.scalars(
                select(ChunkExternalSegment).where(
                    ChunkExternalSegment.chunk_id.in_(chunk_ids)
                )
            )
        )
        segment_ids = [row.source_segment_id for row in segment_rows]
        if segment_ids:
            claims = await session.scalars(
                select(ExternalClaim).where(
                    ExternalClaim.source_segment_id.in_(segment_ids)
                )
            )
            for claim in claims.unique():
                session.add(
                    ResearchPackageExternalClaim(
                        package_id=package_id,
                        claim_id=claim.id,
                        source_version_id=claim.source_version_id,
                        source_segment_id=claim.source_segment_id,
                    )
                )
        entities = await session.scalars(
            select(ChunkExternalEntity).where(
                ChunkExternalEntity.chunk_id.in_(chunk_ids)
            )
        )
        work_ids: set[UUID] = set()
        person_ids: set[UUID] = set()
        for entity in entities:
            if entity.work_id is not None:
                work_ids.add(entity.work_id)
            if entity.person_id is not None:
                person_ids.add(entity.person_id)
        session.add_all(
            [
                ResearchPackageExternalWork(package_id=package_id, work_id=work_id)
                for work_id in work_ids
            ]
            + [
                ResearchPackageExternalPerson(
                    package_id=package_id, person_id=person_id
                )
                for person_id in person_ids
            ]
        )


async def lesson_research_summary(
    session: AsyncSession,
    project: EditorialProject,
) -> LessonResearchSummary | None:
    """Summarize only the package currently pinned to this project."""

    if project.research_package_id is None:
        return None
    package = await session.get(ResearchPackage, project.research_package_id)
    if package is None or package.lesson_id is None:
        return None
    snapshot = package.retrieval_snapshot
    queries = snapshot.get("queries", [])
    chunks: set[str] = set()
    counter_chunks: set[str] = set()
    sources: set[str] = set()
    selected_sources: list[SelectedExternalSource] = []
    selected_source_keys: set[tuple[str, str]] = set()
    labels: list[str] = []
    role_labels = {
        "EMPIRICAL_CONTEXT": "Empirischer Kontext",
        "CONCEPTUAL_PARALLEL": "Konzeptuelle Parallele",
        "HISTORICAL_CONTEXT": "Historischer Kontext",
        "EXAMPLE": "Beispiel",
        "ILLUSTRATION": "Illustration",
        "ALTERNATIVE_EXPLANATION": "Alternative Erklärung",
        "COUNTERARGUMENT": "Gegenargument",
        "COUNTEREVIDENCE": "Gegenposition",
        "TENSION": "Spannung",
        "CHALLENGE": "Herausforderung",
        "NON_EQUIVALENCE": "Nicht gleichzusetzen",
        "OPEN_QUESTION": "Offene Frage",
    }
    if isinstance(queries, list):
        for query in queries:
            if not isinstance(query, dict):
                continue
            label = str(query.get("label") or "Externe Recherche")
            if label not in labels:
                labels.append(label)
            results = query.get("results", [])
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                if result.get("selected") is False:
                    continue
                chunk_id = str(result.get("chunk_id", ""))
                if chunk_id:
                    chunks.add(chunk_id)
                    if query.get("kind") == ResearchQuestionKind.COUNTEREVIDENCE.value:
                        counter_chunks.add(chunk_id)
                provenance = result.get("provenance", {})
                if isinstance(provenance, dict):
                    title = str(provenance.get("source_title") or "").strip()
                    if title:
                        sources.add(title)
                        raw_role = str(result.get("source_role") or "")
                        source_key = (chunk_id, raw_role)
                        if source_key not in selected_source_keys:
                            selected_source_keys.add(source_key)
                            selected_sources.append(
                                SelectedExternalSource(
                                    title=title,
                                    role=role_labels.get(raw_role, label),
                                    relevant_claim=str(result.get("text") or "")[:320],
                                    inclusion_reason=str(
                                        result.get("inclusion_reason")
                                        or f"Relevant für „{label}“."
                                    ),
                                )
                            )
    master_ready = False
    if project.semantic_master_id is not None:
        from app.lecture.models import LectureMasterVersion

        master = await session.get(LectureMasterVersion, project.semantic_master_id)
        master_ready = (
            master is not None
            and master.research_package_id == package.id
            and master.status is MasterStatus.READY
        )
    issue_codes = tuple(
        str(item.get("code", ""))
        for item in package.unresolved_issues
        if isinstance(item, dict) and item.get("code")
    )
    if master_ready:
        status_label, badge_class = "Bereit für den Entwurf", "success"
    elif chunks:
        status_label, badge_class = "Prüfung erforderlich", "warning"
    else:
        status_label, badge_class = "Keine externen Treffer", "warning"
    rejected_raw = snapshot.get("rejected_candidates", [])
    rejected_count = len(rejected_raw) if isinstance(rejected_raw, list) else 0
    return LessonResearchSummary(
        status_label=status_label,
        badge_class=badge_class,
        result_count=len(chunks),
        source_count=len(sources),
        counterevidence_count=len(counter_chunks),
        sources=tuple(sorted(sources)),
        query_labels=tuple(labels),
        issues=issue_codes,
        ready_for_writing=master_ready,
        selected_sources=tuple(selected_sources),
        rejected_count=rejected_count,
    )

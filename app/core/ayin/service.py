"""Read services for versioned Ayin data."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.models import (
    AyinConcept,
    AyinConceptVersion,
    AyinDistinction,
    AyinDistinctionVersion,
    AyinOpenQuestion,
    AyinOpenQuestionVersion,
    AyinPrinciple,
    AyinPrincipleVersion,
    AyinRelation,
    CanonDocument,
    CanonVersion,
    ExtractionRun,
    PreferredExtractionRun,
)
from app.core.ayin.schemas import (
    ConceptRead,
    ConceptVersionRead,
    DistinctionRead,
    DistinctionVersionRead,
    DocumentDetail,
    DocumentSummary,
    ExtractionRunRead,
    OpenQuestionRead,
    OpenQuestionVersionRead,
    PreferredExtractionRead,
    PrincipleRead,
    PrincipleVersionRead,
    RelationRead,
    TermFormRead,
    TermRead,
    VersionSummary,
)
from app.core.exceptions import ResourceNotFoundError
from app.core.terminology.models import Term, TermForm
from app.ops.assets.models import utc_now


class AyinReadService:
    """Assemble API/CLI read models without exposing mutable ORM objects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def documents(self) -> list[DocumentSummary]:
        rows = await self._session.scalars(
            select(CanonDocument).order_by(CanonDocument.created_at)
        )
        return [DocumentSummary.model_validate(row) for row in rows]

    async def document(self, document_id: UUID) -> DocumentDetail:
        document = await self._session.get(CanonDocument, document_id)
        if document is None:
            raise ResourceNotFoundError
        versions = list(
            await self._session.scalars(
                select(CanonVersion)
                .where(CanonVersion.document_id == document_id)
                .order_by(CanonVersion.created_at)
            )
        )
        version_ids = [item.id for item in versions]
        runs = list(
            await self._session.scalars(
                select(ExtractionRun)
                .where(ExtractionRun.canon_version_id.in_(version_ids))
                .order_by(ExtractionRun.created_at)
            )
        )
        preferred = {
            item.canon_version_id: item.extraction_run_id
            for item in await self._session.scalars(
                select(PreferredExtractionRun).where(
                    PreferredExtractionRun.canon_version_id.in_(version_ids)
                )
            )
        }
        runs_by_version: dict[UUID, list[ExtractionRunRead]] = defaultdict(list)
        for run in runs:
            runs_by_version[run.canon_version_id].append(
                ExtractionRunRead.model_validate(run)
            )
        base = DocumentSummary.model_validate(document).model_dump()
        return DocumentDetail(
            **base,
            versions=[
                VersionSummary(
                    id=version.id,
                    status=version.status,
                    corpus_zone=version.corpus_zone,
                    semantic_version=version.semantic_version,
                    source_file_hash=version.source_file_hash,
                    created_at=version.created_at,
                    preferred_extraction_run_id=preferred.get(version.id),
                    extraction_runs=runs_by_version[version.id],
                )
                for version in versions
            ],
        )

    async def concepts(self) -> list[ConceptRead]:
        identities = list(
            await self._session.scalars(
                select(AyinConcept).order_by(AyinConcept.stable_key)
            )
        )
        versions = list(
            await self._session.scalars(
                select(AyinConceptVersion).order_by(
                    AyinConceptVersion.concept_id,
                    AyinConceptVersion.version_number,
                )
            )
        )
        grouped: dict[UUID, list[ConceptVersionRead]] = defaultdict(list)
        for version in versions:
            grouped[version.concept_id].append(
                ConceptVersionRead.model_validate(version)
            )
        return [
            ConceptRead(
                id=item.id,
                stable_key=item.stable_key,
                status=item.status,
                versions=grouped[item.id],
            )
            for item in identities
        ]

    async def concept(self, stable_key: str) -> ConceptRead:
        concepts = await self.concepts()
        for concept in concepts:
            if concept.stable_key == stable_key:
                return concept
        raise ResourceNotFoundError

    async def distinctions(self) -> list[DistinctionRead]:
        identities = list(
            await self._session.scalars(
                select(AyinDistinction).order_by(AyinDistinction.stable_key)
            )
        )
        versions = list(await self._session.scalars(select(AyinDistinctionVersion)))
        grouped: dict[UUID, list[DistinctionVersionRead]] = defaultdict(list)
        for version in versions:
            grouped[version.distinction_id].append(
                DistinctionVersionRead.model_validate(version)
            )
        return [
            DistinctionRead(
                id=item.id,
                stable_key=item.stable_key,
                left_concept_id=item.left_concept_id,
                versions=grouped[item.id],
            )
            for item in identities
        ]

    async def principles(self) -> list[PrincipleRead]:
        identities = list(
            await self._session.scalars(
                select(AyinPrinciple).order_by(AyinPrinciple.stable_key)
            )
        )
        versions = list(await self._session.scalars(select(AyinPrincipleVersion)))
        grouped: dict[UUID, list[PrincipleVersionRead]] = defaultdict(list)
        for version in versions:
            grouped[version.principle_id].append(
                PrincipleVersionRead.model_validate(version)
            )
        return [
            PrincipleRead(
                id=item.id,
                stable_key=item.stable_key,
                versions=grouped[item.id],
            )
            for item in identities
        ]

    async def relations(self) -> list[RelationRead]:
        relations = await self._session.scalars(
            select(AyinRelation).order_by(
                AyinRelation.subject_concept_id,
                AyinRelation.object_concept_id,
            )
        )
        return [RelationRead.model_validate(item) for item in relations]

    async def open_questions(self) -> list[OpenQuestionRead]:
        identities = list(
            await self._session.scalars(
                select(AyinOpenQuestion).order_by(AyinOpenQuestion.stable_key)
            )
        )
        versions = list(await self._session.scalars(select(AyinOpenQuestionVersion)))
        grouped: dict[UUID, list[OpenQuestionVersionRead]] = defaultdict(list)
        for version in versions:
            grouped[version.open_question_id].append(
                OpenQuestionVersionRead.model_validate(version)
            )
        return [
            OpenQuestionRead(
                id=item.id,
                stable_key=item.stable_key,
                versions=grouped[item.id],
            )
            for item in identities
        ]

    async def terms(self, query: str | None = None) -> list[TermRead]:
        identities = list(
            await self._session.scalars(select(Term).order_by(Term.stable_key))
        )
        forms = list(await self._session.scalars(select(TermForm)))
        grouped: dict[UUID, list[TermFormRead]] = defaultdict(list)
        for form in forms:
            grouped[form.term_id].append(TermFormRead.model_validate(form))
        results = [
            TermRead(
                id=item.id,
                stable_key=item.stable_key,
                concept_id=item.concept_id,
                status=item.status,
                forms=grouped[item.id],
            )
            for item in identities
        ]
        if query is None:
            return results
        folded = query.casefold()
        return [
            item
            for item in results
            if folded in item.stable_key.casefold()
            or any(folded in form.form.casefold() for form in item.forms)
        ]


class AyinExtractionService:
    """Manage explicit extraction preference without deleting run history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prefer(
        self, run_id: UUID, *, selected_by: str, reason: str
    ) -> PreferredExtractionRead:
        if not selected_by.strip() or not reason.strip():
            raise ValueError("selected_by and reason are required")
        run = await self._session.get(ExtractionRun, run_id)
        if run is None:
            raise ResourceNotFoundError
        preference = await self._session.get(
            PreferredExtractionRun, run.canon_version_id
        )
        if preference is None:
            preference = PreferredExtractionRun(
                canon_version_id=run.canon_version_id,
                extraction_run_id=run.id,
                selected_by=selected_by,
                reason=reason,
            )
            self._session.add(preference)
        else:
            preference.extraction_run_id = run.id
            preference.selected_by = selected_by
            preference.reason = reason
            preference.selected_at = utc_now()
        await self._session.flush()
        return PreferredExtractionRead.model_validate(preference)

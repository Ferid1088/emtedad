"""Transactional, idempotent import of Ayin Working PDFs."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import (
    CorpusZone,
    EditorialStatus,
    LanguageCode,
    OpenQuestionStatus,
    ReviewKind,
    ReviewStatus,
)
from app.core.ayin.extractor import (
    ExtractedPassage,
    PdfExtraction,
    PopplerPdfExtractor,
)
from app.core.ayin.models import (
    AyinConcept,
    AyinConceptVersion,
    AyinDistinction,
    AyinDistinctionVersion,
    AyinOpenQuestion,
    AyinOpenQuestionVersion,
    AyinPassageReview,
    AyinPrinciple,
    AyinPrincipleVersion,
    AyinReviewItem,
    CanonDocument,
    CanonPassage,
    CanonVersion,
    CanonVersionSourceAsset,
)
from app.core.ayin.normalization import normalize_persian_text
from app.core.ayin.repository import AyinRepository
from app.core.ayin.seed import AyinSeedManifest, load_seed_manifest
from app.core.terminology.models import Term, TermForm
from app.db.session import Database
from app.ops.assets.repository import AssetRepository
from app.storage.base import ObjectStore, StoredObject

IMPORTER_VERSION = "ayin-pdf-v1"
DOCUMENT_SLUG = "ayin-e-emtedad"


class AyinImportError(RuntimeError):
    """Raised when an Ayin import cannot preserve its identity or provenance."""


@dataclass(frozen=True)
class ImportResult:
    """Operator-facing import outcome."""

    document_id: UUID
    version_id: UUID
    source_sha256: str
    page_count: int
    passage_count: int
    concept_count: int
    distinction_count: int
    principle_count: int
    open_question_count: int
    term_count: int
    term_form_count: int
    review_item_count: int
    created: bool
    corpus_zone: CorpusZone
    status: EditorialStatus


class AyinImporter:
    """Coordinate object storage, extraction, and one database transaction."""

    def __init__(
        self,
        database: Database,
        object_store: ObjectStore,
        *,
        extractor: PopplerPdfExtractor | None = None,
        importer_version: str = IMPORTER_VERSION,
    ) -> None:
        self._database = database
        self._object_store = object_store
        self._extractor = extractor or PopplerPdfExtractor()
        self._importer_version = importer_version

    async def import_file(
        self,
        source: Path,
        *,
        seed_manifest: AyinSeedManifest | None = None,
    ) -> ImportResult:
        """Import one PDF only as Working, safely reusing an identical import."""

        stored, extraction = await asyncio.to_thread(
            self._prepare_source, source, seed_manifest
        )

        async with self._database.transaction() as session:
            import_identity = _import_identity(
                self._importer_version,
                extraction.extractor_name,
                extraction.extractor_version,
            )
            repository = AyinRepository(session)
            document = await repository.document_by_slug(DOCUMENT_SLUG)
            if document is None:
                document = CanonDocument(
                    slug=DOCUMENT_SLUG,
                    document_type="ayin",
                    title="آیین امتداد",
                    original_language=LanguageCode.FA,
                    corpus_zone=CorpusZone.AYIN_WORKING,
                )
                session.add(document)
                await session.flush()

            existing = await repository.version_by_import_identity(
                document.id, stored.sha256, import_identity
            )
            if existing is not None:
                return await self._existing_result(session, document, existing)

            asset, _ = await AssetRepository(session).get_or_create(
                stored,
                media_type="application/pdf",
                original_filename=source.name,
            )
            version = CanonVersion(
                document_id=document.id,
                semantic_version=None,
                status=EditorialStatus.DRAFT,
                corpus_zone=CorpusZone.AYIN_WORKING,
                source_file_hash=stored.sha256,
                importer_version=import_identity,
                extractor_name=extraction.extractor_name,
                extractor_version=extraction.extractor_version,
                page_count=extraction.page_count,
                change_summary=(
                    "Direct PDF extraction; Working source, not Canon approval."
                ),
            )
            session.add(version)
            await session.flush()
            session.add(
                CanonVersionSourceAsset(
                    canon_version_id=version.id,
                    source_asset_id=asset.id,
                )
            )
            await session.flush()

            passage_models = [
                CanonPassage(
                    canon_version_id=version.id,
                    source_asset_id=asset.id,
                    sequence=item.sequence,
                    page_number=item.page_number,
                    printed_page_label=item.printed_page_label,
                    heading_path=list(item.heading_path),
                    paragraph_index=item.paragraph_index,
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text,
                    content_hash=item.content_hash,
                    language=LanguageCode.FA,
                )
                for item in extraction.passages
            ]
            session.add_all(passage_models)
            await session.flush()
            await self._add_extraction_reviews(
                session, version.id, extraction.passages, passage_models
            )

            counts = _SeedCounts()
            if seed_manifest is not None:
                counts = await self._load_seed(
                    session, version.id, passage_models, seed_manifest
                )
            await session.flush()
            review_count = await session.scalar(
                select(func.count(AyinReviewItem.id)).where(
                    AyinReviewItem.canon_version_id == version.id
                )
            )
            return ImportResult(
                document_id=document.id,
                version_id=version.id,
                source_sha256=stored.sha256,
                page_count=extraction.page_count,
                passage_count=len(passage_models),
                concept_count=counts.concepts,
                distinction_count=counts.distinctions,
                principle_count=counts.principles,
                open_question_count=counts.open_questions,
                term_count=counts.terms,
                term_form_count=counts.term_forms,
                review_item_count=int(review_count or 0),
                created=True,
                corpus_zone=CorpusZone.AYIN_WORKING,
                status=EditorialStatus.DRAFT,
            )

    def _prepare_source(
        self, source: Path, seed_manifest: AyinSeedManifest | None
    ) -> tuple[StoredObject, PdfExtraction]:
        if not source.is_file():
            raise AyinImportError(f"source file does not exist: {source}")
        with source.open("rb") as stream:
            stored = self._object_store.put_stream(stream)
        if seed_manifest is not None and stored.sha256 != seed_manifest.source_sha256:
            raise AyinImportError("source SHA-256 does not match the seed manifest")
        extraction = self._extractor.extract(source)
        if (
            seed_manifest is not None
            and extraction.page_count != seed_manifest.expected_page_count
        ):
            raise AyinImportError("source page count does not match the seed manifest")
        return stored, extraction

    async def _existing_result(
        self, session: AsyncSession, document: CanonDocument, version: CanonVersion
    ) -> ImportResult:
        count_models = (
            (CanonPassage, "passages"),
            (AyinConceptVersion, "concepts"),
            (AyinDistinctionVersion, "distinctions"),
            (AyinPrincipleVersion, "principles"),
            (AyinOpenQuestionVersion, "open_questions"),
            (TermForm, "term_forms"),
            (AyinReviewItem, "reviews"),
        )
        counts: dict[str, int] = {}
        for model, key in count_models:
            count = await session.scalar(
                select(func.count(model.id)).where(model.canon_version_id == version.id)
            )
            counts[key] = int(count or 0)
        term_count = await session.scalar(select(func.count(Term.id)))
        return ImportResult(
            document_id=document.id,
            version_id=version.id,
            source_sha256=version.source_file_hash,
            page_count=version.page_count,
            passage_count=counts["passages"],
            concept_count=counts["concepts"],
            distinction_count=counts["distinctions"],
            principle_count=counts["principles"],
            open_question_count=counts["open_questions"],
            term_count=int(term_count or 0),
            term_form_count=counts["term_forms"],
            review_item_count=counts["reviews"],
            created=False,
            corpus_zone=version.corpus_zone,
            status=version.status,
        )

    @staticmethod
    async def _add_extraction_reviews(
        session: AsyncSession,
        version_id: UUID,
        extracted: tuple[ExtractedPassage, ...],
        passages: list[CanonPassage],
    ) -> None:
        for item, passage in zip(extracted, passages, strict=True):
            if not item.needs_review:
                continue
            review = AyinReviewItem(
                canon_version_id=version_id,
                kind=ReviewKind.EXTRACTION_AMBIGUITY,
                status=ReviewStatus.OPEN,
                page_number=item.page_number,
                message="Direct extraction contains a suspicious embedded-font glyph.",
            )
            session.add(review)
            await session.flush()
            session.add(
                AyinPassageReview(review_item_id=review.id, passage_id=passage.id)
            )

    async def _load_seed(
        self,
        session: AsyncSession,
        version_id: UUID,
        passages: list[CanonPassage],
        manifest: AyinSeedManifest,
    ) -> "_SeedCounts":
        by_page: dict[int, list[CanonPassage]] = defaultdict(list)
        for passage in passages:
            by_page[passage.page_number].append(passage)

        concepts: dict[str, AyinConcept] = {}
        concept_count = 0
        for concept_seed in manifest.concepts:
            concept_passage = await self._source_passage(
                session,
                version_id,
                by_page,
                concept_seed.page,
                concept_seed.anchor,
            )
            if concept_passage is None:
                continue
            concept = await _identity(session, AyinConcept, concept_seed.stable_key)
            if concept is None:
                concept = AyinConcept(
                    stable_key=concept_seed.stable_key,
                    status=EditorialStatus.REVIEW,
                )
                session.add(concept)
                await session.flush()
            concepts[concept_seed.stable_key] = concept
            version_number = await _next_version(
                session, AyinConceptVersion, "concept_id", concept.id
            )
            session.add(
                AyinConceptVersion(
                    concept_id=concept.id,
                    canon_version_id=version_id,
                    source_passage_id=concept_passage.id,
                    version_number=version_number,
                    definition=concept_seed.definition,
                    scope="AYIN_WORKING source-backed proposal",
                    notes="Imported from reviewed Phase 2 seed; not Canon approval.",
                    approval_status=EditorialStatus.REVIEW,
                )
            )
            concept_count += 1

        distinction_count = 0
        for distinction_seed in manifest.distinctions:
            distinction_passage = await self._source_passage(
                session,
                version_id,
                by_page,
                distinction_seed.page,
                distinction_seed.anchor,
            )
            left = concepts.get(distinction_seed.left)
            if distinction_passage is None or left is None:
                continue
            distinction = await _identity(
                session, AyinDistinction, distinction_seed.stable_key
            )
            if distinction is None:
                distinction = AyinDistinction(
                    stable_key=distinction_seed.stable_key,
                    left_concept_id=left.id,
                )
                session.add(distinction)
                await session.flush()
            number = await _next_version(
                session, AyinDistinctionVersion, "distinction_id", distinction.id
            )
            session.add(
                AyinDistinctionVersion(
                    distinction_id=distinction.id,
                    canon_version_id=version_id,
                    source_passage_id=distinction_passage.id,
                    version_number=number,
                    relation=distinction_seed.relation,
                    right_label=distinction_seed.right_label,
                    explanation=distinction_seed.explanation,
                    discourse_type=distinction_seed.discourse_type,
                    status=EditorialStatus.REVIEW,
                )
            )
            distinction_count += 1

        principle_count = 0
        for principle_seed in manifest.principles:
            principle_passage = await self._source_passage(
                session,
                version_id,
                by_page,
                principle_seed.page,
                principle_seed.anchor,
            )
            if principle_passage is None:
                continue
            principle = await _identity(
                session, AyinPrinciple, principle_seed.stable_key
            )
            if principle is None:
                principle = AyinPrinciple(stable_key=principle_seed.stable_key)
                session.add(principle)
                await session.flush()
            number = await _next_version(
                session, AyinPrincipleVersion, "principle_id", principle.id
            )
            session.add(
                AyinPrincipleVersion(
                    principle_id=principle.id,
                    canon_version_id=version_id,
                    source_passage_id=principle_passage.id,
                    version_number=number,
                    statement=principle_seed.statement,
                    discourse_type=principle_seed.discourse_type,
                    status=EditorialStatus.REVIEW,
                )
            )
            principle_count += 1

        question_count = 0
        for question_seed in manifest.open_questions:
            question_passage = await self._source_passage(
                session,
                version_id,
                by_page,
                question_seed.page,
                question_seed.anchor,
            )
            if question_passage is None:
                continue
            question = await _identity(
                session, AyinOpenQuestion, question_seed.stable_key
            )
            if question is None:
                question = AyinOpenQuestion(stable_key=question_seed.stable_key)
                session.add(question)
                await session.flush()
            number = await _next_version(
                session, AyinOpenQuestionVersion, "open_question_id", question.id
            )
            session.add(
                AyinOpenQuestionVersion(
                    open_question_id=question.id,
                    canon_version_id=version_id,
                    source_passage_id=question_passage.id,
                    version_number=number,
                    question=question_seed.question,
                    context=question_seed.context,
                    discourse_type=question_seed.discourse_type,
                    status=OpenQuestionStatus.OPEN,
                )
            )
            question_count += 1

        term_count = 0
        term_form_count = 0
        for term_seed in manifest.terms:
            term_passage = await self._source_passage(
                session, version_id, by_page, term_seed.page, term_seed.anchor
            )
            concept = concepts.get(term_seed.concept)
            if term_passage is None or concept is None:
                continue
            term = await _identity(session, Term, term_seed.stable_key)
            if term is None:
                term = Term(
                    stable_key=term_seed.stable_key,
                    concept_id=concept.id,
                    status=EditorialStatus.REVIEW,
                )
                session.add(term)
                await session.flush()
            term_count += 1
            for form in term_seed.forms:
                number = await _next_term_form_version(
                    session, term.id, form.language.value, form.form_type.value
                )
                session.add(
                    TermForm(
                        term_id=term.id,
                        canon_version_id=version_id,
                        source_passage_id=term_passage.id,
                        language=form.language,
                        script=form.script,
                        scope="global",
                        form=form.form,
                        form_type=form.form_type,
                        explanation=(
                            "Editorially forbidden default equivalent."
                            if form.form_type.value == "forbidden_equivalent"
                            else None
                        ),
                        approval_status=form.status,
                        version=number,
                        notes="Working terminology; no translation is finalized.",
                    )
                )
                term_form_count += 1

        return _SeedCounts(
            concepts=concept_count,
            distinctions=distinction_count,
            principles=principle_count,
            open_questions=question_count,
            terms=term_count,
            term_forms=term_form_count,
        )

    @staticmethod
    async def _source_passage(
        session: AsyncSession,
        version_id: UUID,
        by_page: dict[int, list[CanonPassage]],
        page: int,
        anchor: str,
    ) -> CanonPassage | None:
        normalized_anchor = normalize_persian_text(anchor)
        matches = [
            passage
            for passage in by_page.get(page, [])
            if normalized_anchor in passage.normalized_text
        ]
        if len(matches) == 1:
            return matches[0]
        session.add(
            AyinReviewItem(
                canon_version_id=version_id,
                kind=ReviewKind.SEED_PROVENANCE,
                status=ReviewStatus.OPEN,
                page_number=page,
                message=(
                    f"Seed anchor resolved to {len(matches)} passages: "
                    f"{normalized_anchor[:80]}"
                ),
            )
        )
        return None


@dataclass(frozen=True)
class _SeedCounts:
    concepts: int = 0
    distinctions: int = 0
    principles: int = 0
    open_questions: int = 0
    terms: int = 0
    term_forms: int = 0


async def _identity(session: AsyncSession, model: Any, stable_key: str) -> Any:
    result = await session.execute(select(model).where(model.stable_key == stable_key))
    return result.scalar_one_or_none()


async def _next_version(
    session: AsyncSession, model: Any, identity_field: str, identity_id: UUID
) -> int:
    field = getattr(model, identity_field)
    result = await session.scalar(
        select(func.max(model.version_number)).where(field == identity_id)
    )
    return int(result or 0) + 1


async def _next_term_form_version(
    session: AsyncSession, term_id: UUID, language: str, form_type: str
) -> int:
    result = await session.scalar(
        select(func.max(TermForm.version)).where(
            TermForm.term_id == term_id,
            TermForm.language == language,
            TermForm.form_type == form_type,
        )
    )
    return int(result or 0) + 1


def _import_identity(
    importer_version: str, extractor_name: str, extractor_version: str
) -> str:
    """Keep parser provenance distinct within the database length limit."""

    identity = f"{importer_version}:{extractor_name}:{extractor_version}"
    if len(identity) <= 64:
        return identity
    digest = sha256(identity.encode()).hexdigest()[:32]
    return f"{identity[:31]}:{digest}"


def default_seed_manifest() -> AyinSeedManifest:
    """Load the repository's reviewed current-source Working seed."""

    return load_seed_manifest()

"""Transactional, idempotent import of Ayin Working PDFs."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
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
    ReviewReason,
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
    ExtractionRun,
    PreferredExtractionRun,
)
from app.core.ayin.normalization import normalize_persian_text
from app.core.ayin.provenance import configuration_hash, passage_set_hash
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
    extraction_run_id: UUID
    source_sha256: str
    output_hash: str
    page_count: int
    passage_count: int
    concept_count: int
    distinction_count: int
    principle_count: int
    open_question_count: int
    term_count: int
    term_form_count: int
    review_item_count: int
    source_version_created: bool
    extraction_run_created: bool
    is_preferred: bool
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

        config_hash = configuration_hash(extraction.configuration)
        output_hash = passage_set_hash(extraction.passages)

        async with self._database.transaction() as session:
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

            asset, _ = await AssetRepository(session).get_or_create(
                stored,
                media_type="application/pdf",
                original_filename=source.name,
            )
            version = await repository.version_by_source_identity(
                document.id, stored.sha256
            )
            source_version_created = version is None
            if version is None:
                version = CanonVersion(
                    document_id=document.id,
                    semantic_version=None,
                    status=EditorialStatus.DRAFT,
                    corpus_zone=CorpusZone.AYIN_WORKING,
                    source_file_hash=stored.sha256,
                    change_summary=(
                        "Working source artifact; extraction runs are versioned "
                        "separately."
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
            else:
                linked_asset = await session.scalar(
                    select(CanonVersionSourceAsset.source_asset_id).where(
                        CanonVersionSourceAsset.canon_version_id == version.id
                    )
                )
                if linked_asset != asset.id:
                    raise AyinImportError(
                        "source version does not reference the content-addressed asset"
                    )

            run = await repository.extraction_run_by_identity(
                version.id,
                importer_version=self._importer_version,
                extractor_name=extraction.extractor_name,
                extractor_version=extraction.extractor_version,
                normalization_version=extraction.normalization_version,
                segmentation_version=extraction.segmentation_version,
                configuration_hash=config_hash,
            )
            if run is not None:
                if (
                    run.output_hash != output_hash
                    or run.page_count != extraction.page_count
                    or run.passage_count != len(extraction.passages)
                ):
                    raise AyinImportError(
                        "identical extraction identity produced different output"
                    )
                passage_models = list(
                    await session.scalars(
                        select(CanonPassage)
                        .where(CanonPassage.extraction_run_id == run.id)
                        .order_by(CanonPassage.sequence)
                    )
                )
                if seed_manifest is not None and not await _has_seed_data(
                    session, version.id
                ):
                    await self._load_seed(
                        session,
                        version.id,
                        run.id,
                        passage_models,
                        seed_manifest,
                    )
                    await session.flush()
                return await self._run_result(
                    session,
                    document,
                    version,
                    run,
                    source_version_created=source_version_created,
                    extraction_run_created=False,
                )

            run = ExtractionRun(
                canon_version_id=version.id,
                source_asset_id=asset.id,
                importer_version=self._importer_version,
                extractor_name=extraction.extractor_name,
                extractor_version=extraction.extractor_version,
                normalization_version=extraction.normalization_version,
                segmentation_version=extraction.segmentation_version,
                configuration=extraction.configuration,
                configuration_hash=config_hash,
                output_hash=output_hash,
                page_count=extraction.page_count,
                passage_count=len(extraction.passages),
            )
            session.add(run)
            await session.flush()

            passage_models = [
                CanonPassage(
                    canon_version_id=version.id,
                    extraction_run_id=run.id,
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
                session,
                version.id,
                run.id,
                extraction.passages,
                passage_models,
            )

            if seed_manifest is not None and not await _has_seed_data(
                session, version.id
            ):
                await self._load_seed(
                    session,
                    version.id,
                    run.id,
                    passage_models,
                    seed_manifest,
                )
            await session.flush()
            return await self._run_result(
                session,
                document,
                version,
                run,
                source_version_created=source_version_created,
                extraction_run_created=True,
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

    async def _run_result(
        self,
        session: AsyncSession,
        document: CanonDocument,
        version: CanonVersion,
        run: ExtractionRun,
        *,
        source_version_created: bool,
        extraction_run_created: bool,
    ) -> ImportResult:
        count_models = (
            (AyinConceptVersion, "concepts"),
            (AyinDistinctionVersion, "distinctions"),
            (AyinPrincipleVersion, "principles"),
            (AyinOpenQuestionVersion, "open_questions"),
            (TermForm, "term_forms"),
        )
        counts: dict[str, int] = {}
        for model, key in count_models:
            count = await session.scalar(
                select(func.count(model.id)).where(model.canon_version_id == version.id)
            )
            counts[key] = int(count or 0)
        passage_count = await session.scalar(
            select(func.count(CanonPassage.id)).where(
                CanonPassage.extraction_run_id == run.id
            )
        )
        review_count = await session.scalar(
            select(func.count(AyinReviewItem.id)).where(
                AyinReviewItem.extraction_run_id == run.id
            )
        )
        term_count = await session.scalar(
            select(func.count(func.distinct(TermForm.term_id))).where(
                TermForm.canon_version_id == version.id
            )
        )
        preferred = await session.scalar(
            select(PreferredExtractionRun.extraction_run_id).where(
                PreferredExtractionRun.canon_version_id == version.id
            )
        )
        return ImportResult(
            document_id=document.id,
            version_id=version.id,
            extraction_run_id=run.id,
            source_sha256=version.source_file_hash,
            output_hash=run.output_hash,
            page_count=run.page_count,
            passage_count=int(passage_count or 0),
            concept_count=counts["concepts"],
            distinction_count=counts["distinctions"],
            principle_count=counts["principles"],
            open_question_count=counts["open_questions"],
            term_count=int(term_count or 0),
            term_form_count=counts["term_forms"],
            review_item_count=int(review_count or 0),
            source_version_created=source_version_created,
            extraction_run_created=extraction_run_created,
            is_preferred=preferred == run.id,
            corpus_zone=version.corpus_zone,
            status=version.status,
        )

    @staticmethod
    async def _add_extraction_reviews(
        session: AsyncSession,
        version_id: UUID,
        extraction_run_id: UUID,
        extracted: tuple[ExtractedPassage, ...],
        passages: list[CanonPassage],
    ) -> None:
        for item, passage in zip(extracted, passages, strict=True):
            for reason in item.review_reasons:
                review = AyinReviewItem(
                    canon_version_id=version_id,
                    extraction_run_id=extraction_run_id,
                    kind=ReviewKind.EXTRACTION_AMBIGUITY,
                    reason_for_review=reason,
                    status=ReviewStatus.OPEN,
                    page_number=item.page_number,
                    message=_review_message(reason),
                )
                session.add(review)
                await session.flush()
                session.add(
                    AyinPassageReview(
                        review_item_id=review.id,
                        extraction_run_id=extraction_run_id,
                        passage_id=passage.id,
                    )
                )

    async def _load_seed(
        self,
        session: AsyncSession,
        version_id: UUID,
        extraction_run_id: UUID,
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
                extraction_run_id,
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
                extraction_run_id,
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
                extraction_run_id,
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
                extraction_run_id,
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
                session,
                version_id,
                extraction_run_id,
                by_page,
                term_seed.page,
                term_seed.anchor,
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
        extraction_run_id: UUID,
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
                extraction_run_id=extraction_run_id,
                kind=ReviewKind.SEED_PROVENANCE,
                reason_for_review=ReviewReason.SEED_PROVENANCE,
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


async def _has_seed_data(session: AsyncSession, version_id: UUID) -> bool:
    count = await session.scalar(
        select(func.count(AyinConceptVersion.id)).where(
            AyinConceptVersion.canon_version_id == version_id
        )
    )
    return bool(count)


def _review_message(reason: ReviewReason) -> str:
    messages = {
        ReviewReason.SUSPICIOUS_EXTRACTION: "Direct extraction requires review.",
        ReviewReason.HEADING_UNCERTAINTY: "Extracted heading boundary is uncertain.",
        ReviewReason.BROKEN_PARAGRAPH: "Extracted paragraph boundary may be broken.",
        ReviewReason.CHARACTER_CORRUPTION: (
            "Direct extraction contains a suspicious embedded-font glyph."
        ),
        ReviewReason.PAGE_LAYOUT_AMBIGUITY: (
            "Page layout may have changed extraction order or grouping."
        ),
        ReviewReason.POSSIBLE_MISSING_CONTENT: (
            "Direct extraction may be missing source content."
        ),
        ReviewReason.SEED_PROVENANCE: "Seed source anchor requires review.",
    }
    return messages[reason]


def default_seed_manifest() -> AyinSeedManifest:
    """Load the repository's reviewed current-source Working seed."""

    return load_seed_manifest()

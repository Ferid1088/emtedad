"""Transactional, idempotent Manasek Working import."""

import asyncio
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
    ReviewStatus,
)
from app.core.ayin.models import AyinConcept, AyinConceptVersion, CanonVersion
from app.core.ayin.provenance import configuration_hash, passage_set_hash
from app.db.session import Database
from app.ops.assets.repository import AssetRepository
from app.ritual.domain import (
    GATE_ORDER,
    RitualFamilyType,
    RitualMode,
    RitualPieceType,
    RitualRelationType,
    RitualReviewReason,
)
from app.ritual.extractor import PopplerRitualExtractor, RitualPdfExtraction
from app.ritual.models import (
    ArchitectureVersion,
    Gate,
    GateConceptLink,
    GateVersion,
    LocalizationSafetyRule,
    MusicSpecification,
    Ritual,
    RitualConceptLink,
    RitualCue,
    RitualDocument,
    RitualExtractionRun,
    RitualFamily,
    RitualFamilyVersion,
    RitualLocalization,
    RitualPassage,
    RitualReturn,
    RitualReviewFlag,
    RitualSequenceItem,
    RitualSourceVersion,
    RitualStage,
    RitualVersion,
    RitualVersionSafetyRule,
    RitualVersionSourceAsset,
    SafetyRule,
    SafetyRuleVersion,
    StageConceptLink,
    StageConceptLinkProposal,
)
from app.ritual.parser import ParsedManasek, ParsedRitual, parse_manasek
from app.ritual.repository import RitualRepository
from app.ritual.seed import (
    GATE_CONCEPTS,
    GATES,
    SAFETY_RULES,
    STAGE_CONCEPTS,
    STAGES,
)
from app.storage.base import ObjectStore, StoredObject

IMPORTER_VERSION = "manasek-pdf-v1"
DOCUMENT_SLUG = "manasek-v1"


class ManasekImportError(RuntimeError):
    """Raised when ritual identity or source provenance cannot be preserved."""


@dataclass(frozen=True)
class ManasekImportResult:
    document_id: UUID
    source_version_id: UUID
    extraction_run_id: UUID
    source_sha256: str
    output_hash: str
    page_count: int
    passage_count: int
    gate_count: int
    stage_count: int
    gate_ritual_count: int
    return_count: int
    collective_count: int
    cue_count: int
    music_specification_count: int
    concept_link_count: int
    concept_proposal_count: int
    safety_rule_count: int
    review_flag_count: int
    source_version_created: bool
    extraction_run_created: bool
    corpus_zone: CorpusZone
    status: EditorialStatus


class ManasekImporter:
    """Import a source artifact and its explicit ritual structure atomically."""

    def __init__(
        self,
        database: Database,
        object_store: ObjectStore,
        *,
        extractor: PopplerRitualExtractor | None = None,
        importer_version: str = IMPORTER_VERSION,
    ) -> None:
        self._database = database
        self._store = object_store
        self._extractor = extractor or PopplerRitualExtractor()
        self._importer_version = importer_version

    async def import_file(self, source: Path) -> ManasekImportResult:
        stored, extraction, parsed = await asyncio.to_thread(self._prepare, source)
        config_hash = configuration_hash(extraction.configuration)
        output_hash = passage_set_hash(extraction.passages)

        async with self._database.transaction() as session:
            ayin_version = await self._current_ayin_version(session)
            repository = RitualRepository(session)
            document = await repository.document_by_slug(DOCUMENT_SLUG)
            if document is None:
                document = RitualDocument(
                    slug=DOCUMENT_SLUG,
                    title="کتابچه جامع مناسک آیین امتداد",
                    original_language=LanguageCode.FA,
                    corpus_zone=CorpusZone.MANASEK_WORKING,
                )
                session.add(document)
                await session.flush()

            asset, _ = await AssetRepository(session).get_or_create(
                stored,
                media_type="application/pdf",
                original_filename=source.name,
            )
            source_version = await repository.version_by_source(
                document.id, stored.sha256
            )
            source_version_created = source_version is None
            if source_version is None:
                source_version = RitualSourceVersion(
                    document_id=document.id,
                    designed_against_ayin_version_id=ayin_version.id,
                    semantic_version=None,
                    status=EditorialStatus.DRAFT,
                    corpus_zone=CorpusZone.MANASEK_WORKING,
                    source_file_hash=stored.sha256,
                    change_summary=(
                        "Working Manasek source; extraction runs are separate."
                    ),
                )
                session.add(source_version)
                await session.flush()
                session.add(
                    RitualVersionSourceAsset(
                        source_version_id=source_version.id,
                        source_asset_id=asset.id,
                    )
                )
                await session.flush()

            run = await repository.run_by_identity(
                source_version.id,
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
                    raise ManasekImportError(
                        "identical extraction identity produced different output"
                    )
                await self._ensure_extraction_review_flag(
                    session, source_version.id, run.id
                )
                return await self._result(
                    session,
                    document,
                    source_version,
                    run,
                    source_version_created=source_version_created,
                    extraction_run_created=False,
                )

            run = RitualExtractionRun(
                source_version_id=source_version.id,
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
            passages = {
                item.page_number: RitualPassage(
                    source_version_id=source_version.id,
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
            }
            session.add_all(passages.values())
            await session.flush()

            has_structure = bool(
                await session.scalar(
                    select(func.count(RitualVersion.id)).where(
                        RitualVersion.source_version_id == source_version.id
                    )
                )
            )
            if not has_structure:
                await self._load_structure(
                    session,
                    source_version,
                    run,
                    ayin_version,
                    passages,
                    parsed,
                )
            await self._ensure_extraction_review_flag(
                session, source_version.id, run.id
            )
            await session.flush()
            return await self._result(
                session,
                document,
                source_version,
                run,
                source_version_created=source_version_created,
                extraction_run_created=True,
            )

    def _prepare(
        self, source: Path
    ) -> tuple[StoredObject, RitualPdfExtraction, ParsedManasek]:
        if not source.is_file():
            raise ManasekImportError(f"source file does not exist: {source}")
        with source.open("rb") as stream:
            stored = self._store.put_stream(stream)
        extraction = self._extractor.extract(source)
        return stored, extraction, parse_manasek(extraction)

    @staticmethod
    async def _current_ayin_version(session: AsyncSession) -> CanonVersion:
        versions = list(
            await session.scalars(
                select(CanonVersion)
                .where(CanonVersion.corpus_zone == CorpusZone.AYIN_WORKING)
                .order_by(CanonVersion.created_at.desc())
            )
        )
        if len(versions) != 1:
            raise ManasekImportError(
                "Phase 3 requires exactly one explicit AYIN_WORKING source version"
            )
        return versions[0]

    async def _load_structure(
        self,
        session: AsyncSession,
        source_version: RitualSourceVersion,
        run: RitualExtractionRun,
        ayin_version: CanonVersion,
        passages: dict[int, RitualPassage],
        parsed: ParsedManasek,
    ) -> None:
        families: dict[RitualFamilyType, RitualFamily] = {}
        for family_type in RitualFamilyType:
            family = await session.scalar(
                select(RitualFamily).where(RitualFamily.family_type == family_type)
            )
            if family is None:
                family = RitualFamily(
                    stable_key=family_type.value.lower(), family_type=family_type
                )
                session.add(family)
                await session.flush()
            families[family_type] = family
        session.add(
            RitualFamilyVersion(
                family_id=families[RitualFamilyType.GATE].id,
                source_version_id=source_version.id,
                source_passage_id=passages[2].id,
                version_number=1,
                title_fa="مناسک دروازه‌ای",
                description="پنج زاویه نمادین توجه؛ نه اجزای بن یا عناصر متافیزیکی.",
                status=EditorialStatus.DRAFT,
            )
        )

        gates: dict[object, Gate] = {}
        for position, gate_seed in enumerate(GATES, start=1):
            gate = await session.scalar(
                select(Gate).where(Gate.stable_key == gate_seed.key)
            )
            if gate is None:
                gate = Gate(stable_key=gate_seed.key, sequence_position=position)
                session.add(gate)
                await session.flush()
            gates[gate_seed.key] = gate
            session.add(
                GateVersion(
                    gate_id=gate.id,
                    source_version_id=source_version.id,
                    source_passage_id=passages[2].id,
                    version_number=1,
                    title_fa=gate_seed.title_fa,
                    symbolic_role=gate_seed.role,
                    is_bon_component=False,
                    is_metaphysical_element=False,
                    is_personality_category=False,
                    status=EditorialStatus.DRAFT,
                )
            )

        individual = ArchitectureVersion(
            source_version_id=source_version.id,
            source_passage_id=passages[2].id,
            mode=RitualMode.INDIVIDUAL,
            version_number=1,
            title="معماری هفت‌مرحله‌ای فردی",
            status=EditorialStatus.DRAFT,
        )
        collective = ArchitectureVersion(
            source_version_id=source_version.id,
            source_passage_id=passages[40].id,
            mode=RitualMode.COLLECTIVE,
            version_number=1,
            title="معماری مستقل جمعی",
            status=EditorialStatus.DRAFT,
        )
        session.add_all([individual, collective])
        await session.flush()

        stages: dict[int, RitualStage] = {}
        for position, stage_seed in enumerate(STAGES, start=1):
            stage = RitualStage(
                architecture_version_id=individual.id,
                source_version_id=source_version.id,
                source_passage_id=passages[4].id,
                stable_key=stage_seed.key,
                sequence_position=position,
                title_fa=stage_seed.title_fa,
                purpose=stage_seed.purpose,
            )
            stages[position] = stage
            session.add(stage)
        await session.flush()

        safety_versions = await self._load_safety_rules(
            session, source_version.id, passages
        )
        ritual_versions: list[tuple[ParsedRitual, RitualVersion]] = []
        individual_position = 0
        for parsed_ritual in parsed.rituals:
            ritual = await session.scalar(
                select(Ritual).where(Ritual.stable_key == parsed_ritual.stable_key)
            )
            if ritual is None:
                ritual = Ritual(stable_key=parsed_ritual.stable_key)
                session.add(ritual)
                await session.flush()
            architecture = (
                collective
                if parsed_ritual.piece_type is RitualPieceType.COLLECTIVE
                else individual
            )
            stage_model: RitualStage | None = (
                stages[parsed_ritual.stage_position]
                if parsed_ritual.stage_position is not None
                else None
            )
            gate = gates.get(parsed_ritual.gate)
            passage = passages[parsed_ritual.page]
            ritual_version = RitualVersion(
                ritual_id=ritual.id,
                source_version_id=source_version.id,
                source_passage_id=passage.id,
                architecture_version_id=architecture.id,
                family_id=families[RitualFamilyType.GATE].id,
                designed_against_ayin_version_id=ayin_version.id,
                stage_id=stage_model.id if stage_model else None,
                gate_id=gate.id if gate else None,
                version_number=1,
                piece_type=parsed_ritual.piece_type,
                mode=(
                    RitualMode.COLLECTIVE
                    if parsed_ritual.piece_type is RitualPieceType.COLLECTIVE
                    else RitualMode.INDIVIDUAL
                ),
                title=parsed_ritual.title,
                purpose=parsed_ritual.purpose,
                estimated_duration_seconds=parsed_ritual.duration_seconds,
                preparation=(
                    "حلقه یا نیم‌دایره؛ تماس و نگاه فقط با رضایت روشن."
                    if parsed_ritual.piece_type is RitualPieceType.COLLECTIVE
                    else None
                ),
                experiential_instructions=parsed_ritual.instructions,
                safety_notes=("چشم‌بستن، حرکت، لمس، سخن و اشتراک‌گذاری اختیاری است."),
                exit_instructions=(
                    "می‌توانی توقف کنی، چشم‌ها را باز کنی، بنشینی، صدا را "
                    "کم کنی، آب بنوشی یا کاملاً خارج شوی."
                ),
                status=EditorialStatus.DRAFT,
            )
            session.add(ritual_version)
            await session.flush()
            ritual_versions.append((parsed_ritual, ritual_version))

            if parsed_ritual.piece_type is RitualPieceType.RETURN:
                session.add(
                    RitualReturn(
                        ritual_version_id=ritual_version.id,
                        piece_type=RitualPieceType.RETURN,
                        integration_function=parsed_ritual.purpose,
                        ordinary_reorientation=True,
                        lowers_interpretive_intensity=True,
                    )
                )
            if parsed_ritual.piece_type is RitualPieceType.COLLECTIVE:
                sequence_position = 1
                stage_position = None
                gate_position = None
            else:
                individual_position += 1
                sequence_position = individual_position
                stage_position = (
                    GATE_ORDER.index(parsed_ritual.gate) + 1
                    if parsed_ritual.gate is not None
                    else 6
                )
                gate_position = stage_position if stage_position <= 5 else None
            session.add(
                RitualSequenceItem(
                    architecture_version_id=architecture.id,
                    stage_id=stage_model.id if stage_model else None,
                    ritual_version_id=ritual_version.id,
                    sequence_position=sequence_position,
                    stage_sequence_position=stage_position,
                    slot_kind=parsed_ritual.piece_type,
                    gate_position=gate_position,
                )
            )
            for cue in parsed_ritual.cues:
                session.add(
                    RitualCue(
                        ritual_version_id=ritual_version.id,
                        source_passage_id=passages[cue.page].id,
                        sequence=cue.sequence,
                        cue_type=cue.cue_type,
                        start_seconds=cue.start_seconds,
                        end_seconds=cue.end_seconds,
                        text=cue.text,
                        language=LanguageCode.FA,
                        optional=cue.optional,
                    )
                )
            music = parsed_ritual.music
            session.add(
                MusicSpecification(
                    ritual_version_id=ritual_version.id,
                    source_passage_id=passages[music.page].id,
                    duration_seconds=music.duration_seconds,
                    sonic_family=music.sonic_family,
                    emotional_arc=music.emotional_arc,
                    intensity_profile=music.intensity_profile,
                    prohibited_features=list(music.prohibited_features),
                    transition_requirements=music.transition_requirements,
                    ending_requirements=music.ending_requirements,
                    original_prompt=music.original_prompt,
                )
            )
            localization = RitualLocalization(
                ritual_version_id=ritual_version.id,
                source_passage_id=passage.id,
                language=LanguageCode.FA,
                version_number=1,
                title=parsed_ritual.title,
                narration_text="\n".join(cue.text for cue in parsed_ritual.cues),
                instructions=parsed_ritual.instructions,
                safety_language=(
                    "همه مشارکت‌ها اختیاری‌اند؛ می‌توانی هر لحظه توقف کنی یا خارج شوی."
                ),
                terminology_version=None,
                status=EditorialStatus.DRAFT,
            )
            session.add(localization)
            await session.flush()
            for safety_version in safety_versions.values():
                session.add(
                    RitualVersionSafetyRule(
                        ritual_version_id=ritual_version.id,
                        safety_rule_version_id=safety_version.id,
                    )
                )
                session.add(
                    LocalizationSafetyRule(
                        localization_id=localization.id,
                        safety_rule_version_id=safety_version.id,
                    )
                )

        await self._load_concept_links(
            session,
            source_version,
            ayin_version,
            passages,
            gates,
            stages,
            ritual_versions,
        )
        session.add(
            RitualReviewFlag(
                source_version_id=source_version.id,
                extraction_run_id=run.id,
                source_passage_id=passages[33].id,
                ritual_version_id=None,
                source_page=33,
                reason=RitualReviewReason.UNCERTAIN_AYIN_CONCEPT_LINK,
                status=ReviewStatus.OPEN,
                message=(
                    "horizontal_emtedad is explicit in Manasek but has no current "
                    "Ayin concept identity; review the typed proposal before creation."
                ),
            )
        )

    @staticmethod
    async def _ensure_extraction_review_flag(
        session: AsyncSession, source_version_id: UUID, extraction_run_id: UUID
    ) -> None:
        existing = await session.scalar(
            select(RitualReviewFlag.id).where(
                RitualReviewFlag.extraction_run_id == extraction_run_id,
                RitualReviewFlag.reason
                == RitualReviewReason.UNCERTAIN_AYIN_CONCEPT_LINK,
            )
        )
        if existing is not None:
            return
        passage = await session.scalar(
            select(RitualPassage).where(
                RitualPassage.extraction_run_id == extraction_run_id,
                RitualPassage.page_number == 33,
            )
        )
        if passage is None:
            raise ManasekImportError(
                "horizontal Emtedad review provenance requires source page 33"
            )
        session.add(
            RitualReviewFlag(
                source_version_id=source_version_id,
                extraction_run_id=extraction_run_id,
                source_passage_id=passage.id,
                ritual_version_id=None,
                source_page=33,
                reason=RitualReviewReason.UNCERTAIN_AYIN_CONCEPT_LINK,
                status=ReviewStatus.OPEN,
                message=(
                    "horizontal_emtedad is explicit in Manasek but has no current "
                    "Ayin concept identity; review the typed proposal before creation."
                ),
            )
        )

    @staticmethod
    async def _load_safety_rules(
        session: AsyncSession,
        source_version_id: UUID,
        passages: dict[int, RitualPassage],
    ) -> dict[str, SafetyRuleVersion]:
        versions: dict[str, SafetyRuleVersion] = {}
        for seed in SAFETY_RULES:
            rule = await session.scalar(
                select(SafetyRule).where(SafetyRule.stable_key == seed.key)
            )
            if rule is None:
                rule = SafetyRule(stable_key=seed.key, category=seed.category)
                session.add(rule)
                await session.flush()
            version = SafetyRuleVersion(
                rule_id=rule.id,
                source_version_id=source_version_id,
                source_passage_id=passages[seed.page].id,
                version_number=1,
                severity=seed.severity,
                requirement_text=seed.requirement,
                required_capability=seed.capability,
                prohibited_pattern=seed.prohibited_pattern,
                status=EditorialStatus.REVIEW,
            )
            session.add(version)
            await session.flush()
            versions[seed.key] = version
        return versions

    @staticmethod
    async def _load_concept_links(
        session: AsyncSession,
        source_version: RitualSourceVersion,
        ayin_version: CanonVersion,
        passages: dict[int, RitualPassage],
        gates: dict[object, Gate],
        stages: dict[int, RitualStage],
        ritual_versions: list[tuple[ParsedRitual, RitualVersion]],
    ) -> None:
        rows = await session.execute(
            select(AyinConcept.stable_key, AyinConceptVersion.id)
            .join(AyinConceptVersion, AyinConceptVersion.concept_id == AyinConcept.id)
            .where(AyinConceptVersion.canon_version_id == ayin_version.id)
        )
        concepts: dict[str, UUID] = {
            stable_key: concept_version_id for stable_key, concept_version_id in rows
        }
        for gate_key, stable_keys in GATE_CONCEPTS.items():
            for stable_key in stable_keys:
                session.add(
                    GateConceptLink(
                        gate_id=gates[gate_key].id,
                        ayin_concept_version_id=concepts[stable_key],
                        source_version_id=source_version.id,
                        source_passage_id=passages[2].id,
                        relation=RitualRelationType.EXPERIENTIALIZES,
                        review_status=ReviewStatus.OPEN,
                    )
                )
        for stage_position, stable_keys in STAGE_CONCEPTS.items():
            for stable_key in stable_keys:
                session.add(
                    StageConceptLink(
                        stage_id=stages[stage_position].id,
                        ayin_concept_version_id=concepts[stable_key],
                        source_passage_id=passages[4].id,
                        relation=RitualRelationType.RELATES_TO,
                        review_status=ReviewStatus.OPEN,
                    )
                )
        session.add(
            StageConceptLinkProposal(
                stage_id=stages[6].id,
                proposed_stable_key="horizontal_emtedad",
                source_passage_id=passages[33].id,
                relation=RitualRelationType.RELATES_TO,
                review_status=ReviewStatus.OPEN,
                confidence=1.0,
                proposed_by="deterministic-source-import",
            )
        )
        for parsed, ritual_version in ritual_versions:
            stable_keys = (
                GATE_CONCEPTS[parsed.gate]
                if parsed.gate is not None
                else STAGE_CONCEPTS.get(parsed.stage_position or 6, ("between",))
            )
            for stable_key in stable_keys[:1]:
                session.add(
                    RitualConceptLink(
                        ritual_version_id=ritual_version.id,
                        ayin_concept_version_id=concepts[stable_key],
                        source_passage_id=passages[parsed.page].id,
                        relation=RitualRelationType.RELATES_TO,
                        review_status=ReviewStatus.OPEN,
                        confidence=1.0,
                        proposed_by="deterministic-source-import",
                    )
                )

    @staticmethod
    async def _result(
        session: AsyncSession,
        document: RitualDocument,
        source_version: RitualSourceVersion,
        run: RitualExtractionRun,
        *,
        source_version_created: bool,
        extraction_run_created: bool,
    ) -> ManasekImportResult:
        async def count(column: Any, *conditions: Any) -> int:
            value = await session.scalar(select(func.count(column)).where(*conditions))
            return int(value or 0)

        return ManasekImportResult(
            document_id=document.id,
            source_version_id=source_version.id,
            extraction_run_id=run.id,
            source_sha256=source_version.source_file_hash,
            output_hash=run.output_hash,
            page_count=run.page_count,
            passage_count=await count(
                RitualPassage.id, RitualPassage.extraction_run_id == run.id
            ),
            gate_count=await count(Gate.id),
            stage_count=await count(
                RitualStage.id, RitualStage.source_version_id == source_version.id
            ),
            gate_ritual_count=await count(
                RitualVersion.id,
                RitualVersion.source_version_id == source_version.id,
                RitualVersion.piece_type == RitualPieceType.GATE,
            ),
            return_count=await count(
                RitualReturn.ritual_version_id,
                RitualReturn.ritual_version_id.in_(
                    select(RitualVersion.id).where(
                        RitualVersion.source_version_id == source_version.id
                    )
                ),
            ),
            collective_count=await count(
                RitualVersion.id,
                RitualVersion.source_version_id == source_version.id,
                RitualVersion.piece_type == RitualPieceType.COLLECTIVE,
            ),
            cue_count=await count(
                RitualCue.id,
                RitualCue.ritual_version_id.in_(
                    select(RitualVersion.id).where(
                        RitualVersion.source_version_id == source_version.id
                    )
                ),
            ),
            music_specification_count=await count(
                MusicSpecification.ritual_version_id,
                MusicSpecification.ritual_version_id.in_(
                    select(RitualVersion.id).where(
                        RitualVersion.source_version_id == source_version.id
                    )
                ),
            ),
            concept_link_count=await count(
                RitualConceptLink.id,
                RitualConceptLink.ritual_version_id.in_(
                    select(RitualVersion.id).where(
                        RitualVersion.source_version_id == source_version.id
                    )
                ),
            ),
            concept_proposal_count=await count(StageConceptLinkProposal.id),
            safety_rule_count=await count(
                SafetyRuleVersion.id,
                SafetyRuleVersion.source_version_id == source_version.id,
            ),
            review_flag_count=await count(
                RitualReviewFlag.id, RitualReviewFlag.extraction_run_id == run.id
            ),
            source_version_created=source_version_created,
            extraction_run_created=extraction_run_created,
            corpus_zone=source_version.corpus_zone,
            status=source_version.status,
        )

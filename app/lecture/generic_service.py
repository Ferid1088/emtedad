"""Generic Semantic Master built from a ContentBrief.

Origin ``CONTENT_BRIEF``: the master is a deterministic projection of the
already-frozen upstream artifacts (brief, frozen package, evidence matrix,
argument plan, narrative plan, pinned strategy). No lesson canon, no spine,
no LLM call — the master is the immutable semantic contract handed to the
writer.
"""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.briefs.domain import BriefStatus
from app.briefs.models import ContentBrief
from app.content_engine.domain import PlanStatus
from app.content_engine.models import (
    ArgumentPlan,
    ArgumentPlanSection,
    NarrativePlan,
    NarrativePlanSection,
)
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
)
from app.knowledge.units.models import KnowledgeUnit
from app.lecture.domain import (
    CitationKind,
    ClaimEpistemicStatus,
    ClaimOrigin,
    EvidenceBindingRole,
    EvidenceKind,
    LectureProjectStatus,
    LectureType,
    MasterOriginType,
    MasterStatus,
    SectionRole,
)
from app.lecture.models import (
    LectureCitation,
    LectureClaim,
    LectureClaimEvidence,
    LectureMasterVersion,
    LectureProject,
    LectureSection,
)
from app.lecture.validator import LectureValidator
from app.research.domain import (
    EvidenceMatrixStatus,
    EvidenceSelectionRole,
    PackageStatus,
)
from app.research.models import (
    EvidenceMatrix,
    EvidenceMatrixItem,
    ResearchPackage,
)
from app.topics.models import ScriptSignature

GENERIC_MASTER_VERSION = "generic_master_v1"

# §10 channel-specific semantic constraints, loaded alongside the pinned
# ChannelStrategyVersion so the writer contract carries them explicitly.
CHANNEL_SEMANTIC_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "emtedad": (
        "Preserve conceptual meaning and terminology exactly",
        "Keep source fidelity whenever Ayin material is used",
        "Keep philosophical interpretation within stated boundaries",
    ),
    "science-mystery": (
        "Preserve the epistemic status of every claim",
        "Keep the science / hypothesis / philosophy distinction visible",
        "Keep alternative explanations alongside the main one",
        "Never overclaim beyond the evidence level",
    ),
    "history-human-stories": (
        "Preserve timeline constraints",
        "Surface source conflicts instead of smoothing them",
        "No causal certainty beyond what sources support",
    ),
    "pop-psychology-relationships": (
        "Respect the stated evidence strength",
        "No overgeneralization from single studies",
        "Stay inside practical-advice boundaries",
    ),
    "psychology-evolution": (
        "Keep biology / culture / environment alternatives open",
        "Avoid adaptationist just-so certainty",
    ),
}

_ROLE_EPISTEMIC: dict[EvidenceSelectionRole, ClaimEpistemicStatus] = {
    EvidenceSelectionRole.COUNTEREVIDENCE: ClaimEpistemicStatus.COUNTEREVIDENCE,
    EvidenceSelectionRole.COUNTERARGUMENT: ClaimEpistemicStatus.COUNTEREVIDENCE,
    EvidenceSelectionRole.ALTERNATIVE_EXPLANATION: (
        ClaimEpistemicStatus.ALTERNATIVE_EXPLANATION
    ),
    EvidenceSelectionRole.OPEN_QUESTION: ClaimEpistemicStatus.OPEN_QUESTION,
    EvidenceSelectionRole.UNRESOLVED: ClaimEpistemicStatus.OPEN_QUESTION,
    EvidenceSelectionRole.EXAMPLE: ClaimEpistemicStatus.ILLUSTRATIVE_EXAMPLE,
    EvidenceSelectionRole.CASE_STUDY: ClaimEpistemicStatus.ILLUSTRATIVE_EXAMPLE,
    EvidenceSelectionRole.ILLUSTRATION: ClaimEpistemicStatus.ILLUSTRATIVE_EXAMPLE,
    EvidenceSelectionRole.PHILOSOPHICAL_CONTEXT: (
        ClaimEpistemicStatus.EXTERNAL_PHILOSOPHICAL_ARGUMENT
    ),
    EvidenceSelectionRole.HISTORICAL_CONTEXT: (
        ClaimEpistemicStatus.EXTERNAL_ATTRIBUTED_CLAIM
    ),
}

_ROLE_ORIGIN: dict[EvidenceSelectionRole, ClaimOrigin] = {
    EvidenceSelectionRole.OPEN_QUESTION: ClaimOrigin.OPEN_QUESTION,
    EvidenceSelectionRole.UNRESOLVED: ClaimOrigin.OPEN_QUESTION,
    EvidenceSelectionRole.EXAMPLE: ClaimOrigin.EXAMPLE,
    EvidenceSelectionRole.CASE_STUDY: ClaimOrigin.EXAMPLE,
    EvidenceSelectionRole.ILLUSTRATION: ClaimOrigin.EXAMPLE,
}

_NARRATIVE_ROLE_MAP: dict[str, SectionRole] = {
    "COLD_OPEN": SectionRole.HUMAN_ENTRY,
    "HOOK": SectionRole.HUMAN_ENTRY,
    "HUMAN_ENTRY": SectionRole.HUMAN_ENTRY,
    "OPENING": SectionRole.HUMAN_ENTRY,
    "DEFINITION": SectionRole.CONCEPT_DEFINITION,
    "CONCEPT": SectionRole.CONCEPT_DEFINITION,
    "CONCEPT_DEFINITION": SectionRole.CONCEPT_DEFINITION,
    "DISTINCTION": SectionRole.DISTINCTION,
    "EVIDENCE": SectionRole.EMPIRICAL_EVIDENCE,
    "EMPIRICAL_EVIDENCE": SectionRole.EMPIRICAL_EVIDENCE,
    "STORY": SectionRole.EMPIRICAL_EVIDENCE,
    "CASE_STUDY": SectionRole.EMPIRICAL_EVIDENCE,
    "COUNTERARGUMENT": SectionRole.COUNTERARGUMENT,
    "COUNTEREVIDENCE": SectionRole.COUNTERARGUMENT,
    "LIMITATION": SectionRole.LIMITATION,
    "OPEN_QUESTION": SectionRole.OPEN_QUESTION,
    "ENDING": SectionRole.LIFE_RETURN,
    "RETURN": SectionRole.LIFE_RETURN,
    "LIFE_RETURN": SectionRole.LIFE_RETURN,
    "CONCLUSION": SectionRole.CONCLUSION,
}


def _hash(payload: object) -> str:
    return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _section_role(narrative_role: str) -> SectionRole:
    return _NARRATIVE_ROLE_MAP.get(narrative_role.upper(), SectionRole.NARRATIVE_BEAT)


class GenericMasterService:
    """Build and export CONTENT_BRIEF-origin Semantic Masters."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.validator = LectureValidator()

    async def latest_ready_for_brief(
        self, brief_id: UUID
    ) -> LectureMasterVersion | None:
        async with self.database.transaction() as session:
            master: LectureMasterVersion | None = await session.scalar(
                select(LectureMasterVersion)
                .where(
                    LectureMasterVersion.content_brief_id == brief_id,
                    LectureMasterVersion.origin_type == MasterOriginType.CONTENT_BRIEF,
                    LectureMasterVersion.status == MasterStatus.READY,
                )
                .order_by(LectureMasterVersion.version_number.desc())
                .limit(1)
            )
            return master

    async def build_from_content_brief(
        self, brief_id: UUID, *, created_by: str = "studio"
    ) -> LectureMasterVersion:
        """Freeze a generic master from the brief's ready artifacts.

        Gates (§16): READY/LOCKED brief, FROZEN package, READY/FROZEN matrix,
        READY argument, READY narrative — all for this brief and mutually
        consistent. Anything else raises GateBlockedError.
        """

        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            if brief.status not in {BriefStatus.READY, BriefStatus.LOCKED}:
                raise GateBlockedError("Cannot build master: brief is not READY")
            package = await self._frozen_package(session, brief_id)
            matrix = await self._matrix(session, brief_id)
            argument = await self._argument(session, brief_id)
            narrative = await self._narrative(session, brief_id)
            strategy = await self._strategy(session, brief)
            channel = await session.get(EditorialChannel, brief.editorial_channel_id)

            if argument.evidence_matrix_id != matrix.id:
                raise GateBlockedError(
                    "ArgumentPlan is bound to a different EvidenceMatrix"
                )
            snapshot_matrix = (package.retrieval_snapshot or {}).get(
                "evidence_matrix_id"
            )
            if snapshot_matrix is not None and snapshot_matrix != str(matrix.id):
                raise GateBlockedError(
                    "ResearchPackage was frozen from a different EvidenceMatrix"
                )
            if narrative.argument_plan_id != argument.id:
                raise GateBlockedError(
                    "NarrativePlan is bound to a different ArgumentPlan"
                )
            argument.sections.sort(key=lambda section: section.ordinal)
            narrative.sections.sort(key=lambda section: section.ordinal)

            items = list(
                (
                    await session.scalars(
                        select(EvidenceMatrixItem)
                        .where(EvidenceMatrixItem.evidence_matrix_id == matrix.id)
                        .order_by(EvidenceMatrixItem.ordinal)
                    )
                ).all()
            )
            units = await self._units(session, items)
            signatures = list(
                (
                    await session.scalars(
                        select(ScriptSignature).where(
                            ScriptSignature.editorial_channel_id
                            == brief.editorial_channel_id
                        )
                    )
                ).all()
            )
            project = await self._project(session, brief, package, created_by)
            input_hash = _hash(
                {
                    "builder": GENERIC_MASTER_VERSION,
                    "brief": str(brief.id),
                    "strategy_version": str(strategy.id),
                    "package": [str(package.id), package.content_hash],
                    "matrix": [str(matrix.id), matrix.content_hash],
                    "argument": [str(argument.id), argument.content_hash],
                    "narrative": [str(narrative.id), narrative.content_hash],
                }
            )
            existing = await session.scalar(
                select(LectureMasterVersion).where(
                    LectureMasterVersion.lecture_project_id == project.id,
                    LectureMasterVersion.input_hash == input_hash,
                )
            )
            if existing is not None:
                return existing

            version = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(LectureMasterVersion.version_number), 0)
                        + 1
                    ).where(LectureMasterVersion.lecture_project_id == project.id)
                )
                or 1
            )
            master = LectureMasterVersion(
                id=uuid4(),
                lecture_project_id=project.id,
                version_number=version,
                research_package_id=package.id,
                research_package_version=package.package_version,
                research_package_content_hash=package.content_hash,
                origin_type=MasterOriginType.CONTENT_BRIEF,
                content_brief_id=brief.id,
                channel_strategy_version_id=strategy.id,
                argument_plan_id=argument.id,
                narrative_plan_id=narrative.id,
                evidence_matrix_id=matrix.id,
                package_authority={
                    "origin": MasterOriginType.CONTENT_BRIEF.value,
                    "external_research_only": True,
                    "ayin": None,
                    "manasek": None,
                    "package_status": package.status.value,
                },
                central_human_question=brief.question,
                ending_mode=self._ending_mode(narrative),
                architecture=self._architecture(
                    brief,
                    channel,
                    strategy,
                    package,
                    matrix,
                    argument,
                    narrative,
                    signatures,
                ),
                prohibited_conflations=[
                    *brief.forbidden_claims_json,
                    "Do not present evidence as stronger than its stated level",
                    "Do not merge alternative explanations into the main claim",
                ],
                uncertainty_constraints=self._uncertainty(brief, channel, items),
                status=MasterStatus.ARCHITECTED,
                input_hash=input_hash,
                created_by=created_by,
            )
            session.add(master)
            await session.flush()

            sections = self._sections(session, master, narrative, argument)
            await session.flush()
            claims = await self._claims(
                session, master, sections, narrative, argument, items, units
            )
            await session.flush()

            findings = self.validator.validate(
                self._validation_payload(sections, claims)
            )
            blocking = [finding for finding in findings if finding.blocking]
            if blocking:
                raise GateBlockedError(
                    "Generic master validation failed: "
                    + ", ".join(f.code for f in blocking[:5])
                )
            master.status = MasterStatus.READY
            master.frozen_at = datetime.now(UTC)
            project.status = LectureProjectStatus.ARCHITECTED
            await session.flush()
            return master

    async def writer_export(self, master_id: UUID) -> dict[str, object]:
        """Bounded writer input (§11): pinned artifacts only, never corpora."""

        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise LookupError(f"Unknown master {master_id}")
            brief = (
                await session.get(ContentBrief, master.content_brief_id)
                if master.content_brief_id
                else None
            )
            strategy = (
                await session.get(
                    ChannelStrategyVersion, master.channel_strategy_version_id
                )
                if master.channel_strategy_version_id
                else None
            )
            sections = list(
                (
                    await session.scalars(
                        select(LectureSection)
                        .where(LectureSection.lecture_master_version_id == master.id)
                        .order_by(LectureSection.ordinal)
                    )
                ).all()
            )
            claims = list(
                (
                    await session.scalars(
                        select(LectureClaim)
                        .where(LectureClaim.lecture_master_version_id == master.id)
                        .order_by(LectureClaim.sequence)
                    )
                ).all()
            )
            citations = list(
                (
                    await session.scalars(
                        select(LectureCitation).where(
                            LectureCitation.lecture_master_version_id == master.id
                        )
                    )
                ).all()
            )
            return {
                "export_version": GENERIC_MASTER_VERSION,
                "master": {
                    "id": str(master.id),
                    "version_number": master.version_number,
                    "origin_type": master.origin_type.value
                    if master.origin_type
                    else None,
                    "central_human_question": master.central_human_question,
                    "ending_mode": master.ending_mode,
                    "architecture": master.architecture,
                    "prohibited_conflations": master.prohibited_conflations,
                    "uncertainty_constraints": master.uncertainty_constraints,
                },
                "strategy": (
                    {
                        "id": str(strategy.id),
                        "version_number": strategy.version_number,
                        "narrative_policy": strategy.narrative_policy_json,
                        "style_policy": strategy.style_policy_json,
                        "hook_policy": strategy.hook_policy_json,
                        "ending_policy": strategy.ending_policy_json,
                    }
                    if strategy
                    else {}
                ),
                "brief": (
                    {
                        "id": str(brief.id),
                        "question": brief.question,
                        "thesis": brief.thesis,
                        "angle": brief.angle,
                        "target_audience": brief.target_audience,
                        "target_duration_minutes": brief.target_duration_minutes,
                        "forbidden_claims": brief.forbidden_claims_json,
                        "required_counterargument": brief.required_counterargument,
                    }
                    if brief
                    else {}
                ),
                "sections": [
                    {
                        "ordinal": section.ordinal,
                        "role": section.role.value,
                        "purpose": section.purpose,
                        "narrative_role": section.rhetorical_function,
                        "transition_intent": section.transition_intent,
                        "duration_seconds": section.duration_seconds,
                        "prohibited_formulations": (section.prohibited_formulations),
                    }
                    for section in sections
                ],
                "claims": [
                    {
                        "stable_key": claim.stable_key,
                        "semantic_proposition": claim.semantic_proposition,
                        "epistemic_status": claim.epistemic_status.value,
                        "claim_origin": claim.claim_origin.value,
                        "required_qualifiers": claim.required_qualifiers,
                        "prohibited_overstatements": (claim.prohibited_overstatements),
                        "formulation_constraints": (claim.formulation_constraints),
                        "source_evidence": claim.source_evidence,
                    }
                    for claim in claims
                ],
                "citations": [
                    {
                        "claim_id": str(citation.claim_id)
                        if citation.claim_id
                        else None,
                        "kind": citation.kind.value,
                        "data": citation.citation_data,
                    }
                    for citation in citations
                ],
                "upstream": {
                    "content_brief_id": str(master.content_brief_id)
                    if master.content_brief_id
                    else None,
                    "research_package_id": str(master.research_package_id),
                    "research_package_version": master.research_package_version,
                    "evidence_matrix_id": str(master.evidence_matrix_id)
                    if master.evidence_matrix_id
                    else None,
                    "argument_plan_id": str(master.argument_plan_id)
                    if master.argument_plan_id
                    else None,
                    "narrative_plan_id": str(master.narrative_plan_id)
                    if master.narrative_plan_id
                    else None,
                },
            }

    async def _frozen_package(
        self, session: AsyncSession, brief_id: UUID
    ) -> ResearchPackage:
        package = await session.scalar(
            select(ResearchPackage)
            .where(
                ResearchPackage.content_brief_id == brief_id,
                ResearchPackage.status == PackageStatus.FROZEN,
            )
            .order_by(
                ResearchPackage.package_version.desc(),
                ResearchPackage.created_at.desc(),
            )
            .limit(1)
        )
        if package is None:
            raise GateBlockedError(
                "Cannot build master: no FROZEN ResearchPackage for the brief"
            )
        return package

    @staticmethod
    async def _matrix(session: AsyncSession, brief_id: UUID) -> EvidenceMatrix:
        matrix = await session.scalar(
            select(EvidenceMatrix)
            .where(
                EvidenceMatrix.content_brief_id == brief_id,
                EvidenceMatrix.status.in_(
                    [EvidenceMatrixStatus.READY, EvidenceMatrixStatus.FROZEN]
                ),
            )
            .order_by(EvidenceMatrix.version_number.desc())
            .limit(1)
        )
        if matrix is None:
            raise GateBlockedError(
                "Cannot build master: no ready EvidenceMatrix for the brief"
            )
        return matrix

    @staticmethod
    async def _argument(session: AsyncSession, brief_id: UUID) -> ArgumentPlan:
        plan = await session.scalar(
            select(ArgumentPlan)
            .where(
                ArgumentPlan.content_brief_id == brief_id,
                ArgumentPlan.status == PlanStatus.READY,
            )
            .options(selectinload(ArgumentPlan.sections))
            .order_by(ArgumentPlan.version_number.desc())
            .limit(1)
        )
        if plan is None:
            raise GateBlockedError(
                "Cannot build master: no ready ArgumentPlan for the brief"
            )
        return plan

    @staticmethod
    async def _narrative(session: AsyncSession, brief_id: UUID) -> NarrativePlan:
        plan = await session.scalar(
            select(NarrativePlan)
            .where(
                NarrativePlan.content_brief_id == brief_id,
                NarrativePlan.status == PlanStatus.READY,
            )
            .options(selectinload(NarrativePlan.sections))
            .order_by(NarrativePlan.version_number.desc())
            .limit(1)
        )
        if plan is None:
            raise GateBlockedError(
                "Cannot build master: no ready NarrativePlan for the brief"
            )
        return plan

    @staticmethod
    async def _strategy(
        session: AsyncSession, brief: ContentBrief
    ) -> ChannelStrategyVersion:
        strategy = await session.get(ChannelStrategyVersion, brief.strategy_version_id)
        if strategy is None:
            raise GateBlockedError(
                "Cannot build master: brief's pinned strategy is missing"
            )
        if strategy.editorial_channel_id != brief.editorial_channel_id:
            raise GateBlockedError(
                "Cannot build master: strategy belongs to another channel"
            )
        return strategy

    async def _project(
        self,
        session: AsyncSession,
        brief: ContentBrief,
        package: ResearchPackage,
        created_by: str,
    ) -> LectureProject:
        """Reuse the project bound to this package, else create one."""

        project = await session.scalar(
            select(LectureProject)
            .where(LectureProject.research_package_id == package.id)
            .limit(1)
        )
        if project is not None:
            return project
        project = LectureProject(
            research_package_id=package.id,
            lecture_type=LectureType.HUMAN_QUESTION,
            working_title=brief.question[:512],
            target_duration_seconds=brief.target_duration_minutes * 60,
            target_audience=brief.target_audience or None,
            created_by=created_by,
        )
        session.add(project)
        await session.flush()
        return project

    @staticmethod
    async def _units(
        session: AsyncSession, items: list[EvidenceMatrixItem]
    ) -> dict[str, KnowledgeUnit]:
        unit_ids = {
            unit_id
            for item in items
            for unit_id in (
                item.supporting_unit_ids
                + item.counterevidence_unit_ids
                + item.alternative_unit_ids
            )
        }
        if not unit_ids:
            return {}
        rows = await session.scalars(
            select(KnowledgeUnit).where(
                KnowledgeUnit.id.in_([UUID(u) for u in unit_ids])
            )
        )
        return {str(unit.id): unit for unit in rows}

    @staticmethod
    def _ending_mode(narrative: NarrativePlan) -> str:
        if narrative.sections:
            method = (narrative.sections[-1].ending_method or "").upper()
            if method in {"OPEN", "CLOSED", "RESOLVED", "RETURN"}:
                return method
        return "OPEN"

    @staticmethod
    def _architecture(
        brief: ContentBrief,
        channel: EditorialChannel | None,
        strategy: ChannelStrategyVersion,
        package: ResearchPackage,
        matrix: EvidenceMatrix,
        argument: ArgumentPlan,
        narrative: NarrativePlan,
        signatures: list[ScriptSignature],
    ) -> dict[str, object]:
        slug = channel.slug if channel else ""
        return {
            "builder": GENERIC_MASTER_VERSION,
            "question": brief.question,
            "thesis": brief.thesis,
            "angle": brief.angle,
            "channel": {"id": str(brief.editorial_channel_id), "slug": slug},
            "strategy_version": {
                "id": str(strategy.id),
                "version_number": strategy.version_number,
            },
            "semantic_constraints": list(CHANNEL_SEMANTIC_CONSTRAINTS.get(slug, ())),
            "distinctiveness": {
                "avoid_hook_types": sorted(
                    {s.hook_type for s in signatures if s.hook_type}
                ),
                "avoid_ending_types": sorted(
                    {s.ending_type for s in signatures if s.ending_type}
                ),
                "avoid_argument_signatures": sorted(
                    {s.argument_signature for s in signatures if s.argument_signature}
                ),
            },
            "upstream": {
                "research_package_version": package.package_version,
                "research_package_content_hash": (package.content_hash),
                "evidence_matrix_version": matrix.version_number,
                "evidence_matrix_content_hash": matrix.content_hash,
                "argument_plan_version": argument.version_number,
                "argument_plan_content_hash": argument.content_hash,
                "narrative_plan_version": narrative.version_number,
                "narrative_plan_content_hash": narrative.content_hash,
            },
            "target_duration_minutes": brief.target_duration_minutes,
            "sections": [
                {
                    "ordinal": section.ordinal,
                    "narrative_role": section.narrative_role,
                    "target_seconds": section.target_seconds,
                    "argument_section_ids": section.argument_section_ids,
                    "story_unit_ids": section.story_unit_ids,
                }
                for section in narrative.sections
            ],
            "argument_sections": [
                {
                    "ordinal": section.ordinal,
                    "role": section.role,
                    "evidence_item_ids": section.evidence_item_ids,
                    "counterargument_ids": section.counterargument_ids,
                    "must_include": section.must_include,
                    "must_not_claim": section.must_not_claim,
                }
                for section in argument.sections
            ],
        }

    @staticmethod
    def _uncertainty(
        brief: ContentBrief,
        channel: EditorialChannel | None,
        items: list[EvidenceMatrixItem],
    ) -> list[str]:
        slug = channel.slug if channel else ""
        constraints = [
            "Never strengthen a claim beyond its allowed wording",
            "Keep uncertainty, limitations, and counterevidence visible",
            *CHANNEL_SEMANTIC_CONSTRAINTS.get(slug, ()),
        ]
        constraints.extend(item.limitations for item in items if item.limitations)
        if brief.required_counterargument:
            constraints.append(
                f"Counterargument must be addressed: {brief.required_counterargument}"
            )
        return constraints

    def _sections(
        self,
        session: AsyncSession,
        master: LectureMasterVersion,
        narrative: NarrativePlan,
        argument: ArgumentPlan,
    ) -> list[LectureSection]:
        """Map narrative beats onto master sections — never regenerate."""

        argument_by_id = {str(s.id): s for s in argument.sections}
        sections: list[LectureSection] = []
        for order, section in enumerate(narrative.sections, start=1):
            linked = [
                argument_by_id[ref]
                for ref in section.argument_section_ids
                if ref in argument_by_id
            ]
            must_not = [
                value for linked_arg in linked for value in linked_arg.must_not_claim
            ]
            master_section = LectureSection(
                lecture_master_version_id=master.id,
                ordinal=order,
                role=_section_role(section.narrative_role),
                purpose=self._purpose(section, linked),
                rhetorical_function=section.narrative_role,
                transition_intent=(
                    section.transition_out
                    or (linked[0].transition_intent if linked else None)
                    or None
                ),
                duration_seconds=section.target_seconds,
                prohibited_formulations=must_not,
            )
            session.add(master_section)
            sections.append(master_section)
        return sections

    @staticmethod
    def _purpose(
        section: NarrativePlanSection,
        linked: list[ArgumentPlanSection],
    ) -> str:
        if not linked:
            return section.purpose
        argument_purposes = "; ".join(s.purpose for s in linked)
        return f"{section.purpose} — argument: {argument_purposes}"

    async def _claims(
        self,
        session: AsyncSession,
        master: LectureMasterVersion,
        sections: list[LectureSection],
        narrative: NarrativePlan,
        argument: ArgumentPlan,
        items: list[EvidenceMatrixItem],
        units: dict[str, KnowledgeUnit],
    ) -> list[LectureClaim]:
        """One semantic claim per matrix item, placed on a mapped section."""

        argument_to_sections: dict[str, list[UUID]] = {}
        for order, section in enumerate(narrative.sections):
            master_id = sections[order].id
            for ref in section.argument_section_ids:
                argument_to_sections.setdefault(ref, []).append(master_id)

        fallback = self._fallback_section(sections)
        claims: list[LectureClaim] = []
        for sequence, item in enumerate(items, start=1):
            section_id = self._item_section(
                item, argument, argument_to_sections, sections, fallback
            )
            claim = self._claim(master, sequence, item, units, section_id)
            session.add(claim)
            await session.flush()
            claims.append(claim)
            self._bindings(session, claim, item, master.research_package_id)
            self._citations(session, master, claim, item, units)
        return claims

    def _item_section(
        self,
        item: EvidenceMatrixItem,
        argument: ArgumentPlan,
        argument_to_sections: dict[str, list[UUID]],
        sections: list[LectureSection],
        fallback: UUID | None,
    ) -> UUID | None:
        item_key = str(item.id)
        for arg_section in argument.sections:
            refs = set(arg_section.evidence_item_ids) | set(
                arg_section.counterargument_ids
            )
            if item_key in refs and str(arg_section.id) in argument_to_sections:
                return argument_to_sections[str(arg_section.id)][0]
        return fallback

    @staticmethod
    def _fallback_section(sections: list[LectureSection]) -> UUID | None:
        """Prefer a counterargument/limitation section, else the middle."""

        for section in sections:
            if section.role in {
                SectionRole.COUNTERARGUMENT,
                SectionRole.LIMITATION,
            }:
                return section.id
        if sections:
            return sections[len(sections) // 2].id
        return None

    @staticmethod
    def _claim(
        master: LectureMasterVersion,
        sequence: int,
        item: EvidenceMatrixItem,
        units: dict[str, KnowledgeUnit],
        section_id: UUID | None,
    ) -> LectureClaim:
        role = item.role
        epistemic = _ROLE_EPISTEMIC.get(
            role, ClaimEpistemicStatus.EXTERNAL_EMPIRICAL_CLAIM
        )
        origin = _ROLE_ORIGIN.get(role, ClaimOrigin.EXTERNAL)
        proposition = item.claim_text.strip()
        if epistemic is ClaimEpistemicStatus.OPEN_QUESTION and "?" not in (proposition):
            proposition = f"Open question: {proposition}?"
        source_evidence = [
            {
                "unit_id": unit_id,
                "source_version_id": str(units[unit_id].source_version_id),
                "title": units[unit_id].title,
                "summary": units[unit_id].summary,
                "content_hash": units[unit_id].content_hash,
            }
            for unit_id in (
                item.supporting_unit_ids
                + item.counterevidence_unit_ids
                + item.alternative_unit_ids
            )
            if unit_id in units
        ]
        return LectureClaim(
            lecture_master_version_id=master.id,
            section_id=section_id,
            stable_key=f"matrix_item_{item.ordinal}",
            sequence=sequence,
            claim_intent=proposition,
            semantic_proposition=proposition,
            plain_meaning=item.allowed_wording or item.claim_text,
            required_concepts=[],
            required_qualifiers=([item.limitations] if item.limitations else []),
            prohibited_overstatements=(
                [item.forbidden_wording] if item.forbidden_wording else []
            ),
            source_support_summary=item.claim_text,
            source_evidence=source_evidence,
            claim_origin=origin,
            epistemic_status=epistemic,
            certainty=(item.epistemic_status or "CALIBRATED")[:32],
            formulation_constraints=(
                [item.allowed_wording] if item.allowed_wording else []
            ),
        )

    @staticmethod
    def _bindings(
        session: AsyncSession,
        claim: LectureClaim,
        item: EvidenceMatrixItem,
        package_id: UUID,
    ) -> None:
        """Bind the claim to its matrix row and every referenced unit."""

        session.add(
            LectureClaimEvidence(
                claim_id=claim.id,
                evidence_kind=EvidenceKind.EXTERNAL_CHUNK,
                evidence_item_id=str(item.id),
                package_id=package_id,
                binding_role=EvidenceBindingRole.PRIMARY,
                provenance={"evidence_matrix_item_id": str(item.id)},
            )
        )
        for unit_id in item.supporting_unit_ids:
            session.add(
                LectureClaimEvidence(
                    claim_id=claim.id,
                    evidence_kind=EvidenceKind.EXTERNAL_CHUNK,
                    evidence_item_id=unit_id,
                    package_id=package_id,
                    binding_role=EvidenceBindingRole.PRIMARY,
                    provenance={"knowledge_unit_id": unit_id},
                )
            )
        for unit_id in item.counterevidence_unit_ids:
            session.add(
                LectureClaimEvidence(
                    claim_id=claim.id,
                    evidence_kind=EvidenceKind.EXTERNAL_CHUNK,
                    evidence_item_id=unit_id,
                    package_id=package_id,
                    binding_role=EvidenceBindingRole.COUNTEREVIDENCE,
                    provenance={"knowledge_unit_id": unit_id},
                )
            )
        for unit_id in item.alternative_unit_ids:
            session.add(
                LectureClaimEvidence(
                    claim_id=claim.id,
                    evidence_kind=EvidenceKind.EXTERNAL_CHUNK,
                    evidence_item_id=unit_id,
                    package_id=package_id,
                    binding_role=EvidenceBindingRole.CONTEXT,
                    provenance={"knowledge_unit_id": unit_id},
                )
            )

    @staticmethod
    def _citations(
        session: AsyncSession,
        master: LectureMasterVersion,
        claim: LectureClaim,
        item: EvidenceMatrixItem,
        units: dict[str, KnowledgeUnit],
    ) -> None:
        for unit_id in item.supporting_unit_ids:
            unit = units.get(unit_id)
            session.add(
                LectureCitation(
                    lecture_master_version_id=master.id,
                    claim_id=claim.id,
                    kind=CitationKind.EXTERNAL,
                    package_id=master.research_package_id,
                    citation_data={
                        "knowledge_unit_id": unit_id,
                        "source_version_id": (
                            str(unit.source_version_id) if unit else None
                        ),
                        "unit_title": unit.title if unit else None,
                        "unit_content_hash": (unit.content_hash if unit else None),
                        "evidence_matrix_item_id": str(item.id),
                    },
                )
            )

    @staticmethod
    def _validation_payload(
        sections: list[LectureSection], claims: list[LectureClaim]
    ) -> dict[str, object]:
        """In-memory payload for the deterministic integrity validators."""

        bound: set[str] = set()
        claim_dicts: list[dict[str, object]] = []
        for claim in claims:
            bound.add(str(claim.id))
            claim_dicts.append(
                {
                    "id": str(claim.id),
                    "stable_key": claim.stable_key,
                    "claim_intent": claim.claim_intent,
                    "semantic_proposition": claim.semantic_proposition,
                    "plain_meaning": claim.plain_meaning,
                    "claim_origin": claim.claim_origin,
                    "epistemic_status": claim.epistemic_status,
                    "formulation_constraints": claim.formulation_constraints,
                    "required": claim.required,
                    "source_evidence": claim.source_evidence,
                }
            )
        return {
            "master": {"id": "pending"},
            "sections": [
                {
                    "id": str(section.id),
                    "purpose": section.purpose,
                    "transition_intent": section.transition_intent,
                }
                for section in sections
            ],
            "claims": claim_dicts,
            "evidence": [{"claim_id": claim_id} for claim_id in bound],
            "citations": [],
            "ritual_links": [],
            "dialogue_relations": [],
            "terminology_references": [],
        }

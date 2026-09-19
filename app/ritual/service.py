"""Read services for ritual API and CLI boundaries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.ritual.models import (
    Gate,
    GateVersion,
    MusicSpecification,
    Ritual,
    RitualCue,
    RitualDocument,
    RitualFamily,
    RitualReviewFlag,
    RitualSequenceItem,
    RitualStage,
    RitualVersion,
    SafetyRule,
    SafetyRuleVersion,
)
from app.ritual.schemas import (
    CueRead,
    FamilyRead,
    GateRead,
    MusicSpecificationRead,
    ReviewFlagRead,
    RitualDetail,
    RitualDocumentRead,
    RitualSummary,
    SafetyRuleRead,
    SequenceItemRead,
    StageRead,
)


class RitualReadService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def documents(self) -> list[RitualDocumentRead]:
        rows = await self._session.scalars(
            select(RitualDocument).order_by(RitualDocument.created_at)
        )
        return [RitualDocumentRead.model_validate(item) for item in rows]

    async def families(self) -> list[FamilyRead]:
        rows = await self._session.scalars(
            select(RitualFamily).order_by(RitualFamily.family_type)
        )
        return [FamilyRead.model_validate(item) for item in rows]

    async def gates(self) -> list[GateRead]:
        rows = await self._session.execute(
            select(Gate, GateVersion)
            .join(GateVersion, GateVersion.gate_id == Gate.id)
            .order_by(Gate.sequence_position, GateVersion.version_number.desc())
        )
        seen: set[UUID] = set()
        output: list[GateRead] = []
        for gate, version in rows:
            if gate.id in seen:
                continue
            seen.add(gate.id)
            output.append(
                GateRead(
                    id=gate.id,
                    stable_key=gate.stable_key,
                    sequence_position=gate.sequence_position,
                    title_fa=version.title_fa,
                    symbolic_role=version.symbolic_role,
                )
            )
        return output

    async def stages(self) -> list[StageRead]:
        rows = await self._session.scalars(
            select(RitualStage).order_by(RitualStage.sequence_position)
        )
        return [StageRead.model_validate(item) for item in rows]

    async def rituals(self) -> list[RitualSummary]:
        rows = await self._session.execute(
            select(Ritual, RitualVersion)
            .join(RitualVersion, RitualVersion.ritual_id == Ritual.id)
            .order_by(RitualVersion.created_at, Ritual.stable_key)
        )
        return [self._summary(ritual, version) for ritual, version in rows]

    async def ritual(self, ritual_id: UUID) -> RitualDetail:
        row = (
            await self._session.execute(
                select(Ritual, RitualVersion)
                .join(RitualVersion, RitualVersion.ritual_id == Ritual.id)
                .where(Ritual.id == ritual_id)
                .order_by(RitualVersion.version_number.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            raise ResourceNotFoundError
        ritual, version = row
        cues = list(
            await self._session.scalars(
                select(RitualCue)
                .where(RitualCue.ritual_version_id == version.id)
                .order_by(RitualCue.sequence)
            )
        )
        music = await self._session.get(MusicSpecification, version.id)
        if music is None:
            raise ResourceNotFoundError
        return RitualDetail(
            **self._summary(ritual, version).model_dump(),
            purpose=version.purpose,
            estimated_duration_seconds=version.estimated_duration_seconds,
            experiential_instructions=version.experiential_instructions,
            safety_notes=version.safety_notes,
            exit_instructions=version.exit_instructions,
            cues=[CueRead.model_validate(item) for item in cues],
            music=MusicSpecificationRead.model_validate(music),
        )

    async def stage_sequence(self, stage_id: UUID) -> list[SequenceItemRead]:
        if await self._session.get(RitualStage, stage_id) is None:
            raise ResourceNotFoundError
        items = await self._session.scalars(
            select(RitualSequenceItem)
            .where(RitualSequenceItem.stage_id == stage_id)
            .order_by(RitualSequenceItem.stage_sequence_position)
        )
        return [SequenceItemRead.model_validate(item) for item in items]

    async def safety_rules(self) -> list[SafetyRuleRead]:
        rows = await self._session.execute(
            select(SafetyRule, SafetyRuleVersion)
            .join(SafetyRuleVersion, SafetyRuleVersion.rule_id == SafetyRule.id)
            .order_by(SafetyRule.category, SafetyRule.stable_key)
        )
        return [
            SafetyRuleRead(
                id=rule.id,
                stable_key=rule.stable_key,
                category=rule.category,
                version_id=version.id,
                severity=version.severity,
                requirement_text=version.requirement_text,
                status=version.status,
            )
            for rule, version in rows
        ]

    async def review_queue(self) -> list[ReviewFlagRead]:
        rows = await self._session.scalars(
            select(RitualReviewFlag).order_by(
                RitualReviewFlag.status, RitualReviewFlag.source_page
            )
        )
        return [ReviewFlagRead.model_validate(item) for item in rows]

    @staticmethod
    def _summary(ritual: Ritual, version: RitualVersion) -> RitualSummary:
        return RitualSummary(
            id=ritual.id,
            stable_key=ritual.stable_key,
            version_id=version.id,
            title=version.title,
            mode=version.mode,
            piece_type=version.piece_type,
            status=version.status,
            stage_id=version.stage_id,
            gate_id=version.gate_id,
        )

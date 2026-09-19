"""Thin Phase 3 read-only ritual endpoints."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.db.session import Database
from app.ritual.schemas import (
    FamilyRead,
    GateRead,
    ReviewFlagRead,
    RitualDetail,
    RitualSummary,
    SafetyRuleRead,
    SequenceItemRead,
    StageRead,
)
from app.ritual.service import RitualReadService

router = APIRouter(prefix="/ritual", tags=["ritual"])


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


@router.get("/families", response_model=list[FamilyRead])
async def families(request: Request) -> list[FamilyRead]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).families()


@router.get("/gates", response_model=list[GateRead])
async def gates(request: Request) -> list[GateRead]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).gates()


@router.get("/stages", response_model=list[StageRead])
async def stages(request: Request) -> list[StageRead]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).stages()


@router.get("/rituals", response_model=list[RitualSummary])
async def rituals(request: Request) -> list[RitualSummary]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).rituals()


@router.get("/rituals/{ritual_id}", response_model=RitualDetail)
async def ritual(request: Request, ritual_id: UUID) -> RitualDetail:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).ritual(ritual_id)


@router.get("/stages/{stage_id}/sequence", response_model=list[SequenceItemRead])
async def stage_sequence(request: Request, stage_id: UUID) -> list[SequenceItemRead]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).stage_sequence(stage_id)


@router.get("/safety-rules", response_model=list[SafetyRuleRead])
async def safety_rules(request: Request) -> list[SafetyRuleRead]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).safety_rules()


@router.get("/review-queue", response_model=list[ReviewFlagRead])
async def review_queue(request: Request) -> list[ReviewFlagRead]:
    async with _database(request).transaction() as session:
        return await RitualReadService(session).review_queue()

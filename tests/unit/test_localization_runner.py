"""The runner walks the native pipeline like the certification driver."""

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.localization.domain import LocalizationPipelineStage as S
from app.localization.runner import NativeLocalizationRunner


@dataclass
class _Run:
    id: object
    stage: S


class _FakePipeline:
    """Coverage → draft → review (findings) → correct → review (clean) →
    premium → finalize → READY_FOR_VOICE."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.run = _Run(uuid4(), S.SEMANTIC_ALIGNED)
        self.reviews = 0

    async def _go(self, name: str, stage: S) -> _Run:
        self.calls.append(name)
        self.run.stage = stage
        return self.run

    async def coverage_translate(self, run_id: object) -> _Run:
        return await self._go("coverage", S.COVERAGE_TRANSLATED)

    async def native_draft(self, run_id: object) -> _Run:
        return await self._go("draft", S.NATIVE_DRAFTED)

    async def review(self, run_id: object) -> list[object]:
        self.reviews += 1
        await self._go(
            "review", S.NATIVE_REVIEW if self.reviews == 1 else S.FIDELITY_REVIEW
        )
        return []

    async def _load_run(self, run_id: object) -> _Run:
        return self.run

    async def correct(self, run_id: object) -> _Run:
        return await self._go("correct", S.NATIVE_DRAFTED)

    async def premium_final(self, run_id: object) -> _Run:
        return await self._go("premium", S.FINAL_FIDELITY)

    async def finalize(self, run_id: object) -> _Run:
        return await self._go("finalize", S.READY_FOR_VOICE)


@pytest.mark.asyncio
async def test_runner_walks_all_stages_to_ready_for_voice() -> None:
    pipeline = _FakePipeline()
    runner = NativeLocalizationRunner(
        database=None,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        package_service=object(),  # type: ignore[arg-type]
    )
    run = await runner._advance(pipeline.run)  # type: ignore[arg-type]
    assert run.stage is S.READY_FOR_VOICE
    assert pipeline.calls == [
        "coverage",
        "draft",
        "review",
        "correct",
        "review",
        "premium",
        "finalize",
    ]


@pytest.mark.asyncio
async def test_runner_resumes_from_persisted_stage_and_stops_when_blocked() -> None:
    pipeline = _FakePipeline()
    pipeline.run.stage = S.BLOCKED
    runner = NativeLocalizationRunner(
        database=None,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        package_service=object(),  # type: ignore[arg-type]
    )
    run = await runner._advance(pipeline.run)  # type: ignore[arg-type]
    assert run.stage is S.BLOCKED
    assert pipeline.calls == []

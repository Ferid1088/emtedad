"""Topic language policy: script-based validation and miner prompt contract."""

import pytest

from app.topics.miner import TopicMiner
from app.topics.schemas import TopicCandidateProposal, TopicMiningBatch
from app.topics.service import _batch_language_ok, _language_matches

PERSIAN = "چرا انسان در برابر انتخاب‌های اشتباه مقاومت نمی‌کند؟"
ENGLISH = "Why do people persist with bad decisions?"


def _proposal(**overrides: object) -> TopicCandidateProposal:
    base: dict[str, object] = {
        "title": PERSIAN,
        "video_question": PERSIAN,
        "tentative_thesis": PERSIAN,
        "angle": PERSIAN,
        "channel_fit_reason": PERSIAN,
        "knowledge_gaps": [PERSIAN],
    }
    base.update(overrides)
    return TopicCandidateProposal(**base)  # type: ignore[arg-type]


def test_language_matches_persian() -> None:
    assert _language_matches(PERSIAN, "fa")
    assert not _language_matches(ENGLISH, "fa")


def test_language_matches_english() -> None:
    assert _language_matches(ENGLISH, "en")
    assert not _language_matches(PERSIAN, "en")


def test_language_matches_mixed_rejects_minority_script() -> None:
    mixed = f"{ENGLISH} {ENGLISH} {ENGLISH} {PERSIAN}"
    assert _language_matches(mixed, "en")
    assert not _language_matches(mixed, "fa")


def test_language_matches_unknown_language_accepts() -> None:
    assert _language_matches(PERSIAN, "ja")


def test_batch_language_ok_checks_all_editorial_fields() -> None:
    batch = TopicMiningBatch(topics=[_proposal()])
    assert _batch_language_ok(batch, "fa")
    assert not _batch_language_ok(batch, "en")


@pytest.mark.parametrize(
    "field",
    ["title", "video_question", "tentative_thesis", "angle", "channel_fit_reason"],
)
def test_batch_language_ok_rejects_english_field(field: str) -> None:
    batch = TopicMiningBatch(topics=[_proposal(**{field: ENGLISH})])
    assert not _batch_language_ok(batch, "fa")


def test_batch_language_ok_rejects_english_gaps() -> None:
    batch = TopicMiningBatch(topics=[_proposal(knowledge_gaps=[ENGLISH])])
    assert not _batch_language_ok(batch, "fa")


class _CapturingProvider:
    name = "capture"

    def __init__(self) -> None:
        self.instructions: list[str] = []

    async def extract(self, request):  # noqa: ANN001, ANN202
        self.instructions.append(request.instructions)
        return TopicMiningBatch(topics=[])


@pytest.mark.asyncio
async def test_miner_prompt_declares_editorial_language() -> None:
    provider = _CapturingProvider()
    miner = TopicMiner(provider, model="test-model")
    await miner.propose(
        strategy_payload={"channel": "emtedad"},
        units=[],
        published_signatures=[],
        editorial_language="fa",
    )
    prompt = provider.instructions[0]
    assert "Persian" in prompt


@pytest.mark.asyncio
async def test_miner_correction_prompt_is_explicit() -> None:
    provider = _CapturingProvider()
    miner = TopicMiner(provider, model="test-model")
    await miner.propose(
        strategy_payload={"channel": "emtedad"},
        units=[],
        published_signatures=[],
        editorial_language="en",
        language_correction=True,
    )
    prompt = provider.instructions[0]
    assert "English" in prompt
    assert "wrong language" in prompt

"""Persian pronunciation key: validation, harakat consistency, voice text."""

import pytest
from pydantic import BaseModel

from app.knowledge.llm.base import StructuredExtractionRequest
from app.voice.pronunciation_key import (
    PronunciationKeyEditor,
    harakat_agree,
    strip_harakat,
    validate_key,
)


def test_harakat_must_agree_with_the_reading() -> None:
    assert harakat_agree("مُلک", "molk")
    assert not harakat_agree("مَلک", "molk")


def test_validate_key_drops_unusable_entries() -> None:
    sentence = "او در ملک خدا سیر می‌کرد."
    entries = validate_key(
        sentence,
        [
            {"w": "ملک", "read": "molk", "meaning": "realm", "vowelled": "مُلک"},
            {"w": "ملک", "read": "molk", "vowelled": "مَلک"},  # contradicts
            {"w": "کتاب", "read": "ketaab", "vowelled": "کِتاب"},  # not in sentence
            {"w": "خدا", "read": "خدا", "vowelled": "خُدا"},  # reading not Latin
        ],
    )
    assert [e["w"] for e in entries] == ["ملک"]
    assert entries[0]["vowelled"] == "مُلک"
    assert strip_harakat("مُلْک") == "ملک"


class _Provider:
    name = "fake"

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        return request.output_model.model_validate(
            {
                "sentences": [
                    {
                        "i": 0,
                        "words": [
                            {
                                "w": "ملک",
                                "read": "molk",
                                "vowelled": "مُلک",
                                "full": "مُلْک",
                            }
                        ],
                    },
                    {"i": 1, "words": [{"w": "سر", "read": "serr", "vowelled": "سِرّ"}]},
                ]
            }
        )


@pytest.mark.asyncio
async def test_voice_text_carries_harakat_only_for_risky_words() -> None:
    text = "او در ملک خدا سیر می‌کرد. این سر بزرگی است."
    key = await PronunciationKeyEditor(_Provider()).annotate(text)  # type: ignore[arg-type]
    voice = key.voice_text()
    assert "مُلک" in voice and "سِرّ" in voice
    assert "سیر" in voice  # untouched words stay as written
    assert "مُلْک" in key.voice_text("full")
    assert len(key.entries) == 2

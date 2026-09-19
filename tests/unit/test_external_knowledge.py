"""Deterministic unit tests for Phase 4 provider boundaries."""

import json
import subprocess
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from app.knowledge.adapters.youtube import parse_youtube_video_id
from app.knowledge.domain import EntityType, ResolutionProvider
from app.knowledge.extraction_schema import WindowExtraction
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.codex import CodexCliProvider, CodexProviderError
from app.knowledge.media import MediaValidationError, validate_and_render_pdf
from app.knowledge.normalization import normalize_external_text
from app.knowledge.resolution import ProviderCandidate, candidate_score
from app.knowledge.windowing import WindowSegment, build_windows


@pytest.mark.parametrize(
    "locator",
    [
        "331XLUCCybU",
        "https://www.youtube.com/watch?v=331XLUCCybU",
        "https://youtu.be/331XLUCCybU",
        "https://www.youtube.com/embed/331XLUCCybU",
    ],
)
def test_youtube_locator_parsing(locator: str) -> None:
    assert parse_youtube_video_id(locator) == "331XLUCCybU"


def test_youtube_locator_rejects_untrusted_hosts() -> None:
    with pytest.raises(ValueError):
        parse_youtube_video_id("https://example.com/watch?v=331XLUCCybU")


def test_persian_normalization_is_separate_and_deterministic() -> None:
    assert normalize_external_text("  علي\u200c  كيان  ") == "علی کیان"


def test_windows_preserve_order_and_overlap() -> None:
    segments = [
        WindowSegment(
            uuid4(), number, Decimal(number), Decimal(number + 1), str(number)
        )
        for number in range(1, 7)
    ]
    windows = build_windows(segments, window_size=4, overlap=1)
    assert [[item.sequence for item in window.segments] for window in windows] == [
        [1, 2, 3, 4],
        [4, 5, 6],
    ]
    assert windows[0].content_hash != windows[1].content_hash


@pytest.mark.asyncio
async def test_codex_provider_uses_schema_timeout_and_no_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed.update(command=command, **kwargs)
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"mentions": [], "claims": []}), ""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    request = StructuredExtractionRequest(
        task="test",
        prompt_version="v1",
        model="configured-default",
        instructions="extract",
        input_text="[1] text",
        output_model=WindowExtraction,
        timeout_seconds=17,
    )
    output = await CodexCliProvider().extract(request)
    assert output == WindowExtraction(mentions=[], claims=[])
    assert observed["shell"] is False
    assert observed["timeout"] == 17
    command = observed["command"]
    assert isinstance(command, list)
    assert "--output-schema" in command


@pytest.mark.asyncio
async def test_codex_provider_rejects_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "not-json", ""),
    )
    request = StructuredExtractionRequest(
        "test", "v1", "configured-default", "extract", "text", WindowExtraction
    )
    with pytest.raises(CodexProviderError):
        await CodexCliProvider().extract(request)


def test_candidate_score_and_media_validation() -> None:
    candidate = ProviderCandidate(
        ResolutionProvider.CROSSREF,
        "10.1/test",
        EntityType.WORK,
        "The Extended Mind",
        {"doi": "10.1/test"},
        None,
        {},
    )
    assert candidate_score("Extended Mind", candidate) > 90
    with pytest.raises(MediaValidationError):
        validate_and_render_pdf(b"not a pdf")


def test_valid_pdf_renders_first_page_only() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    rendered = validate_and_render_pdf(buffer.getvalue())
    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")

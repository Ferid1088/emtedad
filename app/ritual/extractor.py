"""Page-aware direct extraction for the Manasek source."""

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.ayin.normalization import digits_to_ascii, normalize_persian_text

NORMALIZATION_VERSION = "persian-v1"
SEGMENTATION_VERSION = "page-preserving-v1"


@dataclass(frozen=True)
class ExtractedRitualPassage:
    sequence: int
    page_number: int
    printed_page_label: str | None
    heading_path: tuple[str, ...]
    paragraph_index: int
    raw_text: str
    normalized_text: str
    content_hash: str


@dataclass(frozen=True)
class RitualPdfExtraction:
    page_count: int
    extractor_name: str
    extractor_version: str
    normalization_version: str
    segmentation_version: str
    configuration: dict[str, object]
    passages: tuple[ExtractedRitualPassage, ...]
    raw_pages: tuple[str, ...]


class RitualPdfExtractionError(RuntimeError):
    """Raised when Manasek extraction cannot preserve source structure."""


class PopplerRitualExtractor:
    """Extract exactly one immutable page passage per PDF page."""

    def __init__(self, executable: str = "pdftotext") -> None:
        self._executable = executable

    def extract(self, source: Path) -> RitualPdfExtraction:
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise RitualPdfExtractionError("encrypted PDFs are not supported")
        page_count = len(reader.pages)
        try:
            result = subprocess.run(
                [self._executable, "-layout", "-enc", "UTF-8", str(source), "-"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            version_result = subprocess.run(
                [self._executable, "-v"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RitualPdfExtractionError("direct PDF text extraction failed") from exc

        pages = result.stdout.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        if len(pages) != page_count:
            raise RitualPdfExtractionError(
                f"expected {page_count} extracted pages, received {len(pages)}"
            )
        if any(not normalize_persian_text(page) for page in pages):
            raise RitualPdfExtractionError("one or more PDF pages produced no text")

        headings: list[str] = []
        passages: list[ExtractedRitualPassage] = []
        for page_number, raw_text in enumerate(pages, start=1):
            normalized = digits_to_ascii(normalize_persian_text(raw_text))
            first_line = next(
                (
                    digits_to_ascii(normalize_persian_text(line))
                    for line in raw_text.splitlines()
                    if normalize_persian_text(line)
                ),
                f"page-{page_number}",
            )
            if "مرحله" in first_line or "مناسک جمعی" in first_line:
                headings = [first_line]
            passages.append(
                ExtractedRitualPassage(
                    sequence=page_number,
                    page_number=page_number,
                    printed_page_label=str(page_number),
                    heading_path=tuple(headings),
                    paragraph_index=1,
                    raw_text=raw_text,
                    normalized_text=normalized,
                    content_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
                )
            )
        version_lines = (version_result.stderr or version_result.stdout).splitlines()
        version = version_lines[0].strip()[:128] if version_lines else "unknown"
        return RitualPdfExtraction(
            page_count=page_count,
            extractor_name="poppler-pdftotext",
            extractor_version=version,
            normalization_version=NORMALIZATION_VERSION,
            segmentation_version=SEGMENTATION_VERSION,
            configuration={"encoding": "UTF-8", "layout": True, "ocr": False},
            passages=tuple(passages),
            raw_pages=tuple(pages),
        )

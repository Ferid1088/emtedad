"""Page-aware direct PDF extraction and deterministic passage derivation."""

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.ayin.domain import ReviewReason
from app.core.ayin.normalization import digits_to_ascii, normalize_persian_text

_PAGE_SEPARATOR = "\f"
_BLOCK_SEPARATOR = re.compile(r"\n[ \t]*\n+")
_SUSPICIOUS_GLYPH = re.compile(r"(?:[آ-ی]\s*n|n\s*[آ-ی]|#|�)")
_SENTENCE_ENDINGS = (".", "!", "؛", ";", ":")
NORMALIZATION_VERSION = "persian-v1"
SEGMENTATION_VERSION = "logical-blocks-v1"


@dataclass(frozen=True)
class ExtractedPassage:
    """One source block with stable location and separate normalized text."""

    sequence: int
    page_number: int
    printed_page_label: str | None
    heading_path: tuple[str, ...]
    paragraph_index: int
    raw_text: str
    normalized_text: str
    content_hash: str
    review_reasons: tuple[ReviewReason, ...]

    @property
    def needs_review(self) -> bool:
        """Return whether any explicit extraction concern was detected."""

        return bool(self.review_reasons)


@dataclass(frozen=True)
class PdfExtraction:
    """Complete reproducible output of one direct-text PDF extraction."""

    page_count: int
    extractor_name: str
    extractor_version: str
    normalization_version: str
    segmentation_version: str
    configuration: dict[str, object]
    passages: tuple[ExtractedPassage, ...]


class PdfExtractionError(RuntimeError):
    """Raised when direct PDF text extraction cannot be trusted."""


class PopplerPdfExtractor:
    """Extract tagged PDF text with Poppler; OCR is intentionally not used."""

    def __init__(self, executable: str = "pdftotext") -> None:
        self._executable = executable

    def extract(self, source: Path) -> PdfExtraction:
        """Extract pages and derive passages without mutating source text."""

        reader = PdfReader(source)
        if reader.is_encrypted:
            raise PdfExtractionError("encrypted PDFs are not supported")
        page_count = len(reader.pages)
        version = self._version()
        try:
            result = subprocess.run(
                [
                    self._executable,
                    "-layout",
                    "-enc",
                    "UTF-8",
                    str(source),
                    "-",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PdfExtractionError("direct PDF text extraction failed") from exc

        pages = result.stdout.split(_PAGE_SEPARATOR)
        if pages and not pages[-1].strip():
            pages.pop()
        if len(pages) != page_count:
            raise PdfExtractionError(
                f"expected {page_count} extracted pages, received {len(pages)}"
            )

        passages = self._derive_passages(pages)
        if not passages:
            raise PdfExtractionError("PDF produced no logical passages")
        return PdfExtraction(
            page_count=page_count,
            extractor_name="poppler-pdftotext",
            extractor_version=version,
            normalization_version=NORMALIZATION_VERSION,
            segmentation_version=SEGMENTATION_VERSION,
            configuration={"encoding": "UTF-8", "layout": True, "ocr": False},
            passages=tuple(passages),
        )

    def _version(self) -> str:
        try:
            result = subprocess.run(
                [self._executable, "-v"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PdfExtractionError("pdftotext is unavailable") from exc
        output = (result.stderr or result.stdout).splitlines()
        return output[0].strip()[:128] if output else "unknown"

    @staticmethod
    def _derive_passages(pages: list[str]) -> list[ExtractedPassage]:
        passages: list[ExtractedPassage] = []
        section: str | None = None
        chapter: str | None = None
        subsection: str | None = None
        sequence = 0

        for page_number, page_text in enumerate(pages, start=1):
            body, printed_label = _strip_page_furniture(page_text, page_number)
            blocks = [
                block.strip("\n")
                for block in _BLOCK_SEPARATOR.split(body)
                if normalize_persian_text(block)
                and set(normalize_persian_text(block)) != {"━"}
            ]
            logical_blocks = _logical_blocks(blocks)
            for paragraph_index, (raw_text, is_heading) in enumerate(
                logical_blocks, start=1
            ):
                normalized = normalize_persian_text(raw_text)
                if page_number <= 4:
                    section, chapter, subsection = "Front Matter", None, None
                elif normalized.startswith("بخش "):
                    section, chapter, subsection = normalized, None, None
                elif normalized.startswith("فصل "):
                    chapter, subsection = normalized, None
                elif is_heading:
                    subsection = normalized

                heading_path = tuple(
                    item for item in (section, chapter, subsection) if item is not None
                )
                sequence += 1
                passages.append(
                    ExtractedPassage(
                        sequence=sequence,
                        page_number=page_number,
                        printed_page_label=printed_label,
                        heading_path=heading_path,
                        paragraph_index=paragraph_index,
                        raw_text=raw_text,
                        normalized_text=normalized,
                        content_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
                        review_reasons=(
                            (ReviewReason.CHARACTER_CORRUPTION,)
                            if _SUSPICIOUS_GLYPH.search(normalized)
                            else ()
                        ),
                    )
                )
        return passages


def _strip_page_furniture(page_text: str, page_number: int) -> tuple[str, str | None]:
    lines = page_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and normalize_persian_text(lines[0]) == "آیین امتداد":
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    printed_label: str | None = None
    if lines:
        candidate = digits_to_ascii(normalize_persian_text(lines[-1]))
        if candidate.isdecimal() and int(candidate) == page_number:
            printed_label = candidate
            lines.pop()
    return "\n".join(lines).strip("\n"), printed_label


def _is_subheading(raw_text: str, normalized: str) -> bool:
    if raw_text.startswith(" ") or len(normalized) > 60:
        return False
    if normalized.startswith(("•", "-")) or re.match(r"^[۰-۹0-9]+[.)]", normalized):
        return False
    return not normalized.endswith(_SENTENCE_ENDINGS)


def _is_heading(raw_text: str) -> bool:
    normalized = normalize_persian_text(raw_text)
    return normalized.startswith(("بخش ", "فصل ")) or _is_subheading(
        raw_text, normalized
    )


def _logical_blocks(blocks: list[str]) -> list[tuple[str, bool]]:
    """Join wrapped physical lines while keeping isolated headings addressable."""

    logical: list[tuple[str, bool]] = []
    pending: list[str] = []

    def flush_pending() -> None:
        if pending:
            logical.append(("\n\n".join(pending), False))
            pending.clear()

    for block in blocks:
        if _is_heading(block):
            flush_pending()
            logical.append((block, True))
            continue
        pending.append(block)
        if normalize_persian_text(block).endswith((".", "!", "؟")):
            flush_pending()
    flush_pending()
    return logical

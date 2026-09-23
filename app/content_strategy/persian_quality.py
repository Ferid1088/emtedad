"""Deterministic quality checks for Persian editorial drafts."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class PersianDraftFinding:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class PersianDraftQualityReport:
    findings: list[PersianDraftFinding]
    repetition_ratio: float

    @property
    def valid(self) -> bool:
        return not any(item.blocking for item in self.findings)


class PersianDraftQualityValidator:
    """Reject research dumps and extraction artifacts before persistence."""

    _forbidden = (
        "The selected Ayin Working source states",
        "The external source provides evidence",
        "ResearchPackage",
        "Semantic Master",
        "source chunk",
        "retrieved passage",
        "منبع انتخاب‌شده",
        "قطعه بازیابی‌شده",
        "منبع خارجی می‌گوید",
    )

    def validate(
        self, text: str, evidence_texts: list[str]
    ) -> PersianDraftQualityReport:
        findings: list[PersianDraftFinding] = []
        lowered = text.casefold()
        for phrase in self._forbidden:
            if phrase.casefold() in lowered:
                findings.append(
                    PersianDraftFinding(
                        "INTERNAL_SCAFFOLDING_LEAKAGE",
                        f"Internal pipeline phrase leaked into prose: {phrase}",
                    )
                )
        if any(
            unicodedata.category(char) == "Cf" and char != "\u200c" for char in text
        ):
            findings.append(
                PersianDraftFinding(
                    "PDF_EXTRACTION_ARTIFACT",
                    "Unicode format controls remain in prose.",
                )
            )
        paragraphs = [
            item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()
        ]
        normalized = [_normalize(item) for item in paragraphs]
        duplicate_count = len(normalized) - len(set(normalized))
        repetition_ratio = duplicate_count / max(len(normalized), 1)
        if repetition_ratio > 0.15:
            findings.append(
                PersianDraftFinding(
                    "DUPLICATE_PARAGRAPHS",
                    "Repeated paragraphs exceed the permitted ratio.",
                )
            )
        if evidence_texts:
            leaked = sum(
                1
                for evidence in evidence_texts
                if len(evidence.strip()) >= 120
                and _normalize(evidence) in _normalize(text)
            )
            if leaked:
                findings.append(
                    PersianDraftFinding(
                        "RAW_EVIDENCE_DUMP",
                        "Verbatim evidence blocks were copied into prose.",
                    )
                )
        words = re.findall(r"[\w\u0600-\u06ff]+", text)
        if words:
            non_persian = sum(
                1 for word in words if not re.search(r"[\u0600-\u06ff]", word)
            )
            if non_persian / len(words) > 0.35:
                findings.append(
                    PersianDraftFinding(
                        "EXCESSIVE_NON_PERSIAN_PROSE",
                        "Draft contains too much non-Persian prose.",
                    )
                )
        return PersianDraftQualityReport(findings, repetition_ratio)


def clean_source_text(value: str) -> str:
    """Remove extraction-only controls while preserving source wording."""

    value = "".join(
        char for char in value if unicodedata.category(char) != "Cf" or char == "\u200c"
    )
    value = value.replace("\u00ad", "")
    value = re.sub(r"(?<=[\u0600-\u06ff])n(?=[\u0600-\u06ff])", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n\s*\n+", "\n\n", value)
    return value.strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", clean_source_text(value)).strip()

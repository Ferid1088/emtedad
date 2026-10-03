"""Language-agnostic text helpers shared by the generic review stages."""

import re

from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.quality import clean_source_text


def words(text: str) -> list[str]:
    return [
        item.casefold()
        for item in re.findall(r"[\w\u0600-\u06ff]+", clean_source_text(text))
    ]


def ngrams(token_list: list[str], size: int) -> set[str]:
    return {
        " ".join(token_list[index : index + size])
        for index in range(len(token_list) - size + 1)
    }


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / max(len(left | right), 1)


def paragraph_shape(text: str) -> tuple[int, ...]:
    paragraphs = [item for item in re.split(r"\n\s*\n", text) if item.strip()]
    return tuple(min(len(words(item)) // 20, 8) for item in paragraphs)


def extract_examples(text: str) -> list[str]:
    """Sentences that carry an explicit example marker (ledger-extractable)."""

    sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
    return [
        item
        for item in sentences
        if any(marker in item for marker in ("مثلاً", "برای مثال", "فرض کنید"))
    ][:12]


def extract_open_promises(text: str) -> list[dict[str, object]]:
    """Sentences that promise a follow-up the script must later keep."""

    sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
    return [
        {"text": item, "status": "OPEN"}
        for item in sentences
        if any(marker in item for marker in ("بعداً", "در آینده", "بعدتر خواهیم"))
    ][:10]


def explicit_ayin_reference_ratio(text: str) -> float:
    """Share of sentence words that explicitly invoke the Ayin frame."""

    sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
    total = sum(len(words(item)) for item in sentences)
    explicit = sum(
        len(words(item))
        for item in sentences
        if "آیین امتداد" in item or "از نگاه آیین" in item
    )
    return round(explicit / max(total, 1), 4)


def deduplicate_findings(
    findings: list[PipelineFinding],
) -> list[PipelineFinding]:
    result: list[PipelineFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result

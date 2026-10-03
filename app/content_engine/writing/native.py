"""Native-Persian review and minimal optimization.

``PersianNativeReviewer`` is moved verbatim from the retired lesson module.
``PersianNativeOptimizer`` is generalized: the rewrite context is now an
opaque ``context`` payload supplied by the caller (a generic Semantic Master
export, a historical lesson package, or any bounded provenance dict) instead
of a required ``LessonContentPackage``.
"""

import json
import re
from collections import Counter
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.quality import clean_source_text
from app.content_engine.writing.text import words
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest


class PersianNativeReviewer:
    """Ask whether educated readers would recognize the prose as native Persian."""

    _translated_connectors = (
        "از سوی دیگر",
        "در نتیجه",
        "به طور کلی",
        "در این راستا",
        "لازم به ذکر است",
    )

    def review(self, text: str) -> list[PipelineFinding]:
        findings: list[PipelineFinding] = []
        tokens = words(text)
        persian_words = [word for word in tokens if re.search(r"[\u0600-\u06ff]", word)]
        if tokens and len(persian_words) / len(tokens) < 0.8:
            findings.append(
                PipelineFinding(
                    "NON_NATIVE_LANGUAGE_MIX",
                    "NATIVE_PERSIAN",
                    "ERROR",
                    "Der Text wirkt nicht wie ursprünglich auf Persisch geschrieben.",
                    blocking=True,
                )
            )
        connector_count = sum(
            text.count(value) for value in self._translated_connectors
        )
        if connector_count >= 4:
            findings.append(
                PipelineFinding(
                    "TRANSLATED_CONNECTOR_PATTERN",
                    "NATIVE_PERSIAN",
                    "WARNING",
                    "Zu viele formelhafte Übergänge erzeugen übersetzten Satzrhythmus.",
                )
            )
        sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
        long_sentences = [item for item in sentences if len(words(item)) > 48]
        if long_sentences:
            findings.append(
                PipelineFinding(
                    "UNNATURAL_SENTENCE_LENGTH",
                    "NATIVE_PERSIAN",
                    "WARNING",
                    "Einige Sätze sind für gesprochene persische Prosa zu lang.",
                    metadata={"count": len(long_sentences)},
                )
            )
        starts = [" ".join(words(item)[:3]) for item in sentences if words(item)]
        repeated_starts = [
            value for value, count in Counter(starts).items() if count >= 3
        ]
        if repeated_starts:
            findings.append(
                PipelineFinding(
                    "ROBOTIC_SENTENCE_SYMMETRY",
                    "NATIVE_PERSIAN",
                    "WARNING",
                    "Mehrere Sätze beginnen mit derselben mechanischen Struktur.",
                )
            )
        if not findings:
            findings.append(
                PipelineFinding(
                    "NATIVE_PERSIAN_PASS",
                    "NATIVE_PERSIAN",
                    "INFO",
                    (
                        "Der Text besteht die heuristische Prüfung auf natürliche "
                        "persische Prosa."
                    ),
                )
            )
        return findings


class _OptimizedPersianOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


class PersianNativeOptimizer:
    """Apply only requested language fixes without receiving archive prose."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def optimize(
        self,
        text: str,
        findings: list[PipelineFinding],
        context: dict[str, object],
        semantic_constraints: list[str],
        owner_style_rules: str | None,
    ) -> str:
        actionable = [
            item
            for item in findings
            if item.category == "NATIVE_PERSIAN" and item.severity != "INFO"
        ]
        if not actionable:
            return text
        payload = {
            "draft": text,
            "language_findings": [
                {"code": item.code, "message": item.message} for item in actionable
            ],
            "production_context": context,
            "semantic_constraints": semantic_constraints,
            "owner_style_rules": owner_style_rules,
        }
        result = cast(
            _OptimizedPersianOutput,
            await self.provider.extract(
                StructuredExtractionRequest(
                    task="Minimal native Persian editorial optimization",
                    prompt_version="persian-native-optimizer-v2",
                    model="configured-default",
                    instructions=(
                        "Rewrite only what the listed language findings require. "
                        "Preserve every claim, uncertainty, protected term, "
                        "canonical distinction, attribution, and the single central "
                        "movement. Do not add facts, examples, titles, or doctrine. "
                        "Return only the complete optimized Persian script."
                    ),
                    input_text=json.dumps(payload, ensure_ascii=False),
                    output_model=_OptimizedPersianOutput,
                    timeout_seconds=300,
                )
            ),
        )
        return clean_source_text(result.text)

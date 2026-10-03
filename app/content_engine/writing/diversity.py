"""Repetition and diversity checks against published memory.

Moved verbatim from the retired lesson-production module. The validator is
prose-level: it detects repeated openings, endings, phrase overlap, paragraph
shape, and reused examples without exposing archive prose to the writer.
Metadata-level distinctiveness stays with ``ScriptSignature`` /
``DistinctivenessPlanner``.
"""

from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.memory import PublishedMemoryItem
from app.content_engine.writing.text import (
    deduplicate_findings,
    extract_examples,
    jaccard,
    ngrams,
    paragraph_shape,
    words,
)


class ScriptDiversityValidator:
    """Detect repeat patterns without exposing archive prose to the writer."""

    def validate(
        self, text: str, published: list[PublishedMemoryItem]
    ) -> list[PipelineFinding]:
        findings: list[PipelineFinding] = []
        tokens = words(text)
        opening = set(tokens[:55])
        ending = set(tokens[-55:])
        phrases = ngrams(tokens, 5)
        shape = paragraph_shape(text)
        for item in published:
            other_words = words(item.text)
            opening_overlap = jaccard(opening, set(other_words[:55]))
            ending_overlap = jaccard(ending, set(other_words[-55:]))
            phrase_overlap = jaccard(phrases, ngrams(other_words, 5))
            if opening_overlap >= 0.62:
                findings.append(
                    PipelineFinding(
                        "REPEATED_OPENING_PATTERN",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        (
                            "Der Einstieg ähnelt dem veröffentlichten Text "
                            f"„{item.title}“."
                        ),
                        metadata={"overlap": round(opening_overlap, 3)},
                    )
                )
            if ending_overlap >= 0.62:
                findings.append(
                    PipelineFinding(
                        "REPEATED_ENDING_PATTERN",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        f"Der Schluss ähnelt dem veröffentlichten Text „{item.title}“.",
                        metadata={"overlap": round(ending_overlap, 3)},
                    )
                )
            if phrase_overlap >= 0.34:
                findings.append(
                    PipelineFinding(
                        "EXCESSIVE_PHRASE_OVERLAP",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        (
                            "Zu viele Formulierungen überschneiden sich mit "
                            f"„{item.title}“."
                        ),
                        metadata={"overlap": round(phrase_overlap, 3)},
                    )
                )
            if shape and shape == paragraph_shape(item.text):
                findings.append(
                    PipelineFinding(
                        "REPEATED_PARAGRAPH_STRUCTURE",
                        "EXCESSIVE_REPETITION",
                        "INFO",
                        f"Die Absatzbewegung entspricht „{item.title}“.",
                    )
                )
            used_examples = set(extract_examples(text)) & set(item.examples)
            if used_examples:
                findings.append(
                    PipelineFinding(
                        "REUSED_EXAMPLE",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        f"Ein Beispiel wurde bereits in „{item.title}“ verwendet.",
                        metadata={"examples": sorted(used_examples)},
                    )
                )
        return deduplicate_findings(findings)

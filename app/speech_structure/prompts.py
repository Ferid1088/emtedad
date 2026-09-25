"""Versioned prompts for the bounded speech-structure pipeline."""

LOCAL_INSTRUCTIONS = (
    "Return JSON only. Identify meaningful conceptual topics in this window.\n"
    "Use only the supplied segment IDs. Distinguish TOPIC/SUBTOPIC from EXAMPLE, "
    "STORY, ARGUMENT, EXPLANATION, REFERENCE and DIGRESSION. Group non-contiguous "
    "discussion when it clearly returns to the same topic; do not create a chapter "
    "for every anecdote."
)

GLOBAL_INSTRUCTIONS = (
    "Return JSON only. Build a concise book-like hierarchy from the local topics.\n"
    "Merge repeated topics, recognize returns to earlier topics, and keep examples "
    "beneath their conceptual topic. Use only supplied topic IDs, normally 2-4 levels, "
    "with titles in the transcript language and no claims absent from the transcript."
)

ASSIGNMENT_INSTRUCTIONS = (
    "Segment assignment is deterministic. Every mapping must reference an existing "
    "source segment ID; never invent timestamps or transcript text."
)

VALIDATION_INSTRUCTIONS = (
    "Review structural coverage and provenance. Report missing, duplicate or invalid "
    "segment mappings explicitly; do not silently discard transcript content."
)

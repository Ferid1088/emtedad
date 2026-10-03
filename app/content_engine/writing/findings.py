"""Shared finding type for deterministic post-draft review stages."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PipelineFinding:
    """One owner-readable finding from a distinct post-draft review stage."""

    code: str
    category: str
    severity: str
    message: str
    blocking: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

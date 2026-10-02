"""Provider selection shared by every LLM call site.

``EMTEDAD_LLM_PROVIDER`` (``codex`` | ``devin``) overrides the per-caller
default. Unset means each subsystem keeps its established provider.
"""

from typing import Literal

from app.core.config import get_settings
from app.knowledge.llm.base import LLMProvider

ProviderName = Literal["codex", "devin"]


def resolve_llm_provider(default: ProviderName = "codex") -> LLMProvider:
    """Return the configured structured-extraction provider."""

    configured = get_settings().llm_provider
    kind: ProviderName = configured if configured is not None else default
    if kind == "devin":
        from app.knowledge.llm.devin import DevinCloudProvider

        return DevinCloudProvider()
    from app.knowledge.llm.codex import CodexCliProvider

    return CodexCliProvider()

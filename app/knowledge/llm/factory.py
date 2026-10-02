"""Structured LLM provider boundary — Devin Cloud API is the only provider.

All call sites resolve through ``resolve_llm_provider()``; the parameter is
kept for signature compatibility but the platform standard is Devin.
"""

from app.knowledge.llm.base import LLMProvider


def resolve_llm_provider(default: str | None = None) -> LLMProvider:
    """Return the Devin Cloud structured-extraction provider."""

    del default
    from app.knowledge.llm.devin import DevinCloudProvider

    return DevinCloudProvider()

"""Context firewall: every role receives only what its task needs.

Two independent controls:

- ``guard_payload`` enforces a per-role allowlist of payload keys before a
  request leaves the service layer. Unknown keys are rejected loudly —
  prompts are never silently widened.
- ``assert_no_secrets`` scans the final serialized request body for
  configured secret values and credential-shaped keys. This is the
  backstop: even if a caller bypasses the allowlist, no API key, database
  URL, or token may enter a model prompt.
"""

from __future__ import annotations

import re
from typing import Any

from app.knowledge.llm.roles import AgentRole


class ContextFirewallError(ValueError):
    """A payload key or value is not permitted for the role."""


# What each role is allowed to see. Anything not listed is rejected.
# The lists are payload *key* allowlists for the JSON ``input_text`` the
# services hand to the provider.
ROLE_CONTEXT_KEYS: dict[AgentRole, frozenset[str]] = {
    AgentRole.TOPIC_MINER: frozenset(
        {"strategy", "units", "concepts", "recent_signatures", "language"}
    ),
    AgentRole.PRONUNCIATION_EDITOR: frozenset({"sentences", "language"}),
    AgentRole.SEARCH_PLANNER: frozenset(
        {"brief", "thesis", "evidence_gaps", "source_policy", "language"}
    ),
    AgentRole.SEARCH_QUERY: frozenset(
        {"brief", "thesis", "evidence_gaps", "source_policy", "language"}
    ),
    AgentRole.COUNTERARGUMENT: frozenset(
        {"brief", "thesis", "claims", "evidence", "language"}
    ),
    AgentRole.COVERAGE_TRANSLATION: frozenset(
        {
            "package",
            "source_script",
            "language_profile",
            "duration_contract",
            "language",
        }
    ),
    AgentRole.NATIVE_RECONSTRUCTION: frozenset(
        {
            "package",
            "coverage_translation",
            "language_profile",
            "duration_contract",
            "section_budgets",
            "language",
        }
    ),
    AgentRole.TARGETED_LOCALIZATION_REPAIR: frozenset(
        {
            "package",
            "target_script",
            "target_sections",
            "neighbor_context",
            "relevant_claims",
            "section_targets",
            "section_budgets",
            "findings",
            "language_profile",
            "duration_contract",
            "language",
        }
    ),
    AgentRole.SEMANTIC_PATCH_REPAIR: frozenset(
        {
            "package",
            "target_script",
            "target_sections",
            "neighbor_context",
            "relevant_claims",
            "section_targets",
            "section_budgets",
            "findings",
            "language_profile",
            "duration_contract",
            "language",
        }
    ),
    AgentRole.LANGUAGE_NARRATIVE_EDITOR: frozenset(
        {
            "package",
            "native_draft",
            "language_profile",
            "duration_contract",
            "section_budgets",
            "language",
        }
    ),
    AgentRole.NATIVE_SPOKEN_CRITIC: frozenset(
        {"target_script", "language_profile", "language"}
    ),
    AgentRole.AUDIENCE_RETENTION_CRITIC: frozenset(
        {"target_script", "language_profile", "language"}
    ),
    AgentRole.FIDELITY_CRITIC: frozenset({"package", "target_script", "language"}),
    AgentRole.FINAL_FIDELITY_GATE: frozenset({"package", "target_script", "language"}),
    AgentRole.SEMANTIC_PACKAGE: frozenset(
        {"source_script", "master_export", "book_references", "language"}
    ),
    AgentRole.DURATION_ADJUSTMENT: frozenset(
        {
            "package",
            "target_script",
            "target_sections",
            "section_targets",
            "relevant_claims",
            "duration_delta_seconds",
            "duration_contract",
            "language_profile",
            "language",
        }
    ),
    AgentRole.PERSIAN_SEMANTIC_MASTER: frozenset(
        {"brief", "argument", "narrative", "evidence", "constraints"}
    ),
    AgentRole.PERSIAN_SCRIPT_WRITER: frozenset(
        {
            "semantic_master",
            "narrative",
            "evidence_summary",
            "book_references",
            "language_profile",
            "section_budgets",
        }
    ),
    AgentRole.PREMIUM_TARGETED_REVISION: frozenset(
        {
            "draft",
            "findings",
            "affected_sections",
            "constraints",
            "package",
            "target_script",
            "section_budgets",
            "language_profile",
            "duration_contract",
            "language",
        }
    ),
    AgentRole.TARGET_FINAL_EDITOR: frozenset(
        {
            "native_draft",
            "package",
            "fidelity_findings",
            "native_findings",
            "language_profile",
            "duration_contract",
            "language",
        }
    ),
    AgentRole.TITLE_CANDIDATE: frozenset(
        {"package", "target_script_summary", "language_profile", "language"}
    ),
    AgentRole.HOOK_CANDIDATE: frozenset(
        {"package", "target_script_summary", "language_profile", "language"}
    ),
    AgentRole.DESCRIPTION_CANDIDATE: frozenset(
        {"package", "target_script_summary", "language_profile", "language"}
    ),
}

# Keys that may never appear in any model payload regardless of role.
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "token",
        "secret",
        "password",
        "database_url",
        "connection_string",
        "owner_settings",
        "env",
        "credentials",
    }
)

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-or-v1-[A-Za-z0-9]{16,}"),
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_-]{15,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s\"']+"),
)


def guard_payload(role: AgentRole, payload: dict[str, Any]) -> None:
    """Reject payload keys outside the role's allowlist or forbidden set."""

    allowed = ROLE_CONTEXT_KEYS.get(role)
    if allowed is None:
        raise ContextFirewallError(f"No context policy defined for {role}")
    keys = set(payload)
    forbidden = keys & _FORBIDDEN_KEYS
    if forbidden:
        raise ContextFirewallError(
            f"Forbidden payload keys for {role}: {sorted(forbidden)}"
        )
    unexpected = keys - allowed
    if unexpected:
        raise ContextFirewallError(
            f"Unexpected payload keys for {role}: {sorted(unexpected)}"
        )


def assert_no_secrets(serialized: str, extra_secrets: list[str] | None = None) -> None:
    """Backstop scan of the serialized request body for secret material."""

    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(serialized):
            raise ContextFirewallError(
                "Request payload contains credential-shaped material"
            )
    for value in extra_secrets or []:
        if value and len(value) >= 8 and value in serialized:
            raise ContextFirewallError(
                "Request payload contains a configured secret value"
            )

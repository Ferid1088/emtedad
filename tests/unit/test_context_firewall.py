"""Unit tests for the context firewall and secret backstop."""

import pytest

from app.knowledge.llm.context import (
    ContextFirewallError,
    assert_no_secrets,
    guard_payload,
)
from app.knowledge.llm.roles import AgentRole


def test_guard_payload_accepts_allowed_keys() -> None:
    guard_payload(
        AgentRole.COVERAGE_TRANSLATION,
        {
            "package": {"claims": []},
            "source_script": "متن",
            "language_profile": {"code": "de"},
            "language": "de",
        },
    )


def test_guard_payload_rejects_unknown_keys() -> None:
    with pytest.raises(ContextFirewallError, match="Unexpected payload keys"):
        guard_payload(
            AgentRole.COVERAGE_TRANSLATION,
            {
                "package": {},
                "source_script": "x",
                "language_profile": {},
                "language": "de",
                "raw_database_dump": "should never reach a model",
            },
        )


def test_guard_payload_rejects_credential_keys_even_when_allowed() -> None:
    with pytest.raises(ContextFirewallError, match="Forbidden payload keys"):
        guard_payload(AgentRole.TOPIC_MINER, {"language": "de", "api_key": "x"})


def test_guard_payload_rejects_roles_without_policy() -> None:
    class Fake:
        pass

    with pytest.raises(ContextFirewallError, match="No context policy"):
        guard_payload(Fake(), {"language": "de"})  # type: ignore[arg-type]


def test_assert_no_secrets_detects_provider_keys() -> None:
    with pytest.raises(ContextFirewallError):
        assert_no_secrets('{"script": "call sk-or-v1-abcdef0123456789abcdef"}')


def test_assert_no_secrets_detects_database_urls() -> None:
    with pytest.raises(ContextFirewallError):
        assert_no_secrets('{"text": "postgres+psycopg://user:pass@host/db embedded"}')


def test_assert_no_secrets_detects_bearer_tokens() -> None:
    with pytest.raises(ContextFirewallError):
        assert_no_secrets('{"text": "Bearer abcdef0123456789abcdef01234567"}')


def test_assert_no_secrets_detects_configured_secret_values() -> None:
    with pytest.raises(ContextFirewallError):
        assert_no_secrets(
            '{"settings": "owner-secret-value"}',
            extra_secrets=["owner-secret-value"],
        )


def test_assert_no_secrets_passes_clean_content() -> None:
    assert_no_secrets(
        '{"package": {"claims": []}, "language": "de"}',
        extra_secrets=["owner-secret-value"],
    )


def test_firewall_boundaries_keep_generated_away_from_canon_roles() -> None:
    """Canonical boundary: critics see the package + script, never the
    full source corpus or settings."""

    with pytest.raises(ContextFirewallError):
        guard_payload(
            AgentRole.NATIVE_SPOKEN_CRITIC,
            {
                "target_script": "x",
                "language": "de",
                "language_profile": {},
                "master_export": {"corpus": "full canon dump"},
            },
        )


def test_guard_payload_allows_patch_repair_keys() -> None:
    """Patch-repair roles may see scoped sections, never the whole corpus."""

    for role in (
        AgentRole.SEMANTIC_PATCH_REPAIR,
        AgentRole.TARGETED_LOCALIZATION_REPAIR,
    ):
        guard_payload(
            role,
            {
                "package": {},
                "target_script": "x",
                "target_sections": [{"section_id": "s01", "sha256": "a", "text": "t"}],
                "neighbor_context": {"before": "", "after": ""},
                "relevant_claims": [],
                "section_targets": [],
                "findings": [],
                "duration_contract": {},
                "language_profile": {},
                "language": "de",
            },
        )
    guard_payload(
        AgentRole.DURATION_ADJUSTMENT,
        {
            "package": {},
            "target_sections": [{"section_id": "s01", "sha256": "a", "text": "t"}],
            "section_targets": [],
            "relevant_claims": [],
            "duration_contract": {},
            "language_profile": {},
            "language": "de",
        },
    )


def test_guard_payload_rejects_extra_keys_on_patch_roles() -> None:
    with pytest.raises(ContextFirewallError, match="Unexpected payload keys"):
        guard_payload(
            AgentRole.SEMANTIC_PATCH_REPAIR,
            {
                "target_sections": [],
                "source_corpus": "must never reach repair models",
                "language": "de",
            },
        )


def test_guard_payload_allows_section_budgets_for_writers() -> None:
    for role in (
        AgentRole.NATIVE_RECONSTRUCTION,
        AgentRole.LANGUAGE_NARRATIVE_EDITOR,
        AgentRole.PERSIAN_SCRIPT_WRITER,
    ):
        guard_payload(role, {"section_budgets": []})


def test_semantic_patch_repair_maps_to_reasoning() -> None:
    """Fidelity repair routes to the reasoning model, not editorial."""

    from app.knowledge.llm.roles import AGENT_TO_MODEL_ROLE, ModelRole

    assert (
        AGENT_TO_MODEL_ROLE[AgentRole.SEMANTIC_PATCH_REPAIR]
        is ModelRole.PROFESSIONAL_REASONING
    )

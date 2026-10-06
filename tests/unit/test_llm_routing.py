"""Unit tests for role routing and the provider factory."""

import pytest
from pydantic import SecretStr

import app.knowledge.llm.factory as factory_module
from app.core.config import Settings
from app.knowledge.llm.apimaster import APIMasterProvider
from app.knowledge.llm.factory import (
    RoutingConfigurationError,
    resolve_llm_provider,
)
from app.knowledge.llm.roles import (
    AGENT_TO_MODEL_ROLE,
    AgentRole,
    ModelRole,
    model_for_role,
)


def _settings(test_settings: Settings, **updates: object) -> Settings:
    return test_settings.model_copy(update=updates)


def test_every_agent_role_maps_to_a_model_role() -> None:
    for role in AgentRole:
        assert role in AGENT_TO_MODEL_ROLE, role


def test_role_matrix_matches_owner_policy(test_settings: Settings) -> None:
    expected = {
        # High-volume model did not certify (live A/B loops) → reasoning tier.
        AgentRole.TOPIC_MINER: "openai/gpt-6.1-sol",
        AgentRole.SEARCH_PLANNER: "openai/gpt-6.1-sol",
        AgentRole.SEMANTIC_PACKAGE: "openai/gpt-6.1-sol",
        AgentRole.FIDELITY_CRITIC: "openai/gpt-6.1-sol",
        AgentRole.COVERAGE_TRANSLATION: "google/gemini-3.8-flash",
        AgentRole.NATIVE_SPOKEN_CRITIC: "google/gemini-3.8-flash",
        AgentRole.PERSIAN_SCRIPT_WRITER: "openai/gpt-6-astra",
        AgentRole.TARGET_FINAL_EDITOR: "openai/gpt-6-astra",
    }
    for role, model in expected.items():
        assert model_for_role(AGENT_TO_MODEL_ROLE[role], test_settings) == model, role


def test_owner_effective_settings_override_models(
    test_settings: Settings,
) -> None:
    effective = {"model_role_editorial": "owner/chosen-model"}
    assert (
        model_for_role(
            ModelRole.MULTILINGUAL_EDITORIAL, test_settings, effective=effective
        )
        == "owner/chosen-model"
    )


def test_factory_always_returns_apimaster(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    """APIMaster is the only provider — no routing flag, no fallback."""

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: _settings(
            test_settings,
            apimaster_api_key=SecretStr("sk-apimaster-testkey1234567890"),
        ),
    )
    provider = resolve_llm_provider(role=AgentRole.TOPIC_MINER)
    assert isinstance(provider, APIMasterProvider)
    assert provider.config.base_url == "https://apimaster.ai/v1"


def test_factory_fails_closed_without_role(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    """No declared role → hard error, never implicit."""

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: _settings(
            test_settings,
            apimaster_api_key=SecretStr("sk-apimaster-testkey1234567890"),
        ),
    )
    with pytest.raises(RoutingConfigurationError, match="no AgentRole"):
        resolve_llm_provider()


def test_every_agent_role_resolves_to_apimaster_in_production(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    """§3 coverage: every production role → APIMaster."""

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: _settings(
            test_settings,
            apimaster_api_key=SecretStr("sk-apimaster-testkey1234567890"),
        ),
    )
    for role in AgentRole:
        provider = resolve_llm_provider(role=role)
        assert isinstance(provider, APIMasterProvider), role
        assert provider.config.model, role


def test_factory_routes_roles_to_apimaster_when_enabled(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: _settings(
            test_settings,
            apimaster_api_key=SecretStr("sk-apimaster-testkey1234567890"),
        ),
    )
    provider = resolve_llm_provider(role=AgentRole.FIDELITY_CRITIC)
    assert isinstance(provider, APIMasterProvider)
    assert provider.config.model == "openai/gpt-6.1-sol"
    assert provider.agent_role == AgentRole.FIDELITY_CRITIC.value


def test_factory_premium_roles_run_synchronously_on_premium_model(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    """APIMaster has no batch API — premium roles resolve to a normal provider."""

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: _settings(
            test_settings,
            apimaster_api_key=SecretStr("sk-apimaster-testkey1234567890"),
        ),
    )
    provider = resolve_llm_provider(role=AgentRole.PERSIAN_SCRIPT_WRITER)
    assert isinstance(provider, APIMasterProvider)
    assert provider.config.model == "openai/gpt-6-astra"


def test_factory_routes_string_roles(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: _settings(
            test_settings,
            apimaster_api_key=SecretStr("sk-apimaster-testkey1234567890"),
        ),
    )
    provider = resolve_llm_provider(role="topic_miner")
    assert isinstance(provider, APIMasterProvider)
    assert provider.config.model == "openai/gpt-6.1-sol"

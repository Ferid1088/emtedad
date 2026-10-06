"""Structured LLM provider boundary.

APIMaster (https://apimaster.ai) is the only LLM gateway. Every
``AgentRole`` resolves to an APIMaster model via its ``ModelRole``; a role
without a mapping is a configuration error. There is no other provider and
no fallback.
"""

from typing import TYPE_CHECKING

from app.core.config import Settings, get_settings
from app.knowledge.llm.base import LLMProvider
from app.knowledge.llm.roles import (
    AGENT_TO_MODEL_ROLE,
    AgentRole,
    ModelRole,
    model_for_role,
)

if TYPE_CHECKING:
    from app.knowledge.llm.apimaster import TelemetryRecorder


class RoutingConfigurationError(RuntimeError):
    """An AgentRole cannot be resolved to an APIMaster model."""


def resolve_llm_provider(
    default: str | None = None,
    *,
    role: AgentRole | str | None = None,
    effective: dict[str, object] | None = None,
    recorder: "TelemetryRecorder | None" = None,
) -> LLMProvider:
    """Return the APIMaster provider for a role.

    APIMaster is the only LLM gateway; there is no fallback provider.
    ``effective`` is the owner's resolved settings dict when a service
    already loaded it — DB overrides for model roles take precedence.
    ``recorder`` receives provider-reported telemetry for APIMaster calls.
    """

    del default
    settings = get_settings()
    if role is None:
        raise RoutingConfigurationError(
            "no AgentRole declared — every LLM call must name its role"
        )
    agent_role = role if isinstance(role, AgentRole) else AgentRole(str(role))
    model_role = AGENT_TO_MODEL_ROLE.get(agent_role)
    if model_role is None:
        raise RoutingConfigurationError(
            f"AgentRole {agent_role.value!r} has no ModelRole mapping — "
            "add it to AGENT_TO_MODEL_ROLE"
        )
    return _apimaster_provider(
        model_role=model_role,
        agent_role=agent_role,
        settings=settings,
        effective=effective,
        recorder=recorder,
    )


def _apimaster_provider(
    *,
    model_role: ModelRole,
    agent_role: AgentRole,
    settings: Settings,
    effective: dict[str, object] | None,
    recorder: "TelemetryRecorder | None" = None,
) -> LLMProvider:
    from app.knowledge.llm.apimaster import (
        APIMasterConfig,
        APIMasterProvider,
    )

    model = model_for_role(model_role, settings, effective=effective)
    key = (
        settings.apimaster_api_key.get_secret_value()
        if settings.apimaster_api_key is not None
        else None
    )
    # The Responses protocol is a per-role decision — only the reasoning
    # model (Sol) is a candidate for the §34–39 certification switch.
    protocol = (
        str(
            (effective or {}).get(
                "apimaster_sol_protocol", settings.apimaster_sol_protocol
            )
        )
        if model_role is ModelRole.PROFESSIONAL_REASONING
        else "chat"
    )
    return APIMasterProvider(
        APIMasterConfig(
            api_key=key,
            base_url=settings.apimaster_base_url,
            model=model,
            timeout_seconds=float(settings.apimaster_timeout_seconds),
            max_retries=int(settings.apimaster_max_retries),
            protocol=protocol,
            retry_timeouts=(
                bool(
                    (effective or {}).get(
                        "apimaster_premium_retry_timeouts",
                        settings.apimaster_premium_retry_timeouts,
                    )
                )
                if model_role
                in {ModelRole.PREMIUM_CREATION, ModelRole.PREMIUM_CREATION_FAST}
                else True
            ),
        ),
        recorder=recorder,
        agent_role=agent_role.value,
    )

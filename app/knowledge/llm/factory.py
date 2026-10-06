"""Structured LLM provider boundary.

Production rule: every declared ``AgentRole`` resolves through APIMaster —
the single external LLM gateway — when ``llm_routing_enabled`` is on. A
role without a model mapping fails as a configuration error; it never
falls back silently.

The Devin provider is opt-in only (``allow_devin_runtime_fallback``) for
development, tests, and explicit legacy/manual operations. With the
production default ``False``, both a missing role and a missing routing
flag raise :class:`RoutingConfigurationError` instead of routing to Devin.
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
    """Provider resolution cannot satisfy the production routing rule."""


def resolve_llm_provider(
    default: str | None = None,
    *,
    role: AgentRole | str | None = None,
    effective: dict[str, object] | None = None,
    recorder: "TelemetryRecorder | None" = None,
) -> LLMProvider:
    """Return the APIMaster provider for a role, or the opt-in Devin default.

    ``effective`` is the owner's resolved settings dict when a service
    already loaded it — DB overrides for model roles take precedence.
    ``recorder`` receives provider-reported telemetry for APIMaster calls.
    """

    del default
    settings = get_settings()
    routing_enabled = _flag("llm_routing_enabled", settings, effective)
    allow_devin = _flag("allow_devin_runtime_fallback", settings, effective)
    if role is not None:
        agent_role = role if isinstance(role, AgentRole) else AgentRole(str(role))
        if routing_enabled:
            model_role = AGENT_TO_MODEL_ROLE.get(agent_role)
            if model_role is None:
                raise RoutingConfigurationError(
                    f"AgentRole {agent_role.value!r} has no ModelRole mapping — "
                    "routing cannot resolve it; do not fall back silently"
                )
            return _apimaster_provider(
                model_role=model_role,
                agent_role=agent_role,
                settings=settings,
                effective=effective,
                recorder=recorder,
            )
        if not allow_devin:
            raise RoutingConfigurationError(
                f"role {agent_role.value!r} requested but llm_routing_enabled "
                "is off and allow_devin_runtime_fallback is false — enable "
                "routing for production or opt into Devin explicitly"
            )
    elif not allow_devin:
        raise RoutingConfigurationError(
            "no AgentRole declared and allow_devin_runtime_fallback is "
            "false — declare a role for production traffic or opt into "
            "Devin explicitly"
        )
    from app.knowledge.llm.devin import DevinCloudProvider

    return DevinCloudProvider()


def _flag(
    key: str,
    settings: Settings,
    effective: dict[str, object] | None,
) -> bool:
    if effective is not None and key in effective:
        return bool(effective[key])
    return bool(getattr(settings, key))


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
        ),
        recorder=recorder,
        agent_role=agent_role.value,
    )

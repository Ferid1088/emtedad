"""Agent-role → model-role → provider/model routing.

Domain services address *roles* (``AgentRole``), never model IDs or
providers. Each role maps to a ``ModelRole``; the concrete model string
behind a model role lives in ``Settings`` (``model_role_*`` fields) and
may be overridden by owner settings — no model name is hardcoded in the
production call path.

All roles resolve through APIMaster, the only LLM gateway.
"""

from enum import StrEnum

from app.core.config import Settings


class AgentRole(StrEnum):
    """Stable production roles. New roles join this vocabulary explicitly."""

    # Preparation / research roles — initially assigned to the high-volume
    # tier, re-mapped to PROFESSIONAL_REASONING after live A/B certification
    # (benchmarks/pipeline/artifacts/ab_qwen_sol_loop{1,2}_*.json): the
    # high-volume model failed structured output on 20/40 calls, ran 2-3×
    # slower, and scored below the reasoning model on every judged axis.
    TOPIC_MINER = "topic_miner"
    SEARCH_PLANNER = "search_planner"
    SEARCH_QUERY = "search_query"
    COUNTERARGUMENT = "counterargument"
    # Professional reasoning / evidence authority
    SOURCE_QUALITY_REVIEWER = "source_quality_reviewer"
    EVIDENCE_EXTRACTOR = "evidence_extractor"
    EVIDENCE_NORMALIZER = "evidence_normalizer"
    SCIENTIFIC_EVIDENCE = "scientific_evidence"
    EPISTEMIC_STATUS = "epistemic_status"
    EVIDENCE_VALIDATOR = "evidence_validator"
    BOOK_REFERENCE_SELECTOR = "book_reference_selector"
    ARGUMENT_DRAFT = "argument_draft"
    NARRATIVE_DRAFT = "narrative_draft"
    SEMANTIC_ALIGNMENT = "semantic_alignment"
    FACT_CRITIC = "fact_critic"
    EPISTEMIC_CRITIC = "epistemic_critic"
    FIDELITY_CRITIC = "fidelity_critic"
    FINAL_FIDELITY_GATE = "final_fidelity_gate"
    SEMANTIC_PACKAGE = "semantic_package"
    QUOTE_VALIDATOR = "quote_validator"
    # Multilingual / editorial
    COVERAGE_TRANSLATION = "coverage_translation"
    NATIVE_RECONSTRUCTION = "native_reconstruction"
    LANGUAGE_NARRATIVE_EDITOR = "language_narrative_editor"
    CULTURAL_RHETORIC = "cultural_rhetoric"
    NATIVE_SPOKEN_CRITIC = "native_spoken_critic"
    AUDIENCE_RETENTION_CRITIC = "audience_retention_critic"
    DURATION_ADJUSTMENT = "duration_adjustment"
    TARGETED_LOCALIZATION_REPAIR = "targeted_localization_repair"
    # Factual/semantic patch repair — routed to the reasoning model (Sol),
    # not the editorial model: fidelity repairs operate on the claim
    # ledger, not on style.
    SEMANTIC_PATCH_REPAIR = "semantic_patch_repair"
    TITLE_CANDIDATE = "title_candidate"
    HOOK_CANDIDATE = "hook_candidate"
    DESCRIPTION_CANDIDATE = "description_candidate"
    # Premium creation
    PERSIAN_SEMANTIC_MASTER = "persian_semantic_master"
    PERSIAN_SCRIPT_WRITER = "persian_script_writer"
    PRONUNCIATION_EDITOR = "pronunciation_editor"
    PREMIUM_TARGETED_REVISION = "premium_targeted_revision"
    TARGET_FINAL_EDITOR = "target_final_editor"
    PREMIUM_CONFLICT_RESOLVER = "premium_conflict_resolver"
    # Legacy fallback for call sites that do not declare a role yet
    LEGACY_DEFAULT = "legacy_default"


class ModelRole(StrEnum):
    """Configured model families behind agent roles."""

    HIGH_VOLUME_REASONING = "high_volume_reasoning"
    PROFESSIONAL_REASONING = "professional_reasoning"
    MULTILINGUAL_EDITORIAL = "multilingual_editorial"
    PREMIUM_CREATION = "premium_creation"
    PREMIUM_CREATION_FAST = "premium_creation_fast"
    LEGACY = "legacy"


AGENT_TO_MODEL_ROLE: dict[AgentRole, ModelRole] = {
    # No live role maps to HIGH_VOLUME_REASONING today: the assigned
    # high-volume model did not certify for any of these roles (live A/B,
    # two loops × five cases each). The tier remains for future cheap-model
    # candidates that pass the same certification.
    AgentRole.TOPIC_MINER: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.SEARCH_PLANNER: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.SEARCH_QUERY: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.COUNTERARGUMENT: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.SOURCE_QUALITY_REVIEWER: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.EVIDENCE_EXTRACTOR: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.EVIDENCE_NORMALIZER: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.SCIENTIFIC_EVIDENCE: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.EPISTEMIC_STATUS: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.EVIDENCE_VALIDATOR: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.BOOK_REFERENCE_SELECTOR: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.ARGUMENT_DRAFT: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.NARRATIVE_DRAFT: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.SEMANTIC_ALIGNMENT: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.FACT_CRITIC: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.EPISTEMIC_CRITIC: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.FIDELITY_CRITIC: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.FINAL_FIDELITY_GATE: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.SEMANTIC_PACKAGE: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.QUOTE_VALIDATOR: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.COVERAGE_TRANSLATION: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.NATIVE_RECONSTRUCTION: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.LANGUAGE_NARRATIVE_EDITOR: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.CULTURAL_RHETORIC: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.NATIVE_SPOKEN_CRITIC: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.AUDIENCE_RETENTION_CRITIC: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.DURATION_ADJUSTMENT: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.TARGETED_LOCALIZATION_REPAIR: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.SEMANTIC_PATCH_REPAIR: ModelRole.PROFESSIONAL_REASONING,
    AgentRole.TITLE_CANDIDATE: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.HOOK_CANDIDATE: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.DESCRIPTION_CANDIDATE: ModelRole.MULTILINGUAL_EDITORIAL,
    AgentRole.PERSIAN_SEMANTIC_MASTER: ModelRole.PREMIUM_CREATION,
    AgentRole.PERSIAN_SCRIPT_WRITER: ModelRole.PREMIUM_CREATION,
    AgentRole.PRONUNCIATION_EDITOR: ModelRole.PREMIUM_CREATION,
    AgentRole.PREMIUM_TARGETED_REVISION: ModelRole.PREMIUM_CREATION,
    AgentRole.TARGET_FINAL_EDITOR: ModelRole.PREMIUM_CREATION,
    AgentRole.PREMIUM_CONFLICT_RESOLVER: ModelRole.PREMIUM_CREATION,
    AgentRole.LEGACY_DEFAULT: ModelRole.LEGACY,
}

_MODEL_ROLE_SETTING: dict[ModelRole, str] = {
    ModelRole.HIGH_VOLUME_REASONING: "model_role_high_volume",
    ModelRole.PROFESSIONAL_REASONING: "model_role_reasoning",
    ModelRole.MULTILINGUAL_EDITORIAL: "model_role_editorial",
    ModelRole.PREMIUM_CREATION: "model_role_premium",
    ModelRole.PREMIUM_CREATION_FAST: "model_role_premium",
    # Legacy ingestion/extraction work routes to the reasoning model —
    # strict-schema structured work, not audience-facing premium text.
    ModelRole.LEGACY: "model_role_reasoning",
}


def model_for_role(
    model_role: ModelRole,
    settings: Settings,
    *,
    effective: dict[str, object] | None = None,
) -> str:
    """Resolve the concrete model ID for a model role.

    ``effective`` carries owner overrides (``StudioSettingsService.effective``)
    when available so DB-level overrides win over environment defaults.
    """

    key = _MODEL_ROLE_SETTING[model_role]
    if effective is not None and key in effective:
        return str(effective[key])
    return str(getattr(settings, key))


def is_premium_role(agent_role: AgentRole) -> bool:
    return AGENT_TO_MODEL_ROLE[agent_role] in {
        ModelRole.PREMIUM_CREATION,
        ModelRole.PREMIUM_CREATION_FAST,
    }

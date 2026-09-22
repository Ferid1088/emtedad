"""Structured, replaceable evidence-role and relation classifier."""

from app.dialogue.domain import ClaimTestability
from app.dialogue.schemas import DialogueClassification
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest

PROMPT_VERSION = "dialogue-evidence-role-v1"
CLASSIFIER_VERSION = "evidence-role-classifier-v1"

_INSTRUCTIONS = """
Classify a possible intellectual relation between the exact Ayin context and the
external source excerpt. External material never defines Ayin and similarity is
not identity or proof. Return zero relations when the excerpt is not genuinely
relevant. SUPPORTS_EMPIRICAL_SUBCLAIM is allowed only for a directly testable
descriptive Ayin statement with actual matching evidence. A conceptual
similarity should use CONCEPTUAL_PARALLEL and, when identity would be misleading,
also NOT_EQUIVALENT_TO. Treat negative, alternative, and unresolved relations as
first-class. Confidence is confidence in the classification, never probability
that Ayin is true. Explanations must be concise and refer only to supplied text.
Do not upgrade external claim verification or resolve an Ayin open question.
""".strip()


class EvidenceRoleClassifier:
    """Classify legitimate evidence role separately from relation type."""

    def __init__(self, provider: LLMProvider, *, model: str) -> None:
        self.provider = provider
        self.model = model

    async def classify(
        self,
        *,
        ayin_context: str,
        external_context: str,
        fixed_testability: ClaimTestability | None,
    ) -> DialogueClassification:
        testability_note = (
            f"The deterministic Ayin classification is {fixed_testability.value}; "
            "return exactly that claim_testability."
            if fixed_testability is not None
            else "Classify whether the descriptive statement is testable."
        )
        output = await self.provider.extract(
            StructuredExtractionRequest(
                task="ayin_external_dialogue_classification",
                prompt_version=PROMPT_VERSION,
                model=self.model,
                instructions=f"{_INSTRUCTIONS}\n{testability_note}",
                input_text=(
                    "AYIN CONTEXT (authoritative only for what Ayin says):\n"
                    f"{ayin_context}\n\nEXTERNAL CONTEXT (external primary material):\n"
                    f"{external_context}"
                ),
                output_model=DialogueClassification,
            )
        )
        classification = DialogueClassification.model_validate(output)
        if (
            fixed_testability is not None
            and classification.claim_testability is not fixed_testability
        ):
            return classification.model_copy(
                update={"claim_testability": fixed_testability}
            )
        return classification

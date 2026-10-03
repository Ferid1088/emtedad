"""Vocabulary for Knowledge Units extracted from structure nodes."""

from enum import StrEnum

from app.knowledge.structure.domain import StructureNodeType


class KnowledgeUnitType(StrEnum):
    CLAIM = "CLAIM"
    DEFINITION = "DEFINITION"
    EXPLANATION = "EXPLANATION"
    STORY = "STORY"
    CASE_STUDY = "CASE_STUDY"
    EXAMPLE = "EXAMPLE"
    EXPERIMENT = "EXPERIMENT"
    QUOTE = "QUOTE"
    COUNTERARGUMENT = "COUNTERARGUMENT"
    OPEN_QUESTION = "OPEN_QUESTION"
    SYNTHESIS = "SYNTHESIS"


class ClaimType(StrEnum):
    FACT = "FACT"
    INTERPRETATION = "INTERPRETATION"
    OPINION = "OPINION"
    NORMATIVE = "NORMATIVE"
    UNKNOWN = "UNKNOWN"


class EvidenceLevel(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    ANECDOTAL = "ANECDOTAL"
    NONE = "NONE"


ATOMIC_UNIT_TYPES: frozenset[KnowledgeUnitType] = frozenset(
    {KnowledgeUnitType.STORY, KnowledgeUnitType.CASE_STUDY}
)

# Container types never become units when they still have children; leaf
# topics/subtopics may carry content and stay eligible.
_CONTAINER_TYPES: frozenset[StructureNodeType] = frozenset(
    {StructureNodeType.TOPIC, StructureNodeType.SUBTOPIC}
)

_NODE_TO_UNIT: dict[StructureNodeType, KnowledgeUnitType] = {
    StructureNodeType.ARGUMENT: KnowledgeUnitType.CLAIM,
    StructureNodeType.EXPLANATION: KnowledgeUnitType.EXPLANATION,
    StructureNodeType.STORY: KnowledgeUnitType.STORY,
    StructureNodeType.CASE_STUDY: KnowledgeUnitType.CASE_STUDY,
    StructureNodeType.EXAMPLE: KnowledgeUnitType.EXAMPLE,
    StructureNodeType.EXPERIMENT: KnowledgeUnitType.EXPERIMENT,
    StructureNodeType.QUESTION: KnowledgeUnitType.OPEN_QUESTION,
    StructureNodeType.ANSWER: KnowledgeUnitType.SYNTHESIS,
    StructureNodeType.COUNTERARGUMENT: KnowledgeUnitType.COUNTERARGUMENT,
    StructureNodeType.DEFINITION: KnowledgeUnitType.DEFINITION,
    StructureNodeType.CONCLUSION: KnowledgeUnitType.SYNTHESIS,
    StructureNodeType.TOPIC: KnowledgeUnitType.EXPLANATION,
    StructureNodeType.SUBTOPIC: KnowledgeUnitType.EXPLANATION,
    StructureNodeType.OTHER: KnowledgeUnitType.CLAIM,
}


def default_unit_type(node_type: StructureNodeType) -> KnowledgeUnitType:
    return _NODE_TO_UNIT[node_type]


def node_is_unit_eligible(node_type: StructureNodeType, *, has_children: bool) -> bool:
    if node_type in {StructureNodeType.STORY, StructureNodeType.CASE_STUDY}:
        return True
    return not (node_type in _CONTAINER_TYPES and has_children)


UNIT_EXTRACTION_TASK = "knowledge_units"
UNIT_EXTRACTION_VERSION = "knowledge_unit_v1"
UNIT_PROMPT_VERSION = "knowledge_unit_metadata_v1"

"""Typed states and policies for the Manasek ritual domain."""

from enum import StrEnum


class RitualFamilyType(StrEnum):
    GATE = "GATE"
    BETWEEN = "BETWEEN"
    LIFE = "LIFE"


class RitualMode(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    COLLECTIVE = "COLLECTIVE"


class RitualPieceType(StrEnum):
    GATE = "GATE"
    RETURN = "RETURN"
    COLLECTIVE = "COLLECTIVE"


class GateKey(StrEnum):
    EARTH = "EARTH"
    WATER = "WATER"
    FIRE = "FIRE"
    WIND = "WIND"
    PULL = "PULL"


class RitualRelationType(StrEnum):
    EXPERIENTIALIZES = "EXPERIENTIALIZES"
    ILLUSTRATES = "ILLUSTRATES"
    RELATES_TO = "RELATES_TO"
    PREPARES_FOR = "PREPARES_FOR"
    REFLECTS = "REFLECTS"
    DOES_NOT_DEFINE = "DOES_NOT_DEFINE"


class CueType(StrEnum):
    NARRATION = "narration"
    WHISPER = "whisper"
    SILENCE = "silence"
    MOVEMENT = "movement"
    ATTENTION = "attention"
    TRANSITION = "transition"
    GROUNDING = "grounding"
    MUSIC_INSTRUCTION = "music_instruction"
    SAFETY_INSTRUCTION = "safety_instruction"


class SafetyCategory(StrEnum):
    CONSENT = "CONSENT"
    EXIT = "EXIT"
    TOUCH = "TOUCH"
    MOVEMENT = "MOVEMENT"
    BREATH = "BREATH"
    INTENSITY = "INTENSITY"
    INTERPRETATION = "INTERPRETATION"
    GROUP_PRESSURE = "GROUP_PRESSURE"
    DISCLOSURE = "DISCLOSURE"
    AFTERCARE = "AFTERCARE"
    MUSIC = "MUSIC"
    MENTAL_HEALTH_BOUNDARY = "MENTAL_HEALTH_BOUNDARY"


class SafetySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class RitualReviewReason(StrEnum):
    UNCERTAIN_RITUAL_BOUNDARY = "uncertain_ritual_boundary"
    UNCERTAIN_HEADING = "uncertain_heading"
    EXTRACTION_CORRUPTION = "extraction_corruption"
    UNCLEAR_TIMING = "unclear_timing"
    AMBIGUOUS_GATE_ASSIGNMENT = "ambiguous_gate_assignment"
    UNCERTAIN_STAGE_ASSIGNMENT = "uncertain_stage_assignment"
    UNCERTAIN_AYIN_CONCEPT_LINK = "uncertain_ayin_concept_link"
    SAFETY_CONCERN = "safety_concern"
    MUSIC_PROMPT_PARSING = "music_prompt_parsing_issue"
    COLLECTIVE_INDIVIDUAL_AMBIGUITY = "collective_individual_ambiguity"


GATE_ORDER: tuple[GateKey, ...] = (
    GateKey.EARTH,
    GateKey.WATER,
    GateKey.FIRE,
    GateKey.WIND,
    GateKey.PULL,
)

STAGE_KEYS: tuple[str, ...] = (
    "CONTACT",
    "DISTINCTION",
    "CONTINUITY_IN_CHANGE",
    "TEMPORAL_EMTEDAD",
    "EFFECT_AND_RESPONSIBILITY",
    "OTHER_AND_BREADTH_OF_PRESENCE",
    "INTEGRATION",
)

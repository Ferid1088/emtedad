"""Validated editorial seed manifest for source-backed Working proposals."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.core.ayin.domain import (
    DiscourseType,
    DistinctionRelation,
    EditorialStatus,
    LanguageCode,
    TermFormType,
)

DEFAULT_SEED_PATH = (
    Path(__file__).parents[3] / "resources" / "ayin" / "working_seed.v1.json"
)


class SeedBase(BaseModel):
    """Forbid silent manifest fields or misspellings."""

    model_config = ConfigDict(extra="forbid")


class ProvenanceSeed(SeedBase):
    page: int = Field(gt=0)
    anchor: str = Field(min_length=2)


class ConceptSeed(ProvenanceSeed):
    stable_key: str
    definition: str


class DistinctionSeed(ProvenanceSeed):
    stable_key: str
    left: str
    relation: DistinctionRelation
    right_label: str
    explanation: str
    discourse_type: DiscourseType


class PrincipleSeed(ProvenanceSeed):
    stable_key: str
    statement: str
    discourse_type: DiscourseType


class OpenQuestionSeed(ProvenanceSeed):
    stable_key: str
    question: str
    context: str
    discourse_type: DiscourseType


class TermFormSeed(SeedBase):
    language: LanguageCode
    script: str
    form: str
    form_type: TermFormType
    status: EditorialStatus


class TermSeed(ProvenanceSeed):
    stable_key: str
    concept: str
    forms: list[TermFormSeed]


class AyinSeedManifest(SeedBase):
    """Source identity plus explicitly reviewed Working proposal records."""

    manifest_version: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_page_count: int = Field(gt=0)
    concepts: list[ConceptSeed]
    distinctions: list[DistinctionSeed]
    principles: list[PrincipleSeed]
    open_questions: list[OpenQuestionSeed]
    terms: list[TermSeed]


def load_seed_manifest(path: Path = DEFAULT_SEED_PATH) -> AyinSeedManifest:
    """Load a seed manifest without treating its Working proposals as Canon."""

    return AyinSeedManifest.model_validate_json(path.read_text(encoding="utf-8"))


def canonical_manifest_hash(manifest: AyinSeedManifest) -> str:
    """Return stable JSON used to identify the exact proposal configuration."""

    import hashlib

    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()

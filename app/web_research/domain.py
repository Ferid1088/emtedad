"""Web research vocabulary."""

from pydantic import BaseModel, Field


class WebFinding(BaseModel):
    """One discovered web page worth ingesting as a source."""

    title: str = ""
    url: str
    snippet: str = ""


class WebResearchReport(BaseModel):
    """Provider output: findings plus an optional synthesized answer.

    ``answer_text`` is provenance context only — it is stored in source
    metadata, never ingested as source material.
    """

    provider: str
    query: str
    answer_text: str = ""
    findings: list[WebFinding] = Field(default_factory=list)


class IngestedWebSource(BaseModel):
    """Outcome of fetching and ingesting one finding."""

    url: str
    source_id: str | None = None
    status: str  # "ingested" | "existing" | "failed"
    detail: str = ""
    publication_type: str = ""
    retrieval_weight: float | None = None

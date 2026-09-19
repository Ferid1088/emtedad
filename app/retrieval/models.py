"""Relational model for versioned chunks, embeddings, runs, and evaluation."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ayin.domain import CorpusZone
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now
from app.retrieval.domain import (
    BuildStatus,
    DistanceMetric,
    EvaluationQueryType,
    QueryLanguage,
    RetrievalLane,
    RetrievalSourceKind,
)

RETRIEVAL = PostgresSchema.RETRIEVAL.value
CORE = PostgresSchema.CORE.value
RITUAL = PostgresSchema.RITUAL.value
KNOWLEDGE = PostgresSchema.KNOWLEDGE.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=RETRIEVAL,
        values_callable=lambda members: [member.value for member in members],
    )


def _core_enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CORE,
        create_type=False,
        values_callable=lambda members: [member.value for member in members],
    )


class ChunkingRun(Base):
    __tablename__ = "chunking_runs"
    __table_args__ = (
        UniqueConstraint("input_hash", "configuration_hash"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="valid_input_hash"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'", name="valid_configuration_hash"
        ),
        CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="valid_output_hash",
        ),
        {"schema": RETRIEVAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    input_hash: Mapped[str] = mapped_column(String(64))
    configuration_hash: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    normalization_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[BuildStatus] = mapped_column(_enum(BuildStatus, "build_status"))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChunkingRunAyinSource(Base):
    __tablename__ = "chunking_run_ayin_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_run_id", "canon_version_id"],
            [f"{CORE}.extraction_runs.id", f"{CORE}.extraction_runs.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": RETRIEVAL},
    )

    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    canon_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    extraction_run_id: Mapped[UUID]


class ChunkingRunRitualSource(Base):
    __tablename__ = "chunking_run_ritual_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_run_id", "source_version_id"],
            [
                f"{RITUAL}.extraction_runs.id",
                f"{RITUAL}.extraction_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": RETRIEVAL},
    )

    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    extraction_run_id: Mapped[UUID]


class ChunkingRunExternalSource(Base):
    __tablename__ = "chunking_run_external_sources"
    __table_args__ = ({"schema": RETRIEVAL},)

    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("chunking_run_id", "ordinal"),
        UniqueConstraint("id", "chunking_run_id"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        CheckConstraint("token_count > 0", name="positive_token_count"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        CheckConstraint(
            "(lane = 'ayin' AND corpus_zone IN ('AYIN_WORKING', 'AYIN_CANON')) OR "
            "(lane = 'manasek' AND corpus_zone IN "
            "('MANASEK_WORKING', 'MANASEK_CANON')) OR "
            "(lane = 'external' AND corpus_zone IN "
            "('EXTERNAL_PRIMARY', 'EXTERNAL_DERIVED'))",
            name="lane_matches_authority",
        ),
        Index("ix_retrieval_chunks_lane_language", "lane", "language"),
        Index(
            "ix_retrieval_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        {"schema": RETRIEVAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="RESTRICT"), index=True
    )
    corpus_zone: Mapped[CorpusZone] = mapped_column(
        _core_enum(CorpusZone, "corpus_zone")
    )
    lane: Mapped[RetrievalLane] = mapped_column(_enum(RetrievalLane, "retrieval_lane"))
    source_kind: Mapped[RetrievalSourceKind] = mapped_column(
        _enum(RetrievalSourceKind, "retrieval_source_kind")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16))
    section_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(normalized_text, ''))", persisted=True
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ChunkCanonPassage(Base):
    __tablename__ = "chunk_canon_passages"
    __table_args__ = (
        UniqueConstraint("chunk_id", "sequence_in_chunk"),
        {"schema": RETRIEVAL},
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="CASCADE"), primary_key=True
    )
    canon_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_passages.id", ondelete="RESTRICT"), primary_key=True
    )
    sequence_in_chunk: Mapped[int] = mapped_column(Integer)


class ChunkRitualPassage(Base):
    __tablename__ = "chunk_ritual_passages"
    __table_args__ = (
        UniqueConstraint("chunk_id", "sequence_in_chunk"),
        {"schema": RETRIEVAL},
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="CASCADE"), primary_key=True
    )
    ritual_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT"), primary_key=True
    )
    sequence_in_chunk: Mapped[int] = mapped_column(Integer)


class ChunkExternalSegment(Base):
    __tablename__ = "chunk_external_segments"
    __table_args__ = (
        UniqueConstraint("chunk_id", "sequence_in_chunk"),
        {"schema": RETRIEVAL},
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="CASCADE"), primary_key=True
    )
    source_segment_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_segments.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    sequence_in_chunk: Mapped[int] = mapped_column(Integer)


class ChunkRitualVersion(Base):
    __tablename__ = "chunk_ritual_versions"
    __table_args__ = ({"schema": RETRIEVAL},)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="CASCADE"), primary_key=True
    )
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ChunkAyinConcept(Base):
    __tablename__ = "chunk_ayin_concepts"
    __table_args__ = ({"schema": RETRIEVAL},)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT"), primary_key=True
    )


class ChunkExternalEntity(Base):
    __tablename__ = "chunk_external_entities"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(person_id, work_id, organization_id, concept_id) = 1",
            name="one_typed_entity",
        ),
        UniqueConstraint("chunk_id", "person_id"),
        UniqueConstraint("chunk_id", "work_id"),
        UniqueConstraint("chunk_id", "organization_id"),
        UniqueConstraint("chunk_id", "concept_id"),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="CASCADE"), index=True
    )
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), nullable=True
    )
    work_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="RESTRICT"), nullable=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.organizations.id", ondelete="RESTRICT"), nullable=True
    )
    concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="RESTRICT"),
        nullable=True,
    )


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"
    __table_args__ = (
        UniqueConstraint("provider", "model_name", "revision"),
        CheckConstraint(
            "dimensions > 0 AND dimensions <= 2000", name="valid_dimensions"
        ),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(512))
    revision: Mapped[str] = mapped_column(String(128))
    dimensions: Mapped[int] = mapped_column(Integer)
    distance_metric: Mapped[DistanceMetric] = mapped_column(
        _enum(DistanceMetric, "distance_metric")
    )
    language_capabilities: Mapped[list[str]] = mapped_column(JSONB)
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class EmbeddingRun(Base):
    __tablename__ = "embedding_runs"
    __table_args__ = (
        UniqueConstraint("chunking_run_id", "embedding_model_id", "configuration_hash"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'", name="valid_configuration_hash"
        ),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="RESTRICT")
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.embedding_models.id", ondelete="RESTRICT")
    )
    configuration_hash: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[BuildStatus] = mapped_column(_enum(BuildStatus, "build_status"))
    embedded_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model_id", "content_hash"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="RESTRICT"), index=True
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.embedding_models.id", ondelete="RESTRICT"), index=True
    )
    embedding_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.embedding_runs.id", ondelete="RESTRICT")
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(VECTOR())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RetrievalConfiguration(Base):
    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        UniqueConstraint("configuration_hash"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'", name="valid_configuration_hash"
        ),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB)
    configuration_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RetrievalRun(Base):
    __tablename__ = "runs"
    __table_args__ = ({"schema": RETRIEVAL},)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="RESTRICT")
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.embedding_models.id", ondelete="RESTRICT")
    )
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.configurations.id", ondelete="RESTRICT")
    )
    query_text: Mapped[str] = mapped_column(Text)
    normalized_query: Mapped[str] = mapped_column(Text)
    language: Mapped[QueryLanguage] = mapped_column(
        _enum(QueryLanguage, "query_language")
    )
    filters: Mapped[dict[str, object]] = mapped_column(JSONB)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RetrievalResult(Base):
    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("retrieval_run_id", "chunk_id"),
        CheckConstraint("final_rank > 0", name="positive_final_rank"),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    retrieval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.runs.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="RESTRICT")
    )
    lexical_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lexical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    dense_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dense_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    entity_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fusion_score: Mapped[float] = mapped_column(Float)
    reranker_score: Mapped[float] = mapped_column(Float)
    final_rank: Mapped[int] = mapped_column(Integer)
    expanded_context: Mapped[list[dict[str, object]]] = mapped_column(JSONB)


class EvaluationQuery(Base):
    __tablename__ = "evaluation_queries"
    __table_args__ = (
        UniqueConstraint("stable_key", "language"),
        {"schema": RETRIEVAL},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255))
    language: Mapped[QueryLanguage] = mapped_column(
        _enum(QueryLanguage, "query_language")
    )
    query_text: Mapped[str] = mapped_column(Text)
    query_type: Mapped[EvaluationQueryType] = mapped_column(
        _enum(EvaluationQueryType, "evaluation_query_type")
    )
    expected_lane: Mapped[RetrievalLane] = mapped_column(
        _enum(RetrievalLane, "retrieval_lane")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvaluationJudgment(Base):
    __tablename__ = "evaluation_judgments"
    __table_args__ = (
        CheckConstraint("relevance >= 0 AND relevance <= 3", name="valid_relevance"),
        {"schema": RETRIEVAL},
    )
    evaluation_query_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.evaluation_queries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="RESTRICT"), primary_key=True
    )
    relevance: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = ({"schema": RETRIEVAL},)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="RESTRICT")
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.embedding_models.id", ondelete="RESTRICT")
    )
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.configurations.id", ondelete="RESTRICT")
    )
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB)
    query_count: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

"""Automated long-form generation over the existing hybrid retrieval stack."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.retrieval.domain import RetrievalLane
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.schemas import SearchResult
from app.retrieval.service import HybridRetrievalService
from app.semantic_content.context import SemanticContextExpander
from app.semantic_content.domain import ContentGenerationStatus
from app.semantic_content.models import GeneratedContentProject, GeneratedContentSection
from app.semantic_content.schemas import (
    CoherenceReportSpec,
    ContentOutlineSpec,
    FinalRevisionSpec,
    GenerateContentRequest,
    GeneratedContentRead,
    GeneratedContentSectionRead,
    GenerationPlanSpec,
    SectionDraftSpec,
    SynthesisSpec,
)

PLAN = """Design 4-8 narrow research queries for one coherent long-form
spoken script. Do not write the script. Cover the central question from
complementary angles and include tension, limits, or counterpoints when relevant."""

SYNTHESIZE = """Synthesize retrieved candidates into a compact knowledge map.
Deduplicate repeated ideas, cluster related material, preserve disagreement and
uncertainty, and never invent or alter candidate IDs or source metadata. Semantic
families are context, not proof that every sentence in the family supports every
claim."""

ARCHITECT = """Create one coherent 4-6 section spoken-content outline when possible.
Every section must advance the central question and transition naturally from the
previous section. Use only supplied cluster IDs and distribute the target word
budget across sections."""

WRITE = """Write only this section of a spoken script. The evidence pack is the
factual boundary. Explain difficult ideas simply, preserve uncertainty, and avoid
repeating concepts already covered. Do not mention retrieval, chunks, prompts, or
candidate IDs. Do not invent facts, people, studies, quotations, or examples."""

AUDIT = """Audit the full draft without rewriting it. Report only meaningful
repetition, abrupt transitions, concepts used before definition, contradictions,
unsupported statements, missing logical steps, or conclusions that introduce new
claims."""

TModel = TypeVar("TModel", bound=BaseModel)


REVISE = """Revise only the problems identified by the audit. Preserve the
argument, qualifications, and evidence boundary. Improve flow surgically and
introduce no new facts."""


class AutomatedContentService:
    """Plan, retrieve, synthesize, write, audit, and revise long-form content."""

    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider,
        llm_provider: LLMProvider,
    ) -> None:
        self._database = database
        self._retrieval = HybridRetrievalService(database, embedding_provider)
        self._llm = llm_provider
        self._expander = SemanticContextExpander()

    async def generate(self, request: GenerateContentRequest) -> GeneratedContentRead:
        target_words = round(
            request.target_duration_seconds / 60 * request.words_per_minute
        )
        async with self._database.transaction() as session:
            project = GeneratedContentProject(
                topic=request.topic,
                language=request.language.value,
                target_duration_seconds=request.target_duration_seconds,
                target_word_count=target_words,
                status=ContentGenerationStatus.PLANNING.value,
                chunking_run_id=request.chunking_run_id,
                embedding_model_id=request.embedding_model_id,
                context_expansion_mode=request.context_expansion_mode.value,
                created_by=request.created_by,
            )
            session.add(project)
            await session.flush()
            project_id = project.id
        try:
            plan = await self._structured(
                "long-form-content-research-plan",
                "content-plan-v2",
                request.model,
                PLAN,
                {
                    "topic": request.topic,
                    "language": request.language.value,
                    "target_word_count": target_words,
                },
                GenerationPlanSpec,
            )
            await self._update(
                project_id,
                ContentGenerationStatus.RETRIEVING,
                plan=plan.model_dump(mode="json"),
            )
            snapshot = await self._retrieve(request, plan)
            await self._update(
                project_id,
                ContentGenerationStatus.SYNTHESIZING,
                retrieval_snapshot=snapshot,
            )
            synthesis = await self._structured(
                "long-form-content-knowledge-synthesis",
                "knowledge-synthesis-v2",
                request.model,
                SYNTHESIZE,
                {
                    "topic": request.topic,
                    "central_question": plan.central_question,
                    "evidence_candidates": snapshot["evidence"],
                },
                SynthesisSpec,
                timeout_seconds=300,
            )
            self._validate_references(synthesis, snapshot["evidence"])
            await self._update(
                project_id,
                ContentGenerationStatus.ARCHITECTING,
                synthesis=synthesis.model_dump(mode="json"),
            )
            outline = await self._structured(
                "long-form-content-architecture",
                "content-architecture-v2",
                request.model,
                ARCHITECT,
                {
                    "topic": request.topic,
                    "central_question": plan.central_question,
                    "thesis_direction": plan.thesis_direction,
                    "target_word_count": target_words,
                    "synthesis": synthesis.model_dump(mode="json"),
                },
                ContentOutlineSpec,
            )
            self._validate_outline(outline, synthesis, target_words)
            await self._update(
                project_id,
                ContentGenerationStatus.WRITING,
                outline=outline.model_dump(mode="json"),
            )
            draft = await self._write(project_id, request, plan, synthesis, outline)
            await self._update(project_id, ContentGenerationStatus.REVIEWING)
            audit = await self._structured(
                "long-form-content-coherence-audit",
                "coherence-audit-v2",
                request.model,
                AUDIT,
                {"draft": draft},
                CoherenceReportSpec,
                timeout_seconds=240,
            )
            if audit.issues:
                revision = await self._structured(
                    "long-form-content-targeted-revision",
                    "targeted-revision-v2",
                    request.model,
                    REVISE,
                    {
                        "language": request.language.value,
                        "audit": audit.model_dump(mode="json"),
                        "draft": draft,
                    },
                    FinalRevisionSpec,
                    timeout_seconds=300,
                )
                final_script = revision.revised_script.strip()
            else:
                final_script = draft
            await self._update(
                project_id,
                ContentGenerationStatus.READY,
                coherence_report=audit.model_dump(mode="json"),
                final_script=final_script,
                provenance_complete=self._provenance_complete(snapshot, synthesis),
            )
            return await self.project(project_id)
        except Exception:
            await self._update(project_id, ContentGenerationStatus.FAILED)
            raise

    async def project(self, project_id: UUID) -> GeneratedContentRead:
        async with self._database.transaction() as session:
            project = await session.get(GeneratedContentProject, project_id)
            if project is None:
                raise ValueError("generated content project not found")
            sections = list(
                await session.scalars(
                    select(GeneratedContentSection)
                    .where(GeneratedContentSection.project_id == project_id)
                    .order_by(GeneratedContentSection.ordinal)
                )
            )
            return GeneratedContentRead(
                id=project.id,
                topic=project.topic,
                language=project.language,
                target_duration_seconds=project.target_duration_seconds,
                target_word_count=project.target_word_count,
                status=project.status,
                plan=project.plan,
                synthesis=project.synthesis,
                outline=project.outline,
                coherence_report=project.coherence_report,
                final_script=project.final_script,
                provenance_complete=project.provenance_complete,
                sections=[
                    GeneratedContentSectionRead.model_validate(section)
                    for section in sections
                ],
            )

    async def _retrieve(
        self, request: GenerateContentRequest, plan: GenerationPlanSpec
    ) -> dict[str, object]:
        evidence: list[dict[str, object]] = []
        queries: list[dict[str, object]] = []
        seen: set[UUID] = set()
        counter = 0
        for query in plan.research_queries:
            response = await self._retrieval.search(
                query.query,
                request.language,
                chunking_run_id=request.chunking_run_id,
                embedding_model_id=request.embedding_model_id,
                lanes=[RetrievalLane.EXTERNAL],
                parameters={"lane_top_n": 8, "context_neighbors": 1},
            )
            ids: list[str] = []
            for hit in response.results:
                if hit.chunk_id in seen:
                    continue
                seen.add(hit.chunk_id)
                counter += 1
                candidate_id = f"E{counter:04d}"
                semantic = await self._semantic_context(request, hit)
                evidence.append(
                    {
                        "candidate_id": candidate_id,
                        "query": query.query,
                        "purpose": query.purpose,
                        "chunk_id": str(hit.chunk_id),
                        "hit_text": hit.text,
                        "expanded_neighbor_context": hit.expanded_context,
                        "semantic_hit_path": semantic["hit_path"],
                        "semantic_root_path": semantic["root_path"],
                        "semantic_family": semantic["nodes"],
                        "source_id": str(hit.provenance.source_id),
                        "source_version_id": str(hit.provenance.source_version_id),
                        "source_title": hit.provenance.source_title,
                        "source_url": hit.provenance.source_url,
                        "timestamp_start": hit.provenance.timestamp_start,
                        "timestamp_end": hit.provenance.timestamp_end,
                        "fusion_score": hit.fusion_score,
                        "reranker_score": hit.reranker_score,
                    }
                )
                ids.append(candidate_id)
            queries.append(
                {
                    "query": query.query,
                    "purpose": query.purpose,
                    "retrieval_run_id": str(response.retrieval_run_id),
                    "candidate_ids": ids,
                }
            )
        if not evidence:
            raise ValueError("retrieval returned no external evidence")
        return {
            "queries": queries,
            "evidence": evidence,
            "context_expansion_mode": request.context_expansion_mode.value,
        }

    async def _semantic_context(
        self, request: GenerateContentRequest, hit: SearchResult
    ) -> dict[str, object]:
        async with self._database.transaction() as session:
            expanded = await self._expander.expand(
                session,
                source_version_id=hit.provenance.source_version_id,
                source_segment_ids=hit.provenance.record_ids,
                mode=request.context_expansion_mode,
            )
        return {
            "hit_path": expanded.hit_path,
            "root_path": expanded.root_path,
            "nodes": expanded.nodes,
        }

    async def _write(
        self,
        project_id: UUID,
        request: GenerateContentRequest,
        plan: GenerationPlanSpec,
        synthesis: SynthesisSpec,
        outline: ContentOutlineSpec,
    ) -> str:
        clusters = {cluster.cluster_id: cluster for cluster in synthesis.clusters}
        state: dict[str, object] = {
            "central_question": plan.central_question,
            "thesis_direction": plan.thesis_direction,
            "defined_concepts": [],
            "claims_used": [],
            "examples_used": [],
            "previous_section_summary": None,
        }
        texts: list[str] = []
        for ordinal, section in enumerate(outline.sections, start=1):
            selected = [clusters[key] for key in section.cluster_ids]
            state_snapshot = {
                key: list(value) if isinstance(value, list) else value
                for key, value in state.items()
            }
            evidence_pack = {
                "section": section.model_dump(mode="json"),
                "clusters": [item.model_dump(mode="json") for item in selected],
                "global_state": state_snapshot,
                "opening_intent": outline.opening_intent if ordinal == 1 else None,
                "conclusion_intent": (
                    outline.conclusion_intent
                    if ordinal == len(outline.sections)
                    else None
                ),
            }
            draft = await self._structured(
                "long-form-content-section-writer",
                "section-writer-v2",
                request.model,
                WRITE + f"\nWrite in language code: {request.language.value}.",
                evidence_pack,
                SectionDraftSpec,
                timeout_seconds=240,
            )
            text = draft.text.strip()
            texts.append(text)
            state["defined_concepts"] = self._merge(
                state["defined_concepts"], draft.concepts_defined
            )
            state["claims_used"] = self._merge(
                state["claims_used"], draft.claims_used
            )
            state["examples_used"] = self._merge(
                state["examples_used"], draft.examples_used
            )
            state["previous_section_summary"] = text[-900:]
            async with self._database.transaction() as session:
                session.add(
                    GeneratedContentSection(
                        project_id=project_id,
                        ordinal=ordinal,
                        title=section.title,
                        purpose=section.purpose,
                        transition_from_previous=section.transition_from_previous,
                        target_word_count=section.target_word_count,
                        evidence_pack=evidence_pack,
                        draft_text=text,
                    )
                )
        return "\n\n".join(texts)

    async def _structured(
        self,
        task: str,
        prompt_version: str,
        model: str,
        instructions: str,
        payload: dict[str, object],
        output_model: type[TModel],
        timeout_seconds: int = 180,
    ) -> TModel:
        result = await self._llm.extract(
            StructuredExtractionRequest(
                task=task,
                prompt_version=prompt_version,
                model=model,
                instructions=instructions,
                input_text=json.dumps(payload, ensure_ascii=False),
                output_model=output_model,
                timeout_seconds=timeout_seconds,
            )
        )
        return output_model.model_validate(result)

    async def _update(
        self,
        project_id: UUID,
        status: ContentGenerationStatus,
        **changes: object,
    ) -> None:
        async with self._database.transaction() as session:
            project = await session.get(GeneratedContentProject, project_id)
            if project is None:
                raise RuntimeError("generated content project disappeared")
            project.status = status.value
            project.updated_at = datetime.now(UTC)
            for key, value in changes.items():
                setattr(project, key, value)

    @staticmethod
    def _validate_outline(
        outline: ContentOutlineSpec,
        synthesis: SynthesisSpec,
        target_words: int,
    ) -> None:
        valid = {cluster.cluster_id for cluster in synthesis.clusters}
        used = {
            key for section in outline.sections for key in section.cluster_ids
        }
        if not used.issubset(valid):
            raise ValueError("outline references unknown synthesis cluster")
        assigned = sum(section.target_word_count for section in outline.sections)
        if not 0.85 * target_words <= assigned <= 1.15 * target_words:
            raise ValueError("outline word budget is outside allowed tolerance")

    @staticmethod
    def _validate_references(
        synthesis: SynthesisSpec, evidence: object
    ) -> None:
        if not isinstance(evidence, list):
            raise ValueError("invalid retrieval evidence")
        available = {
            str(item["candidate_id"]): item
            for item in evidence
            if isinstance(item, dict) and item.get("candidate_id")
        }
        keys = (
            "source_id",
            "source_version_id",
            "source_title",
            "source_url",
            "timestamp_start",
            "timestamp_end",
            "chunk_id",
            "semantic_root_path",
            "semantic_hit_path",
        )
        for cluster in synthesis.clusters:
            for reference in cluster.references:
                source = available.get(reference.candidate_id)
                if source is None:
                    raise ValueError(
                        f"synthesis invented candidate {reference.candidate_id}"
                    )
                actual = reference.model_dump()
                for key in keys:
                    expected = source.get(key)
                    if key in {"source_id", "source_version_id", "chunk_id"}:
                        expected = str(expected)
                    if actual[key] != expected:
                        raise ValueError(
                            f"synthesis changed provenance for "
                            f"{reference.candidate_id}"
                        )

    @staticmethod
    def _provenance_complete(
        snapshot: dict[str, object], synthesis: SynthesisSpec
    ) -> bool:
        evidence = snapshot.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return False
        known = {
            str(item.get("candidate_id"))
            for item in evidence
            if isinstance(item, dict) and item.get("candidate_id")
        }
        used = {
            ref.candidate_id
            for cluster in synthesis.clusters
            for ref in cluster.references
        }
        return bool(used) and used.issubset(known)

    @staticmethod
    def _merge(existing: object, additions: list[str]) -> list[str]:
        values = (\n            [str(value) for value in existing]\n            if isinstance(existing, list)\n            else []\n        )
        seen = set(values)
        for value in additions:
            if value not in seen:
                values.append(value)
                seen.add(value)
        return values

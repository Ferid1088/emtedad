"""Idempotent, provenance-complete chunk construction across source domains."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import CorpusZone
from app.core.ayin.models import (
    AyinConceptVersion,
    CanonPassage,
    CanonVersion,
    PreferredExtractionRun,
)
from app.core.ayin.provenance import configuration_hash
from app.db.session import Database
from app.knowledge.models import Mention, Source, SourceSegment, SourceVersion
from app.retrieval.domain import BuildStatus, RetrievalLane, RetrievalSourceKind
from app.retrieval.models import (
    Chunk,
    ChunkAyinConcept,
    ChunkCanonPassage,
    ChunkExternalEntity,
    ChunkExternalSegment,
    ChunkingRun,
    ChunkingRunAyinSource,
    ChunkingRunExternalSource,
    ChunkingRunRitualSource,
    ChunkRitualPassage,
    ChunkRitualVersion,
)
from app.retrieval.normalization import normalize_search_text, token_count
from app.ritual.models import (
    PreferredRitualExtractionRun,
    RitualPassage,
    RitualSourceVersion,
    RitualVersion,
)

NORMALIZATION_VERSION = "multilingual-search-v2"
CHUNKER_VERSION = "semantic-record-window-v1"


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    run_id: UUID
    created: bool
    chunk_count: int
    lane_counts: dict[str, int]
    output_hash: str


@dataclass(frozen=True, slots=True)
class _Record:
    id: UUID
    sequence: int
    raw_text: str
    normalized_text: str
    language: str
    section_title: str | None
    metadata: dict[str, object]


class ChunkBuilder:
    """Build stable chunks without mutating any source-domain record."""

    def __init__(
        self,
        database: Database,
        *,
        target_tokens: int = 450,
        max_tokens: int = 700,
        overlap_records: int = 1,
    ) -> None:
        if target_tokens <= 0 or max_tokens < target_tokens or overlap_records < 0:
            raise ValueError("invalid chunk configuration")
        self._database = database
        self._target = target_tokens
        self._max = max_tokens
        self._overlap = overlap_records

    async def build(self) -> ChunkingResult:
        async with self._database.transaction() as session:
            sources = await self._source_identity(session)
            input_hash = hashlib.sha256(
                json.dumps(sources, sort_keys=True).encode()
            ).hexdigest()
            configuration: dict[str, object] = {
                "chunker_version": CHUNKER_VERSION,
                "normalization_version": NORMALIZATION_VERSION,
                "target_tokens": self._target,
                "max_tokens": self._max,
                "overlap_records": self._overlap,
            }
            config_hash = configuration_hash(configuration)
            existing = await session.scalar(
                select(ChunkingRun).where(
                    ChunkingRun.input_hash == input_hash,
                    ChunkingRun.configuration_hash == config_hash,
                    ChunkingRun.status == BuildStatus.SUCCEEDED,
                )
            )
            if existing is not None:
                return await self._result(session, existing, created=False)
            run = ChunkingRun(
                input_hash=input_hash,
                configuration_hash=config_hash,
                configuration=configuration,
                normalization_version=NORMALIZATION_VERSION,
                status=BuildStatus.RUNNING,
                chunk_count=0,
            )
            session.add(run)
            await session.flush()
            await self._bind_sources(session, run.id)
            ordinal = 0
            ordinal = await self._build_ayin(session, run.id, ordinal)
            ordinal = await self._build_ritual_passages(session, run.id, ordinal)
            ordinal = await self._build_ritual_content(session, run.id, ordinal)
            ordinal = await self._build_external(session, run.id, ordinal)
            chunks = list(
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.chunking_run_id == run.id)
                    .order_by(Chunk.ordinal)
                )
            )
            output_hash = hashlib.sha256(
                "\n".join(item.content_hash for item in chunks).encode()
            ).hexdigest()
            run.chunk_count = len(chunks)
            run.output_hash = output_hash
            run.status = BuildStatus.SUCCEEDED
            run.completed_at = datetime.now(UTC)
            return await self._result(session, run, created=True)

    async def _source_identity(self, session: AsyncSession) -> list[dict[str, str]]:
        identity: list[dict[str, str]] = []
        ayin = await session.execute(
            select(CanonVersion.id, PreferredExtractionRun.extraction_run_id)
            .join(
                PreferredExtractionRun,
                PreferredExtractionRun.canon_version_id == CanonVersion.id,
            )
            .where(CanonVersion.corpus_zone == CorpusZone.AYIN_WORKING)
        )
        identity.extend(
            {"kind": "ayin", "version": str(version), "run": str(run)}
            for version, run in ayin
        )
        ritual = await session.execute(
            select(
                RitualSourceVersion.id,
                PreferredRitualExtractionRun.extraction_run_id,
            )
            .join(
                PreferredRitualExtractionRun,
                PreferredRitualExtractionRun.source_version_id
                == RitualSourceVersion.id,
            )
            .where(RitualSourceVersion.corpus_zone == CorpusZone.MANASEK_WORKING)
        )
        identity.extend(
            {"kind": "ritual", "version": str(version), "run": str(run)}
            for version, run in ritual
        )
        external = await session.scalars(
            select(SourceVersion.id).where(
                SourceVersion.corpus_zone == CorpusZone.EXTERNAL_PRIMARY
            )
        )
        identity.extend(
            {"kind": "external", "version": str(version)} for version in external
        )
        return sorted(identity, key=lambda item: (item["kind"], item["version"]))

    async def _bind_sources(self, session: AsyncSession, run_id: UUID) -> None:
        for version, extraction in await session.execute(
            select(CanonVersion.id, PreferredExtractionRun.extraction_run_id)
            .join(
                PreferredExtractionRun,
                PreferredExtractionRun.canon_version_id == CanonVersion.id,
            )
            .where(CanonVersion.corpus_zone == CorpusZone.AYIN_WORKING)
        ):
            session.add(
                ChunkingRunAyinSource(
                    chunking_run_id=run_id,
                    canon_version_id=version,
                    extraction_run_id=extraction,
                )
            )
        for version, extraction in await session.execute(
            select(
                RitualSourceVersion.id,
                PreferredRitualExtractionRun.extraction_run_id,
            )
            .join(
                PreferredRitualExtractionRun,
                PreferredRitualExtractionRun.source_version_id
                == RitualSourceVersion.id,
            )
            .where(RitualSourceVersion.corpus_zone == CorpusZone.MANASEK_WORKING)
        ):
            session.add(
                ChunkingRunRitualSource(
                    chunking_run_id=run_id,
                    source_version_id=version,
                    extraction_run_id=extraction,
                )
            )
        for version in await session.scalars(
            select(SourceVersion.id).where(
                SourceVersion.corpus_zone == CorpusZone.EXTERNAL_PRIMARY
            )
        ):
            session.add(
                ChunkingRunExternalSource(
                    chunking_run_id=run_id,
                    source_version_id=version,
                )
            )

    async def _build_ayin(
        self, session: AsyncSession, run_id: UUID, ordinal: int
    ) -> int:
        sources = await session.execute(
            select(CanonVersion.id, PreferredExtractionRun.extraction_run_id)
            .join(
                PreferredExtractionRun,
                PreferredExtractionRun.canon_version_id == CanonVersion.id,
            )
            .where(CanonVersion.corpus_zone == CorpusZone.AYIN_WORKING)
        )
        for version_id, extraction_id in sources:
            passages = list(
                await session.scalars(
                    select(CanonPassage)
                    .where(CanonPassage.extraction_run_id == extraction_id)
                    .order_by(CanonPassage.sequence)
                )
            )
            records = [
                _Record(
                    item.id,
                    item.sequence,
                    item.raw_text,
                    item.normalized_text,
                    item.language.value,
                    " / ".join(item.heading_path) if item.heading_path else None,
                    {
                        "canon_version_id": str(version_id),
                        "page_number": item.page_number,
                        "printed_page_label": item.printed_page_label,
                    },
                )
                for item in passages
            ]
            for group in self._groups(records):
                ordinal += 1
                chunk = await self._add_chunk(
                    session,
                    run_id,
                    ordinal,
                    CorpusZone.AYIN_WORKING,
                    RetrievalLane.AYIN,
                    RetrievalSourceKind.AYIN_PASSAGE,
                    group,
                )
                session.add_all(
                    [
                        ChunkCanonPassage(
                            chunk_id=chunk.id,
                            canon_passage_id=item.id,
                            sequence_in_chunk=index,
                        )
                        for index, item in enumerate(group, 1)
                    ]
                )
                passage_ids = [item.id for item in group]
                concept_ids = await session.scalars(
                    select(AyinConceptVersion.concept_id)
                    .where(AyinConceptVersion.source_passage_id.in_(passage_ids))
                    .distinct()
                )
                session.add_all(
                    [
                        ChunkAyinConcept(chunk_id=chunk.id, concept_id=value)
                        for value in concept_ids
                    ]
                )
        return ordinal

    async def _build_ritual_passages(
        self, session: AsyncSession, run_id: UUID, ordinal: int
    ) -> int:
        sources = await session.execute(
            select(
                RitualSourceVersion.id,
                PreferredRitualExtractionRun.extraction_run_id,
            )
            .join(
                PreferredRitualExtractionRun,
                PreferredRitualExtractionRun.source_version_id
                == RitualSourceVersion.id,
            )
            .where(RitualSourceVersion.corpus_zone == CorpusZone.MANASEK_WORKING)
        )
        for version_id, extraction_id in sources:
            passages = list(
                await session.scalars(
                    select(RitualPassage)
                    .where(RitualPassage.extraction_run_id == extraction_id)
                    .order_by(RitualPassage.sequence)
                )
            )
            records = [
                _Record(
                    item.id,
                    item.sequence,
                    item.raw_text,
                    item.normalized_text,
                    item.language.value,
                    " / ".join(item.heading_path) if item.heading_path else None,
                    {
                        "source_version_id": str(version_id),
                        "page_number": item.page_number,
                    },
                )
                for item in passages
            ]
            for group in self._groups(records):
                ordinal += 1
                chunk = await self._add_chunk(
                    session,
                    run_id,
                    ordinal,
                    CorpusZone.MANASEK_WORKING,
                    RetrievalLane.MANASEK,
                    RetrievalSourceKind.RITUAL_PASSAGE,
                    group,
                )
                session.add_all(
                    [
                        ChunkRitualPassage(
                            chunk_id=chunk.id,
                            ritual_passage_id=item.id,
                            sequence_in_chunk=index,
                        )
                        for index, item in enumerate(group, 1)
                    ]
                )
                ritual_ids = await session.scalars(
                    select(RitualVersion.id).where(
                        RitualVersion.source_passage_id.in_([item.id for item in group])
                    )
                )
                session.add_all(
                    [
                        ChunkRitualVersion(chunk_id=chunk.id, ritual_version_id=value)
                        for value in ritual_ids
                    ]
                )
        return ordinal

    async def _build_ritual_content(
        self, session: AsyncSession, run_id: UUID, ordinal: int
    ) -> int:
        rows = await session.scalars(
            select(RitualVersion)
            .join(
                RitualSourceVersion,
                RitualSourceVersion.id == RitualVersion.source_version_id,
            )
            .where(RitualSourceVersion.corpus_zone == CorpusZone.MANASEK_WORKING)
            .order_by(RitualVersion.created_at, RitualVersion.id)
        )
        for item in rows:
            text = "\n".join(
                part
                for part in (
                    item.title,
                    item.purpose,
                    item.preparation,
                    item.experiential_instructions,
                    item.safety_notes,
                    item.exit_instructions,
                )
                if part
            )
            record = _Record(
                item.id,
                1,
                text,
                normalize_search_text(text),
                "fa",
                item.title,
                {
                    "ritual_version_id": str(item.id),
                    "source_version_id": str(item.source_version_id),
                    "piece_type": item.piece_type.value,
                    "mode": item.mode.value,
                },
            )
            ordinal += 1
            chunk = await self._add_chunk(
                session,
                run_id,
                ordinal,
                CorpusZone.MANASEK_WORKING,
                RetrievalLane.MANASEK,
                RetrievalSourceKind.RITUAL_CONTENT,
                [record],
            )
            session.add(
                ChunkRitualVersion(chunk_id=chunk.id, ritual_version_id=item.id)
            )
        return ordinal

    async def _build_external(
        self, session: AsyncSession, run_id: UUID, ordinal: int
    ) -> int:
        versions = await session.execute(
            select(SourceVersion, Source)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(SourceVersion.corpus_zone == CorpusZone.EXTERNAL_PRIMARY)
            .order_by(SourceVersion.acquired_at)
        )
        for version, source in versions:
            segments = list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.source_version_id == version.id)
                    .order_by(SourceSegment.sequence)
                )
            )
            records = [
                _Record(
                    item.id,
                    item.sequence,
                    item.raw_text,
                    item.normalized_text,
                    item.language,
                    source.title,
                    {
                        "source_id": str(source.id),
                        "source_version_id": str(version.id),
                        "url": source.canonical_url,
                        "start_seconds": float(item.start_seconds),
                        "end_seconds": float(item.end_seconds),
                    },
                )
                for item in segments
            ]
            for group in self._groups(records):
                ordinal += 1
                chunk = await self._add_chunk(
                    session,
                    run_id,
                    ordinal,
                    CorpusZone.EXTERNAL_PRIMARY,
                    RetrievalLane.EXTERNAL,
                    RetrievalSourceKind.EXTERNAL_SEGMENT,
                    group,
                )
                segment_ids = [item.id for item in group]
                session.add_all(
                    [
                        ChunkExternalSegment(
                            chunk_id=chunk.id,
                            source_segment_id=item.id,
                            sequence_in_chunk=index,
                        )
                        for index, item in enumerate(group, 1)
                    ]
                )
                mentions = await session.scalars(
                    select(Mention).where(Mention.source_segment_id.in_(segment_ids))
                )
                seen: set[tuple[UUID | None, UUID | None, UUID | None, UUID | None]] = (
                    set()
                )
                for mention in mentions:
                    key = (
                        mention.person_id,
                        mention.work_id,
                        mention.organization_id,
                        mention.concept_id,
                    )
                    if key in seen or all(value is None for value in key):
                        continue
                    seen.add(key)
                    session.add(
                        ChunkExternalEntity(
                            chunk_id=chunk.id,
                            person_id=mention.person_id,
                            work_id=mention.work_id,
                            organization_id=mention.organization_id,
                            concept_id=mention.concept_id,
                        )
                    )
        return ordinal

    async def _add_chunk(
        self,
        session: AsyncSession,
        run_id: UUID,
        ordinal: int,
        zone: CorpusZone,
        lane: RetrievalLane,
        kind: RetrievalSourceKind,
        records: list[_Record],
    ) -> Chunk:
        raw = "\n".join(item.raw_text for item in records)
        normalized = normalize_search_text(
            "\n".join(item.normalized_text for item in records)
        )
        metadata = {
            "first": records[0].metadata,
            "last": records[-1].metadata,
            "source_record_count": len(records),
        }
        digest = hashlib.sha256(
            json.dumps(
                {
                    "kind": kind.value,
                    "ids": [str(item.id) for item in records],
                    "text": raw,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        chunk = Chunk(
            chunking_run_id=run_id,
            corpus_zone=zone,
            lane=lane,
            source_kind=kind,
            ordinal=ordinal,
            text=raw,
            normalized_text=normalized,
            language=records[0].language,
            section_title=records[0].section_title,
            token_count=token_count(raw),
            content_hash=digest,
            metadata_json=metadata,
        )
        session.add(chunk)
        await session.flush()
        return chunk

    def _groups(self, records: list[_Record]) -> list[list[_Record]]:
        groups: list[list[_Record]] = []
        start = 0
        while start < len(records):
            group: list[_Record] = []
            total = 0
            index = start
            while index < len(records):
                count = token_count(records[index].raw_text)
                if group and total + count > self._max:
                    break
                group.append(records[index])
                total += count
                index += 1
                if total >= self._target:
                    break
            groups.append(group)
            if index >= len(records):
                break
            start = max(start + 1, index - self._overlap)
        return groups

    @staticmethod
    async def _result(
        session: AsyncSession, run: ChunkingRun, *, created: bool
    ) -> ChunkingResult:
        rows = await session.execute(
            select(Chunk.lane, Chunk.id).where(Chunk.chunking_run_id == run.id)
        )
        counts: dict[str, int] = {}
        for lane, _ in rows:
            counts[lane.value] = counts.get(lane.value, 0) + 1
        return ChunkingResult(
            run_id=run.id,
            created=created,
            chunk_count=sum(counts.values()),
            lane_counts=counts,
            output_hash=run.output_hash or "",
        )

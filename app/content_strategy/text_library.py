"""Query and lifecycle view layer for the canonical editorial text records."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.lesson_workflow import (
    LessonProjectMetadata,
    lesson_project_metadata,
)
from app.content_strategy.models import (
    ChannelLedgerEntry,
    ContentTopic,
    EditorialLanguageTrack,
    EditorialProject,
    PersianDraft,
    TopicStrategyNode,
)
from app.content_strategy.persian_pipeline import (
    extract_ledger_examples,
    extract_open_promises,
)

STATUS_LABELS = {
    "RESEARCH_PENDING": "In Arbeit",
    "RESEARCH_READY": "Recherche bereit",
    "PERSIAN_APPROVED": "Persisch freigegeben",
    "TRANSLATED": "Übersetzungen offen",
    "READY_FOR_VOICE": "Voice Ready",
    "PERFORMANCE_READY": "Voice Ready",
    "VIDEO_READY": "Video Ready",
    "PUBLISHED": "Veröffentlicht",
    "ARCHIVED": "Archiviert",
}
TRACK_STATUS_LABELS = {
    "TRANSLATED": "Übersetzt",
    "READY_FOR_VOICE": "Voice Ready",
    "PERFORMANCE_READY": "ElevenLabs bereit",
    "REVIEW_REQUIRED": "Prüfung erforderlich",
    "STALE": "Ausgangsversion geändert",
}
ORIGIN_LABELS = {
    "LESSON": "Kanonische Lektion",
    "STRATEGY": "Historisches Strategiethema",
    "AI_SUGGESTED": "KI-Thema",
    "USER_CREATED": "Eigenes Thema",
    "LEGACY": "Historisches Thema",
}


@dataclass(frozen=True, slots=True)
class TextLibraryItem:
    project: EditorialProject
    topic: ContentTopic | None
    strategy_node: TopicStrategyNode | None
    lesson: LessonProjectMetadata | None
    branch_title: str | None
    tracks: dict[str, EditorialLanguageTrack]
    approved_persian: PersianDraft | None
    drafts: tuple[PersianDraft, ...]
    updated_at: datetime
    origin_key: str
    origin_label: str
    status_key: str
    status_label: str

    @property
    def voice_ready_languages(self) -> tuple[str, ...]:
        return tuple(
            language
            for language, track in self.tracks.items()
            if track.voice_ready_text
        )

    @property
    def language_status(self) -> dict[str, str]:
        return {language: track.status for language, track in self.tracks.items()}

    @property
    def published_at(self) -> datetime | None:
        snapshot = self.project.strategy_topic_snapshot or {}
        publication = snapshot.get("publication")
        if not isinstance(publication, dict):
            return None
        raw = publication.get("published_at")
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def published_title(self) -> str:
        snapshot = self.project.strategy_topic_snapshot or {}
        publication = snapshot.get("publication")
        if isinstance(publication, dict):
            title = publication.get("published_title")
            if isinstance(title, str) and title.strip():
                return title
        return self.project.title


def _origin(
    project: EditorialProject,
    topic: ContentTopic | None,
    strategy_node: TopicStrategyNode | None,
) -> tuple[str, str]:
    lesson = lesson_project_metadata(project)
    if lesson is not None:
        return "LESSON", f"Lektion {lesson.number} / {lesson.total}"
    if strategy_node is not None:
        return "STRATEGY", ORIGIN_LABELS["STRATEGY"]
    if getattr(project, "strategy_topic_snapshot", None):
        return "STRATEGY", ORIGIN_LABELS["STRATEGY"]
    key = getattr(topic.origin, "value", topic.origin) if topic else "LEGACY"
    key = str(key)
    return key, ORIGIN_LABELS.get(key, "Historisches Thema")


def _status(
    item_tracks: dict[str, EditorialLanguageTrack],
    approved: PersianDraft | None,
    project: EditorialProject,
) -> tuple[str, str]:
    snapshot = getattr(project, "strategy_topic_snapshot", None) or {}
    if project.status == "PUBLISHED" or isinstance(snapshot.get("publication"), dict):
        return "PUBLISHED", STATUS_LABELS["PUBLISHED"]
    if project.status == "ARCHIVED":
        return "ARCHIVED", STATUS_LABELS["ARCHIVED"]
    if project.status == "VIDEO_READY":
        return "VIDEO_READY", STATUS_LABELS["VIDEO_READY"]
    if approved is None:
        return project.status, STATUS_LABELS.get(project.status, "In Arbeit")
    if set(item_tracks) >= {"fa", "de", "en", "ar"}:
        if all(
            item_tracks[language].voice_ready_text
            for language in ("fa", "de", "en", "ar")
        ):
            return "VOICE_READY", "Voice Ready"
        return "COMPLETE", "Vier Sprachen fertig"
    if item_tracks:
        return "TRANSLATIONS", "Übersetzungen offen"
    return "PERSIAN_APPROVED", "Persisch freigegeben"


def _branch_title(
    node: TopicStrategyNode | None,
    nodes: dict[UUID, TopicStrategyNode],
) -> str | None:
    if node is None or node.parent_id is None:
        return None
    parent = nodes.get(node.parent_id)
    if parent is None:
        return None
    if parent.node_type == "BRANCH":
        return parent.title
    if parent.parent_id is not None and parent.parent_id in nodes:
        return nodes[parent.parent_id].title
    return parent.title


async def load_library_items(
    session: AsyncSession,
    *,
    query: str | None = None,
    status: str | None = None,
    origin: str | None = None,
    language: str | None = None,
    branch: str | None = None,
    sort: str = "updated",
) -> list[TextLibraryItem]:
    """Build owner-facing rows from the existing project/version entities."""

    projects = list(await session.scalars(select(EditorialProject)))
    topics = {item.id: item for item in await session.scalars(select(ContentTopic))}
    nodes = {item.id: item for item in await session.scalars(select(TopicStrategyNode))}
    drafts = list(
        await session.scalars(
            select(PersianDraft).order_by(PersianDraft.version_number.desc())
        )
    )
    tracks = list(
        await session.scalars(
            select(EditorialLanguageTrack).order_by(
                EditorialLanguageTrack.version_number.desc()
            )
        )
    )
    drafts_by_project: dict[UUID, list[PersianDraft]] = {}
    for draft in drafts:
        drafts_by_project.setdefault(draft.editorial_project_id, []).append(draft)
    tracks_by_project: dict[UUID, dict[str, EditorialLanguageTrack]] = {}
    for track in tracks:
        by_language = tracks_by_project.setdefault(track.editorial_project_id, {})
        by_language.setdefault(track.language, track)

    items: list[TextLibraryItem] = []
    for project in projects:
        topic = (
            topics.get(project.content_topic_id) if project.content_topic_id else None
        )
        node = nodes.get(project.strategy_node_id) if project.strategy_node_id else None
        project_drafts = tuple(drafts_by_project.get(project.id, []))
        approved = next(
            (draft for draft in project_drafts if draft.status == "PERSIAN_APPROVED"),
            None,
        )
        project_tracks = tracks_by_project.get(project.id, {})
        lesson = lesson_project_metadata(project)
        origin_key, origin_label = _origin(project, topic, node)
        status_key, status_label = _status(project_tracks, approved, project)
        if (
            project_drafts
            and approved is None
            and status_key not in {"PUBLISHED", "VIDEO_READY", "ARCHIVED"}
        ):
            if any(draft.status == "REVIEW_REQUIRED" for draft in project_drafts):
                status_key, status_label = "IN_REVIEW", "In Prüfung"
            else:
                status_key, status_label = "TEXT_AVAILABLE", "Text vorhanden"
        timestamps = [project.created_at]
        timestamps.extend(draft.created_at for draft in project_drafts)
        timestamps.extend(track.created_at for track in project_tracks.values())
        item = TextLibraryItem(
            project=project,
            topic=topic,
            strategy_node=node,
            lesson=lesson,
            branch_title=(
                _branch_title(node, nodes)
                if node is not None
                else (
                    str(project.strategy_topic_snapshot.get("branch_title"))
                    if project.strategy_topic_snapshot
                    and project.strategy_topic_snapshot.get("branch_title")
                    else None
                )
            ),
            tracks=project_tracks,
            approved_persian=approved,
            drafts=project_drafts,
            updated_at=max(timestamps),
            origin_key=origin_key,
            origin_label=origin_label,
            status_key=status_key,
            status_label=status_label,
        )
        haystack = " ".join(
            value
            for value in (
                project.title,
                project.human_question,
                project.owner_prompt or "",
                topic.title if topic else "",
                topic.human_question if topic else "",
                lesson.title if lesson else "",
            )
        ).casefold()
        if query and query.casefold() not in haystack:
            continue
        if status == "ACTIVE" and status_key == "ARCHIVED":
            continue
        if status and status != "ACTIVE" and status != status_key:
            continue
        if origin and origin != origin_key:
            continue
        if language and language not in project_tracks:
            continue
        if branch and branch != item.branch_title:
            continue
        items.append(item)

    if sort == "title":
        items.sort(key=lambda item: item.project.title.casefold())
    elif sort == "oldest":
        items.sort(key=lambda item: item.updated_at)
    elif sort == "newest":
        items.sort(key=lambda item: item.project.created_at, reverse=True)
    else:
        items.sort(key=lambda item: item.updated_at, reverse=True)
    return items


async def duplicate_project(
    session: AsyncSession, project_id: UUID
) -> EditorialProject:
    """Create a new production shell without mutating the historical project."""

    original = await session.get(EditorialProject, project_id)
    if original is None:
        raise ValueError("editorial project not found")
    copy = EditorialProject(
        strategy_node_id=original.strategy_node_id,
        strategy_topic_snapshot=deepcopy(original.strategy_topic_snapshot),
        content_topic_id=original.content_topic_id,
        title=f"{original.title} (Kopie)",
        human_question=original.human_question,
        owner_prompt=original.owner_prompt,
        target_duration_minutes=original.target_duration_minutes,
        status="RESEARCH_PENDING",
    )
    session.add(copy)
    await session.flush()
    return copy


async def archive_project(session: AsyncSession, project_id: UUID) -> EditorialProject:
    project = await session.get(EditorialProject, project_id)
    if project is None:
        raise ValueError("editorial project not found")
    project.status = "ARCHIVED"
    return project


async def restore_project(session: AsyncSession, project_id: UUID) -> EditorialProject:
    project = await session.get(EditorialProject, project_id)
    if project is None:
        raise ValueError("editorial project not found")
    project.status = "RESEARCH_PENDING"
    return project


async def publish_project(session: AsyncSession, project_id: UUID) -> EditorialProject:
    """Publish an approved text and record owner-facing channel-memory metadata."""

    project = await session.get(EditorialProject, project_id)
    if project is None:
        raise ValueError("editorial project not found")
    approved = await session.scalar(
        select(PersianDraft)
        .where(
            PersianDraft.editorial_project_id == project_id,
            PersianDraft.status == "PERSIAN_APPROVED",
        )
        .order_by(PersianDraft.version_number.desc())
    )
    if approved is None:
        raise ValueError("publication requires an approved Persian text")
    snapshot = deepcopy(project.strategy_topic_snapshot) or {}
    published_at = datetime.now(UTC)
    snapshot["publication"] = {
        "published_at": published_at.isoformat(),
        "published_title": project.title,
    }
    project.strategy_topic_snapshot = snapshot
    project.status = "PUBLISHED"
    existing_ledger = await session.scalar(
        select(ChannelLedgerEntry).where(
            ChannelLedgerEntry.editorial_project_id == project.id
        )
    )
    if existing_ledger is None:
        package = snapshot.get("lesson_content_package_snapshot", {})
        package = package if isinstance(package, dict) else {}
        raw_registry = package.get("core_concept_registry", [])
        registry = raw_registry if isinstance(raw_registry, list) else []
        session.add(
            ChannelLedgerEntry(
                editorial_project_id=project.id,
                published_draft_id=approved.id,
                lesson_id=str(snapshot.get("lesson_id") or "") or None,
                published_title=project.title,
                concept_keys=[
                    str(item) for item in package.get("core_concepts", [])
                ],
                canonical_definitions=[
                    item for item in registry if isinstance(item, dict)
                ],
                examples=extract_ledger_examples(approved.text),
                open_promises=extract_open_promises(approved.text),
                fulfilled_promises=[],
                title_history=[project.title],
                coverage_summary={
                    "lesson_id": snapshot.get("lesson_id"),
                    "lesson_canon_hash": snapshot.get("lesson_canon_hash"),
                    "word_count": approved.actual_word_count,
                },
                content_hash=sha256(approved.text.encode()).hexdigest(),
                published_at=published_at,
            )
        )
    return project


def library_filter_options(items: list[TextLibraryItem]) -> dict[str, list[str]]:
    return {
        "origins": sorted({item.origin_key for item in items}),
        "branches": sorted(
            {item.branch_title for item in items if item.branch_title is not None}
        ),
    }

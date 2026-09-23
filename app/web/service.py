"""Small, grounded services used by the owner web application."""

import hashlib
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import ChannelVideoCandidate, MonitoredChannel
from app.content_strategy.domain import ContentStatus, LectureAngle, TopicOrigin
from app.content_strategy.models import ContentTopic
from app.core.ayin.models import AyinConcept, AyinConceptVersion
from app.knowledge.adapters.youtube import parse_youtube_video_id
from app.knowledge.models import (
    ExternalClaim,
    Person,
    ReviewFlag,
    Source,
    SourceSegment,
    Work,
)


@dataclass(frozen=True, slots=True)
class TopicSuggestion:
    title: str
    human_question: str
    rationale: str
    suggestion_type: str
    concepts: tuple[str, ...]
    source_count: int
    works: tuple[str, ...]
    provenance: tuple[str, ...]
    overlap_score: float


def validate_youtube_url(value: str) -> str:
    """Validate a URL before handing it to the existing ingestion pipeline."""

    return parse_youtube_video_id(value)


class TopicSuggestionService:
    """Create grounded, deterministic suggestions from the current corpus."""

    async def suggestions(self, session: AsyncSession) -> list[TopicSuggestion]:
        concepts = list(
            await session.scalars(select(AyinConcept).order_by(AyinConcept.stable_key))
        )
        concept_names = tuple(concept.stable_key for concept in concepts[:8])
        source_count = await session.scalar(select(func.count(Source.id))) or 0
        works = tuple(
            row.canonical_title
            for row in await session.scalars(
                select(Work).order_by(Work.canonical_title).limit(5)
            )
        )
        topics = list(await session.scalars(select(ContentTopic)))
        prompts = [
            (
                "Muster verstehen, ohne bei der Einsicht stehenzubleiben",
                "Warum können Muster weiterwirken, obwohl wir sie erkannt haben?",
                "FOUNDATION",
            ),
            (
                "Veränderung und Identität",
                "Kann sich ein Mensch verändern, ohne jemand anderes zu werden?",
                "HUMAN_QUESTION",
            ),
            (
                "Das Dazwischen",
                "Was geschieht zwischen zwei Menschen, das sich nicht auf einen "
                "allein reduzieren lässt?",
                "DIALOGUE",
            ),
            (
                "Bedingungen und Handlungsspielraum",
                "Wie verändert sich unser Handlungsspielraum, wenn wir unsere "
                "Bedingungen sehen?",
                "APPLICATION",
            ),
            (
                "Ayin im Dialog mit gesammeltem Wissen",
                "Welche externalen Erklärungen beleuchten Ayins Begriffe, "
                "ohne sie zu ersetzen?",
                "DIALOGUE",
            ),
        ]
        output: list[TopicSuggestion] = []
        for title, question, kind in prompts:
            overlap = max(
                (self._overlap(question, topic.human_question) for topic in topics),
                default=0.0,
            )
            output.append(
                TopicSuggestion(
                    title=title,
                    human_question=question,
                    rationale=(
                        "Der Vorschlag verbindet Ayin-Struktur mit dem aktuell "
                        "gesammelten Wissensbestand; er behauptet keine neuen Fakten."
                    ),
                    suggestion_type=kind,
                    concepts=concept_names[:4],
                    source_count=int(source_count),
                    works=works,
                    provenance=tuple(str(item.id) for item in topics[:3])
                    + ("ayin:structured-concepts", "knowledge:source-count"),
                    overlap_score=round(overlap, 3),
                )
            )
        return output

    @staticmethod
    def _overlap(left: str, right: str) -> float:
        def tokens(text: str) -> set[str]:
            return {
                token.lower() for token in re.findall(r"\w+", text) if len(token) > 3
            }

        a, b = tokens(left), tokens(right)
        return round(len(a & b) / len(a | b), 3) if a | b else 0.0


class TopicAnalysisService:
    """Analyze a topic without starting research or creating a lecture."""

    async def analyze(self, session: AsyncSession, text: str) -> dict[str, object]:
        normalized = text.strip().lower()
        versions = list(
            await session.scalars(
                select(AyinConceptVersion).order_by(
                    AyinConceptVersion.version_number.desc()
                )
            )
        )
        concepts = [
            version
            for version in versions
            if any(
                token in (version.definition or "").lower() or token in normalized
                for token in re.findall(r"\w+", version.definition or "")
                if len(token) > 4
            )
        ][:8]
        source_count = int(await session.scalar(select(func.count(Source.id))) or 0)
        claim_count = int(
            await session.scalar(select(func.count(ExternalClaim.id))) or 0
        )
        works = list(
            await session.scalars(select(Work).order_by(Work.canonical_title).limit(5))
        )
        people = list(
            await session.scalars(
                select(Person).order_by(Person.canonical_name).limit(5)
            )
        )
        topics = list(await session.scalars(select(ContentTopic)))
        overlaps = sorted(
            (
                (
                    topic.title,
                    TopicSuggestionService._overlap(text, topic.human_question),
                )
                for topic in topics
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        return {
            "concepts": [version.definition[:160] for version in concepts],
            "concept_ids": [str(version.concept_id) for version in concepts],
            "source_count": source_count,
            "claim_count": claim_count,
            "works": [work.canonical_title for work in works],
            "people": [person.canonical_name for person in people],
            "similar_topics": overlaps[:3],
            "overlap_score": overlaps[0][1] if overlaps else 0.0,
            "warnings": (
                ["Wenig vorhandenes Quellenmaterial."] if source_count == 0 else []
            )
            + (
                ["Ähnliche Themen existieren bereits."]
                if overlaps and overlaps[0][1] >= 0.45
                else []
            ),
        }


async def save_topic(
    session: AsyncSession,
    *,
    title: str,
    question: str,
    origin: TopicOrigin,
) -> ContentTopic:
    """Persist a selected topic only; research is deliberately not started."""

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:180] or "topic"
    stable_key = f"owner-{slug}-{uuid4().hex[:8]}"
    concept = await session.scalar(select(AyinConcept).order_by(AyinConcept.stable_key))
    topic = ContentTopic(
        stable_key=stable_key,
        title=title[:512],
        human_question=question,
        primary_concept_key=concept.stable_key if concept else "unassigned",
        life_domain="self",
        lecture_angle=LectureAngle.HUMAN_QUESTION,
        status=ContentStatus.PLANNED,
        origin=origin,
        semantic_hash=hashlib.sha256(question.encode()).hexdigest(),
    )
    session.add(topic)
    await session.flush()
    return topic


async def dashboard_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "sources": int(await session.scalar(select(func.count(Source.id))) or 0),
        "youtube": int(
            await session.scalar(
                select(func.count(Source.id)).where(Source.platform == "youtube")
            )
            or 0
        ),
        "segments": int(
            await session.scalar(select(func.count(SourceSegment.id))) or 0
        ),
        "people": int(await session.scalar(select(func.count(Person.id))) or 0),
        "works": int(await session.scalar(select(func.count(Work.id))) or 0),
        "claims": int(await session.scalar(select(func.count(ExternalClaim.id))) or 0),
        "reviews": int(
            await session.scalar(
                select(func.count(ReviewFlag.id)).where(
                    ReviewFlag.status.in_(["open", "in_review"])
                )
            )
            or 0
        ),
        "topics": int(await session.scalar(select(func.count(ContentTopic.id))) or 0),
        "channels": int(
            await session.scalar(select(func.count(MonitoredChannel.id))) or 0
        ),
        "pending_candidates": int(
            await session.scalar(
                select(func.count(ChannelVideoCandidate.id)).where(
                    ChannelVideoCandidate.status == CandidateStatus.NEW
                )
            )
            or 0
        ),
    }

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
from app.core.ayin.models import (
    AyinConcept,
    AyinConceptVersion,
    AyinDistinction,
    AyinDistinctionVersion,
    AyinOpenQuestionVersion,
)
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
        query_tokens = self._tokens(normalized)
        aliases = {
            "between": {
                "between",
                "dazwischen",
                "zwischen",
                "relational",
                "other",
                "mitten",
            },
            "pattern": {
                "pattern",
                "muster",
                "repetition",
                "repeat",
                "wiederholen",
                "habit",
                "habituation",
                "عادت",
                "تکرار",
                "الگو",
            },
            "conditions": {"conditions", "bedingungen", "context", "umstände"},
            "change": {"change", "veränder", "identität", "identity", "werden"},
            "emtedad": {"emtedad", "امتداد"},
            "bon": {"bon", "بُن", "person", "personality", "identität"},
            "majal": {"majal", "مجال", "handlungsraum"},
            "other": {"other", "andere", "anderer", "dazwischen"},
        }
        concepts = list(await session.scalars(select(AyinConcept)))
        versions = list(
            await session.scalars(
                select(AyinConceptVersion).order_by(
                    AyinConceptVersion.version_number.desc()
                )
            )
        )
        concept_keys = {concept.id: concept.stable_key for concept in concepts}
        latest: dict[object, AyinConceptVersion] = {}
        for version in versions:
            latest.setdefault(version.concept_id, version)
        ranked_concepts: list[tuple[int, AyinConceptVersion]] = []
        for version in latest.values():
            key = concept_keys.get(version.concept_id, "")
            haystack = self._tokens(f"{key} {version.definition}")
            score = len(query_tokens & haystack)
            for alias_key, alias_tokens in aliases.items():
                if alias_key in key and query_tokens & alias_tokens:
                    score += 3
            if score:
                ranked_concepts.append((score, version))
        ranked_concepts.sort(
            key=lambda item: (-item[0], concept_keys.get(item[1].concept_id, ""))
        )
        selected_concepts = [item[1] for item in ranked_concepts[:8]]
        retrieval_tokens = set(query_tokens)
        for version in selected_concepts:
            key = concept_keys.get(version.concept_id, "")
            retrieval_tokens.update(self._tokens(f"{key} {version.definition}"))
            for alias_key, alias_tokens in aliases.items():
                if alias_key in key:
                    retrieval_tokens.update(alias_tokens)

        distinctions = list(await session.scalars(select(AyinDistinctionVersion)))
        distinction_defs = list(await session.scalars(select(AyinDistinction)))
        distinction_keys = {item.id: item.stable_key for item in distinction_defs}
        selected_distinctions = [
            item
            for item in distinctions
            if query_tokens
            & self._tokens(
                f"{distinction_keys.get(item.distinction_id, '')} "
                f"{item.explanation} {item.right_label or ''}"
            )
        ][:8]

        open_questions = list(await session.scalars(select(AyinOpenQuestionVersion)))
        selected_questions = [
            item
            for item in open_questions
            if query_tokens & self._tokens(f"{item.question} {item.context}")
        ][:8]

        sources = list(
            await session.scalars(select(Source).order_by(Source.created_at.desc()))
        )
        selected_sources = [
            source
            for source in sources
            if retrieval_tokens
            & self._tokens(f"{source.title} {source.description or ''}")
        ][:12]
        claims = list(
            await session.scalars(
                select(ExternalClaim).order_by(ExternalClaim.created_at.desc())
            )
        )
        selected_claims = [
            claim
            for claim in claims
            if retrieval_tokens
            & self._tokens(
                f"{claim.claim_text} {claim.claim_domain} {claim.claim_type}"
            )
        ][:20]
        works = list(await session.scalars(select(Work).order_by(Work.canonical_title)))
        selected_works = [
            work
            for work in works
            if retrieval_tokens & self._tokens(work.canonical_title)
        ][:8]
        people = list(
            await session.scalars(select(Person).order_by(Person.canonical_name))
        )
        selected_people = [
            person
            for person in people
            if retrieval_tokens & self._tokens(person.canonical_name)
        ][:8]
        topics = list(await session.scalars(select(ContentTopic)))
        overlaps = sorted(
            (
                (topic, TopicSuggestionService._overlap(text, topic.human_question))
                for topic in topics
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        primary = selected_concepts[0] if selected_concepts else None
        source_payload = [
            {
                "id": str(source.id),
                "title": source.title,
                "url": source.canonical_url,
                "language": source.language,
            }
            for source in selected_sources
        ]
        claim_payload = [
            {
                "id": str(claim.id),
                "text": claim.claim_text,
                "verification_status": str(claim.verification_status),
            }
            for claim in selected_claims
        ]
        concept_payload = [
            {
                "id": str(version.concept_id),
                "stable_key": concept_keys.get(version.concept_id, ""),
                "definition": version.definition,
            }
            for version in selected_concepts
        ]
        result: dict[str, object] = {
            "analyzed": True,
            "primary_concept_key": concept_keys.get(primary.concept_id)
            if primary
            else None,
            "concepts": concept_payload,
            "distinctions": [
                {
                    "id": str(item.id),
                    "stable_key": distinction_keys.get(item.distinction_id, ""),
                    "explanation": item.explanation,
                }
                for item in selected_distinctions
            ],
            "open_questions": [
                {"id": str(item.id), "question": item.question, "context": item.context}
                for item in selected_questions
            ],
            "sources": source_payload,
            "claims": claim_payload,
            "source_count": len(source_payload),
            "claim_count": len(claim_payload),
            "works": [
                {"id": str(work.id), "title": work.canonical_title}
                for work in selected_works
            ],
            "people": [
                {"id": str(person.id), "name": person.canonical_name}
                for person in selected_people
            ],
            "similar_topics": [
                {"id": str(topic.id), "title": topic.title, "score": score}
                for topic, score in overlaps[:3]
                if score > 0
            ],
            "overlap_score": overlaps[0][1] if overlaps and overlaps[0][1] > 0 else 0.0,
        }
        warnings: list[str] = []
        if not selected_concepts:
            warnings.append("Keine belastbare Zuordnung gefunden.")
        if not selected_sources and not selected_claims:
            warnings.append("Kein passendes externes Material gefunden.")
        if overlaps and overlaps[0][1] >= 0.45:
            warnings.append("Ähnliche Themen existieren bereits.")
        result["warnings"] = warnings
        return result

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token for token in re.findall(r"[\wäöüß]+", text.lower()) if len(token) > 3
        }


def topic_detail_view(topic: ContentTopic) -> dict[str, object]:
    """Build a template-safe detail view from the persisted analysis snapshot."""

    raw = topic.analysis_json
    if not raw:
        return {
            "analysis_status": "not_analyzed",
            "primary_concept": None,
            "concepts": [],
            "distinctions": [],
            "open_questions": [],
            "sources": [],
            "claims": [],
            "works": [],
            "people": [],
            "similar_topics": [],
            "overlap_score": 0.0,
            "warnings": ["Analyse noch nicht durchgeführt."],
        }
    raw_concepts = raw.get("concepts", [])
    concepts = raw_concepts if isinstance(raw_concepts, list) else []
    primary_key = raw.get("primary_concept_key")
    primary = next(
        (
            item
            for item in concepts
            if isinstance(item, dict) and item.get("stable_key") == primary_key
        ),
        None,
    )
    return {
        "analysis_status": "analyzed",
        "primary_concept": primary,
        "concepts": concepts,
        "distinctions": raw.get("distinctions", []),
        "open_questions": raw.get("open_questions", []),
        "sources": raw.get("sources", []),
        "claims": raw.get("claims", []),
        "works": raw.get("works", []),
        "people": raw.get("people", []),
        "similar_topics": raw.get("similar_topics", []),
        "overlap_score": raw.get("overlap_score", 0.0),
        "warnings": raw.get("warnings", []),
        "source_count": raw.get("source_count", 0),
        "claim_count": raw.get("claim_count", 0),
    }


async def save_topic(
    session: AsyncSession,
    *,
    title: str,
    question: str,
    origin: TopicOrigin,
    analysis: dict[str, object] | None = None,
) -> ContentTopic:
    """Persist a selected topic only; research is deliberately not started."""

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:180] or "topic"
    stable_key = f"owner-{slug}-{uuid4().hex[:8]}"
    primary = analysis.get("primary_concept_key") if analysis else None
    topic = ContentTopic(
        stable_key=stable_key,
        title=title[:512],
        human_question=question,
        primary_concept_key=primary if isinstance(primary, str) else None,
        life_domain="self",
        lecture_angle=LectureAngle.HUMAN_QUESTION,
        status=ContentStatus.PLANNED,
        origin=origin,
        semantic_hash=hashlib.sha256(question.encode()).hexdigest(),
        analysis_json=analysis,
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

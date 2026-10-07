"""Search orchestration: every language and query runs in parallel."""

import asyncio
import logging
from collections.abc import Sequence

from app.knowledge.adapters.youtube import YouTubeAdapter
from app.search_engine.models import SEARCH_LANGUAGES, SearchHit, SearchKind
from app.search_engine.planner import QueryPlanner
from app.search_engine.ranking import rank
from app.search_engine.searxng import SearchBackendError, SearxngClient

logger = logging.getLogger(__name__)


class SearchEngine:
    def __init__(
        self,
        searxng: SearxngClient,
        *,
        youtube: YouTubeAdapter | None = None,
        planner: QueryPlanner | None = None,
        languages: Sequence[str] = SEARCH_LANGUAGES,
        concurrency: int = 6,
    ) -> None:
        self.searxng = searxng
        self.youtube = youtube or YouTubeAdapter()
        self.planner = planner
        self.languages = tuple(languages)
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _youtube(self, query: str, language: str, limit: int) -> list[SearchHit]:
        videos = await self.youtube.search_videos(query, limit)
        return [
            SearchHit(
                kind=SearchKind.VIDEO,
                title=video.title,
                url=f"https://www.youtube.com/watch?v={video.youtube_video_id}",
                language=language,
                position=position,
                thumbnail_url=video.thumbnail_url or "",
                published=video.published_at.date().isoformat()
                if video.published_at
                else "",
                duration_seconds=video.duration_seconds,
                engines=("youtube",),
                found_by=[query],
            )
            for position, video in enumerate(videos, start=1)
        ]

    async def _one(
        self, query: str, language: str, kind: SearchKind, limit: int
    ) -> list[SearchHit]:
        async with self._semaphore:
            if kind is SearchKind.VIDEO:
                # YouTube directly via yt-dlp (no API key), plus SearXNG's
                # video category for other platforms when available.
                results: list[SearchHit] = []
                try:
                    results.extend(await self._youtube(query, language, limit))
                except Exception as exc:  # noqa: BLE001 — one backend may fail
                    logger.warning("youtube search failed: %s", exc)
                try:
                    results.extend(
                        await self.searxng.search(
                            query, language=language, kind=kind, limit=limit
                        )
                    )
                except SearchBackendError as exc:
                    if not results:
                        raise
                    logger.info("searxng video search skipped: %s", exc)
                return results
            return await self.searxng.search(
                query, language=language, kind=kind, limit=limit
            )

    async def search(
        self,
        queries: dict[str, list[str]],
        *,
        kind: SearchKind,
        topic: str,
        per_query: int = 15,
        limit: int = 40,
    ) -> list[SearchHit]:
        """Run every (language, query) pair in parallel and rank the union."""

        jobs = [
            self._one(query, language, kind, per_query)
            for language, language_queries in queries.items()
            for query in language_queries
        ]
        outcomes = await asyncio.gather(*jobs, return_exceptions=True)
        hits: list[SearchHit] = []
        errors: list[BaseException] = []
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                errors.append(outcome)
            else:
                hits.extend(outcome)
        if not hits and errors:
            raise errors[0]
        return rank(hits, topic, limit)

    async def plan_queries(
        self,
        *,
        topic: str,
        thesis: str = "",
        gaps: list[str] | None = None,
        per_language: int = 5,
    ) -> dict[str, list[str]]:
        """One planner agent per language, in parallel. Falls back to the
        topic itself when no planner is configured or planning fails."""

        if self.planner is None:
            return {language: [topic] for language in self.languages}
        planner = self.planner

        async def plan(language: str) -> list[str]:
            try:
                planned = await planner.plan(
                    topic=topic,
                    thesis=thesis,
                    gaps=gaps or [],
                    language=language,
                    max_queries=per_language,
                    previous=[],
                )
            except Exception as exc:  # noqa: BLE001 — search still works
                logger.warning("query planning failed for %s: %s", language, exc)
                planned = []
            return planned or [topic]

        planned_lists = await asyncio.gather(*(plan(lang) for lang in self.languages))
        return dict(zip(self.languages, planned_lists, strict=True))

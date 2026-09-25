"""Validated, curated story material for owner-facing lesson research."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_STORIES_PATH = Path(__file__).resolve().parents[2] / "stories.json"


class StoryRelation(BaseModel):
    """A curator-supplied, human-readable lesson connection."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(min_length=1)
    lesson_title_fa: str = Field(min_length=1)
    relation_fa: str = Field(min_length=1)


class StoryRecord(BaseModel):
    """One immutable story record supplied by the editorial story bank."""

    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)
    title_en: str = Field(min_length=1)
    title_fa: str = Field(min_length=1)
    years: str = Field(min_length=1)
    place: str = Field(min_length=1)
    key_people: list[str] = Field(default_factory=list)
    category: str = Field(min_length=1)
    narrative_fa: str = Field(min_length=1)
    hook_fa: str = Field(min_length=1)
    uncertain_or_myth_fa: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)
    related_lessons: list[StoryRelation] = Field(default_factory=list)
    has_relation: bool
    no_relation_note_fa: str | None = None


class StoryLibrary:
    """Load and search the curated story bank without inventing story links."""

    def __init__(self, path: Path = DEFAULT_STORIES_PATH) -> None:
        self.path = path
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("stories.json must contain an object")
        raw_stories = payload.get("stories")
        if not isinstance(raw_stories, list):
            raise ValueError("stories.json must contain a stories array")
        self.meta = payload.get("meta", {})
        self._stories = tuple(StoryRecord.model_validate(item) for item in raw_stories)
        self._by_id = {story.story_id: story for story in self._stories}
        if len(self._by_id) != len(self._stories):
            raise ValueError("story IDs must be unique")
        declared_count = self.meta.get("count") if isinstance(self.meta, dict) else None
        if declared_count is not None and int(declared_count) != len(self._stories):
            raise ValueError("stories.json meta.count does not match stories")

    @property
    def count(self) -> int:
        return len(self._stories)

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({story.category for story in self._stories}))

    def all(self) -> tuple[StoryRecord, ...]:
        return self._stories

    def story(self, story_id: str) -> StoryRecord:
        story = self._by_id.get(story_id)
        if story is None:
            raise ValueError(f"story not found: {story_id}")
        return story

    def for_lesson(self, lesson_id: str) -> tuple[StoryRecord, ...]:
        return tuple(
            story
            for story in self._stories
            if any(
                relation.lesson_id == lesson_id
                for relation in story.related_lessons
            )
        )

    def search(
        self,
        *,
        query: str = "",
        category: str = "",
        lesson_id: str = "",
    ) -> tuple[StoryRecord, ...]:
        needle = " ".join(query.casefold().split())
        selected: list[StoryRecord] = []
        for story in self._stories:
            if category and story.category != category:
                continue
            if lesson_id and not any(
                relation.lesson_id == lesson_id for relation in story.related_lessons
            ):
                continue
            haystack = " ".join(
                [
                    story.title_en,
                    story.title_fa,
                    story.years,
                    story.place,
                    story.category,
                    story.narrative_fa,
                    story.hook_fa,
                    *(person for person in story.key_people),
                    *(relation.lesson_title_fa for relation in story.related_lessons),
                ]
            ).casefold()
            if needle and needle not in haystack:
                continue
            selected.append(story)
        return tuple(selected)

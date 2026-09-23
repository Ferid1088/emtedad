"""Direct approved-Persian language tracks and voice-ready preparation."""

import re
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.content_strategy.models import EditorialLanguageTrack, PersianDraft
from app.db.session import Database
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.codex import CodexCliProvider
from app.lecture.domain import PublicationLanguage
from app.localization.models import PronunciationLexiconEntry
from app.localization.performance import (
    ElevenLabsCapabilityProfile,
    NativeLanguageOptimizer,
    NativeLanguageReviewer,
    PerformanceDirector,
)
from app.localization.prompts import native_realization_instruction
from app.localization.pronunciation import prepare_pronunciation
from app.localization.validators import (
    PronunciationValidator,
    ProtectedTerminologyValidator,
)


class _Translation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


def _count(text: str) -> int:
    return len(re.findall(r"[\w\u0600-\u06ff]+", text))


class MultilingualEditorialService:
    """Create DE/EN/AR independently from the exact approved Persian text."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.provider = CodexCliProvider()

    async def create(
        self,
        draft_id: UUID,
        languages: tuple[str, ...],
        *,
        expected_project_id: UUID | None = None,
    ) -> list[UUID]:
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None or draft.status != "PERSIAN_APPROVED":
                raise ValueError("translations require an approved Persian version")
            source_text = draft.text
            project_id = draft.editorial_project_id
            master_id = draft.semantic_master_id
            if expected_project_id is not None and project_id != expected_project_id:
                raise ValueError("draft does not belong to this editorial project")
        tracks: list[UUID] = []
        for language in languages:
            if language not in {item.value for item in PublicationLanguage}:
                raise ValueError("unsupported language")
            if language == "fa":
                text = source_text
            else:
                result = cast(
                    _Translation,
                    await self.provider.extract(
                        StructuredExtractionRequest(
                            task="approved Persian editorial translation",
                            prompt_version="phase-12-fa-source-v1",
                            model="configured-default",
                            instructions=(
                                native_realization_instruction(
                                    PublicationLanguage(language)
                                )
                                + "\n\nUse the approved Persian text as the "
                                "semantic source of truth, while rewriting natively."
                            ),
                            input_text=source_text,
                            output_model=_Translation,
                            timeout_seconds=300,
                        )
                    ),
                )
                text = result.text
            async with self.database.transaction() as session:
                latest = await session.scalar(
                    select(EditorialLanguageTrack)
                    .where(
                        EditorialLanguageTrack.editorial_project_id == project_id,
                        EditorialLanguageTrack.language == language,
                    )
                    .order_by(EditorialLanguageTrack.version_number.desc())
                )
                track = EditorialLanguageTrack(
                    editorial_project_id=project_id,
                    source_persian_draft_id=draft_id,
                    semantic_master_id=master_id,
                    language=language,
                    version_number=(latest.version_number + 1 if latest else 1),
                    display_text=text,
                    actual_word_count=_count(text),
                    estimated_duration_seconds=round(_count(text) / 130 * 60),
                    semantic_validation_status=(
                        "PASSED" if language == "fa" else "REVIEW_REQUIRED"
                    ),
                    provenance={
                        "source_persian_draft_id": str(draft_id),
                        "direct_source_language": "fa",
                        "semantic_master_id": str(master_id),
                        "translation_mode": "direct_from_approved_persian",
                    },
                )
                session.add(track)
                await session.flush()
                tracks.append(track.id)
        return tracks

    async def prepare_voice(
        self, track_id: UUID, *, expected_project_id: UUID | None = None
    ) -> UUID:
        async with self.database.transaction() as session:
            track = await session.get(EditorialLanguageTrack, track_id)
            if track is None:
                raise ValueError("language track not found")
            if (
                expected_project_id is not None
                and track.editorial_project_id != expected_project_id
            ):
                raise ValueError("language track does not belong to this project")
            if track.semantic_validation_status != "PASSED":
                raise ValueError(
                    "semantic validation is required before voice preparation"
                )
            language = PublicationLanguage(track.language)
            native_review = NativeLanguageReviewer().review(
                language, track.display_text
            )
            if not native_review.passed:
                raise ValueError(
                    "native-language review is required before voice preparation"
                )
            source_draft = await session.get(
                PersianDraft, track.source_persian_draft_id
            )
            if source_draft is None:
                raise ValueError("source Persian version not found")
            terminology_findings = ProtectedTerminologyValidator().validate(
                language, source_draft.text, track.display_text
            )
            if any(item.blocking for item in terminology_findings):
                raise ValueError(
                    "protected Ayin terminology is missing from the native text"
                )
            lexicon_rows = list(
                await session.scalars(
                    select(PronunciationLexiconEntry).where(
                        PronunciationLexiconEntry.language == language
                    )
                )
            )
            lexicon: list[dict[str, object]] = [
                {
                    "written_form": row.written_form,
                    "preferred_pronunciation": row.preferred_pronunciation,
                    "criticality": row.criticality.value,
                    "provider_representation": row.provider_representation,
                }
                for row in lexicon_rows
            ]
            prepared = prepare_pronunciation(
                language,
                track.display_text,
                lexicon,
                lexicon_version=1,
                provider_profile="elevenlabs_v3",
            )
            pronunciation_findings = (
                PronunciationValidator().validate_voice_preparation(
                    language, track.display_text, prepared.voice_text
                )
            )
            if any(item.blocking for item in pronunciation_findings):
                raise ValueError(
                    "language-specific pronunciation preparation is incomplete"
                )
            track.voice_ready_text = prepared.voice_text
            performance = PerformanceDirector().prepare(
                language,
                prepared.voice_text,
                profile=ElevenLabsCapabilityProfile.eleven_v3(),
            )
            blocking = [item for item in performance.findings if item.blocking]
            if blocking:
                raise ValueError(
                    "ElevenLabs performance preparation failed: "
                    + "; ".join(item.code for item in blocking)
                )
            track.elevenlabs_performance_text = performance.elevenlabs_performance_text
            track.status = "PERFORMANCE_READY"
            provenance = dict(track.provenance or {})
            provenance["native_quality_status"] = "NATIVE_QUALITY_PASSED"
            provenance["performance_profile"] = {
                "provider": performance.profile.provider,
                "model_id": performance.profile.model_id,
                "supports_ssml": performance.profile.supports_ssml,
                "audio_generated": False,
            }
            track.provenance = provenance
            return track.id

    async def prepare_performance(
        self,
        track_id: UUID,
        *,
        expected_project_id: UUID | None = None,
        tags_by_paragraph: dict[int, str] | None = None,
    ) -> UUID:
        """Prepare inspectable ElevenLabs input without calling the provider."""

        async with self.database.transaction() as session:
            track = await session.get(EditorialLanguageTrack, track_id)
            if track is None:
                raise ValueError("language track not found")
            if (
                expected_project_id is not None
                and track.editorial_project_id != expected_project_id
            ):
                raise ValueError("language track does not belong to this project")
            if not track.voice_ready_text:
                raise ValueError(
                    "voice-ready text is required before performance preparation"
                )
            native_review = NativeLanguageReviewer().review(
                PublicationLanguage(track.language), track.display_text
            )
            if not native_review.passed:
                raise ValueError(
                    "native-language review is required before performance preparation"
                )
            # The optimizer is an explicit boundary.  The default implementation
            # is identity-preserving; model-backed rewrites must create a new
            # translation version rather than mutate owner-approved text.
            optimized_text = NativeLanguageOptimizer().optimize(
                PublicationLanguage(track.language), track.display_text
            )
            if optimized_text != track.display_text:
                raise ValueError(
                    "native optimization requires a new translation version"
                )
            final_native_review = NativeLanguageReviewer().review(
                PublicationLanguage(track.language), optimized_text
            )
            if not final_native_review.passed:
                raise ValueError(
                    "final native-language review is required before "
                    "performance preparation"
                )
            preparation = PerformanceDirector().prepare(
                PublicationLanguage(track.language),
                track.voice_ready_text,
                tags_by_paragraph=tags_by_paragraph,
                profile=ElevenLabsCapabilityProfile.eleven_v3(),
            )
            blocking = [finding for finding in preparation.findings if finding.blocking]
            if blocking:
                raise ValueError(
                    "performance preparation failed: "
                    + "; ".join(item.code for item in blocking)
                )
            track.elevenlabs_performance_text = preparation.elevenlabs_performance_text
            track.status = "PERFORMANCE_READY"
            provenance = dict(track.provenance or {})
            provenance["performance_profile"] = {
                "provider": preparation.profile.provider,
                "model_id": preparation.profile.model_id,
                "supports_ssml": preparation.profile.supports_ssml,
                "tags": list(preparation.profile.supported_tags),
                "audio_generated": False,
            }
            track.provenance = provenance
            return track.id

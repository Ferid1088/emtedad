"""Content strategy graph and reproducible publication package exports."""

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.content_strategy.domain import PublicationPackageStatus, RepetitionDecision
from app.content_strategy.models import (
    ContentCoverage,
    ContentLectureLink,
    ContentPathway,
    ContentRepetitionAssessment,
    ContentSeries,
    ContentTopic,
    PublicationPackageRecord,
)
from app.content_strategy.schemas import LectureStrategyLinkCreate
from app.db.session import Database
from app.lecture.domain import PublicationLanguage
from app.lecture.models import LectureMasterVersion
from app.lecture.service import LectureMasterService
from app.localization.models import (
    LocalizationProject,
    LocalizationStatement,
    LocalizationVersion,
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


class ContentStrategyService:
    """Plan lectures without altering semantic masters or localizations."""

    def __init__(self, database: Database, export_root: Path) -> None:
        self.database = database
        self.export_root = export_root.resolve()
        self.master_service = LectureMasterService(database)

    async def link_lecture(self, request: LectureStrategyLinkCreate) -> UUID:
        async with self.database.transaction() as session:
            master = await session.get(
                LectureMasterVersion, request.lecture_master_version_id
            )
            if master is None or master.status.value != "READY":
                raise ValueError("content strategy requires a READY Semantic Master")
            series = await session.scalar(
                select(ContentSeries).where(
                    ContentSeries.stable_key == request.series_key
                )
            )
            if series is None:
                series = ContentSeries(
                    stable_key=request.series_key,
                    title=request.series_title,
                    description=request.series_title,
                )
                session.add(series)
                await session.flush()
            pathway = None
            if request.pathway_key and request.pathway_title:
                pathway = await session.scalar(
                    select(ContentPathway).where(
                        ContentPathway.stable_key == request.pathway_key
                    )
                )
                if pathway is None:
                    pathway = ContentPathway(
                        series_id=series.id,
                        stable_key=request.pathway_key,
                        title=request.pathway_title,
                        description=request.pathway_title,
                        ordinal=request.ordinal,
                    )
                    session.add(pathway)
                    await session.flush()
            topic = await session.scalar(
                select(ContentTopic).where(
                    ContentTopic.stable_key == request.topic.stable_key
                )
            )
            if topic is None:
                data = request.topic.model_dump()
                data["life_domain"] = request.topic.life_domain.value
                data["semantic_hash"] = _hash(data)
                topic = ContentTopic(**data)
                session.add(topic)
                await session.flush()
            existing = await session.scalar(
                select(ContentLectureLink).where(
                    ContentLectureLink.lecture_master_version_id == master.id
                )
            )
            if existing is not None:
                return existing.id
            assessment = await self._assess_locked(session, master.id, topic)
            link = ContentLectureLink(
                lecture_master_version_id=master.id,
                series_id=series.id,
                pathway_id=pathway.id if pathway else None,
                topic_id=topic.id,
                ordinal=request.ordinal,
            )
            session.add_all(
                [
                    link,
                    assessment,
                    ContentCoverage(
                        lecture_master_version_id=master.id,
                        concept_key=request.topic.primary_concept_key,
                        distinction_key="",
                        evidence_count=0,
                    ),
                ]
            )
            await session.flush()
            return link.id

    async def _assess_locked(
        self, session: Any, master_id: UUID, topic: ContentTopic
    ) -> ContentRepetitionAssessment:
        links = list(
            await session.scalars(
                select(ContentLectureLink).where(
                    ContentLectureLink.lecture_master_version_id != master_id
                )
            )
        )
        best_score, best_id, best_reasons = (
            0.0,
            master_id,
            ["no substantial semantic overlap found"],
        )
        for link in links:
            other = await session.get(ContentTopic, link.topic_id)
            if other is None:
                continue
            left = set(
                re.findall(
                    r"\w+",
                    f"{topic.primary_concept_key} {topic.human_question}".lower(),
                )
            )
            right = set(
                re.findall(
                    r"\w+",
                    f"{other.primary_concept_key} {other.human_question}".lower(),
                )
            )
            score = len(left & right) / max(1, len(left | right))
            reasons = (
                ["same primary concept"]
                if topic.primary_concept_key == other.primary_concept_key
                else []
            ) + (
                ["same human question"]
                if topic.human_question == other.human_question
                else []
            )
            if score > best_score:
                best_score, best_id, best_reasons = (
                    score,
                    link.lecture_master_version_id,
                    reasons,
                )
        decision = (
            RepetitionDecision.REVIEW_REQUIRED
            if best_score >= 0.85
            and best_reasons != ["no substantial semantic overlap found"]
            else RepetitionDecision.ALLOW_DEEPENING
        )
        return ContentRepetitionAssessment(
            lecture_master_version_id=master_id,
            compared_lecture_master_version_id=best_id,
            overlap_score=best_score,
            reasons=best_reasons,
            decision=decision,
        )

    async def export_package(self, master_id: UUID) -> Path:
        export = await self.master_service.export(master_id)
        if export.master.get("status") != "READY":
            raise ValueError("publication package requires a READY Semantic Master")
        async with self.database.transaction() as session:
            localizations = list(
                await session.scalars(
                    select(LocalizationVersion)
                    .join(
                        LocalizationProject,
                        LocalizationProject.id
                        == LocalizationVersion.localization_project_id,
                    )
                    .where(LocalizationProject.lecture_master_version_id == master_id)
                )
            )
            required = {item.value for item in PublicationLanguage}
            if {
                item.display_language.value
                for item in localizations
                if item.status.value == "READY_FOR_VOICE"
            } != required:
                raise ValueError("all four READY_FOR_VOICE localizations are required")
            root = self.export_root / "publication_packages" / str(master_id)
            root.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=root.parent) as temporary:
                directory = Path(temporary) / str(master_id)
                directory.joinpath("master").mkdir(parents=True)
                for language in required:
                    directory.joinpath(language).mkdir()
                metadata = {
                    "master": export.master,
                    "supported_languages": sorted(required),
                    "localization_ids": {
                        item.display_language.value: str(item.id)
                        for item in localizations
                    },
                    "validation": export.validation.model_dump(mode="json"),
                }
                self._write_json(directory / "master" / "metadata.json", metadata)
                for version in localizations:
                    statements = list(
                        await session.scalars(
                            select(LocalizationStatement)
                            .where(
                                LocalizationStatement.localization_version_id
                                == version.id
                            )
                            .order_by(LocalizationStatement.sequence)
                        )
                    )
                    lang = version.display_language.value
                    (directory / lang / "display.txt").write_text(
                        "\n\n".join(item.display_text for item in statements) + "\n",
                        encoding="utf-8",
                    )
                    (directory / lang / "voice.txt").write_text(
                        "\n\n".join(
                            item.voice_text or item.display_text for item in statements
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    self._write_json(
                        directory / lang / "metadata.json",
                        {
                            "localization_id": str(version.id),
                            "language": lang,
                            "status": version.status.value,
                            "semantic_validation_status": (
                                version.semantic_validation_status.value
                            ),
                            "pronunciation_status": version.pronunciation_status.value,
                            "claims": [item.claim_metadata for item in statements],
                        },
                    )
                self._write_json(directory / "citations.json", export.citations)
                self._write_json(
                    directory / "sources.json",
                    [
                        {
                            "evidence_id": item.get("id"),
                            "text": item.get("text"),
                            "provenance": item.get(
                                "package_provenance", item.get("provenance", {})
                            ),
                        }
                        for item in export.evidence
                    ],
                )
                self._write_json(
                    directory / "provenance.json",
                    {
                        "research_package_id": export.master.get("research_package_id"),
                        "research_package_content_hash": export.master.get(
                            "research_package_content_hash"
                        ),
                        "authority": export.master.get("package_authority"),
                        "dialogue_relations": export.dialogue_relations,
                        "terminology_references": export.terminology_references,
                    },
                )
                files = sorted(
                    path.relative_to(directory).as_posix()
                    for path in directory.rglob("*")
                    if path.is_file()
                )
                content_hash = _hash(
                    {
                        name: (directory / name).read_text(encoding="utf-8")
                        for name in files
                    }
                )
                self._write_json(
                    directory / "manifest.json",
                    {
                        "files": files,
                        "master_id": str(master_id),
                        "localization_ids": metadata["localization_ids"],
                        "content_hash": content_hash,
                    },
                )
                if root.exists():
                    for old in root.rglob("*"):
                        if old.is_file():
                            old.unlink()
                root.mkdir(parents=True, exist_ok=True)
                for source in directory.rglob("*"):
                    target = root / source.relative_to(directory)
                    if source.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.write_bytes(source.read_bytes())
            session.add(
                PublicationPackageRecord(
                    lecture_master_version_id=master_id,
                    package_version=1,
                    root_path=str(root),
                    content_hash=content_hash,
                    status=PublicationPackageStatus.VALIDATED,
                    manifest={"master_id": str(master_id), "files": files},
                )
            )
            await session.flush()
            return root

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

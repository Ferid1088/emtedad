"""Owner pronunciation lexicon lifecycle against a real database."""

import asyncio
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.config import Environment, Settings
from app.db.session import Database
from app.lecture.domain import PublicationLanguage
from app.localization.domain import PronunciationLexiconStatus
from app.localization.lexicon import ApprovedLexicon, load_approved_lexicon
from app.localization.models import PronunciationLexiconEntry
from app.main import create_app


@pytest.mark.integration
def test_owner_lexicon_review_lifecycle() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-lexicon-test"),
    )
    suffix = uuid4().hex[:6]
    written_form = f"تستواژه{suffix}"
    pronunciation = f"تِست‌واژه{suffix}"
    provider_form = f"test-{suffix}"
    sample_text = f"این {written_form} یک نمونه است."
    created: list[UUID] = []

    with TestClient(create_app(settings)) as client:
        page = client.get("/lexicon")
        assert page.status_code == 200
        assert "Aussprache-Lexikon" in page.text

        proposed = client.post(
            "/lexicon",
            data={
                "language": "fa",
                "written_form": written_form,
                "preferred_pronunciation": pronunciation,
                "criticality": "CRITICAL",
                "provider_form": provider_form,
                "notes": "integration test entry",
            },
            follow_redirects=False,
        )
        assert proposed.status_code == 303
        entry_id = asyncio.run(_entry_id(database, written_form))
        created.append(entry_id)

        # A proposal must not reach voice preparation before approval.
        lexicon = asyncio.run(_approved_lexicon(database, PublicationLanguage.FA))
        assert entry_id not in lexicon.entry_ids
        preview = client.post(
            "/lexicon/preview",
            data={"language": "fa", "text": sample_text},
        )
        assert preview.status_code == 200
        assert pronunciation not in _voice_block(preview.text)

        approved = client.post(f"/lexicon/{entry_id}/approve", follow_redirects=False)
        assert approved.status_code == 303
        lexicon = asyncio.run(_approved_lexicon(database, PublicationLanguage.FA))
        assert entry_id in lexicon.entry_ids

        # The preview and the standalone studio tool apply approved entries;
        # the ElevenLabs provider representation wins under the v3 profile.
        preview = client.post(
            "/lexicon/preview",
            data={"language": "fa", "text": sample_text},
        )
        assert provider_form in _voice_block(preview.text)
        studio = client.post(
            "/studio/voice", data={"language": "fa", "text": sample_text}
        )
        assert studio.status_code == 200
        assert provider_form in studio.text

        # A second active entry for the same written form is rejected.
        duplicate = client.post(
            "/lexicon",
            data={
                "language": "fa",
                "written_form": written_form,
                "preferred_pronunciation": "x",
            },
        )
        assert "already exists" in duplicate.text

        deprecated = client.post(
            f"/lexicon/{entry_id}/deprecate", follow_redirects=False
        )
        assert deprecated.status_code == 303
        lexicon = asyncio.run(_approved_lexicon(database, PublicationLanguage.FA))
        assert entry_id not in lexicon.entry_ids

        # Re-proposing a deprecated form versions up instead of mutating.
        reproposed = client.post(
            "/lexicon",
            data={
                "language": "fa",
                "written_form": written_form,
                "preferred_pronunciation": pronunciation,
            },
            follow_redirects=False,
        )
        assert reproposed.status_code == 303
        new_id = asyncio.run(_entry_id(database, written_form))
        created.append(new_id)
        asyncio.run(_assert_versions(database, written_form, {entry_id: 1, new_id: 2}))

    asyncio.run(_cleanup(database, created))
    asyncio.run(database.dispose())


def _voice_block(html: str) -> str:
    """Extract only the prepared voice text, excluding the entry list."""

    match = re.search(r"<h3>Voice Ready</h3><pre[^>]*>(.*?)</pre>", html, re.DOTALL)
    assert match is not None
    return match.group(1)


async def _entry_id(database: Database, written_form: str) -> UUID:
    async with database.transaction() as session:
        entry = await session.scalar(
            select(PronunciationLexiconEntry)
            .where(PronunciationLexiconEntry.written_form == written_form)
            .order_by(PronunciationLexiconEntry.version.desc())
        )
        assert entry is not None
        return entry.id


async def _approved_lexicon(
    database: Database, language: PublicationLanguage
) -> ApprovedLexicon:
    async with database.transaction() as session:
        return await load_approved_lexicon(session, language)


async def _assert_versions(
    database: Database, written_form: str, expected: dict[UUID, int]
) -> None:
    async with database.transaction() as session:
        rows = list(
            await session.scalars(
                select(PronunciationLexiconEntry).where(
                    PronunciationLexiconEntry.written_form == written_form
                )
            )
        )
        versions = {row.id: row.version for row in rows}
        assert versions == expected
        by_version = {row.version: row.status for row in rows}
        assert by_version[1] == PronunciationLexiconStatus.DEPRECATED
        assert by_version[2] == PronunciationLexiconStatus.PROPOSED


async def _cleanup(database: Database, entry_ids: list[UUID]) -> None:
    async with database.transaction() as session:
        await session.execute(
            delete(PronunciationLexiconEntry).where(
                PronunciationLexiconEntry.id.in_(entry_ids)
            )
        )

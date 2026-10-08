import asyncio
import os

import pytest

from app.db.session import Database
from app.web.service import TopicAnalysisService


@pytest.mark.integration
def test_topic_analysis_does_not_fabricate_concept_for_unmatched_text() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def analyze() -> dict[str, object]:
        async with database.transaction() as session:
            return await TopicAnalysisService().analyze(
                session, "qzxv-unmatched-topic-83917"
            )

    result = asyncio.run(analyze())
    assert result["primary_concept_key"] is None
    assert result["concepts"] == []
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    assert "Keine belastbare Zuordnung gefunden." in warnings
    asyncio.run(database.dispose())

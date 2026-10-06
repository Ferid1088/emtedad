"""Live web-research grounding loops (APIMaster certification §5-6).

Runs ``WebResearchService.research_and_ingest`` twice against a real,
URL-capable retrieval backend (Wikipedia — keyless, no Tavily key
available). Verifies that findings carry verifiable URLs, fetched pages
are ingested as sources, and the run is persisted for provenance.

Usage:
    uv run python -m benchmarks.pipeline.run_research_loop
"""

import asyncio
import json
import time
from pathlib import Path

# Register every mapped model so cross-schema FKs resolve (same set as
# alembic/env.py).
from app.briefs import models as _brief_models  # noqa: F401
from app.channel_monitoring import models as _cm_models  # noqa: F401
from app.content_engine import models as _ce_models  # noqa: F401
from app.content_strategy import models as _cs_models  # noqa: F401
from app.core.ayin import models as _ayin_models  # noqa: F401
from app.core.config import get_settings
from app.core.terminology import models as _term_models  # noqa: F401
from app.db.session import Database
from app.dialogue import models as _dlg_models  # noqa: F401
from app.editorial_channels import models as _ec_models  # noqa: F401
from app.knowledge import models as _k_models  # noqa: F401
from app.knowledge.llm import models as _llm_models  # noqa: F401
from app.knowledge.structure import models as _st_models  # noqa: F401
from app.knowledge.units import models as _u_models  # noqa: F401
from app.lecture import models as _lec_models  # noqa: F401
from app.localization import models as _loc_models  # noqa: F401
from app.ops.assets import models as _asset_models  # noqa: F401
from app.ops.settings import models as _set_models  # noqa: F401
from app.production import models as _prod_models  # noqa: F401
from app.research import models as _r_models  # noqa: F401
from app.retrieval import models as _ret_models  # noqa: F401
from app.ritual import models as _rit_models  # noqa: F401
from app.speech_structure import models as _ss_models  # noqa: F401
from app.topics import models as _topic_models  # noqa: F401
from app.web_research import models as _wr_models  # noqa: F401
from app.web_research.service import WebResearchService

ARTIFACT_DIR = Path(__file__).parent / "artifacts"

QUERIES = [
    (
        "shame vulnerability Brené Brown research",
        "lecture on shame resilience and vulnerability claims",
    ),
    (
        "alcohol dependence craving cue exposure",
        "lecture on craving patterns in addiction treatment",
    ),
]


async def main() -> None:
    db = Database(get_settings().database_url.get_secret_value())
    try:
        service = WebResearchService(
            db,
            effective_overrides={
                "web_research_enabled": True,
                "web_research_provider": "wikipedia",
                "web_research_model": "",
                "web_research_base_url": "https://en.wikipedia.org",
                "web_research_api_key": "",
                "web_research_language": "en",
                "web_research_max_results": 5,
            },
        )
        loops = []
        for i, (query, context) in enumerate(QUERIES, start=1):
            print(f"--- loop {i}: {query!r}", flush=True)
            outcome = await service.research_and_ingest(
                query,
                context=context,
                schedule=False,
                trigger="certification_loop",
                round_number=i,
                query_kind="knowledge_gap",
            )
            report = outcome.report
            findings = report.findings if report else []
            entry: dict[str, object] = {
                "loop": i,
                "query": query,
                "error": outcome.error,
                "findings": [
                    {"title": f.title, "url": f.url, "snippet": f.snippet[:200]}
                    for f in (report.findings if report else [])
                ],
                "answer_text": (report.answer_text[:2000] if report else ""),
                "ingested": [
                    {
                        "url": g.url,
                        "source_id": str(g.source_id) if g.source_id else None,
                        "status": g.status,
                        "detail": g.detail,
                    }
                    for g in outcome.ingested
                ],
                "new_source_ids": [str(x) for x in outcome.new_source_ids],
            }
            loops.append(entry)
            print(
                f"    findings={len(findings)} "
                f"urls={sum(1 for f in findings if f.url)} "
                f"ingested={len(outcome.new_source_ids)} error={outcome.error}",
                flush=True,
            )
        ts = time.time()
        artifact = {
            "provider": "wikipedia",
            "loops": loops,
            "timestamp": ts,
        }
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        path = ARTIFACT_DIR / f"research_loop_{int(ts)}.json"
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        print(f"wrote {path}")
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())

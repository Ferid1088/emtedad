"""Baseline comparison for §14: run the same Persian critics used in the
Astra writer benchmark on the owner-approved Persian master draft, so
generated output can be compared against the historical baseline on the
same brief.

Usage:
    uv run python -m benchmarks.pipeline.run_baseline_critics <artifact.json>
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from app.briefs import models as _brief_models  # noqa: F401
from app.content_engine import models as _ce_models  # noqa: F401
from app.core.config import get_settings
from app.db.session import Database
from app.localization import models as _loc_models  # noqa: F401
from app.ops.settings import models as _set_models  # noqa: F401
from app.research import models as _r_models  # noqa: F401
from app.topics import models as _topic_models  # noqa: F401
from benchmarks.pipeline.astra_persian_writer import (
    GEMINI,
    NATIVE_CRITIC_INSTRUCTIONS,
    SEMANTIC_CRITIC_INSTRUCTIONS,
    SOL,
    CriticOutput,
    SemanticMasterOutput,
    _extract,
    _provider,
)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"


async def _approved_draft_text(db: Database, brief_id: str) -> str:
    from sqlalchemy import text

    async with db.transaction() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT text FROM content.script_drafts
                    WHERE status = 'APPROVED' AND content_brief_id = :brief_id
                    ORDER BY version_number DESC
                    LIMIT 1
                    """
                ),
                {"brief_id": brief_id},
            )
        ).first()
    if not row or not row[0]:
        raise RuntimeError(f"no approved script draft found for brief {brief_id}")
    return str(row[0])


async def main() -> int:
    artifact_path = Path(sys.argv[1])
    artifact = json.loads(artifact_path.read_text())
    master = SemanticMasterOutput.model_validate(artifact["semantic_master"]["output"])
    evidence = artifact.get("inputs", {}).get("evidence") or []
    db = Database(get_settings().database_url.get_secret_value())
    try:
        script_text = await _approved_draft_text(db, str(artifact["brief_id"]))
        print(f"approved draft: {len(script_text.split())} words")
        gemini = _provider(db, GEMINI, "NATIVE_SPOKEN_CRITIC")
        t0 = time.monotonic()
        native = await _extract(
            gemini,
            "fa_native_critic",
            NATIVE_CRITIC_INSTRUCTIONS,
            {
                "target_script": script_text,
                "language": "fa",
                "language_profile": {"register": "spoken_documentary"},
            },
            CriticOutput,
        )
        sol = _provider(db, SOL, "FACT_CRITIC")
        t1 = time.monotonic()
        evid = await _extract(
            sol,
            "fa_evidence_critic",
            SEMANTIC_CRITIC_INSTRUCTIONS,
            {
                "semantic_master_claims": [c.model_dump() for c in master.claims],
                "evidence": evidence,
                "target_script": script_text,
            },
            CriticOutput,
        )
        native_out = CriticOutput.model_validate(native.model_dump())
        evid_out = CriticOutput.model_validate(evid.model_dump())
        baseline = {
            "approved_draft_words": len(script_text.split()),
            "native_critic": {
                "latency_s": round(t1 - t0, 1),
                **native_out.model_dump(),
            },
            "evidence_critic": {
                "latency_s": round(time.monotonic() - t1, 1),
                **evid_out.model_dump(),
            },
        }
        artifact.setdefault("baseline_approved_draft", baseline)
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        print("native:", native_out.score, native_out.verdict[:150])
        print("evidence:", evid_out.score, evid_out.verdict[:150])
        print(f"updated {artifact_path}")
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

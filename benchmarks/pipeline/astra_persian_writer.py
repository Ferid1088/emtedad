"""Real Persian premium-writer certification (§11-14).

For a real brief with a complete upstream chain (frozen ResearchPackage,
READY ArgumentPlan + NarrativePlan, EvidenceMatrix items):

    Astra SemanticMaster   (gpt-6-astra, role PERSIAN_SEMANTIC_MASTER)
    → Astra ScriptWriter   (gpt-6-astra, role PERSIAN_SCRIPT_WRITER)
    → Gemini native critic (gemini-3.8-flash — style/narrative/spoken)
    → Sol semantic critic  (gpt-6.1-sol — evidence/epistemic fidelity)

Writes ``benchmarks/pipeline/artifacts/astra_fa_loop<N>_<ts>.json``.
Does not approve or mutate any production state; all calls record
``run_scope='certification'`` telemetry.

    uv run python -m benchmarks.pipeline.astra_persian_writer \
        --brief <uuid> --loop 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.briefs import models as _brief_models  # noqa: F401
from app.briefs.models import ContentBrief
from app.content_engine import models as _ce_models  # noqa: F401
from app.content_engine.models import (
    ArgumentPlan,
    ArgumentPlanSection,
    NarrativePlan,
    NarrativePlanSection,
)
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm import models as _llm_models  # noqa: F401
from app.knowledge.llm.apimaster import APIMasterConfig, APIMasterProvider
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.ops.settings import models as _set_models  # noqa: F401
from app.research import models as _r_models  # noqa: F401
from app.research.models import EvidenceMatrixItem
from app.topics import models as _topic_models  # noqa: F401

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
ASTRA = "gpt-6-astra"
GEMINI = "gemini-3.8-flash"
SOL = "gpt-6.1-sol"
PROMPT_VERSION = "astra-fa-cert.v2"
TARGET_SECONDS = 1650  # 25–30 min window midpoint


class MasterSection(BaseModel):
    id: str
    title: str
    purpose: str
    key_claims: list[str]
    evidence_refs: list[str]
    approx_seconds: int


class MasterClaim(BaseModel):
    id: str
    text: str
    epistemic_status: str
    evidence_refs: list[str]


class SemanticMasterOutput(BaseModel):
    thesis: str
    audience: str
    sections: list[MasterSection] = Field(min_length=5)
    claims: list[MasterClaim]
    allowed_book_references: list[str]
    epistemic_notes: str


class SectionTextOutput(BaseModel):
    section_id: str
    text: str
    word_count_self_report: int


class TitleOutput(BaseModel):
    title: str
    hook: str


class Finding(BaseModel):
    severity: str
    area: str = ""
    kind: str = ""
    claim: str = ""
    detail: str


class CriticOutput(BaseModel):
    score: float = Field(ge=0, le=10)
    verdict: str
    findings: list[Finding]


MASTER_INSTRUCTIONS = """You are the Persian Semantic Master writer for an \
evidence-grounded documentary lecture channel.

Produce the SEMANTIC MASTER in Persian — the authoritative content \
blueprint the script will be written from. It is not the script itself. \
Keep every field SHORT — this is a compact contract, not an essay: \
purpose ≤ 1 sentence, each claim ≤ 1 sentence.

Required JSON fields:
- thesis: the lecture's central claim, in Persian, ≤ 3 sentences
- audience: who this speaks to, in Persian, ≤ 1 sentence
- sections: ordered list; each item {id (s1..sN), title, purpose, \
key_claims (claim ids only), evidence_refs, approx_seconds}. 7-9 \
sections covering a 25-30 minute arc with a real opening, development, \
and ending
- claims: the load-bearing claims; each {id (c1..cN), text ≤ 1 sentence, \
epistemic_status (FACT|INFERENCE|INTERPRETATION|UNCERTAIN|STORY), \
evidence_refs}
- allowed_book_references: book/work names the script may cite
- epistemic_notes: ≤ 3 sentences on what must stay hedged, in Persian

Rules:
- Every claim must trace to the provided argument/evidence inputs.
- Never invent citations, studies, numbers, or quotations.
- Preserve uncertainty; do not upgrade evidence strength.""".strip()

WRITER_INSTRUCTIONS = """You are the premium Persian scriptwriter for a \
25-30 minute spoken documentary lecture.

Write ONE SECTION of the complete Persian narration script — the section \
specified in the input — from the Semantic Master and narrative plan. \
This is final audience-facing text in natural spoken Persian.

Required JSON fields:
- section_id: echo the input section id
- text: this section's narration as one Persian string. Natural spoken \
Persian — sentences a narrator can breathe through, not written-essay \
register.
- word_count_self_report: integer word count of text

Absolute rules:
- Persian only. No English scaffolding, no meta commentary, no \
[brackets], no stage directions, no section headers in the text.
- Every claim stays inside the master's claim ledger — no new facts, \
numbers, studies, or quotations.
- Keep hedged claims hedged. Do not strengthen evidence.
- Stay inside the NARRATOR's voice — tell the story and its meaning. \
Never slip into reviewing, citing, or fact-checking the material aloud \
(no «در چارچوب او»، «در نگاه سخنران»، «نتایج نشان می‌دهد» meta-voice); \
the audience hears a story, not a literature review.
- Uncertainty is expressed ONCE, inside the story («هنوز نمی‌دانیم»، \
«شاید») — never as repeated methodology warnings, evidence-limitation \
discussions, or academic caveats. One honest hedge per idea, then move \
on. The epistemic_notes govern wording, not airtime.
- Write with concrete sensory detail — scenes, objects, gestures, \
moments a listener can picture. Abstract-to-abstract narration is a \
defect, not a style.
- Each claim is used in ONE section only. The input lists claims already \
covered — never restate an earlier section's argument, example, or \
conclusion in new words. Move forward.
- Hit the section's word budget (±15%). No repetition padding, no \
rhetorical filler loops.
- Continue naturally from the provided previous-section ending — no \
re-introduction of the topic.
- If this is the opening section, it must earn attention immediately. \
If this is the ending, it must land — not summarize.""".strip()

TITLE_INSTRUCTIONS = """Choose the episode title for this Persian \
documentary lecture script. Return JSON {title: Persian title, hook: \
first-sentence strength note}. The title must be honest — no clickbait \
promises the script does not keep.""".strip()

NATIVE_CRITIC_INSTRUCTIONS = """You are a native-Persian literary critic \
for spoken documentary scripts. Judge ONLY native quality:
- naturalness of spoken Persian (not translationese, not essay register)
- rhythm and breath for a narrator
- narrative pull: hook, middle momentum, ending payoff
- repetition / filler / padding
- beginning/middle/end structural quality
Return JSON: score 0-10, verdict (one sentence, Persian ok), findings \
list [{severity: BLOCKER|MAJOR|MINOR, area, detail}]. Be honest and \
specific; cite the offending passage fragment.""".strip()

SEMANTIC_CRITIC_INSTRUCTIONS = """You are an evidence-fidelity critic. \
Compare the Persian script against the Semantic Master + evidence items.
Check:
- every factual claim in the script traces to a master claim or evidence \
item (flag TARGET_ONLY claims that appear in the script but not inputs)
- no invented studies, numbers, quotations, or attributions
- uncertainty preserved (hedged claims not stated as fact)
- no strengthened evidence, no dropped load-bearing caveats
Return JSON: score 0-10, verdict, findings [{severity, kind, claim, \
detail}]. kind in TARGET_ONLY_CLAIM|EPISTEMIC_DRIFT|INVENTED_REFERENCE|\
QUOTE_RISK|NUMBERS_DRIFT|DROPPED_CAVEAT.""".strip()


def _provider(db: Database, model: str, role: str) -> APIMasterProvider:
    settings = get_settings()
    return APIMasterProvider(
        APIMasterConfig(
            api_key=settings.apimaster_api_key.get_secret_value()
            if settings.apimaster_api_key
            else None,
            model=model,
            max_retries=1,
            timeout_seconds=600.0,
        ),
        recorder=DatabaseLLMRecorder(db, run_scope="certification"),
        agent_role=role,
    )


async def _extract(
    provider: APIMasterProvider,
    task: str,
    instructions: str,
    payload: dict[str, Any],
    output_model: type[BaseModel],
    timeout_seconds: int = 600,
) -> BaseModel:
    return await provider.extract(
        StructuredExtractionRequest(
            task=task,
            prompt_version=PROMPT_VERSION,
            model=provider.config.model,
            instructions=instructions,
            input_text=json.dumps(payload, ensure_ascii=False),
            output_model=output_model,
            timeout_seconds=timeout_seconds,
        )
    )


async def _inputs(db: Database, brief_id: UUID) -> dict[str, Any]:
    async with db.transaction() as session:
        brief = await session.get(ContentBrief, brief_id)
        if brief is None:
            raise SystemExit(f"brief {brief_id} not found")
        arg = (
            await session.execute(
                select(ArgumentPlan)
                .where(ArgumentPlan.content_brief_id == brief_id)
                .order_by(ArgumentPlan.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        arg_sections = (
            (
                await session.execute(
                    select(ArgumentPlanSection)
                    .where(ArgumentPlanSection.argument_plan_id == arg.id)
                    .order_by(ArgumentPlanSection.ordinal)
                )
            )
            .scalars()
            .all()
        )
        nar = await session.scalar(
            select(NarrativePlan).where(NarrativePlan.argument_plan_id == arg.id)
        )
        nar_sections: list[NarrativePlanSection] = []
        if nar is not None:
            nar_sections = list(
                (
                    await session.execute(
                        select(NarrativePlanSection)
                        .where(NarrativePlanSection.narrative_plan_id == nar.id)
                        .order_by(NarrativePlanSection.ordinal)
                    )
                )
                .scalars()
                .all()
            )
        evidence: list[EvidenceMatrixItem] = []
        if arg.evidence_matrix_id:
            evidence = list(
                (
                    await session.execute(
                        select(EvidenceMatrixItem)
                        .where(
                            EvidenceMatrixItem.evidence_matrix_id
                            == arg.evidence_matrix_id
                        )
                        .order_by(EvidenceMatrixItem.ordinal)
                    )
                )
                .scalars()
                .all()
            )
        return {
            "brief": {
                "question": brief.question,
                "thesis": brief.thesis,
                "angle": brief.angle,
                "target_audience": brief.target_audience,
                "target_duration_minutes": brief.target_duration_minutes,
            },
            "argument": [
                {
                    "ordinal": s.ordinal,
                    "role": str(s.role),
                    "purpose": s.purpose,
                    "claim_ids": s.claim_ids,
                    "evidence_item_ids": s.evidence_item_ids,
                    "must_include": s.must_include,
                    "must_not_claim": s.must_not_claim,
                }
                for s in arg_sections
            ],
            "narrative": [
                {
                    "ordinal": s.ordinal,
                    "narrative_role": str(s.narrative_role),
                    "purpose": s.purpose,
                    "target_seconds": s.target_seconds,
                    "emotional_function": s.emotional_function,
                    "opening_method": s.opening_method,
                    "ending_method": s.ending_method,
                }
                for s in nar_sections
            ],
            "evidence": [
                {
                    "ordinal": e.ordinal,
                    "role": str(e.role),
                    "claim": e.claim_text,
                    "epistemic_status": str(e.epistemic_status),
                    "limitations": e.limitations,
                    "allowed_wording": e.allowed_wording,
                    "forbidden_wording": e.forbidden_wording,
                }
                for e in evidence
            ],
        }


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


async def run(brief_id: UUID, loop: int) -> dict[str, Any]:
    db = Database(get_settings().database_url.get_secret_value())
    try:
        inputs = await _inputs(db, brief_id)
        astra = _provider(db, ASTRA, "PERSIAN_SEMANTIC_MASTER")
        artifact: dict[str, Any] = {
            "loop": loop,
            "brief_id": str(brief_id),
            "question": inputs["brief"]["question"],
        }
        # Persist incrementally — a late crash must not lose an expensive run.
        out_path = ARTIFACT_DIR / f"astra_fa_loop{loop}_{int(time.time())}.json"
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

        def _save() -> None:
            out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))

        # Step A — Astra SemanticMaster
        t0 = time.monotonic()
        master_raw = await _extract(
            astra,
            "persian_semantic_master",
            MASTER_INSTRUCTIONS,
            {
                "brief": inputs["brief"],
                "argument": inputs["argument"],
                "narrative": inputs["narrative"],
                "evidence": inputs["evidence"],
                "constraints": {
                    "language": "fa",
                    "duration_seconds": TARGET_SECONDS,
                    "no_invented_evidence": True,
                },
            },
            SemanticMasterOutput,
        )
        master = SemanticMasterOutput.model_validate(master_raw.model_dump())
        artifact["semantic_master"] = {
            "latency_s": round(time.monotonic() - t0, 1),
            "sections": len(master.sections),
            "claims": len(master.claims),
            "output": master.model_dump(),
        }
        print(f"master: {len(master.sections)} sections, {len(master.claims)} claims")
        _save()

        # Step B — Astra ScriptWriter, section by section.
        # Live-probed gateway fact (2026-10-05): the APIMaster Astra route
        # hard-limits upstream generation to ~4 minutes — a single-shot
        # 3,800-word script (~7k output tokens) 504s, while ~900-token
        # outputs complete. Bounded per-section writes are the honest
        # premium path; each section gets master + budgets + the previous
        # section's ending for continuity.
        writer = _provider(db, ASTRA, "PERSIAN_SCRIPT_WRITER")
        t0 = time.monotonic()
        total_seconds = sum(s.approx_seconds for s in master.sections) or TARGET_SECONDS
        total_word_budget = int(total_seconds / 60 * 140)
        section_texts: list[dict[str, Any]] = []
        previous_tail = ""
        claims_used: list[str] = []
        for section in master.sections:
            budget = max(int(section.approx_seconds / 60 * 140), 250)
            raw = await _extract(
                writer,
                "persian_script_writer",
                WRITER_INSTRUCTIONS,
                {
                    "semantic_master": master.model_dump(),
                    "narrative": inputs["narrative"],
                    "evidence_summary": inputs["evidence"],
                    "book_references": master.allowed_book_references,
                    "language_profile": {
                        "language": "fa",
                        "register": "spoken_documentary",
                    },
                    "section": section.model_dump(),
                    "word_budget": budget,
                    "previous_section_ending": previous_tail,
                    "claims_already_used": claims_used,
                },
                SectionTextOutput,
            )
            out = SectionTextOutput.model_validate(raw.model_dump())
            section_texts.append(
                {
                    "section_id": section.id,
                    "title": section.title,
                    "budget": budget,
                    "words": _words(out.text),
                    "text": out.text,
                }
            )
            previous_tail = out.text[-400:]
            claims_used.extend(section.key_claims)
            print(f"  section {section.id}: {_words(out.text)} words (budget {budget})")
        title_raw = await _extract(
            writer,
            "persian_title",
            TITLE_INSTRUCTIONS,
            {
                "thesis": master.thesis,
                "script_opening": section_texts[0]["text"][:600]
                if section_texts
                else "",
            },
            TitleOutput,
        )
        title = TitleOutput.model_validate(title_raw.model_dump()).title
        script_text = "\n\n".join(s["text"] for s in section_texts)
        words = _words(script_text)
        artifact["script"] = {
            "latency_s": round(time.monotonic() - t0, 1),
            "title": title,
            "words": words,
            "word_budget": total_word_budget,
            "duration_estimate_min": round(words / 140, 1),
            "sections": [
                {k: v for k, v in s.items() if k != "text"} for s in section_texts
            ],
            "text": script_text,
        }
        print(f"script: {words} words (~{words / 140:.1f} min)")
        _save()

        await _critics(db, artifact, script_text, master, inputs["evidence"])
        _save()
        return artifact
    finally:
        await db.dispose()


async def _critics(
    db: Database,
    artifact: dict[str, Any],
    script_text: str,
    master: SemanticMasterOutput,
    evidence: list[dict[str, Any]],
) -> None:
    gemini = _provider(db, GEMINI, "NATIVE_SPOKEN_CRITIC")
    t0 = time.monotonic()
    native_raw = await _extract(
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
    artifact["native_critic"] = {
        "latency_s": round(time.monotonic() - t0, 1),
        **CriticOutput.model_validate(native_raw.model_dump()).model_dump(),
    }
    print(
        f"native critic: {artifact['native_critic']['score']} "
        f"({len(artifact['native_critic']['findings'])} findings)"
    )
    for f in artifact["native_critic"]["findings"][:6]:
        print(
            f"   [{f.get('severity')}] "
            f"{f.get('area') or f.get('kind')}: {str(f.get('detail'))[:110]}"
        )
    sol = _provider(db, SOL, "FACT_CRITIC")
    t0 = time.monotonic()
    sem_raw = await _extract(
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
    artifact["evidence_critic"] = {
        "latency_s": round(time.monotonic() - t0, 1),
        **CriticOutput.model_validate(sem_raw.model_dump()).model_dump(),
    }
    print(
        f"evidence critic: {artifact['evidence_critic']['score']} "
        f"({len(artifact['evidence_critic']['findings'])} findings)"
    )
    for f in artifact["evidence_critic"]["findings"][:8]:
        print(
            f"   [{f.get('severity')}] "
            f"{f.get('kind') or f.get('area')}: {str(f.get('detail'))[:110]}"
        )


REVISION_INSTRUCTIONS = """You are the premium targeted reviser of a \
Persian documentary script.

You receive the full script plus critic findings. Rewrite ONLY what the \
findings implicate: fix the named defects (register/POV drift, repeated \
arguments, invented details, epistemic overstatement) while preserving \
everything else as close to the original wording as possible.

Hard rules:
- Persian only, same spoken-narrator register throughout — pick ONE \
audience address (formal «شما» narration voice) and keep it.
- Delete invented details flagged as unsupported (numbers, anecdotes, \
mechanisms not in the master claims). Do not replace them with new \
inventions — cut or generalize to what the master supports.
- Restore hedged wording wherever epistemic drift was flagged.
- Merge/trim repeated passages rather than restating them.
- Stay within ±8% of the target_words budget. If previous trimming \
pushed the script under target, restore depth from the supplied \
original script — reusing passages that were NOT implicated by findings. \
Expansion must come from restored original material or elaboration of \
existing supported claims, never new facts.
- Return the COMPLETE revised script in `script` — whole text, not a diff.
- Do not add facts, studies, numbers, quotes, or book references.""".strip()


class RevisedScriptOutput(BaseModel):
    script: str
    word_count_self_report: int
    changes_summary: str


async def run_revise(db: Database, artifact_path: Path) -> None:
    """PREMIUM_TARGETED_REVISION: fix critic findings, re-gate, save."""

    artifact = json.loads(artifact_path.read_text())
    master = SemanticMasterOutput.model_validate(artifact["semantic_master"]["output"])
    # Revise from the best-scoring revision so far (a regression pass does
    # not become the base for the next one).
    prior_keys = sorted(k for k in artifact if k.startswith("revision"))

    def _combined(key: str) -> float:
        crit = artifact.get(f"critics_after_{key}") or {}
        n = crit.get("native_critic", {}).get("score") or 0
        e = crit.get("evidence_critic", {}).get("score") or 0
        return float(n) + float(e)

    best_key = max(prior_keys, key=_combined) if prior_keys else None
    prior = artifact[best_key] if best_key else None
    rev_n = len(prior_keys) + 1
    rev_key = "revision" if prior is None else f"revision_{rev_n}"
    crit_key = (
        "critics_after_revision" if prior is None else f"critics_after_revision_{rev_n}"
    )
    script_text = prior["text"] if prior else artifact["script"]["text"]
    latest_crit = f"critics_after_{best_key}" if best_key else None
    findings_source = (
        artifact[latest_crit] if latest_crit and artifact.get(latest_crit) else artifact
    )
    findings = {
        "native": findings_source.get("native_critic", {}).get("findings", []),
        "evidence": findings_source.get("evidence_critic", {}).get("findings", []),
    }
    astra = _provider(db, ASTRA, "PREMIUM_TARGETED_REVISION")
    t0 = time.monotonic()
    revised_raw = await _extract(
        astra,
        "premium_targeted_revision",
        REVISION_INSTRUCTIONS,
        {
            "draft": script_text,
            "original_script": artifact["script"]["text"],
            "findings": findings,
            "affected_sections": [
                s.get("area") or s.get("kind") or ""
                for s in findings["native"] + findings["evidence"]
            ],
            "constraints": {
                "master_claims": [c.model_dump() for c in master.claims],
                "language": "fa",
                "target_words": artifact["script"].get("word_budget")
                or int(artifact["script"]["words"]),
            },
        },
        RevisedScriptOutput,
        timeout_seconds=900,
    )
    revised = RevisedScriptOutput.model_validate(revised_raw.model_dump())
    artifact[rev_key] = {
        "latency_s": round(time.monotonic() - t0, 1),
        "words": _words(revised.script),
        "duration_estimate_min": round(_words(revised.script) / 140, 1),
        "changes": revised.changes_summary,
        "text": revised.script,
    }
    print(
        f"{rev_key}: {artifact[rev_key]['words']} words "
        f"(~{artifact[rev_key]['duration_estimate_min']} min)"
    )
    inputs = await _inputs(db, UUID(artifact["brief_id"]))
    artifact[crit_key] = {}
    await _critics(
        db,
        artifact[crit_key],
        revised.script,
        master,
        inputs["evidence"],
    )
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    print(f"updated {artifact_path}")


async def run_critics_only(db: Database, artifact_path: Path) -> None:
    """Re-run only the critics against a saved artifact's script."""

    artifact = json.loads(artifact_path.read_text())
    master = SemanticMasterOutput.model_validate(artifact["semantic_master"]["output"])
    inputs = await _inputs(db, UUID(artifact["brief_id"]))
    await _critics(db, artifact, artifact["script"]["text"], master, inputs["evidence"])
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    print(f"updated {artifact_path}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief")
    parser.add_argument("--loop", type=int, choices=(1, 2))
    parser.add_argument(
        "--critics-only",
        metavar="ARTIFACT",
        help="re-run only the critics against a saved artifact",
    )
    parser.add_argument(
        "--revise",
        metavar="ARTIFACT",
        help="premium targeted revision on critic findings, then re-gate",
    )
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if args.critics_only or args.revise:
        db = Database(get_settings().database_url.get_secret_value())
        try:
            if args.critics_only:
                await run_critics_only(db, Path(args.critics_only))
            else:
                await run_revise(db, Path(args.revise))
        finally:
            await db.dispose()
        return 0
    if not args.brief or not args.loop:
        parser.error("--brief and --loop are required")
    artifact = await run(UUID(args.brief), args.loop)
    out = ARTIFACT_DIR / f"astra_fa_loop{args.loop}_{int(time.time())}.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

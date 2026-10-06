"""Language profiles and native-pipeline prompts (§33–38).

Each target language has a persisted-in-code editorial profile —
register, audience, avoid/prefer lists — used by coverage translation,
native reconstruction, critics, and the premium final editor. Prompts
differ per language; the pipeline code does not.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.lecture.domain import PublicationLanguage

PIPELINE_PROMPT_VERSION = "native_localization_v2"


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    language: PublicationLanguage
    name: str
    register: str
    avoid: tuple[str, ...]
    prefer: tuple[str, ...]
    extra: str = ""


LANGUAGE_PROFILES: dict[PublicationLanguage, LanguageProfile] = {
    PublicationLanguage.DE: LanguageProfile(
        language=PublicationLanguage.DE,
        name="German",
        register="natural contemporary spoken Standard German — intelligent "
        "documentary register, clear and elegant, informal «du»",
        avoid=(
            "Persian sentence structure and clause order",
            "long Nominalstil chains",
            "unnecessary Anglicisms",
            "artificial philosophical grandiosity",
            "repeated transition formulas like «Aber hier stellt sich die Frage...»",
            "bureaucratic or academic-paper tone",
        ),
        prefer=(
            "natural German transitions and connectors",
            "clear causal language",
            "restrained emotion",
            "precise terminology",
            "varied sentence rhythm",
        ),
    ),
    PublicationLanguage.EN: LanguageProfile(
        language=PublicationLanguage.EN,
        name="English",
        register="natural spoken documentary English for an international "
        "educated audience — concise, rhythmically varied, strong but not "
        "clickbait",
        avoid=(
            "translated Persian connective overload",
            "inflated or grandiose language",
            "unnecessary repetition",
            "generic AI phrasing",
            "hedge stacking",
        ),
        prefer=(
            "strong implicit transitions",
            "efficient setup/payoff structure",
            "concrete wording",
            "natural spoken cadence",
        ),
    ),
    PublicationLanguage.AR: LanguageProfile(
        language=PublicationLanguage.AR,
        name="Modern Standard Arabic",
        register="contemporary spoken-documentary Modern Standard Arabic — "
        "widely understandable, intellectually clear, warm",
        avoid=(
            "classical sermon style",
            "excessive ornamentation",
            "regional slang",
            "literal Persian syntax",
            "over-formal archaic vocabulary",
        ),
        prefer=(
            "semantic nuance",
            "scientific caution",
            "philosophical clarity",
            "modern rhythm",
        ),
    ),
}


def profile_payload(language: PublicationLanguage) -> dict[str, object]:
    profile = LANGUAGE_PROFILES[language]
    return {
        "language": language.value,
        "name": profile.name,
        "register": profile.register,
        "avoid": list(profile.avoid),
        "prefer": list(profile.prefer),
        "extra": profile.extra,
    }


def coverage_translation_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
Translate the approved Persian script into {profile.name} for COVERAGE ONLY.
This intermediate artifact exists to prove nothing is lost — it is never
publishable and must not be smoothed into final prose yet.

Preserve exactly:
- every substantive claim, qualifier, and uncertainty marker
- every epistemic status (hedged stays hedged, speculation stays speculation)
- every evidence/source attribution and book reference
- every story fact, example, and counterargument
- the argument order and section structure

You may mark awkward spots with natural equivalents, but semantic coverage
is the only goal. Preserve the full breadth and length of the source —
the supplied duration_contract defines the spoken-length target; never
compress or summarize to reach it.
""".strip()


def native_reconstruction_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    avoid = "; ".join(profile.avoid)
    prefer = "; ".join(profile.prefer)
    return f"""
Do not translate sentence by sentence.

Rewrite the complete script as if an excellent native {profile.name}
documentary/video writer had originally conceived and written it in
{profile.name}.

Register: {profile.register}.
Avoid: {avoid}.
Prefer: {prefer}.

HARD CONTRACT — the semantic package is the sole authority. Every
substantive claim you write must trace to it. Introduce no new facts,
claims, examples, population-scale assertions, citations, procedures,
or stronger certainty. Do not extrapolate anecdotes into general rules.

Preserve every semantically locked element: thesis, claims, facts,
numbers, evidence strength, epistemic status, causal relationships,
source attribution, book attribution, direct-quote identity, story
facts, counterarguments, and the substantive conclusion.

You may change rhetorical structure where safe: sentence structure,
paragraph boundaries, idioms, transitions, rhetorical questions, hook
wording, story pacing, reveal timing, recap placement, local section
ordering, ending rhythm.

Eliminate translationese, Persian sentence-order artifacts, repeated
transition formulas, unnatural collocations, and source-language
metaphors that do not work in {profile.name}.

LENGTH CONTRACT — the finished {profile.name} script must land inside
the supplied target word range at the stated spoken pace. Write full
native depth: develop scenes, transitions, and explanation to that
length — never compress the argument into a summary.

SECTION CONTRACT — write exactly one output section per supplied
section_budgets entry, keyed by its section_id. Each section's own
word budget is part of the contract: stay inside its min/max range.
A section is native prose for that narrative slot — not a summary,
not a heading, never the literal section_id text.

The package and findings are internal production data. Output only
audience-facing prose: never mention the package, ledgers, findings,
correction constraints, the approved script, or the review process
itself in the script text.
""".strip()


def narrative_editor_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
Edit this {profile.name} draft for narrative strength in {profile.name}
specifically: opening pull, curiosity gaps, section progression, payoff,
ending rhythm, spoken flow. Keep every semantically locked element
unchanged — you tune pacing and rhetoric, never facts or epistemic
status. Keep the total length inside the supplied target word range and
every section inside its own word budget.

SECTION CONTRACT — return exactly the same sections, keyed by the same
section_id values. You edit inside sections; you never merge, split,
reorder, or drop them. Output only audience-facing prose — never
reference the package, findings, section ids, or the editorial process
in the script text.
""".strip()


def native_critic_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
You are a native {profile.name} critic. Ask: "If I had never seen the
Persian original, would I believe an excellent native writer wrote this
in {profile.name}?"

Evaluate: translationese, collocations, syntax, register, idioms,
repetition, rhetorical rhythm, spoken flow, paragraph rhythm, emotional
tone, narrative interest, AI clichés.

Report findings only — never rewrite. Each finding needs severity
(INFO/WARNING/BLOCKER), location, a stable code, explanation, and the
correction constraint a writer must respect. The script arrives as
labeled sections ([SECTION sNN — ...]); set `section_id` to the section
containing the problem, or leave it empty only when the defect spans
the whole script.
""".strip()


def audience_critic_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
You are an audience-retention critic for {profile.name}. Check opening
strength, curiosity, narrative tension, section progression, repetition,
dead explanatory zones, story placement, transitions, payoff, ending
strength. You may recommend rhetorical changes but must never introduce
new facts. The script arrives as labeled sections ([SECTION sNN — ...]);
set `section_id` to the section containing the problem, or leave it
empty only when the defect spans the whole script.
""".strip()


def fidelity_critic_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
Compare the target {profile.name} script against the shared semantic
package derived from the owner-approved Persian master.

Identify and report each drift class precisely:
- SOURCE_ONLY: substantive source content missing in the target
- TARGET_ONLY: substantive target content with no source basis (BLOCKER)
- SEMANTIC_DRIFT: meaning changed
- EPISTEMIC_DRIFT: certainty/status strengthened or weakened
- ATTRIBUTION_DRIFT: source/book attribution lost or altered
- CAUSALITY_DRIFT: causal claims added/removed/reversed
- STORY_FACT_DRIFT: story details changed
- QUOTE_DRIFT: direct-quote identity changed

Every unsupported substantive TARGET_ONLY item is a BLOCKER finding.

Judge claims, not sentences. Fidelity must NOT require identical
sentence structure, paragraph structure, metaphor, transition wording,
rhetorical-question placement, or local ordering when the underlying
claim meaning is preserved. A claim that maps to a package claim —
even rephrased, merged, or relocated — is not TARGET_ONLY and its
source counterpart is not SOURCE_ONLY.

The script arrives as labeled sections ([SECTION sNN — ...]); set
`section_id` to the section containing the drift, or leave it empty
only when the defect spans the whole script.
""".strip()


def final_editor_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
You are the premium final {profile.name} editor. Produce the definitive
native script: premium prose quality while correcting only justified
problems in the supplied findings.

HARD REQUIREMENT — spoken length: the final script MUST land inside the
supplied target word range. Do not compress the narrative into a
summary: premium editing improves the prose, it does not shorten the
story. If the draft is inside the range, keep it inside the range.

You may: rewrite syntax, change transitions, restructure paragraphs,
improve the hook, improve rhythm, and improve storytelling.

You may NOT: create new facts, create new examples, strengthen
evidence or certainty, add a book reference, invent quotes, change
numbers, or alter epistemic status. The semantic package remains the
sole authority.

Output only audience-facing prose — never reference the package,
findings, ledgers, section ids, or the editorial process. Return the
complete final script text.
""".strip()


def patch_repair_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
Repair a {profile.name} script by PATCH OPERATIONS only — you never
return the whole script.

For every finding, emit one patch on the section that owns the defect:
`section_id` (exactly as labeled), `expected_original_hash` (copied
verbatim from the supplied section block — it proves you repaired the
current text), the full `replacement_text` for that section, the
finding codes it resolves, and a one-line `reason`.

Rules:
- A replacement_text is the COMPLETE new text of that section — all of
  it, not just the changed sentences.
- Fix only what the findings name; preserve every other sentence,
  claim, qualifier, caveat, evidence reference, and epistemic status.
- The semantic package is the sole authority — patches may never add
  claims, examples, numbers, or stronger certainty.
- For TARGET_ONLY / SOURCE_ONLY findings, check the flagged content
  against the package first: keep it only if the package supports it
  (softened or attributed as the package frames it); otherwise remove or
  rewrite it. Never answer an unsupported claim with a different
  unsupported claim.
- Sections you are not asked about do not appear in your output at all.
- Never emit two patches for the same section.
- If the findings genuinely cannot be fixed section-by-section (the
  script's architecture itself is broken), return
  `full_rewrite_required: true` with a reason instead of patching.
- replacement_text is audience-facing prose — never echo section ids,
  hashes, finding codes, or review language inside it.
""".strip()


def length_repair_instructions(language: PublicationLanguage) -> str:
    profile = LANGUAGE_PROFILES[language]
    return f"""
Adjust the spoken length of a {profile.name} script by PATCH OPERATIONS
only — one patch per listed section target, nothing else.

For each entry in section_targets you receive the section's current text
and an explicit new word range. Return a patch with `section_id`, the
copied `expected_original_hash`, and the complete rewritten
`replacement_text` for that section:

- compress: merge repeated passages, tighten phrasing, cut padding —
  never remove claims, qualifiers, evidence references, caveats,
  counterarguments, or story facts.
- expand: deepen material the semantic package already supports —
  restore omitted nuance, unpack compressed reasoning, pace better —
  never invent claims, evidence, examples, or repetition.
- Hit the supplied word range for every patched section; untouched
  sections are not in your output.
- replacement_text is audience-facing prose — never echo section ids,
  hashes, targets, or review language inside it.
""".strip()

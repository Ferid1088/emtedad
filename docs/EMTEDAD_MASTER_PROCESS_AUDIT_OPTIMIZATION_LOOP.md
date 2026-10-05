# EMTEDAD STUDIO — MASTER END-TO-END AUDIT, TEST, CRITIQUE & OPTIMIZATION LOOP

## Purpose

You are working in the existing repository:

```text
Ferid1088/emtedad
```

The architecture is already substantial and working.

This task is NOT another broad rewrite.

Your job is to **systematically audit, test, criticize, optimize and re-test every production process one by one**, using real persisted data and realistic end-to-end flows.

The coding agent must NOT assume that something works because a unit test passes or because a UI checkbox is green.

Every process stage must be independently verified.

You must work in controlled loops until the acceptance gates for that process are satisfied.

Do not commit until the complete audit is finished and the owner reviews the final report.

---

# 1. CORE RULE — NEVER MARK MULTIPLE STAGES COMPLETE AT ONCE

The current UI/production flow must never "check all boxes" or advance several stages just because one downstream action succeeded.

Every stage is an independent persisted artifact.

Required conceptual stages:

```text
SOURCE
↓
SOURCE STRUCTURE / VORTRAGSSTRUKTUR
↓
KNOWLEDGE UNITS
↓
CONCEPT MAPPING
↓
TOPIC CANDIDATE
↓
CONTENT BRIEF
↓
RESEARCH PLAN
↓
INTERNET RESEARCH
↓
EVIDENCE MATRIX
↓
ARGUMENT PLAN
↓
NARRATIVE PLAN
↓
SEMANTIC MASTER
↓
SCRIPT
↓
CRITIC REVIEW
↓
OWNER APPROVAL
↓
TRANSLATIONS
↓
PUBLICATION PREPARATION
```

Each stage must have its own real state.

Use existing enums where available.

If needed, normalize UI representation to states equivalent to:

```text
NOT_STARTED
READY_TO_START
RUNNING
READY
REVIEW_REQUIRED
FAILED
APPROVED
```

Do NOT introduce a second competing state machine if one already exists.

---

# 2. STAGE COMPLETION INVARIANT

A stage may show:

```text
✓ completed
```

ONLY when:

1. the required artifact exists in the database
2. its status is valid for completion
3. its validator passes
4. required upstream references are correct
5. its provenance is persisted
6. its content hash/version is persisted where applicable
7. its stage-specific acceptance checks pass

Example:

```text
Narrative = READY
```

does NOT imply:

```text
Master = READY
Script = READY
Review = READY
```

Those remain incomplete until separately created and verified.

---

# 3. ADD STATE-TRANSITION REGRESSION TESTS

Create tests that explicitly prove:

```text
creating ContentBrief
does NOT mark Research READY

creating ResearchPackage
does NOT mark Evidence READY

creating EvidenceMatrix
does NOT mark Argument READY

creating ArgumentPlan
does NOT mark Narrative READY

creating NarrativePlan
does NOT mark Semantic Master READY

creating Semantic Master
does NOT mark Script READY

creating ScriptDraft
does NOT mark Review READY

running critics
does NOT auto-approve the script

approving master script
does NOT mark translations complete

creating one translation
does NOT mark all languages complete
```

This is a HARD GATE.

---

# 4. MASTER OPTIMIZATION LOOP

For EACH process described below, use this exact loop.

```text
A. INSPECT
↓
B. BASELINE
↓
C. TEST
↓
D. CRITIQUE
↓
E. IDENTIFY ROOT CAUSE
↓
F. FIX / OPTIMIZE
↓
G. RE-TEST
↓
H. ADVERSARIAL TEST
↓
I. REAL-DATA TEST
↓
J. DOCUMENT
↓
K. DECIDE PASS / LOOP AGAIN
```

Do not skip steps.

---

# 5. LOOP STOP RULE

A process is considered complete only when:

```text
all deterministic tests pass
stage invariants pass
real-data acceptance passes
no critical/major defect remains
no fake UI state exists
no silent failure exists
no obvious unnecessary LLM call remains
provenance is intact
```

If not:

```text
repeat the loop
```

Do not loop indefinitely.

Maximum:

```text
3 optimization loops per process
```

If still failing after 3 loops:

```text
STOP that process
mark BLOCKED
document exact blocker
continue only with independent processes
```

Do not hide unresolved failures.

---

# 6. DO NOT OPTIMIZE RANDOMLY

Every change must be connected to:

```text
observed defect
measured quality weakness
incorrect state transition
bad real-data output
unnecessary cost
bad latency
poor UX
weak evidence
wrong channel behavior
```

Do not refactor code merely because another style looks nicer.

---

# 7. TARGET CONTENT DURATION

Every normal long-form production for the five channels must target:

```text
25–30 minutes
```

Default planning target:

```text
27.5 minutes
```

This is the target for the approved master script before localization unless the owner explicitly overrides it.

Do NOT use one fixed word count for all languages.

Use configurable speaking-rate estimates per language.

Example configurable defaults may exist as:

```text
fa_words_per_minute
de_words_per_minute
en_words_per_minute
ar_words_per_minute
```

Do not hard-code numbers throughout services.

---

# 8. DURATION VALIDATION

For every script version calculate:

```text
estimated_duration_minutes
```

Required normal range:

```text
25.0 <= duration <= 30.0
```

If below:

```text
TOO_SHORT
```

If above:

```text
TOO_LONG
```

The Revision process must be able to fix duration without:

```text
padding with repetition
removing essential evidence
destroying story coherence
inventing unsupported material
```

---

# 9. TRANSLATION DURATION

Translations should preserve the content and approximate target video duration.

Do not require identical word counts.

For each translated version estimate spoken duration.

Preferred acceptance:

```text
25–30 minutes
```

or, if a language naturally differs substantially:

```text
within configured acceptable duration tolerance
```

The UI must show estimated duration for each language track.

---

# 10. PROCESS 1 — RESOURCE IMPORT

Test separately:

```text
YouTube video
PDF
Book/Text
```

For each:

```text
import
duplicate detection
metadata
language
Source
SourceVersion
SourceSegments
hashes
provenance
failure behavior
retry
```

Critique:

```text
Can malformed input corrupt a source?
Can retries duplicate versions?
Can the same resource be assigned to several EditorialChannels without re-import?
Is the owner told what happened?
```

Optimize only if tests reveal defects.

---

# 11. PROCESS 2 — YOUTUBE CHANNEL MONITORING

Test:

```text
add monitored YouTube channel
validate handle/URL
check one channel
check all channels
discover new videos
avoid duplicate candidates
ignore candidate
import candidate
remove monitored channel
```

Removing monitoring must NOT delete already imported resources.

Test provider/network failures.

UI must clearly distinguish:

```text
YouTube source channels
```

from:

```text
five EditorialChannels
```

---

# 12. PROCESS 3 — VORTRAGSSTRUKTUR

Use real long videos of different styles:

```text
structured lecture
interview
story-rich discussion
long unstructured conversation
```

Test:

```text
hierarchy quality
source-span validity
timestamp/page validity
parent-child containment
coverage
stories
case studies
question/answer
counterarguments
experiments
definitions
```

Critique each real structure.

Explicitly look for:

```text
false splits
merged unrelated sections
missing story endings
too many tiny nodes
huge meaningless nodes
hallucinated summaries
wrong hierarchy
```

Optimize prompts/validation only when required.

---

# 13. PROCESS 4 — KNOWLEDGE UNIT EXTRACTION

Test all unit types:

```text
CLAIM
DEFINITION
EXPLANATION
STORY
CASE_STUDY
EXAMPLE
EXPERIMENT
QUOTE
COUNTERARGUMENT
OPEN_QUESTION
SYNTHESIS
```

Hard rules:

```text
STORY atomic
CASE_STUDY atomic
full_text source-derived
summary not authoritative source
invalid unit proposals rejected
batch survives individual malformed proposal
```

Measure:

```text
unit count
invalid proposal count
oversized units
atomic preservation
duplicate overlap
```

---

# 14. PROCESS 5 — CONCEPT MAPPING

Test:

```text
multilingual aliases
canonical reuse
duplicate prevention
noise rejection
mapping confidence
mapping roles
cross-source reuse
```

Measure:

```text
coverage
avg concepts/unit
strict precision
useful precision
wrong links
concept retrieval contribution
```

Do NOT optimize for 100% coverage.

Target:

```text
useful precision >= 90%
```

---

# 15. PROCESS 6 — RETRIEVAL

Test separately:

```text
lexical
dense
concept
fusion/RRF
reranking
structural expansion
```

Query types:

```text
exact phrase
paraphrase
concept query
story detail
causal question
counterargument
cross-language
ambiguous question
```

Hard gates:

```text
atomic story returned whole
parent-child duplicates suppressed
source provenance present
non-timed sources work
large summary does not flood writer context
```

---

# 16. PROCESS 7 — TOPIC PROPOSAL CREATION

Topic creation must be audited as its OWN process.

Do not mix it with production.

Input:

```text
EditorialChannel
active ChannelStrategyVersion
assigned resources
KnowledgeUnits
concepts
published ScriptSignatures
optional owner seed/question
```

Output:

```text
TopicCandidate / Video Question
```

---

# 17. TOPIC PROPOSAL MUST NOT BE A GENERIC KEYWORD

Bad:

```text
Jealousy
Attachment
War
Consciousness
```

Good:

```text
Why does silence from a partner trigger such intense anxiety?

Why do humans continue fighting even when war harms both sides?

Does consciousness require a biological brain?
```

Main object:

```text
Video Question
```

---

# 18. TOPIC PROPOSAL OUTPUT

Every generated candidate must include:

```text
title
video_question
tentative_thesis
angle
channel-fit explanation
supporting concepts
supporting KnowledgeUnits
supporting sources
knowledge gaps
score breakdown
provenance
```

Do not persist unsupported candidate fields as if verified.

---

# 19. TOPIC SCORING

Evaluate separately:

```text
Channel Fit
Knowledge Coverage
Novelty
Curiosity
Emotional Relevance
Practical Value
```

Weights come from ChannelStrategyVersion.

Do not use universal hard-coded weights.

Test:

```text
high curiosity + low coverage
```

must NOT become automatically production-ready.

---

# 20. TOPIC DIVERSITY

Generate at least:

```text
10 topic candidates per tested channel
```

Critique:

```text
duplicate questions
same thesis with different wording
same story repeatedly
wrong channel
too broad
too narrow
insufficient evidence
low novelty
```

Use ScriptSignature for previous-content comparison.

Do not use full old scripts as writer prompt context.

---

# 21. FIVE CHANNEL AGENT PACKS

Verify each channel uses:

```text
Shared Core Agents
+
Channel-specific Agent Pack
```

No channel may silently fall back to another channel's strategy.

---

# 22. SHARED CORE AGENTS

Audit and test roles equivalent to:

```text
TopicMinerAgent
QuestionGeneratorAgent
ContentBriefAgent
ThesisAgent
DistinctivenessPlanner
ResearchPlannerAgent
ArgumentArchitectAgent
NarrativeArchitectAgent
ScriptWriterAgent
FactCritic
LogicCritic
RetentionCritic
OriginalityCritic
RevisionAgent
```

Do not require one API call per conceptual role if batching is safe.

But preserve responsibility boundaries.

---

# 23. EMTEDAD CHANNEL AGENTS

Verify behavior equivalent to:

```text
HumanProblemAgent
PatternAgent
PhilosophyAgent
CounterargumentAgent
MeaningAgent
EmtedadBoundaryReviewer
```

Test that Emtedad topics/scripts emphasize:

```text
human patterns
continuity
awareness
meaning
change
```

Do not let philosophical interpretations become unsupported scientific claims.

---

# 24. SCIENCE & MYSTERY AGENTS

Verify:

```text
ScientificEvidenceAgent
EpistemicStatusAgent
AlternativeExplanationAgent
PhilosophyBridgeAgent
OverclaimGate
```

Hard classification:

```text
ESTABLISHED_SCIENCE
STRONG_EVIDENCE
LIMITED_EVIDENCE
HYPOTHESIS
CONTESTED
OPEN_QUESTION
SPECULATION
PHILOSOPHICAL_INTERPRETATION
UNKNOWN
```

Test that:

```text
philosophy != scientific proof
hypothesis != established fact
UNKNOWN != strong evidence
```

---

# 25. HISTORY AGENTS

Verify:

```text
TimelineAgent
CausalityAgent
HistoricalContextAgent
CharacterAgent
ConflictAgent
SourceConflictAgent
HistoricalAccuracyAgent
```

Test:

```text
timeline consistency
anachronism
cause vs correlation
conflicting sources
character motivations
uncertainty
```

---

# 26. POP PSYCHOLOGY AGENTS

Verify:

```text
ViralQuestionAgent
PsychologyEvidenceAgent
RelatabilityAgent
PracticalAdviceAgent
HookAgent
EmotionalRelevanceAgent
OvergeneralizationGate
```

Test:

```text
unsupported gender claims
relationship stereotypes
overconfident advice
weak evidence
practical usefulness
relatability
```

---

# 27. PSYCHOLOGY & EVOLUTION AGENTS

Verify:

```text
EvolutionHypothesisAgent
EvidenceAgent
AlternativeExplanationAgent
CultureVsBiologyAgent
ModernMismatchAgent
OvergeneralizationGate
```

Every important explanation must consider where relevant:

```text
biology
culture
environment
development
individual differences
```

Do not reduce every behavior to adaptation.

---

# 28. PROCESS 8 — CONTENT BRIEF

Audit:

```text
question
thesis
audience
angle
concepts
required evidence
counterargument
forbidden claims
forbidden repetitions
duration target
strategy version
```

Hard gate:

```text
question != thesis
```

Thesis must be a defensible response to the question.

Target duration:

```text
25–30 minutes
```

must be present here or inherited from approved channel defaults.

---

# 29. PROCESS 9 — INTERNET RESEARCH

Internet research must be a distinct controlled process.

Do not simply send one vague search query.

Implement/test roles equivalent to:

```text
SearchPlannerAgent
SearchQueryAgent
SearchResultEvaluator
SourceQualityReviewer
ClaimExtractor
ContradictionFinder
SearchCoverageReviewer
```

Use existing web/search connector architecture if present.

Do NOT hard-code a specific provider into domain logic.

---

# 30. SEARCH PLANNER

Input:

```text
ContentBrief
Thesis
Knowledge gaps
Channel evidence policy
Existing internal evidence
```

Output:

```text
research questions
missing evidence roles
search concepts
search priorities
stop criteria
```

---

# 31. SEARCH QUERY AGENT

For each research question produce multiple query forms:

```text
broad discovery
exact concept
synonyms
academic terminology
counterevidence
alternative explanation
recent evidence
primary source query
```

Do not run only one phrasing.

---

# 32. SEARCH TERM LOGIC REVIEW

Before executing search, a logic agent/reviewer must inspect:

```text
Are the concepts correct?
Are synonyms missing?
Is the query too broad?
Is it leading/biasing the result?
Does it assume the thesis is true?
Do we need a falsification query?
Do we need a primary-source query?
```

At least one query per important claim should try to disconfirm or qualify the thesis.

---

# 33. SEARCH RESULT EVALUATION

For every result evaluate:

```text
relevance
source type
source quality
publication date
author/organization
primary vs secondary
claim supported
limitations
possible bias
duplicate/syndicated content
```

Do not accept search ranking as evidence quality.

---

# 34. SOURCE QUALITY

Channel-specific standards apply.

Examples:

Science:

```text
peer-reviewed research
official scientific institutions
primary papers
high-quality reviews
```

History:

```text
primary historical records where available
academic historians
museum/archive/university sources
credible secondary histories
```

Psychology:

```text
peer-reviewed research
systematic reviews
professional guidance
credible clinical/academic sources
```

Do not ban high-quality journalism entirely; classify its evidence role correctly.

---

# 35. INTERNET SEARCH CONTRADICTION LOOP

For every major thesis claim:

```text
support search
↓
counterevidence search
↓
alternative explanation search
↓
source conflict review
```

Do not stop after finding one supportive source.

---

# 36. SEARCH COVERAGE GATE

Internet research is READY only when the SearchCoverageReviewer confirms:

```text
major claims have evidence
important counterevidence searched
important alternatives searched
source diversity sufficient
critical gaps explicit
```

If not:

```text
generate next search round
```

Maximum:

```text
3 search rounds
```

After that:

```text
mark unresolved gaps
```

Do not invent certainty.

---

# 37. PROCESS 10 — EVIDENCE MATRIX

Audit claim-by-claim:

```text
Claim
Supporting Evidence
Counterevidence
Alternative Explanation
Source Quality
Epistemic Status
Limitations
Allowed Wording
Forbidden Wording
```

Every major script claim must trace to this layer.

Test deliberate conflicts.

---

# 38. PROCESS 11 — ARGUMENT PLAN

Argument must be logical structure, not prose.

Test:

```text
claim order
dependency
evidence placement
counterargument
response
story role
transition
consequence
```

Critique:

```text
circular argument
unsupported leap
repetition
weak counterargument
evidence not matching claim
```

---

# 39. PROCESS 12 — NARRATIVE PLAN

Narrative must be distinct from Argument.

Test audience experience:

```text
opening
question/tension
first understanding
evidence
surprise/contrast
story
deeper layer
counterargument
return
ending
```

Critique:

```text
boring opening
too much exposition
story inserted randomly
repetitive beats
no tension
weak ending
```

---

# 40. PROCESS 13 — SEMANTIC MASTER

Audit that it freezes:

```text
question
thesis
strategy
research package
evidence constraints
argument
narrative
duration target
uncertainty
forbidden claims
```

It must NOT regenerate argument/narrative.

It is the contract for the writer.

---

# 41. PROCESS 14 — SCRIPT WRITING

ScriptWriter sees ONLY bounded approved inputs.

Hard deny:

```text
whole Knowledge Base
whole corpus
all old scripts
raw search dump
unfiltered web pages
```

Allowed:

```text
ChannelStrategy
ContentBrief
EvidenceMatrix
Frozen ResearchPackage
ArgumentPlan
NarrativePlan
Semantic Master
revision constraints
```

---

# 42. SCRIPT 25–30 MINUTE GATE

Every draft receives:

```text
word_count
estimated_duration
```

If outside target:

```text
RevisionAgent
```

must revise.

Critique quality after duration correction.

Do not allow:

```text
filler
repeated conclusions
duplicate examples
unnecessary summaries
```

simply to reach 25 minutes.

---

# 43. PROCESS 15 — CRITIC LOOP

Run independent critics:

```text
FactCritic
LogicCritic
ChannelSpecificCritic
RetentionCritic
OriginalityCritic
LanguageQualityCritic
DurationCritic
```

Critics return findings.

They do NOT silently rewrite.

---

# 44. REVIEW SEVERITY

Normalize:

```text
INFO
MINOR
MAJOR
BLOCKING
```

Approval gate:

```text
no unresolved BLOCKING
no unresolved MAJOR unless explicitly owner-overridden
```

Do not mark Review complete merely because critics ran.

---

# 45. REVISION LOOP

For each draft:

```text
Script V1
↓
Critics
↓
Revision Plan
↓
Script V2
↓
Re-run affected critics
```

Maximum normal automatic rounds:

```text
3
```

If blocking findings remain:

```text
OWNER REVIEW REQUIRED
```

Do not loop endlessly.

---

# 46. PROCESS 16 — TRANSLATIONS

Test each language independently.

Do NOT mark all language boxes complete when one translation succeeds.

Example:

```text
Persian      APPROVED
German       READY_FOR_REVIEW
English      NOT_STARTED
Arabic       FAILED
```

must remain exactly separate.

---

# 47. TRANSLATION QUALITY

For each language test:

```text
meaning fidelity
terminology
names
quotes
citations/references
tone
channel voice
native phrasing
duration
```

Do not translate word-for-word if it destroys natural language.

Do not change factual meaning.

---

# 48. TRANSLATION AGENTS

Where applicable use roles equivalent to:

```text
TranslatorAgent
TerminologyConsistencyAgent
NativeLanguageReviewer
MeaningFidelityReviewer
DurationReviewer
```

Each language result has independent validation.

---

# 49. PROCESS 17 — PUBLICATION PREPARATION

Audit:

```text
approved script
approved translation
publication target
title
description
metadata
voice/video readiness
```

If direct publishing is not connected:

```text
show NOT_CONNECTED
```

Do not simulate publication.

---

# 50. COMPLETE CROSS-CHANNEL TEST MATRIX

For each of the five EditorialChannels test at least:

```text
2 resource sets
10 topic candidates
1 selected topic
1 ContentBrief
1 research plan
1 internet-research cycle
1 EvidenceMatrix
1 ArgumentPlan
1 NarrativePlan
1 25–30 min script
critic cycle
at least one translation
```

If live provider cost/quota makes all five full runs impractical:

use:

```text
2 real full runs
+
deterministic fixture/mocked provider coverage for remaining channels
```

but still test channel-specific constraints.

Document which were real and which were deterministic.

---

# 51. ADVERSARIAL TOPIC TESTS

Inject cases:

```text
high curiosity / zero evidence
wrong channel
duplicate previous thesis
same story reused
unsupported sensational claim
overly broad question
too narrow question
science/philosophy conflation
historical anachronism
gender stereotype
evolutionary just-so story
```

Verify rejection/replan behavior.

---

# 52. ADVERSARIAL RESEARCH TESTS

Test:

```text
SEO spam result
low-quality blog
duplicate syndicated article
old outdated source
source contradicting thesis
source with unclear author
paper abstract with overclaimed conclusion
```

SearchResultEvaluator must classify appropriately.

---

# 53. COST / LATENCY AUDIT

For every LLM/search stage record:

```text
provider
model
duration
tokens
cost if available
retry count
status
```

Critique:

```text
unnecessary repeated LLM calls
same artifact regenerated needlessly
search repeated without new gap
sequential calls that can safely batch
oversized prompts
```

Optimize without weakening quality.

---

# 54. DO NOT REMOVE NECESSARY INDEPENDENCE

Some checks should remain independent even if batching could reduce cost.

Keep independent where conflict of interest matters:

```text
writer vs FactCritic
writer vs OriginalityCritic
science claim generation vs Epistemic reviewer
```

Do not let the same single response create and self-certify every artifact.

---

# 55. PROCESS AUDIT TABLE

Maintain:

```text
docs/audits/FULL_PROCESS_OPTIMIZATION.md
```

For each process:

```text
Process
Baseline
Defects found
Critique
Fixes
Tests
Real-data result
Adversarial result
Latency/cost
Remaining issues
Status
Loop count
```

---

# 56. UI AUDIT STARTS ONLY AFTER BACKEND PROCESS AUDIT

Do NOT redesign UI while core stage behavior is still wrong.

First complete the process loops.

Then audit UI.

---

# 57. UI CRITIQUE LOOP

Use the same loop:

```text
inspect
→ perform owner journey
→ identify confusion
→ classify severity
→ fix
→ retest
→ screenshot
→ critique again
```

Maximum 3 UI loops.

---

# 58. UI MUST SHOW TRUE INDEPENDENT STAGE STATES

This specifically addresses the "all boxes become checked" problem.

Create regression tests using a partially complete production.

Example persisted state:

```text
Brief        READY
Research     READY
Evidence     READY
Argument     NOT_STARTED
Narrative    NOT_STARTED
Master       NOT_STARTED
Script       NOT_STARTED
Review       NOT_STARTED
Translations NOT_STARTED
```

UI must display exactly that.

No inferred downstream completion.

---

# 59. UI STAGE TEST 2

Example:

```text
Script       READY
Review       REVIEW_REQUIRED
Approval     NOT_STARTED
Persian      NOT_STARTED
German       NOT_STARTED
English      NOT_STARTED
```

UI must not show:

```text
Approved ✓
Translations ✓
```

---

# 60. UI TRANSLATION TEST

Example:

```text
Persian   APPROVED
German    READY
English   FAILED
Arabic    NOT_STARTED
```

Each language card must show its own state.

No shared "Translations complete" check until configured required languages satisfy completion policy.

---

# 61. UI TOPIC CREATION MUST BE SEPARATE

The UI must clearly distinguish:

```text
Themen generieren
```

from:

```text
Produktion starten
```

Topic generation must not automatically create:

```text
Brief
Research
Evidence
Script
```

unless the owner explicitly starts production.

Add regression test.

---

# 62. UI INTERNET RESEARCH VISIBILITY

In Production > Research show:

```text
Internal Knowledge
Internet Research
```

separately.

Internet research panel should show:

```text
research question
search rounds
queries used
sources considered
sources accepted
sources rejected
counterevidence
gaps
```

Do not expose raw provider internals by default.

---

# 63. UI EVIDENCE TRANSPARENCY

For each important claim owner can inspect:

```text
what supports it
what challenges it
source quality
epistemic status
allowed wording
```

This is required especially for Science, Psychology and History channels.

---

# 64. UI DURATION

Production header should show:

```text
Target: 25–30 min
Estimated current: 27.1 min
```

For translations:

```text
Persian: 26.8 min
German: 28.3 min
English: 25.9 min
```

Use real estimations.

---

# 65. UI ERROR BEHAVIOR

No raw:

```text
JSON
stack traces
provider enum codes
Python repr
```

as main UI copy.

Human-readable first.

Technical details collapsible.

---

# 66. OWNER JOURNEY TEST

Perform without developer knowledge:

```text
Dashboard
→ YouTube Channels
→ Check new videos
→ Import
→ inspect Vortragsstruktur
→ assign channel
→ generate topic suggestions
→ select topic
→ start production
→ brief
→ internet/internal research
→ evidence
→ argument
→ narrative
→ 25–30 min script
→ critics
→ approve
→ translations
```

Record every point where the next action is unclear.

Fix high/medium severity confusion.

---

# 67. "ONE PRIMARY ACTION" RULE

On each stage screen, identify one obvious primary next action.

Examples:

```text
Recherche starten
Evidence Matrix erstellen
Argument erstellen
Narrativ erstellen
Skript erstellen
Review starten
Freigeben
Übersetzungen erstellen
```

Do not present 8 equally prominent buttons.

---

# 68. REAL-DATA TEST SET

Use the existing real acceptance corpus where possible.

Also add:

```text
one new book/PDF
one new YouTube source
```

to verify new-resource flow after all optimizations.

Do not delete historical data.

---

# 69. TEST PYRAMID

For every process use:

```text
unit
service
integration
state-transition
real-data
adversarial
UI route
```

as applicable.

Do not rely solely on snapshots/screenshots.

---

# 70. FULL REGRESSION SUITE

At the end run:

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run mypy --strict app
uv run pytest tests/unit -q
```

Run all deterministic integration suites.

Known external/provider tests must be reported separately.

Do not call the suite fully green if external failures remain.

---

# 71. LOOP CONTROLLER DOCUMENT

Create:

```text
docs/audits/PROCESS_OPTIMIZATION_LOOP.md
```

Record each iteration:

```text
Loop #
Process
Problem
Hypothesis
Change
Tests
Result
Decision
```

This prevents circular/random optimization.

---

# 72. NO COMMIT DURING LOOPS

Do not commit each small loop.

Keep a clean audit trail in documentation.

After all accepted loops:

```text
stop
report
owner review
```

Only then commit if explicitly instructed.

---

# 73. FINAL QUALITY GATES

The system is READY only when all are true:

```text
✓ Resource import reliable
✓ YouTube monitoring reliable
✓ Vortragsstruktur meaningful
✓ Stories/cases preserved
✓ Knowledge Units coherent
✓ Concept precision acceptable
✓ Retrieval grounded
✓ Topic proposals channel-specific
✓ Topic proposals evidence-backed
✓ Topic creation separated from production
✓ Internet search planned logically
✓ Search terminology reviewed
✓ Counterevidence actively searched
✓ Search results quality-reviewed
✓ Evidence Matrix transparent
✓ Argument logically valid
✓ Narrative distinct from argument
✓ Semantic Master frozen correctly
✓ Script grounded
✓ Script duration 25–30 min
✓ Critics independent
✓ Revision loop controlled
✓ Owner approval explicit
✓ Translations independent by language
✓ Translation duration acceptable
✓ UI states match DB exactly
✓ No bulk auto-checking of stages
✓ No fake completion
✓ No dead UI actions
✓ No critical/major defect remains
```

---

# 74. FINAL CRITIQUE

After all tests pass:

Do NOT immediately declare success.

Perform one final system critique.

Ask explicitly:

```text
Where can the system still hallucinate?
Where can weak evidence pass?
Where can channel identity drift?
Where can duplicate topics appear?
Where can one stage incorrectly advance another?
Where can internet search confirm its own bias?
Where can duration optimization add filler?
Where can translation change meaning?
Where can UI mislead the owner?
Where are costs/latency unnecessarily high?
```

Document answers.

If any answer reveals a major defect:

```text
run another targeted loop
```

within the maximum-loop rule.

---

# 75. FINAL UI CRITIQUE

After backend critique:

review screenshots and owner journey.

Critique:

```text
discoverability
navigation
channel context
stage context
next action clarity
error clarity
translation clarity
duration visibility
research transparency
evidence transparency
```

Fix remaining major/medium UX defects.

---

# 76. FINAL REPORT

Report exactly:

```text
1. Processes audited
2. Loop count per process
3. Defects found
4. Defects fixed
5. Remaining blockers
6. Topic-generation quality per channel
7. Agent-pack verification per channel
8. Internet-search logic result
9. Search-result quality result
10. Evidence quality
11. Argument quality
12. Narrative quality
13. Script quality
14. 25–30 minute duration compliance
15. Critic/revision behavior
16. Translation results per language
17. State-transition correctness
18. "all boxes checked" regression result
19. Real-data owner journey
20. UI critique/fixes
21. Cost/latency findings
22. Unit tests
23. Integration tests
24. Real-data tests
25. Adversarial tests
26. Known environmental/provider issues
27. Recommendation:
    READY
    READY WITH ISSUES
    NOT READY
28. git diff --stat
29. git status
```

Do not commit.

STOP for owner review.

---

# 77. FINAL PRINCIPLE

The goal is not:

```text
make every checkbox green
```

The goal is:

```text
make every checkbox truthful
```

Every green stage must correspond to a real, validated, persisted artifact.

The complete production system must behave as:

```text
KNOWLEDGE
→ GOOD QUESTION
→ GOOD RESEARCH
→ GOOD EVIDENCE
→ LOGICAL ARGUMENT
→ STRONG NARRATIVE
→ GROUNDED 25–30 MINUTE SCRIPT
→ INDEPENDENT REVIEW
→ OWNER APPROVAL
→ INDEPENDENT LANGUAGE TRACKS
```

And this must work differently and correctly for each of the five EditorialChannels.

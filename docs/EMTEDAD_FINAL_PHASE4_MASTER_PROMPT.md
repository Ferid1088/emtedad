# EMTEDAD — FINAL PHASE 4 MASTER PROMPT
# REAL SEMANTIC QUALITY + PROVIDER CAPACITY + NATURAL BOOK REFERENCES
# MANDATORY LOOP-BASED EXECUTION

Continue from the CURRENT UNCOMMITTED working tree.

Do NOT commit.
Do NOT push.
Do NOT redesign the existing architecture.
Preserve all validated Phase 1–3 truthfulness mechanisms.

The goal of this phase is to prove that Emtedad does not only show truthful states, but also produces consistently high-quality, well-researched, channel-specific, 25–30 minute scripts.

A new editorial requirement also applies:

> Final Persian scripts may naturally reference real non-Persian books and authors when useful.

Examples:

    «ساپولسکی در کتاب Behave توضیح می‌دهد که ...»

    «در کتابِ ... می‌خوانیم که ...»

    «به گفتهٔ ...»

    «... در کتابِ ... استدلال می‌کند که ...»

    «در بخشی از کتابِ ... به این موضوع اشاره می‌شود.»

    «در کتابِ ... این ادعا مطرح می‌شود، اما ...»

These references should feel natural, varied, and editorially useful.

Do NOT over-engineer this requirement.
Do NOT require exact page-level provenance for every normal paraphrase.
Do NOT force a rigid citation system into spoken scripts.

However:

    the book must be real
    the author/title attribution must be plausible and supported
    Persian-language books must NOT be used for these explicit book references
    direct quotes must not be invented
    criticism/uncertainty must be worded appropriately

---

# 0. UNIVERSAL LOOP RULE

EVERY process in this task MUST run through a loop.

For semantic/content/UI quality, one successful pass is NOT enough.

Minimum:

    LOOP 1
        inspect
        baseline
        test
        critique
        root cause
        fix/optimize
        re-test
        adversarial test
        real-data test
        re-critique
        decision

    LOOP 2
        run again on different data
        re-test
        re-critique
        decision

Maximum:

    3 loops per process

Possible status:

    PASS
    PASS WITH NOTES
    BLOCKED
    NOT AUDITED

Never mark PASS merely because tests are green.

---

# 1. PROVIDER CAPACITY / STARVATION LOOP

Current issue:

    background processing can consume all provider sessions
    interactive owner actions can become blocked
    many retrying sources create backlog pressure

Inspect:

    provider session acquisition
    background concurrency
    interactive concurrency
    retry behavior
    quota behavior
    session cleanup
    duplicate retries

Introduce the smallest provider-agnostic capacity policy needed.

Conceptually:

    provider_max_concurrency
    provider_background_max_concurrency
    provider_interactive_reserved_slots
    provider_retry_backoff
    provider_retry_max_attempts

Priority:

    INTERACTIVE_OWNER
        >
    OWNER_REQUESTED_PROCESSING
        >
    BACKGROUND_NEW
        >
    BACKGROUND_RETRY

Do NOT add a new queue architecture.

LOOP 1:
    measure current behavior
    reproduce starvation
    fix
    retest

LOOP 2:
    backlog present
    run interactive topic generation + review
    verify owner actions still obtain capacity
    verify no leaks / duplicate retries

PASS only after both loops.

---

# 2. RETRY-STORM LOOP

Audit retrying sources.

Ensure:

    no duplicate simultaneous retry for same source
    quota exhaustion does not burn attempts aggressively
    retry uses bounded backoff
    malformed permanent failures stop retrying
    quota/transient failures remain retryable
    successful processing clears retry state

Run 2 loops.

---

# 3. REVIEWRUN AUTHORITY LOOP

Current review truthfulness must remain correct.

The newest review attempt for the exact:

    draft_id
    draft_version
    draft_hash

is authoritative.

Test:

    clean COMPLETED → newer RUNNING
        => IN_REVIEW

    clean COMPLETED → newer FAILED
        => FAILED / REVIEW_REQUIRED

    old findings → newer clean COMPLETED
        => newer run governs

    old clean review → script hash changes
        => review invalid / review again required

Concurrent duplicate RUNNING reviews for same exact draft state must be prevented.

Run 2 loops.

---

# 4. LEGACY REVIEW FINDINGS LOOP

Legacy unscoped findings remain historical.

Modern ReviewRun state must not be corrupted by unscoped old rows.

If a modern current-hash ReviewRun exists:

    only findings from that run determine current review gate

Legacy rows remain visible as history.

Run 2 loops.

---

# 5. SOURCE QUALITY RANKING LOOP

Current source-quality classification should influence actual research selection.

Evaluate:

    relevance
    scholarly/institutional quality
    source type
    primary/secondary role
    recency relevance
    evidence strength
    transparency
    duplication
    bias risk

Do not blindly prefer prestigious domains over relevant evidence.

Test:

    highly relevant peer-reviewed source
    weakly relevant peer-reviewed source
    relevant official source
    reputable journalism
    weak blog
    SEO content farm
    affiliate page
    syndicated duplicate
    primary historical source
    academic history source

LOOP 1:
    integrate source-quality signal into ranking/selection

LOOP 2:
    run different real research queries
    inspect accepted/rejected ordering

PASS only if ranking improves actual evidence selection.

---

# 6. TOPIC GENERATION — FIVE CHANNEL LOOPS

For EACH EditorialChannel:

    Emtedad
    Science & Mystery
    History & Human Stories
    Pop Psychology & Relationships
    Psychology & Evolution

Generate at least:

    10 TopicCandidates

where provider access permits.

Each candidate must include:

    Video Question
    Tentative Thesis
    Angle
    Channel Fit
    Knowledge Coverage
    Novelty
    Curiosity
    Emotional Relevance
    Practical Value
    supporting KnowledgeUnits
    supporting Concepts
    supporting Sources
    knowledge gaps
    ScriptSignature overlap

Topic creation remains separate from production.

Generating topics must NOT automatically create:

    ContentBrief
    ResearchPlan
    EvidenceMatrix
    ArgumentPlan
    NarrativePlan
    Master
    Script

---

# 7. TOPIC LOOP 1

For each channel:

    generate
    inspect
    critique

Look for:

    duplicate questions
    same thesis with different wording
    vague/general questions
    wrong channel
    low evidence
    repeated story
    clickbait
    low novelty

Find root cause:

    retrieval
    prompt
    strategy
    scoring
    distinctiveness
    grounding

Fix only the root cause.

---

# 8. TOPIC LOOP 2

Generate from a different source set / knowledge subset.

Re-critique independently.

PASS only if the channel consistently produces:

    grounded
    diverse
    useful
    channel-specific
    production-worthy questions

---

# 9. TOPIC ADVERSARIAL LOOP

Test:

    high curiosity + zero evidence
    strong evidence + wrong channel
    same thesis, different wording
    repeated STORY
    duplicate ScriptSignature
    sensational unsupported claim
    overly broad question
    overly narrow question
    source supports concept but not thesis

Channel-specific:

SCIENCE:
    speculation presented as fact
    philosophy framed as science

HISTORY:
    anachronism
    false causality

POP PSYCHOLOGY:
    gender stereotype
    unsupported relationship myth

PSYCHOLOGY & EVOLUTION:
    just-so evolutionary explanation

EMTEDAD:
    empty philosophy
    pseudo-scientific framing

Expected:

    reject
    score down
    replan
    or REVIEW_REQUIRED

Never production-ready by accident.

Run 2 loops.

---

# 10. CROSS-CHANNEL DIFFERENTIATION LOOP

Use the SAME real source across all five channels.

Compare:

    question
    thesis
    angle
    audience framing
    evidence expectation
    narrative potential

If two channels produce essentially the same video:

    fix distinctiveness/channel strategy

If they use the same knowledge from legitimately different editorial angles:

    acceptable

Run 2 shared-source tests.

---

# 11. CHANNEL AGENT-PACK QUALITY LOOPS

Do not only verify that agent-profile names load.

Verify behavioral effect.

## EMTEDAD

Test:

    human patterns
    continuity
    awareness
    meaning
    change
    counterargument

Adversarial:

    generic motivation
    unsupported science
    empty philosophy

## SCIENCE & MYSTERY

Test:

    ESTABLISHED_SCIENCE
    STRONG_EVIDENCE
    LIMITED_EVIDENCE
    HYPOTHESIS
    CONTESTED
    OPEN_QUESTION
    SPECULATION
    PHILOSOPHICAL_INTERPRETATION
    UNKNOWN

Ensure:

    philosophy != proof
    hypothesis != fact
    UNKNOWN != strong evidence

## HISTORY

Test:

    timeline conflict
    cause vs correlation
    conflicting sources
    invented motivation
    anachronism

## POP PSYCHOLOGY

Test:

    gender stereotype
    overconfident advice
    pathologizing normal behavior
    weak-source viral claim

## PSYCHOLOGY & EVOLUTION

Test:

    biology-only explanations
    culture ignored
    environment ignored
    development ignored
    individual differences ignored
    adaptation without evidence

Minimum 2 semantic loops/channel.

---

# 12. RESEARCH PLAN LOOP

For a selected topic verify ResearchPlan separates:

    what internal knowledge already supports
    what is missing
    what requires Internet research
    what needs contradiction/falsification search
    what needs source-quality verification

Do not search the web merely because web search exists.

Run 2 loops on different topics.

---

# 13. INTERNET SEARCH PLANNING LOOP

Use responsibilities equivalent to:

    SearchPlanner
    SearchQueryGenerator
    SearchTermLogicReviewer
    SearchResultEvaluator
    SourceQualityReviewer
    ContradictionFinder
    CoverageReviewer

They may be combined efficiently.

Do NOT force unnecessary agent calls.

For major research questions generate where relevant:

    discovery query
    exact terminology
    synonyms
    academic query
    primary-source query
    falsification query
    alternative-explanation query
    recent-evidence query

Run 2 loops.

---

# 14. SEARCH QUERY LOGIC LOOP

Before executing searches ask:

    Is the query leading?
    Does it assume thesis truth?
    Are synonyms missing?
    Is terminology correct?
    Too broad?
    Too narrow?
    Need falsification query?
    Need primary-source query?

At least one search strategy per major claim must try to:

    disconfirm
    qualify
    or provide an alternative explanation

Run 2 loops.

---

# 15. SEARCH RESULT QUALITY LOOP

Evaluate actual results for:

    relevance
    source type
    author/institution
    primary vs secondary
    date
    methodology/evidence
    limitations
    bias risk
    duplication
    actual claim support

Test adversarial sources:

    SEO spam
    content farm
    AI-slop
    affiliate content
    syndicated duplicate
    outdated evidence
    unclear-author page
    press release overstating a study
    source contradicting thesis

Run 2 loops.

---

# 16. COUNTEREVIDENCE LOOP

For every major claim:

    support search
    ↓
    counterevidence search
    ↓
    alternative explanation search
    ↓
    conflict review

Do not stop after supportive evidence.

Run 2 real topic loops.

---

# 17. SEARCH COVERAGE LOOP

Maximum 3 rounds per research plan.

After each round evaluate:

    major claim coverage
    counterevidence
    alternatives
    source diversity
    source quality
    remaining gaps

If gaps remain:

    targeted next search round

After round 3:

    persist unresolved gaps

Do not fabricate completeness.

---

# 18. BOOK / AUTHOR REFERENCE POLICY

Final Persian scripts MAY naturally mention real non-Persian books and authors.

Examples:

    «ساپولسکی در کتاب Behave توضیح می‌دهد که ...»

    «در کتابِ ... می‌خوانیم که ...»

    «به گفتهٔ ...»

    «نویسنده در کتابِ ... استدلال می‌کند که ...»

    «در بخشی از کتابِ ... به این موضوع اشاره می‌شود.»

    «در کتابِ ... این ادعا مطرح می‌شود، اما ...»

Use varied, natural Persian.

Do not repeat the same template.

---

# 19. BOOK RULES — PRACTICAL, NOT OVERLY STRICT

A book reference is allowed when:

    the book is real
    the author/title are correct
    the book is not Persian-language
    the attribution is reasonably supported by:
        imported book knowledge
        existing KnowledgeUnits
        ResearchPackage
        EvidenceMatrix
        or reliable Internet research

For normal paraphrases:

    exact page number is NOT mandatory
    exact source span is NOT mandatory
    a full bibliographic verification workflow is NOT mandatory

Do NOT over-engineer the writer.

The goal is natural intellectual attribution, not academic footnoting.

---

# 20. NON-PERSIAN BOOK HARD RULE

Explicit book references in final scripts must NOT come from Persian-language books.

Reject source-language equivalents:

    fa
    fas
    per
    Persian
    Farsi

Other languages are allowed.

Examples:

    English
    German
    French
    Arabic
    Spanish
    Italian
    etc.

Do not delete Persian books from the Knowledge Base.

They simply should not be used for this explicit spoken-book-reference feature.

---

# 21. BOOK ATTRIBUTION FROM KNOWLEDGE / RESEARCH

The writer should prefer references already supported by:

    KnowledgeUnits
    EvidenceMatrix
    Frozen ResearchPackage
    verified research results

The writer may NOT invent a famous book merely because it sounds good.

If the source data says:

    Robert Sapolsky
    Behave
    relevant concept/argument

then a line such as:

    «ساپولسکی در کتاب Behave توضیح می‌دهد که ...»

is acceptable when the paraphrase fairly represents the idea.

No need to force page-level proof unless required by context.

---

# 22. DIRECT QUOTES ARE DIFFERENT

Be stricter only for direct quotations.

If the script uses quotation marks:

    «...»

the wording must be actually verified.

If exact wording is not available:

    use paraphrase
    do not use quotation marks

Example:

GOOD:
    «ساپولسکی در Behave توضیح می‌دهد که ...»

NOT GOOD:
    «ساپولسکی می‌گوید: "exact sentence invented from memory"»

---

# 23. CRITICAL / DISTANCING LANGUAGE

When the script does not endorse the book's claim, use suitable Persian wording:

    ادعا می‌کند
    استدلال می‌کند
    پیشنهاد می‌کند
    این برداشت را مطرح می‌کند
    چنین نتیجه می‌گیرد

Examples:

    «در کتابِ ... نویسنده ادعا می‌کند که ...»

    «این برداشت در کتابِ ... مطرح می‌شود؛ با این حال ...»

    «نویسنده چنین استدلال می‌کند، اما شواهد دیگری ...»

Do not turn:

    "a book says X"

into:

    "science proves X"

---

# 24. BOOK-REFERENCE PLANNER

Before writing, optionally select a small set of useful book references.

Do not force a minimum.

A 25–30 minute script may have:

    0
    1
    2
    or several

book references.

Use them only when they improve:

    context
    authority
    contrast
    criticism
    explanation
    intellectual texture

Do not decorate every section with book names.

---

# 25. BOOK REFERENCE LOOP 1

Take one real non-Persian book already present or imported.

Identify several plausible ideas/claims.

Generate a test script section using natural Persian references.

Critique:

    correct book?
    correct author?
    correct idea?
    natural Persian?
    repetitive wording?
    overclaim?
    book treated as proof?

Fix root cause and rerun.

---

# 26. BOOK REFERENCE LOOP 2

Use a different non-Persian book.

Include adversarial cases:

    wrong author
    wrong book
    unsupported claim
    Persian-language book
    famous quote remembered by model but not verified
    paraphrase stronger than source
    critical claim presented as fact

Expected:

    wrong/unsupported references removed or corrected

PASS only after two successful loops.

---

# 27. EVIDENCE MATRIX SEMANTIC QUALITY LOOP

Structural validation already exists.

Now inspect semantic quality.

For real matrices evaluate:

    Does evidence really support the claim?
    Is counterevidence meaningful?
    Are alternatives real?
    Is epistemic status correct?
    Are limitations useful?
    Is allowed wording appropriate?
    Is forbidden wording useful?

Run 2 loops on different topics.

---

# 28. ARGUMENT QUALITY LOOP

Evaluate real ArgumentPlans for:

    logical progression
    evidence fit
    causality
    thesis support
    counterargument strength
    response quality
    redundancy
    transitions
    conclusion

Adversarial:

    circular reasoning
    correlation → causation
    strawman
    unsupported jump
    contradictory premises

Run 2 loops.

---

# 29. NARRATIVE QUALITY LOOP

Evaluate:

    opening
    tension
    curiosity
    pacing
    story placement
    information density
    emotional rhythm
    contrast/surprise
    ending

Reject:

    generic intro
    random story insertion
    information dump
    repeated emotional beat
    weak summary ending

Run 2 loops.

---

# 30. SEMANTIC MASTER LOOP

Verify it freezes:

    question
    thesis
    strategy version
    ResearchPackage
    EvidenceMatrix
    ArgumentPlan
    NarrativePlan
    duration target
    uncertainty constraints
    forbidden claims
    selected useful book references where applicable

It must not regenerate earlier stages.

Run 2 loops.

---

# 31. SCRIPT QUALITY LOOP

Generate at least:

    2 real full scripts

Prefer different channel families.

Target:

    25–30 minutes
    planning target 27.5

Evaluate:

    factual grounding
    logic
    narrative
    channel identity
    natural spoken language
    epistemic honesty
    book-reference naturalness
    repetition
    transitions
    hooks
    ending
    filler
    estimated duration

Do not judge quality only from word count.

---

# 32. DURATION REVISION LOOP

Test:

    too-short draft
    in-target draft
    too-long draft

Too short:

allow:
    deeper useful explanation
    evidence context
    relevant story depth
    counterargument depth
    useful transitions

reject:
    filler
    repeated conclusions
    empty summaries

Too long:

preserve:
    evidence
    limitations
    argument integrity
    essential stories
    counterarguments

Run 2 loops.

---

# 33. REVIEW / REVISION LIVE LOOP

Real lifecycle:

    Script V1
    → ReviewRun 1
    → Findings
    → Revision
    → Script V2
    → ReviewRun 2

Evaluate actual improvement.

Check:

    findings scoped correctly
    stale findings do not leak
    exact hash association
    latest run authority
    book-reference errors caught where relevant
    duration issues caught

If needed:

    V3 / ReviewRun 3

Maximum automatic revision rounds remain 3.

---

# 34. TRANSLATION DURATION LOOP

Each language independent.

Calculate:

    word count
    configured WPM
    estimated minutes
    TOO_SHORT / IN_TARGET / TOO_LONG

Target:

    25–30 minutes

Current known issue:

    Persian can be too short
    German can be too long

Do not merely display the problem.

Actively improve it.

---

# 35. PERSIAN TRANSLATION LOOP

Take a real approved master.

Translate/adapt to Persian.

Check:

    meaning fidelity
    terminology
    natural Persian
    book-reference phrasing
    estimated duration

If too short:

expand only by expressing existing meaning more naturally or clearly.

Do not invent facts.

Re-run fidelity review.

Run 2 loops if correction is needed.

---

# 36. GERMAN TRANSLATION LOOP

For an overlong German translation:

compress toward 25–30 minutes while preserving:

    evidence
    limitations
    counterarguments
    thesis logic
    important stories

Re-run fidelity review.

Run 2 loops.

---

# 37. ENGLISH / ARABIC TRANSLATION LOOPS

Where configured/provider available:

    translate
    critique
    duration adjust
    fidelity re-check

No shared "all translations complete" state.

---

# 38. BOOK/PDF COMPLETE REAL LOOP

Use one real PDF or Book/Text source.

Run full flow:

    import
    → SourceVersion
    → SourceSegments
    → Structure
    → KnowledgeUnits
    → Concepts
    → Retrieval
    → READY
    → TopicCandidates

Audit:

    page provenance
    heading hierarchy
    semantic units
    story/case preservation
    duplicate detection
    topic usefulness

Run 2 evaluations on different sections/sources where practical.

---

# 39. YOUTUBE REAL LOOP

Use one safe real or previously unaudited YouTube source.

Run:

    monitor/discover
    → candidate
    → import
    → transcript
    → structure
    → units
    → concepts
    → topics

Critique actual semantic output.

Do not only test HTTP success.

Run 2 loops where provider permits.

---

# 40. YOUTUBE BACKLOG LOOP

Classify retrying/failed sources.

For real failures determine:

    transcript unavailable
    malformed source
    provider quota
    transient provider issue
    validation failure
    implementation bug
    unsupported content

Permanent failures should not retry forever.

Transient/quota failures should remain retryable.

Run 2 loops.

---

# 41. TOKEN / COST LOOP

Inspect provider contracts.

If real usage metadata exists:

    input_tokens
    output_tokens
    total_tokens
    actual cost

persist it.

If unavailable:

    NULL

Do not invent values.

If Devin exposes no usage metadata:

    BLOCKED: PROVIDER_CONTRACT

One verification loop is enough if the API genuinely does not provide it.

---

# 42. PERFORMANCE LOOP

Measure:

    structure
    KnowledgeUnit extraction
    concept mapping
    topic mining
    search
    evidence
    argument
    narrative
    script
    critics
    translation

Record:

    duration
    provider calls
    retries
    tokens where available

Look for:

    duplicate calls
    identical regeneration
    unnecessary sequential calls
    oversized prompts
    repeated searches

Optimize only when quality remains intact.

Run 2 loops for any modified performance path.

---

# 43. FINAL STATE-MACHINE LOOP

Test at minimum:

CASE 1:
    Brief READY
    rest NOT_STARTED

CASE 2:
    Evidence DRAFT

CASE 3:
    Evidence READY
    Argument NOT_STARTED

CASE 4:
    Script READY
    Review NOT_STARTED

CASE 5:
    Review RUNNING

CASE 6:
    Review COMPLETED clean

CASE 7:
    Review COMPLETED with MAJOR

CASE 8:
    clean review then script hash changes

CASE 9:
    FA APPROVED
    DE READY
    EN FAILED
    AR NOT_STARTED

CASE 10:
    resource RETRYING

Compare:

    database state
    service/domain state
    UI state
    allowed actions

All must agree.

Run 2 loops if any mismatch is fixed.

---

# 44. FINAL UI LOOP 1

Perform owner journey:

    Dashboard
    → YouTube-Kanäle
    → check new videos
    → import
    → Resource
    → Structure
    → Topics
    → Production
    → Research
    → Evidence
    → Argument
    → Narrative
    → Master
    → Script
    → Review
    → Approval
    → Translations

At each screen critique:

    next action clarity
    truthful state
    errors
    channel context
    research transparency
    evidence transparency
    duration visibility
    book-reference clarity where relevant

Fix MAJOR/MEDIUM UX defects.

---

# 45. FINAL UI LOOP 2

Repeat with:

    another channel
    another resource
    partially complete production

Capture screenshots.

Critique from scratch.

Only after Loop 2 may UI PASS.

---

# 46. FINAL GLOBAL CRITIQUE LOOP 1

Ask:

    Where can weak evidence still pass?
    Where can search reinforce confirmation bias?
    Where can source quality be ignored?
    Where can channels converge too much?
    Where can book references be invented or overused?
    Where can duration adaptation create filler?
    Where can translation alter meaning?
    Where can background jobs starve owner actions?
    Where can retry storms occur?
    Where can UI still mislead the owner?

Fix MAJOR findings.

---

# 47. FINAL GLOBAL CRITIQUE LOOP 2

Repeat independently after fixes.

If a new MAJOR defect appears:

    targeted LOOP 3

Then stop.

---

# 48. FINAL ACCEPTANCE GATES

READY requires:

    ✓ provider background work cannot starve owner work
    ✓ retry storms prevented
    ✓ topic quality evaluated for all 5 channels
    ✓ topic diversity proven
    ✓ cross-channel differentiation proven
    ✓ agent-pack behavior tested
    ✓ Internet search logically planned
    ✓ counterevidence searched
    ✓ source quality affects real selection
    ✓ unresolved gaps remain explicit
    ✓ EvidenceMatrix semantically strong
    ✓ Argument quality evaluated twice
    ✓ Narrative quality evaluated twice
    ✓ Semantic Master stable
    ✓ at least 2 real script quality loops
    ✓ 25–30 minute target handled without filler
    ✓ natural book references work
    ✓ no Persian-language book used for explicit references
    ✓ no invented direct quotes
    ✓ book references are not overused
    ✓ ReviewRun → Revision → ReviewRun proven
    ✓ translation duration actively corrected
    ✓ fidelity survives duration correction
    ✓ Book/PDF full flow reaches topics
    ✓ YouTube full flow tested
    ✓ failed/retrying sources classified
    ✓ DB state = service state = UI state
    ✓ no false green checkboxes
    ✓ UI receives 2 critique loops
    ✓ final global critique receives 2 loops

Anything unproven remains:

    PASS WITH NOTES
    BLOCKED
    NOT AUDITED

---

# 49. TESTS

After each process loop run targeted tests.

At final:

    uv run ruff check app/ tests/
    uv run ruff format --check app/ tests/
    uv run mypy --strict app
    uv run pytest tests/unit -q

Then run complete deterministic integration suite.

Report deselected/provider-dependent tests exactly.

---

# 50. AUDIT DOCUMENTATION

Update:

    docs/audits/FULL_PROCESS_OPTIMIZATION.md
    docs/audits/PROCESS_OPTIMIZATION_LOOP.md

For every process document:

    Loop 1
    Loop 2
    Loop 3 if needed

with:

    baseline
    critique
    root cause
    change
    re-test
    re-critique
    decision

Do not write PASS without the required loops.

---

# 51. DO NOT COMMIT

Do not commit.
Do not push.

Stop for owner review.

---

# 52. FINAL REPORT

Report exactly:

    1. Provider capacity Loop 1
    2. Provider capacity Loop 2
    3. Retry-storm result
    4. Review authority result
    5. Source-quality ranking Loop 1
    6. Source-quality ranking Loop 2
    7. Topic count per channel
    8. Topic Loop 1 per channel
    9. Topic Loop 2 per channel
    10. Cross-channel differentiation
    11. Agent-pack loop results
    12. Research Plan loops
    13. Search planning loops
    14. Search-result quality loops
    15. Counterevidence result
    16. Search coverage result
    17. Book-reference Loop 1
    18. Book-reference Loop 2
    19. rejected Persian-book references
    20. direct-quote safety result
    21. natural Persian attribution result
    22. Evidence Loop 1
    23. Evidence Loop 2
    24. Argument Loop 1
    25. Argument Loop 2
    26. Narrative Loop 1
    27. Narrative Loop 2
    28. Semantic Master result
    29. Script Loop 1
    30. Script Loop 2
    31. 25–30 minute compliance
    32. Duration-revision result
    33. Review/revision live loop
    34. Persian translation
    35. German translation
    36. English/Arabic translation
    37. translation-duration compliance
    38. Book/PDF full acceptance
    39. YouTube full acceptance
    40. backlog classification
    41. token/cost availability
    42. performance findings
    43. state-machine matrix
    44. UI Loop 1
    45. UI Loop 2
    46. Global Critique Loop 1
    47. Global Critique Loop 2
    48. Loop 3 items if any
    49. unit tests
    50. integration tests
    51. excluded/provider-dependent tests
    52. remaining blockers
    53. recommendation:
        READY
        READY WITH ISSUES
        NOT READY
    54. loop count per process
    55. git diff --stat
    56. git status

STOP.

NO COMMIT.

---

# FINAL PRINCIPLE

Do not optimize toward more green checkboxes.

Optimize toward repeatable quality.

For semantic/content quality:

    first good result proves possibility

    second independent good result + critique proves repeatability

Only repeatable quality earns PASS.

For book references specifically:

    make the script sound naturally well-read,
    but do not invent books, authors, claims, or direct quotations.

Normal paraphrases do not require academic-level citation machinery.

The practical rules are:

    real book
    real author
    non-Persian source
    fair attribution
    no invented direct quote
    natural Persian wording

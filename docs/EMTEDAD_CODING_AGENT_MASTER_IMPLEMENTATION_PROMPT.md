# MASTER IMPLEMENTATION PROMPT — EMTEDAD STUDIO
## Multi-Channel Resource-First Knowledge-to-Content Engine

You are implementing the next architecture of the existing repository:

```text
Ferid1088/emtedad
```

This is an **existing application**, not a greenfield project.

Your job is to transform it from an Emtedad-specific / 100-Lesson-oriented production system into a **working multi-channel content-production studio** while preserving the parts that already work.

You must implement the system in the exact phased order below.

Do not redesign the product.
Do not invent a different architecture.
Do not create shortcuts that violate the data model or provenance rules.
Do not replace deterministic application services with LLM agents.
Do not delete legacy code before the replacement path works.

---

# 0. PRIMARY PRODUCT GOAL

Build a real working application that supports five separate editorial channels:

1. `Emtedad`
2. `Science & Mystery`
3. `History & Human Stories`
4. `Pop Psychology & Relationships`
5. `Psychology & Evolution`

All five channels must share one resource / knowledge infrastructure.

The final conceptual flow is:

```text
RESOURCES
    ↓
SOURCE STRUCTURE
    ↓
KNOWLEDGE UNITS
    ↓
SHARED KNOWLEDGE BASE
    ↓
EDITORIAL CHANNEL STRATEGY
    ↓
DYNAMIC VIDEO QUESTIONS
    ↓
CONTENT BRIEF
    ↓
THESIS
    ↓
RESEARCH
    ↓
EVIDENCE MATRIX
    ↓
ARGUMENT
    ↓
NARRATIVE
    ↓
SCRIPT
    ↓
CRITICS / REVISION
    ↓
OWNER APPROVAL
    ↓
LOCALIZATION
    ↓
VOICE / VIDEO / PUBLICATION
```

The first implementation priority is **not topic generation and not script generation**.

The first implementation priority is:

```text
YouTube import
→ transcript
→ Vortragsstruktur / hierarchical source structure
→ Knowledge Units
→ structure-aware retrieval
```

This must work correctly before the topic engine becomes the primary production entry point.

---

# 1. NON-NEGOTIABLE ARCHITECTURE RULES

These rules are mandatory.

## 1.1 Resources are primary

Topics and scripts are derived artifacts.

Never design the system around a pre-created list of 100 topics or 100 lessons.

---

## 1.2 Remove the 100-Lesson Canon from the active production path

The final architecture must not depend on:

```text
LessonCanonRepository
100 fixed lessons
lesson_canon_hash
lesson_id as the mandatory production origin
```

However:

**Do not delete those files first.**

The migration order is:

```text
build generic replacement
→ prove generic replacement
→ migrate active routes/services
→ preserve historical provenance
→ delete/retire legacy lesson path
```

---

## 1.3 Ayin remains a resource

Do not delete Ayin.

Ayin becomes a high-value foundational resource for the Emtedad editorial channel.

It is no longer the mandatory Canon for the whole platform.

---

## 1.4 One shared Knowledge Base

Do not create five duplicated knowledge databases.

Resources, source versions, source structures, Knowledge Units, concepts, embeddings and provenance are shared.

Channel-specific logic begins at:

```text
resource assignment
channel strategy
topic discovery
content production
```

---

## 1.5 Existing `knowledge.Channel` is NOT an editorial channel

The existing repository already uses `knowledge.Channel` for imported source channels such as YouTube channels.

Therefore the five content channels MUST use:

```text
EditorialChannel
```

Do not rename the existing source-channel model.

Do not overload it.

---

## 1.6 Editorial channel != publication language

Do not create 20 duplicated channel systems for:

```text
5 verticals × FA/DE/EN/AR
```

Use:

```text
EditorialChannel
```

for the content vertical.

Use:

```text
PublicationTarget
```

for platform/language targets later.

Example:

```text
EditorialChannel:
Science & Mystery

PublicationTargets:
YouTube FA
YouTube DE
YouTube EN
YouTube AR
```

---

## 1.7 Semantic boundaries are not token boundaries

Existing chunking may remain temporarily for compatibility and indexing.

But arbitrary token chunks must no longer be the writer-facing semantic unit.

The writer-facing unit is:

```text
KnowledgeUnit
```

---

## 1.8 Preserve stories

Stories, case studies and coherent examples must not be cut into arbitrary fragments.

For those units:

```text
atomic = true
```

When retrieval matches text inside an atomic story, return the complete Knowledge Unit.

---

## 1.9 Writer input firewall

The Script Writer must never receive:

```text
the complete Knowledge Base
hundreds of raw books
the entire transcript corpus
all previous scripts
an unfiltered retrieval dump
```

The writer may receive only:

```text
Active Channel Strategy
Content Brief
Locked Thesis
Evidence Matrix
Frozen ResearchPackage
Argument Plan
Narrative Plan
Revision constraints
```

---

## 1.10 Reuse knowledge, not narrative

Published history is used to detect repetition.

It must not become copy material for the next writer.

---

# 2. CURRENT REPOSITORY COMPONENTS TO KEEP

Do not rewrite these foundations unless required for integration.

Keep and reuse:

```text
app/knowledge/adapters/youtube.py
app/knowledge/importer.py
app/knowledge/models.py
app/knowledge/service.py
```

Preserve:

```text
Source
SourceVersion
SourceSegment
Creator
knowledge.Channel
ExternalClaim
Work
Person
ExternalConcept
SourceQuality
ReviewFlag
```

Preserve:

```text
content hashes
transcript hashes
timestamps
source provenance
source versions
extraction runs
review state
```

Keep and reuse:

```text
app/retrieval/*
```

including:

```text
PostgreSQL
pgvector
FTS
dense retrieval
entity retrieval
RRF / fusion
reranking
retrieval provenance
```

Keep the concepts:

```text
ResearchProject
ResearchPlan
Frozen ResearchPackage
LectureMasterVersion / semantic architecture
EditorialProject
Published memory
Localization
Pronunciation
Performance text
Owner approval
Versioning
Provenance
```

Generalize them instead of rebuilding them.

---

# 3. CURRENT REPOSITORY COMPONENTS TO RETIRE LATER

The following legacy path is no longer part of the final active architecture:

```text
app/content_strategy/lesson_canon.py
app/content_strategy/lesson_catalog.py
app/content_strategy/lesson_workflow.py
app/content_strategy/lesson_research.py
resources/editorial/lesson_canon/
```

Legacy lesson UI:

```text
app/web/templates/lessons.html
app/web/templates/lesson_detail.html
app/web/templates/lesson_concepts.html
```

Lesson-specific routes under:

```text
/lessons
```

must eventually be retired.

But DO NOT delete them until the generic replacement passes end-to-end tests.

---

# 4. DO NOT DELETE APPLIED ALEMBIC MIGRATIONS

Never delete old applied migration files.

Create new forward migrations.

Historical data must remain readable.

---

# 5. TARGET EDITORIAL CHANNELS

Seed exactly these five EditorialChannels.

## 5.1 Emtedad

```text
slug: emtedad
name: Emtedad
```

Focus:

```text
human patterns
continuity
relationships
identity
awareness
meaning
change
philosophy of lived experience
```

Special semantic roles:

```text
HumanProblemAgent
PatternAgent
PhilosophyAgent
CounterargumentAgent
MeaningAgent
EmtedadBoundaryReviewer
```

---

## 5.2 Science & Mystery

```text
slug: science-mystery
name: Science & Mystery
```

Focus:

```text
cosmology
consciousness
time
origin
reality
information
physics
mathematics
origin of life
science/philosophy boundary
```

Special agents/checks:

```text
ScientificEvidenceAgent
EpistemicStatusAgent
AlternativeExplanationAgent
PhilosophyBridgeAgent
OverclaimGate
```

Mandatory epistemic statuses:

```text
ESTABLISHED_SCIENCE
STRONG_EVIDENCE
HYPOTHESIS
OPEN_QUESTION
SPECULATION
PHILOSOPHICAL_INTERPRETATION
```

---

## 5.3 History & Human Stories

```text
slug: history-human-stories
name: History & Human Stories
```

Special roles:

```text
TimelineAgent
CausalityAgent
HistoricalContextAgent
CharacterAgent
ConflictAgent
SourceConflictAgent
HistoricalAccuracyAgent
```

---

## 5.4 Pop Psychology & Relationships

```text
slug: pop-psychology-relationships
name: Pop Psychology & Relationships
```

Special roles:

```text
ViralQuestionAgent
PsychologyEvidenceAgent
RelatabilityAgent
PracticalAdviceAgent
HookAgent
EmotionalRelevanceAgent
OvergeneralizationGate
```

Rules:

```text
no unsupported gender generalizations
no pseudoscientific claims
sexual topics must remain educational/non-explicit
practical advice must be evidence-aware
```

---

## 5.5 Psychology & Evolution

```text
slug: psychology-evolution
name: Psychology & Evolution
```

Special roles:

```text
EvolutionHypothesisAgent
EvidenceAgent
AlternativeExplanationAgent
CultureVsBiologyAgent
ModernMismatchAgent
OvergeneralizationGate
```

Always consider:

```text
biology
culture
environment
development
individual differences
```

---

# 6. IMPLEMENTATION STRATEGY

Implement in phases.

After every phase:

1. run formatting
2. run lint
3. run mypy
4. run unit tests
5. run affected integration tests
6. fix failures caused by the phase
7. write an implementation audit note
8. continue only when the phase acceptance criteria pass

Do not silently leave known regressions.

---

# PHASE 0 — BASELINE AND SAFETY

## Goal

Establish a reproducible baseline before architecture changes.

## Tasks

1. Inspect:

```text
app/
alembic/
tests/
docs/
```

2. Record:

```text
current routes
current models
current test count
current known failures
current active LessonCanon imports
current active lesson routes
```

3. Run:

```bash
uv run ruff check app/ tests/
uv run mypy --strict app
uv run pytest tests/unit -q
```

Run database-backed integration tests using the existing repository test environment.

4. Create:

```text
docs/decisions/ADR-014-multichannel-resource-first-studio.md
```

The ADR must state:

```text
resources are primary
100-lesson path becomes legacy
EditorialChannel is separate from knowledge.Channel
KnowledgeUnit becomes writer-facing semantic unit
source hierarchy is first-class
replacement-before-deletion migration
```

5. Do not alter production behavior yet.

## Acceptance

```text
baseline commands documented
current failures documented
ADR exists
no production behavior changed
```

---

# PHASE 1 — EDITORIAL CHANNEL DOMAIN

## Goal

Create the five editorial verticals and allow the UI/backend to scope work by channel.

---

## 1.1 Create models

Create in a suitable module, preferably:

```text
app/editorial_channels/
```

Files:

```text
app/editorial_channels/__init__.py
app/editorial_channels/models.py
app/editorial_channels/schemas.py
app/editorial_channels/service.py
app/editorial_channels/domain.py
```

---

## 1.2 EditorialChannel model

Implement equivalent fields:

```python
class EditorialChannel(Base):
    __tablename__ = "editorial_channels"
    __table_args__ = {"schema": CONTENT}

    id: UUID
    slug: str  # unique
    name: str
    description: str
    status: str  # ACTIVE / INACTIVE
    icon: str | None
    created_at: datetime
```

Unique:

```text
slug
```

Seed exactly the five required channels.

---

## 1.3 ChannelStrategyVersion

Implement:

```python
class ChannelStrategyVersion(Base):
    id
    editorial_channel_id
    version_number

    core_question

    audience_json
    audience_problems_json

    domains_json
    preferred_angles_json
    forbidden_angles_json

    source_policy_json
    evidence_policy_json

    topic_scoring_policy_json
    narrative_policy_json
    style_policy_json
    hook_policy_json
    ending_policy_json

    agent_profile_json

    status
    created_at
    activated_at
```

Constraints:

```text
unique(editorial_channel_id, version_number)
only one ACTIVE strategy version per EditorialChannel
```

If PostgreSQL partial unique index is appropriate, use it.

Otherwise enforce in service transactionally.

---

## 1.4 Resource assignment model

Create:

```python
class EditorialChannelResource(Base):
    editorial_channel_id
    source_id
    relevance
    role
    assigned_at
```

Composite primary key:

```text
editorial_channel_id + source_id
```

This must reference existing:

```text
knowledge.sources
```

Do not duplicate a Source when assigning it to another channel.

---

## 1.5 Strategy seed

Create one initial active strategy for every EditorialChannel.

The strategies must contain policies, not predefined topics.

---

## 1.6 Service operations

Implement:

```text
list_channels()
get_channel(slug)
get_active_strategy(channel_id)
create_strategy_draft()
activate_strategy()
assign_resource()
unassign_resource()
list_channel_resources()
```

Unassigning a source must not delete the Source.

---

## 1.7 Tests

Add tests for:

```text
five channels seeded
source can belong to 3 channels simultaneously
source is not duplicated
one active strategy per channel
strategy version increments
unassign does not delete source
```

---

# PHASE 2 — WORKING STUDIO UI SHELL

## Goal

Create a real UI that works with persisted backend data.

Do not use fake dashboard state.

---

## 2.1 Technology

Stay with:

```text
FastAPI
Jinja
existing CSS architecture
HTMX only where useful
```

Do not add React/Next.js.

---

## 2.2 Global navigation

Use only:

```text
Home
Channels
Resource Library
Knowledge
Production
Analytics
Settings
```

Do NOT create duplicate global navigation items for:

```text
Research
Script
Voice
Publish
```

Those are production-stage concerns.

---

## 2.3 Channel workspace navigation

Inside one channel:

```text
Overview
Strategy
Resources
Topics
Production
Published
```

---

## 2.4 Routes

Create stable routes:

```text
/studio
/studio/channels
/studio/channels/{slug}
/studio/channels/{slug}/strategy
/studio/channels/{slug}/resources
/studio/channels/{slug}/topics
/studio/channels/{slug}/production
/studio/channels/{slug}/published

/library
/knowledge
/production
/analytics
/settings
```

---

## 2.5 Templates

Create:

```text
app/web/templates/studio/
    layout.html
    home.html
    channels.html

    channel_overview.html
    channel_strategy.html
    channel_resources.html
    channel_topics.html
    channel_production.html
    channel_published.html

    resource_library.html
    resource_detail.html
    resource_structure.html
    resource_units.html

    topic_detail.html

    production_list.html
    production_workspace.html
```

---

## 2.6 CSS

Create:

```text
app/web/static/studio.css
```

Design rules:

```text
light theme
white cards
subtle gray page background
12–16px card radius
minimal shadows
strong typographic hierarchy
one primary accent color
semantic colors only for state/status
```

---

## 2.7 Channel switcher

At top of Studio screens show five cards/tabs.

Each card shows:

```text
Name
Resources
Topics
Active productions
Published
```

All values must come from the database.

---

## 2.8 No contextless dangerous actions

Global actions may include:

```text
Import Resource
Assign Resource
Create Manual Topic
```

Do NOT expose:

```text
Build Script
Publish
Run Research
```

unless an appropriate selected object exists.

---

## 2.9 Tests

Test:

```text
all five channel routes return 200
switching slug changes channel context
unknown slug returns 404
resource assignment visible in correct channel
resource not duplicated
no fake count constants in template context
```

---

# PHASE 3 — YOUTUBE IMPORT MUST CONTINUE TO WORK

## Goal

Preserve and enhance the current YouTube import workflow.

Do not replace current ingestion.

Existing flow stays:

```text
YouTubeAdapter
→ metadata
→ timestamped transcript
→ Source
→ SourceVersion
→ SourceSegment
```

Add new post-ingestion stages after SourceSegments exist.

---

# PHASE 4 — SOURCE STRUCTURE / VORTRAGSSTRUKTUR

## Goal

Every imported YouTube video can automatically become a validated hierarchical semantic structure.

This is a core product feature.

---

## 4.1 Create module

```text
app/knowledge/structure/
    __init__.py
    domain.py
    models.py
    schemas.py
    agent.py
    service.py
    validator.py
```

---

## 4.2 SourceStructureNode model

Create in `knowledge` schema.

Required fields:

```python
class SourceStructureNode(Base):
    id: UUID

    source_version_id: UUID

    parent_id: UUID | None

    level: int
    ordinal: int

    node_type: str

    title: str
    summary: str

    start_segment_id: UUID
    end_segment_id: UUID

    start_seconds: Decimal | None
    end_seconds: Decimal | None

    confidence: float | None

    extraction_run_id: UUID | None

    metadata_json: dict

    created_at: datetime
```

Foreign keys:

```text
source_version_id → knowledge.source_versions.id
start_segment_id → knowledge.source_segments.id
end_segment_id → knowledge.source_segments.id
parent_id → knowledge.source_structure_nodes.id
```

Indexes:

```text
source_version_id
parent_id
node_type
```

Unique rule:

```text
(source_version_id, parent_id, ordinal)
```

---

## 4.3 Node types

Create enum or validated vocabulary:

```text
TOPIC
SUBTOPIC
ARGUMENT
EXPLANATION
STORY
CASE_STUDY
EXAMPLE
EXPERIMENT
QUESTION
ANSWER
COUNTERARGUMENT
DEFINITION
CONCLUSION
OTHER
```

---

## 4.4 SourceStructureAgent

The agent receives transcript segments with stable IDs and timestamps.

The agent does NOT receive an arbitrary plain transcript without IDs.

Input format must include:

```text
segment_id
sequence
start_seconds
end_seconds
normalized_text
```

The agent returns structured nodes only.

Every node must contain:

```text
title
summary
node_type
start_segment_sequence
end_segment_sequence
parent_temp_id
ordinal
```

The application maps segment sequence → actual UUID.

---

## 4.5 Critical rules for the agent prompt

The SourceStructureAgent must be instructed:

```text
Do not invent information.
Do not rewrite the source as new teaching content.
Do not merge distant unrelated sections.
Do not create overlapping sibling spans unless explicitly allowed.
Do not break a continuous story without a semantic reason.
A STORY or CASE_STUDY must span the complete narrative when possible.
Use the transcript order.
All nodes must map to real source segments.
Summary must describe the node but is not a replacement for original text.
```

---

## 4.6 Handling long videos

Do not send a 3-hour transcript in one uncontrolled prompt.

Use a two-pass approach.

Pass A:

```text
local structural proposals over large overlapping transcript regions
```

Pass B:

```text
merge proposals into one global hierarchy
```

The final hierarchy must map back to original SourceSegments.

Persist extraction metadata.

---

## 4.7 StructureValidator

Validator must check:

```text
every node belongs to one source_version
start segment exists
end segment exists
start sequence <= end sequence
parent belongs to same source version
level is consistent with parent
sibling ordinal is valid
child span is contained in parent span
no impossible timestamp ordering
all generated references resolve
STORY/CASE_STUDY spans are non-empty
no node summary exists without source span
```

Warnings, not necessarily blockers:

```text
large uncovered transcript region
very large node
many tiny nodes
possible duplicated structure
possible sibling overlap
```

---

## 4.8 Structure status

Add explicit source-processing state.

Either extend Source metadata/status cleanly or create a processing table.

Required states:

```text
INGESTED
STRUCTURE_PENDING
STRUCTURING
STRUCTURED
STRUCTURE_REVIEW_REQUIRED
UNIT_EXTRACTION_PENDING
UNIT_EXTRACTING
READY
FAILED
```

Do not overload `ingestion_status` if doing so would mix unrelated concerns.

A separate processing-state model is acceptable and may be cleaner.

---

## 4.9 Automatic trigger

After a new SourceVersion is successfully ingested:

```text
enqueue/start SourceStructureService
```

If the current app has no task queue, run it explicitly in the service workflow without pretending background processing exists.

The implementation must be synchronous/awaited unless an actual job system exists.

Do not fake async background completion.

---

## 4.10 Idempotency

Structure generation must be reproducible.

Use:

```text
source_version_id
model/provider
prompt_version
configuration_hash
```

to identify a structure extraction run.

Do not create duplicate structures for identical configuration.

---

## 4.11 UI

Resource Detail must have tabs:

```text
Original
Structure
Knowledge Units
```

Structure tab displays an expandable tree.

Clicking a structure node should show:

```text
title
summary
type
start/end time
source text span
warnings
```

---

## 4.12 Tests

Unit tests:

```text
tree validation
parent containment
invalid segment rejected
cross-source parent rejected
story span preserved
idempotent run
```

Integration:

```text
import fixture YouTube transcript
build structure
verify hierarchy persisted
verify every node maps to segments
```

No network in tests.

Use fixtures/mocks.

---

# PHASE 5 — KNOWLEDGE UNITS

## Goal

Convert validated source structure into coherent retrieval units.

---

## 5.1 Create module

```text
app/knowledge/units/
    __init__.py
    domain.py
    models.py
    schemas.py
    extractor.py
    service.py
    validator.py
```

---

## 5.2 KnowledgeUnit model

Required fields:

```python
class KnowledgeUnit(Base):
    id: UUID

    source_version_id: UUID
    structure_node_id: UUID | None

    unit_type: str

    title: str
    summary: str
    full_text: str

    start_segment_id: UUID
    end_segment_id: UUID

    atomic: bool

    evidence_level: str | None
    claim_type: str | None

    content_hash: str
    extraction_version: str

    metadata_json: dict

    created_at: datetime
```

---

## 5.3 Unit types

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

---

## 5.4 Atomic rule

Default:

```text
STORY → atomic=True
CASE_STUDY → atomic=True
```

`EXAMPLE` may be atomic depending on structure.

---

## 5.5 full_text construction

`full_text` must be reconstructed from the exact ordered SourceSegments covered by the unit.

Do not use the LLM summary as `full_text`.

---

## 5.6 KnowledgeUnitExtractor

Input:

```text
validated SourceStructureNode
exact source segment span
```

Output:

```text
unit_type
title
summary
atomic
evidence_level
claim_type
concept candidates
```

The service constructs authoritative full_text from source segments.

---

## 5.7 KnowledgeUnitValidator

Check:

```text
source span valid
full_text hash valid
full_text equals source-derived segment span
summary exists
title exists
atomic type rule
structure_node source_version matches unit source_version
```

---

## 5.8 UI

Knowledge Units tab shows:

```text
Type
Title
Summary
Concepts
Atomic
Source span
Evidence level
```

Click a unit to show:

```text
full source-derived text
structure path
timestamp/page provenance
concepts
metadata
```

---

# PHASE 6 — CONCEPT MAPPING

## Goal

Connect Knowledge Units from different resources without destroying source structure.

Reuse `ExternalConcept` where possible.

---

## 6.1 Create association

```python
KnowledgeUnitConcept:
    knowledge_unit_id
    concept_id
    confidence
    relation_role
```

---

## 6.2 Create concept relationships

```python
ConceptRelationship:
    from_concept_id
    to_concept_id
    relation_type
    confidence
    provenance_json
```

Allowed relation types:

```text
RELATED_TO
PART_OF
CAUSES
MAY_CAUSE
CONTRASTS
SUPPORTS
CHALLENGES
EXAMPLE_OF
```

---

## 6.3 Important separation

Keep:

```text
SOURCE STRUCTURE
```

separate from:

```text
GLOBAL KNOWLEDGE STRUCTURE
```

Source structure answers:

```text
What did this source say, in what order?
```

Concept graph answers:

```text
How does this knowledge relate to knowledge from other sources?
```

Never replace source hierarchy with global concept hierarchy.

---

# PHASE 7 — RETRIEVAL V2

## Goal

Search Knowledge Units first and preserve semantic context.

Do not delete current chunk system yet.

---

## 7.1 Index Knowledge Units

Create embeddings for:

```text
summary
full_text
```

Prefer using existing embedding infrastructure.

Do not create a separate vector database.

---

## 7.2 Retrieval signals

Support:

```text
lexical / FTS
dense similarity
concept/entity match
existing fusion/RRF
reranking
```

---

## 7.3 Structural expansion

Add explicit expansion mode:

```text
NONE
PARENT
PARENTS
SIBLINGS
FAMILY
SUBTREE
```

---

## 7.4 Atomic return rule

If a hit maps inside an atomic Knowledge Unit:

```text
return the whole unit
```

not an arbitrary excerpt.

---

## 7.5 Backward compatibility

During transition:

```text
KnowledgeUnit retrieval = primary
old Chunk retrieval = fallback
```

Add evaluation comparing both.

---

## 7.6 Search result schema

A KnowledgeUnit search result must include:

```text
knowledge_unit_id
title
summary
full_text
unit_type
atomic
matched concepts
score components
source_id
source_version_id
source title
creator
source URL
timestamp/page span
structure path
expanded context
```

---

# PHASE 8 — DYNAMIC TOPIC ENGINE

Only implement after Phases 4–7 work.

---

## 8.1 Remove hard-coded topic generation behavior

Current hard-coded Emtedad prompt lists must no longer drive topic discovery.

Replace with resource-derived discovery.

---

## 8.2 Create module

```text
app/topics/
    __init__.py
    domain.py
    models.py
    schemas.py
    miner.py
    scorer.py
    novelty.py
    service.py
```

---

## 8.3 TopicCandidate

Required fields:

```python
class TopicCandidate(Base):
    id

    editorial_channel_id
    strategy_version_id

    title
    video_question

    tentative_thesis
    angle

    knowledge_coverage_score
    channel_fit_score
    novelty_score
    curiosity_score
    emotional_score
    practical_value_score
    total_score

    status

    provenance_json

    created_at
```

Use relational association tables for concepts/Knowledge Units if practical instead of stuffing everything into JSON.

---

## 8.4 Status

```text
CANDIDATE
SHORTLISTED
SELECTED
IN_RESEARCH
READY_FOR_PRODUCTION
IN_PRODUCTION
PUBLISHED
REJECTED
ARCHIVED
```

---

## 8.5 Topic generation inputs

TopicMiner receives:

```text
active ChannelStrategyVersion
channel-assigned resources
Knowledge Units
concept clusters
published script signatures
owner instruction, if provided
```

It does NOT receive all published prose.

---

## 8.6 Topic generation output

Each candidate must include:

```text
video_question
tentative_thesis
angle
supporting concepts
supporting Knowledge Units
knowledge gaps
why it fits channel
score components
```

---

## 8.7 Scoring

Base scoring model:

```text
Channel Fit
Knowledge Coverage
Novelty
Curiosity
Emotional Relevance
Practical Value
```

Weights are defined by ChannelStrategyVersion.

Do not hard-code one global set of weights.

---

## 8.8 Knowledge gap rule

A topic may have:

```text
high curiosity
high channel fit
low knowledge coverage
```

It stays:

```text
CANDIDATE / NEEDS_RESEARCH
```

Do not mark it ready.

---

# PHASE 9 — CONTENT BRIEF AND THESIS

## 9.1 ContentBrief model

Create:

```python
class ContentBrief(Base):
    id

    topic_candidate_id
    editorial_channel_id
    strategy_version_id

    question
    thesis

    target_audience
    angle

    primary_concepts_json

    required_evidence_roles_json
    preferred_story_role
    required_counterargument

    forbidden_claims_json
    forbidden_repetitions_json

    target_duration_minutes

    status
    created_at
```

---

## 9.2 ContentBrief is required

A production cannot move to Research until:

```text
question exists
thesis exists
channel exists
strategy version is pinned
target duration exists
```

---

# PHASE 10 — DISTINCTIVENESS

## 10.1 ScriptSignature model

Store published signatures:

```text
question
thesis
angle
concept_ids
story_unit_ids
argument_signature
hook_type
ending_type
```

Do not store full old prose as writer input.

---

## 10.2 DistinctivenessPlanner

Check:

```text
topic overlap
thesis overlap
story overlap
argument overlap
hook overlap
ending overlap
```

Return:

```text
ACCEPT
REPLAN
REVIEW_REQUIRED
```

Thresholds should be configurable per Channel Strategy.

---

# PHASE 11 — GENERIC RESEARCH + EVIDENCE MATRIX

## 11.1 Generalize ResearchPlan

ResearchPlan must be able to originate from:

```text
ContentBrief
```

without requiring:

```text
lesson_id
lesson_canon_hash
AyinSpine
```

Preserve legacy fields temporarily for old records.

---

## 11.2 Evidence roles

Support:

```text
PRIMARY_EVIDENCE
SUPPORTING_EVIDENCE
COUNTEREVIDENCE
ALTERNATIVE_EXPLANATION
HISTORICAL_CONTEXT
PHILOSOPHICAL_CONTEXT
EXAMPLE
CASE_STUDY
OPEN_QUESTION
```

---

## 11.3 EvidenceMatrix model

Create:

```python
class EvidenceMatrix(Base):
    id
    content_brief_id
    version_number
    status
    content_hash
    created_at
```

Create rows/items containing:

```text
claim_text
claim_type
epistemic_status
supporting unit IDs
counterevidence unit IDs
alternative explanation unit IDs
source quality
limitations
allowed_wording
forbidden_wording
```

---

## 11.4 ResearchPackage generic origin

The generic path must freeze:

```text
selected Knowledge Units
claims
evidence roles
counterevidence
alternative explanations
source provenance
source quality
uncertainty
content hash
```

---

# PHASE 12 — ARGUMENT ARCHITECT

Create:

```text
app/content_engine/argument.py
```

Agent:

```text
ArgumentArchitectAgent
```

Output structured plan.

Required structure fields:

```text
argument_plan_id
content_brief_id
version
sections
```

Each section includes:

```text
ordinal
role
purpose
claim_ids
evidence_item_ids
story_unit_ids
counterargument_ids
transition_intent
must_include
must_not_claim
```

No final prose.

---

# PHASE 13 — NARRATIVE ARCHITECT

Create:

```text
app/content_engine/narrative.py
```

Agent:

```text
NarrativeArchitectAgent
```

Input:

```text
ContentBrief
EvidenceMatrix
ArgumentPlan
ChannelStrategy
```

Output sections with:

```text
ordinal
narrative_role
purpose
target_seconds
argument_section_ids
story_unit_ids
emotional_function
transition_in
transition_out
opening_method
ending_method
```

No final full script.

---

# PHASE 14 — GENERIC SCRIPT PIPELINE

Refactor existing Persian lesson writing so it does not require LessonCanonRepository.

---

## 14.1 Script writer input

Allow only:

```text
ChannelStrategy snapshot
ContentBrief
EvidenceMatrix
Frozen ResearchPackage
ArgumentPlan
NarrativePlan
owner style instruction
revision constraints
```

---

## 14.2 Script output

Prefer a generic model:

```python
ScriptDraft:
    id
    editorial_project_id
    language
    version_number
    variant_index
    text
    status
    provenance
    target_duration_minutes
    actual_word_count
    estimated_duration_seconds
```

If renaming `PersianDraft` immediately is too risky:

```text
keep PersianDraft temporarily
create generic service around it
migrate model later
```

Do not perform a huge rename and architecture migration in the same commit unless tests prove safety.

---

# PHASE 15 — REVIEW PIPELINE

Required independent review roles:

```text
FactCritic
LogicCritic
ChannelSpecificCritic
RetentionCritic
OriginalityCritic
```

Critics produce findings.

They do NOT silently rewrite.

Finding schema:

```text
location
code
severity
explanation
correction_constraint
```

Then:

```text
RevisionAgent
```

creates a new draft version.

---

# PHASE 16 — CHANNEL-SPECIFIC REVIEW PACKS

Load only the selected channel's checks.

Example Science:

```text
epistemic status check
overclaim check
alternative explanation check
science/philosophy boundary check
```

History:

```text
timeline consistency
source conflict
causal overclaim
anachronism check
```

Pop Psychology:

```text
evidence strength
overgeneralization
practical advice safety
gender stereotype check
```

Evolution:

```text
adaptationism check
culture/biology alternative
individual-differences check
```

Emtedad:

```text
conceptual continuity
meaning/interpretation boundary
Ayin source fidelity when Ayin is explicitly used
```

---

# PHASE 17 — PRODUCTION WORKSPACE UI

## 17.1 Production stages

Persist and display:

```text
1. Brief
2. Thesis
3. Research
4. Evidence
5. Argument
6. Narrative
7. Script
8. Review
9. Approved
10. Localization
11. Voice
12. Published
```

---

## 17.2 Production page

Route:

```text
/production/{project_id}
```

Top:

```text
channel
question
current stage
status
strategy version
```

Stage stepper:

```text
Brief → Thesis → Research → Evidence → Argument → Narrative → Script → Review
```

Center:

```text
current artifact
```

Right inspector:

```text
sources
warnings
agent findings
version
provenance
allowed next actions
```

---

## 17.3 Backend-driven actions

Button availability must be based on persisted state.

Examples:

Do not enable:

```text
Build Argument
```

unless Evidence Matrix is ready.

Do not enable:

```text
Build Narrative
```

unless ArgumentPlan is ready.

Do not enable:

```text
Build Script
```

unless NarrativePlan is ready.

Do not enable:

```text
Approve
```

while blocking review findings exist.

---

# PHASE 18 — RESOURCE LIBRARY UI

Global route:

```text
/library
```

Show:

```text
Title
Type
Creator
Language
Assigned editorial channels
Structure status
Knowledge Unit count
Review status
Added date
```

Actions:

```text
Import YouTube
Add Resource
Assign to Channel
Unassign from Channel
Inspect
Re-run Structure
Rebuild Knowledge Units
```

---

# PHASE 19 — RESOURCE DETAIL UI

Route:

```text
/library/{source_id}
```

Tabs:

```text
Original
Structure
Knowledge Units
```

Original:

```text
metadata
source URL
transcript
timestamps
versions
provenance
```

Structure:

```text
expandable hierarchy
node detail
source span
warnings
```

Knowledge Units:

```text
filter by type
title
summary
concepts
atomic
evidence level
source span
```

---

# PHASE 20 — LOCALIZATION / PUBLICATION TARGETS

Reuse current localization and voice preparation.

Add:

```python
class PublicationTarget:
    id
    editorial_channel_id
    platform
    language
    name
    status
```

Do not auto-publish.

Owner approval remains mandatory.

---

# PHASE 21 — RETIRE LEGACY 100-LESSON PATH

Only now remove active dependency on Lesson Canon.

Checklist before deletion:

```text
generic ContentBrief path works
generic ResearchPackage path works
generic Semantic/Lecture Master path works
generic script path works
Studio UI works
integration tests pass
historical records retain provenance
```

Then remove active imports/routes/files.

---

## 21.1 Delete/retire code

After replacement verification:

```text
app/content_strategy/lesson_canon.py
app/content_strategy/lesson_catalog.py
app/content_strategy/lesson_workflow.py
app/content_strategy/lesson_research.py
resources/editorial/lesson_canon/
```

Retire lesson templates and routes.

---

## 21.2 Do not destroy historical data

Historical project snapshots remain readable.

Old drafts remain readable.

Old research packages remain readable.

Old semantic masters remain readable.

---

# 22. ROUTE MIGRATION

Current route intentions should migrate as follows:

```text
/sources
→ /library

/topics
→ /studio/channels/{slug}/topics

/workspace/{project_id}
→ /production/{project_id}

/texts
→ channel published / production archive view

/archive
→ channel published archive

/lessons
→ removed after generic replacement is proven
```

During transition use redirects.

---

# 23. AUTOMATIC RESOURCE PROCESSING

After a successful source import:

```text
INGESTED
↓
STRUCTURE_PENDING
↓
STRUCTURING
↓
STRUCTURED
↓
UNIT_EXTRACTION_PENDING
↓
UNIT_EXTRACTING
↓
READY
```

Failure states:

```text
STRUCTURE_REVIEW_REQUIRED
UNIT_REVIEW_REQUIRED
FAILED
```

Do not claim background work unless an actual queue/job system exists.

If no queue exists, perform processing in an awaited request/service flow or expose a deliberate "Process" action.

---

# 24. AGENT REGISTRY

Do not instantiate dozens of hard-coded agent classes directly inside routes.

Create a registry/config layer.

Example conceptual interface:

```python
AgentRegistry.for_channel(channel_slug)
```

returns:

```text
core agents
channel-specific agents
model/provider configuration
prompt versions
```

All agents must remain provider-independent.

Use the existing LLM abstraction layer.

Do not hard-code Claude/Codex/OpenAI behavior into domain services.

---

# 25. LLM OUTPUT CONTRACT

Every semantic LLM call must use structured output.

Use Pydantic schemas.

Do not parse free-form prose when a structured artifact is required.

Examples:

```text
SourceStructureOutput
KnowledgeUnitExtractionOutput
TopicCandidateOutput
ContentBriefOutput
EvidenceReviewOutput
ArgumentPlanOutput
NarrativePlanOutput
ReviewFindingOutput
```

---

# 26. PROVENANCE REQUIREMENTS

Every generated artifact must carry enough provenance to answer:

```text
Which source/version created this?
Which prompt version?
Which model/provider?
Which upstream artifact versions?
Which strategy version?
Which Knowledge Units?
Which research package?
Which owner edits?
```

Use hashes where appropriate.

---

# 27. IDEMPOTENCY REQUIREMENTS

The following must be idempotent when inputs/configuration are identical:

```text
source import
structure extraction
Knowledge Unit extraction
embedding/index build
research package freezing
semantic plan builds where designed as immutable artifacts
```

Do not create duplicate rows on retry.

---

# 28. DATA MIGRATION RULES

Never drop legacy columns before:

```text
new columns populated
new service path deployed
tests pass
legacy reads no longer required
```

Prefer:

```text
add
backfill
dual-read temporarily if required
switch write path
switch read path
remove legacy later
```

---

# 29. REQUIRED TEST STRATEGY

Each new domain needs:

```text
unit tests
service tests
DB integration tests
route tests
state transition tests
provenance tests
idempotency tests
```

---

## 29.1 Source structure tests

Must include:

```text
story across many transcript segments
nested hierarchy
invalid parent
cross-source references
overlapping siblings
missing source span
idempotent extraction
```

---

## 29.2 Knowledge Unit tests

Must include:

```text
atomic story remains whole
full_text reconstructed from source segments
summary not used as authoritative text
same unit not duplicated
concept associations preserved
```

---

## 29.3 Channel tests

Must include:

```text
5 channels seeded
one Source assigned to 3 channels
unassign leaves Source intact
active strategy version works
invalid slug 404
```

---

## 29.4 Topic tests

Must include:

```text
same concept produces channel-specific questions
topic has provenance
low knowledge coverage prevents ready status
novelty uses signatures not old full prose
```

---

## 29.5 Production gate tests

Must include:

```text
cannot research without ContentBrief
cannot argument without EvidenceMatrix
cannot narrative without ArgumentPlan
cannot script without NarrativePlan
cannot approve with blocking findings
```

---

# 30. QUALITY COMMANDS

Use repository-standard commands.

At minimum after each implementation phase:

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run mypy --strict app
uv run pytest tests/unit -q
```

Run relevant integration tests.

Before declaring the full migration complete:

```bash
uv run pytest -q
```

using the configured test database/environment.

---

# 31. IMPLEMENTATION DOCUMENTATION

For each completed phase create:

```text
docs/audits/MULTICHANNEL_PHASE_<N>_<NAME>.md
```

Include:

```text
scope
files changed
migration
behavior
tests run
test results
known limitations
next phase
```

Update:

```text
docs/execution/CURRENT_PHASE.md
```

only after phase acceptance.

---

# 32. PROHIBITED SHORTCUTS

Do NOT:

```text
create 100 new fixed topics
recreate Lesson Canon under another name
create one Knowledge Base per channel
duplicate Source rows per channel
use token chunks as final story units
feed whole corpus to writer
feed all old scripts to writer
hard-code fake dashboard counts
show buttons that do not work
fake async/background processing
delete old migrations
delete historical content
auto-publish
mix source YouTube channels with EditorialChannels
mix editorial verticals with publication languages
present philosophy as science
silently rewrite critic findings
```

---

# 33. FIRST USER-VISIBLE MILESTONE

This is the first milestone that must be demonstrated.

The user must be able to:

1. open Studio
2. see five EditorialChannels
3. click one channel
4. open Resource Library
5. import a YouTube video
6. see the stored transcript
7. see the automatically generated Vortragsstruktur
8. expand the hierarchy
9. click a Story node
10. see the exact original transcript span/timestamps
11. open Knowledge Units
12. see the story as one atomic Knowledge Unit
13. search for a concept
14. retrieve that complete Knowledge Unit with provenance
15. assign the same source to multiple EditorialChannels without duplication

Do not prioritize topic generation before this demonstration works.

---

# 34. SECOND USER-VISIBLE MILESTONE

The user must be able to:

1. switch among all five editorial channels
2. inspect each active Channel Strategy
3. assign existing resources to a channel
4. click `Mine Topics`
5. receive resource-grounded Video Questions
6. see:
   - Channel Fit
   - Knowledge Coverage
   - Novelty
   - Curiosity
7. select one question
8. create a Content Brief
9. see the selected question move into Production

---

# 35. THIRD USER-VISIBLE MILESTONE

The selected production must execute:

```text
Brief
→ Thesis
→ Research
→ Evidence
→ Argument
→ Narrative
→ Script
→ Review
→ Owner Approval
```

Every stage must be persisted and inspectable.

---

# 36. DEFINITION OF DONE

The migration is complete only when all are true:

```text
✓ Five EditorialChannels exist
✓ Each has an active versioned strategy
✓ One Source can belong to multiple channels
✓ YouTube import still works
✓ Transcript provenance still works
✓ Imported video can be automatically structured
✓ Source hierarchy is persisted
✓ Knowledge Units are persisted
✓ Stories remain atomic
✓ KnowledgeUnit retrieval is primary
✓ Structure-aware expansion works
✓ Dynamic Topic Mining uses resources
✓ No fixed 100-topic system
✓ ContentBrief exists
✓ Thesis is explicit
✓ EvidenceMatrix exists
✓ Frozen generic ResearchPackage exists
✓ ArgumentPlan exists
✓ NarrativePlan exists
✓ Script Writer has controlled input
✓ Critics are independent
✓ Revision is versioned
✓ Published signature exists
✓ Localization still works
✓ Voice preparation still works
✓ Owner approval remains mandatory
✓ Active production no longer imports LessonCanonRepository
✓ Legacy 100-Lesson UI/routes are retired
✓ Historical data remains readable
✓ Full test suite passes or pre-existing unrelated failures are explicitly documented
```

---

# 37. FINAL ARCHITECTURE

```text
══════════════════════════════════════════════
                 RESOURCE WORLD
══════════════════════════════════════════════

YouTube / Books / PDFs / Papers / Websites
                   ↓
             Source Ingestion
                   ↓
       SourceVersion + SourceSegment
                   ↓
          SourceStructureAgent
                   ↓
        Vortragsstruktur / Source Tree
                   ↓
        KnowledgeUnit Extraction
                   ↓
        Concepts + Relationships
                   ↓
         Shared Knowledge Base
                   │
═══════════════════╪══════════════════════════
                   │
            EDITORIAL CHANNELS
                   │
  ┌────────────────┼────────────────────┐
  │                │                    │
Emtedad      Science & Mystery      History ...
  │                │                    │
Strategy         Strategy             Strategy
  └────────────────┼────────────────────┘
                   ↓
             Dynamic Topic Mining
                   ↓
              Video Questions
                   ↓
               Topic Ranking
                   ↓
                 Selection
                   │
═══════════════════╪══════════════════════════
                   │
              CONTENT ENGINE
                   │
              Content Brief
                   ↓
                  Thesis
                   ↓
            Distinctiveness
                   ↓
            Research Planner
                   ↓
       Structure-aware Retrieval
                   ↓
             Evidence Matrix
                   ↓
        Frozen Research Package
                   ↓
         Argument Architecture
                   ↓
         Narrative Architecture
                   ↓
        Channel-specific Agent Pack
                   ↓
              Script Writer
                   ↓
            Independent Critics
                   ↓
                Revision
                   ↓
              Owner Approval
                   │
═══════════════════╪══════════════════════════
                   │
              PUBLICATION LAYER
                   │
          Approved Master Script
                   ↓
           Localization Tracks
                   ↓
          Publication Targets
                   ↓
             Voice / Video
                   ↓
               Published
                   ↓
               Analytics
```

---

# 38. FINAL EXECUTION INSTRUCTION

Implement this architecture phase by phase.

Do not stop after creating empty models or visual templates.

Every phase must produce **working behavior**.

Do not mark a feature complete unless:

```text
database persistence works
service works
route/UI works where required
state transition works
tests prove it
provenance is preserved
```

If a legacy dependency prevents a later phase:

```text
generalize it
add a compatibility layer
migrate usage
then retire legacy
```

Do not revert to the old 100-Lesson architecture as a shortcut.

The primary architectural invariant is:

> **One shared structured knowledge system, five separate editorial strategies, dynamic topic generation, and a controlled knowledge-to-script production pipeline.**

MASTER IMPLEMENTATION PROMPT V2
AYIN-E EMTEDAD MULTILINGUAL KNOWLEDGE, RAG, MANASEK, AND LECTURE PLATFORM

ROLE
You are a senior software architect, data engineer, RAG engineer, AI workflow engineer, and Python backend engineer.

Your task is to inspect the existing repository and IMPLEMENT a production-quality platform whose PRIMARY PURPOSE is:

1. preserve and version the canonical intellectual corpus of Ayin-e Emtedad;
2. preserve and model Manasek as the experiential/practical layer of Ayin-e Emtedad;
3. ingest external knowledge from many creators, channels, books, papers, podcasts, PDFs, websites, and future sources;
4. relate that external knowledge to Ayin-e Emtedad without confusing external evidence with Ayin's own concepts;
5. support high-quality multilingual hybrid RAG;
6. generate evidence-grounded lectures whose MAIN CONCEPTUAL CENTER is always Ayin-e Emtedad;
7. produce semantically aligned Persian, English, and Arabic lecture versions;
8. retain exact provenance, references, uncertainty, counterarguments, and ritual relationships;
9. support a long-lived research and publishing program, not a one-off scraper.

Do not merely describe the architecture. Inspect the repository, preserve useful code, implement the system phase-by-phase, create migrations, tests, documentation, and runnable commands.

======================================================================
0. WHY THIS V2 EXISTS — CORRECTIONS TO THE PREVIOUS DESIGN
======================================================================

The earlier platform design had a strong generic knowledge/RAG foundation, but it had several architectural weaknesses for this actual project.

Correct all of them.

WEAKNESS 1 — THE DATABASE WAS THE CENTER
The previous design effectively followed:

external sources
→ knowledge database
→ RAG
→ lecture

That is wrong for this project.

Correct model:

AYIN CANONICAL CORE
→ Ayin question / concept / distinction
→ research questions
→ external knowledge retrieval
→ evidence + contrast + criticism
→ Ayin synthesis
→ lecture

External knowledge serves the Ayin inquiry. It must not define Ayin.

WEAKNESS 2 — AYIN WAS TREATED LIKE AN ORDINARY SOURCE
Ayin-e Emtedad is not merely another PDF in the corpus.

The system needs a dedicated, versioned canonical layer for:
- concepts
- definitions
- distinctions
- principles
- ethical orientations
- open questions
- optional metaphysical readings
- applications
- canonical source passages

This layer must be editorially controlled and separately queryable.

WEAKNESS 3 — MANASEK WAS UNDERSPECIFIED
Manasek is not a media appendix.

It is the experiential layer of Ayin: concept → attention/experience.

The system must represent:
- Gate rituals
- Between/relational rituals
- Life rituals
- the five gates
- the seven-stage individual architecture
- Return
- collective ritual as a separate architecture
- Horizontal Emtedad
- ritual safety rules
- consent/exit rules
- non-interpretation rules
- ritual versions
- concept-to-ritual mappings

IMPORTANT CORRECTION:
Do NOT turn the seven ritual stages into a mandatory seven-stage lecture curriculum.
The seven stages belong to the ritual architecture.
Lectures may relate to a ritual stage when meaningful, but the lecture curriculum must have its own structure.

WEAKNESS 4 — THE FOUR EPISTEMIC LANGUAGES WERE NOT MODELED
Ayin distinguishes:
- conceptual language
- descriptive language
- ethical/value language
- optional metaphysical language

This distinction must exist in the database and generation pipeline.

The system must never silently turn:
- a conceptual distinction into a scientific fact,
- a descriptive observation into a causal scientific claim,
- an ethical orientation into an empirical statement,
- an optional metaphysical interpretation into mandatory Ayin doctrine.

WEAKNESS 5 — "EXTERNAL EVIDENCE SUPPORTS AYIN" WAS TOO SIMPLE
Scientific evidence cannot automatically "prove" a philosophical framework.

Replace simplistic relation types with a precise taxonomy:
- empirically_relevant_to
- supports_empirical_subclaim
- conceptual_parallel
- historical_parallel
- illustrates
- compatible_with
- tension_with
- challenges
- counterexample_to
- alternative_explanation
- not_equivalent_to
- unresolved_relation

Use "supports" only when the supported thing is actually an empirical/descriptive claim that the evidence can support.

WEAKNESS 6 — "LANGUAGE-NEUTRAL MASTER TEXT" WAS TOO VAGUE
There is no magically language-neutral natural-language script.

Instead create a canonical SEMANTIC MASTER made of:
- stable concept IDs
- assertion IDs
- distinctions
- research questions
- approved evidence items
- lecture argument structure
- citation bindings
- ritual links
- style-independent intent

Then create Persian, English, and Arabic language realizations from that master.

WEAKNESS 7 — TRANSLATION WAS NOT STRONGLY GOVERNED
Core Ayin terms can drift badly across languages.

Create a terminology registry with:
- preferred forms
- transliterations
- definitions
- explanatory glosses
- forbidden/misleading equivalents
- review status
- language
- version

Do not auto-finalize important philosophical terms.

WEAKNESS 8 — CANONICAL CONTENT DID NOT HAVE STRONG VERSION GOVERNANCE
The Ayin text explicitly remains open to criticism and revision.

Therefore:
- canonical does NOT mean sacred or eternally frozen;
- canonical means "current editorially approved project version".

All concepts, definitions, principles, rituals, and terminology must be versioned.
Lectures must pin to the canon version used at generation time.

WEAKNESS 9 — COUNTERARGUMENTS WERE OPTIONAL
A long-term philosophical project must not become an AI-generated echo chamber.

For every substantial lecture, the research process should actively retrieve:
- criticism
- competing explanations
- tensions
- boundary cases
- unresolved questions

These should be preserved even when not all appear in the final lecture.

WEAKNESS 10 — LECTURE QUALITY WAS DEFINED MAINLY BY RETRIEVAL
Retrieval quality is necessary but insufficient.

Add:
- Ayin fidelity checks
- epistemic-type checks
- citation coverage
- source attribution checks
- contradiction/counterargument coverage
- translation fidelity
- terminology checks
- ritual safety checks
- style checks
- human approval states

WEAKNESS 11 — RITUAL AND LECTURE CONTENT COULD BLUR
A lecture can explain or reference a ritual.
A ritual is not merely a lecture with music.

Maintain separate content types and separate safety validators.

WEAKNESS 12 — MULTILINGUAL PUBLICATION WAS NOT A FIRST-CLASS DOMAIN
A single lecture identity must support:
- one semantic master
- Persian realization
- English realization
- Arabic realization
- localized examples where approved
- shared core evidence
- optional language/culture-specific enrichment
- independent publishing status per language/channel

======================================================================
1. PROJECT MISSION
======================================================================

The platform is an intellectual and experiential operating system for Ayin-e Emtedad.

It must support this long-term loop:

Ayin canonical corpus
→ question
→ research
→ external evidence / criticism / parallels
→ structured synthesis
→ lecture
→ multilingual publication
→ new questions
→ new research
→ possible editorial review of Ayin itself

The system should make it possible to build hundreds or thousands of connected lectures without reducing Ayin to generic motivational content.

The MAIN CONCEPT of every lecture generated in the Ayin lecture workflow must be Ayin-e Emtedad.

External thinkers, creators, books, studies, and papers are:
- evidence,
- dialogue partners,
- critics,
- historical parallels,
- examples,
- alternative explanations,
not the conceptual center.

======================================================================
2. SOURCE-OF-TRUTH HIERARCHY
======================================================================

Implement explicit corpus zones.

CORPUS_ZONE =

1. AYIN_CANON
   Current editorially approved Ayin documents and structured concepts.

2. AYIN_WORKING
   Draft/revision material not yet canonical.

3. MANASEK_CANON
   Current editorially approved ritual corpus.

4. MANASEK_WORKING
   Draft ritual material.

5. EXTERNAL_PRIMARY
   Original external sources: papers, books, creator transcripts, etc.

6. EXTERNAL_DERIVED
   summaries, extracted claims, machine translations, metadata.

7. GENERATED_CONTENT
   lecture drafts, research packages, localized scripts, etc.

Never mix these zones semantically.

A generated lecture is never promoted into AYIN_CANON automatically.

An external source is never promoted into AYIN_CANON automatically.

AI extraction is never canonical without explicit editorial approval.

======================================================================
3. CANONICAL AYIN PRINCIPLES TO PRESERVE
======================================================================

The implementation must preserve the framing found in the canonical Ayin material.

At minimum, the system must model that:

- Ayin-e Emtedad is a coherent way of seeing, questioning, and living.
- It is not automatically a new religion, scientific theory, psychological diagnostic system, or final answer to existence.
- Emtedad is continuation/continuity, not repetition.
- Bon concerns the fundamental determination/uniqueness of "this being"; it is not automatically personality, genes, biography, body, consciousness, or soul.
- Jan is distinct from intelligence, consciousness, and self-consciousness.
- Pattern is not identity.
- Acceptance is not surrender.
- Majal is not freedom outside causality.
- The Other remains a center in their own right.
- "The Between" concerns qualities arising in relation without becoming a third Bon.
- uncertainty and "we do not know" are legitimate outcomes.
- the framework distinguishes conceptual, descriptive, ethical, and optional metaphysical language.
- the framework is revisable and must preserve unresolved questions.
- ritual experience does not prove metaphysical truth.
- intensity of experience is not a truth criterion.
- no guide may claim privileged access to another person's Bon/Jan/ultimate truth.
- refusal, silence, non-participation, stopping, and leaving must remain valid.

Do not encode these merely as prose comments.
Represent them as structured, queryable, versioned canonical assertions/distinctions.

======================================================================
4. POSTGRESQL DOMAIN SEPARATION
======================================================================

Use PostgreSQL 17 + pgvector.

Prefer logical PostgreSQL schemas to reduce conceptual mixing:

core
knowledge
ritual
retrieval
content
ops

Suggested responsibilities:

core.*
- Ayin canon
- concepts
- terminology
- distinctions
- principles
- open questions
- canonical versions
- editorial states

knowledge.*
- creators
- channels
- external sources
- source segments
- external people/works/organizations
- mentions
- external claims
- evidence
- external relations
- reference resolution
- media metadata

ritual.*
- Manasek canon
- gates
- stages
- ritual families
- ritual versions
- ritual safety
- concept mappings
- localized ritual text

retrieval.*
- chunks
- embedding models
- embeddings
- lexical search material
- retrieval snapshots
- evaluation sets

content.*
- lecture projects
- Ayin Spines
- research packages
- semantic masters
- lecture claims
- sections
- citations
- localizations
- publication records

ops.*
- extraction runs
- pipeline jobs
- caches
- review queues
- errors
- audit logs

If the existing repo strongly favors a single public schema, namespaces may instead be represented through table naming/modules, but the conceptual separation must remain.

======================================================================
5. CANON DOCUMENT VERSIONING
======================================================================

Create:

core.canon_documents
- id
- slug
- document_type
- title
- original_language
- corpus_zone
- created_at

core.canon_versions
- id
- document_id
- semantic_version
- status
- source_file_hash
- source_file_path/object_key
- effective_from
- effective_to nullable
- change_summary
- approved_by nullable
- approved_at nullable
- created_at

Statuses:
- draft
- review
- approved
- superseded
- deprecated

Create canonical passage storage:

core.canon_passages
- id
- canon_version_id
- sequence
- page_number nullable
- heading_path
- raw_text
- normalized_text
- content_hash
- language
- created_at

Never overwrite approved historical versions.

Every generated lecture must store:
- which Ayin canon version it used;
- which Manasek version it used.

======================================================================
6. AYIN ONTOLOGY
======================================================================

Create first-class structured Ayin entities.

core.ayin_concepts
- id
- stable_key
- status
- created_at

core.ayin_concept_versions
- id
- concept_id
- canon_version_id
- definition
- scope
- notes
- valid_from
- valid_to nullable
- approval_status

Examples:
- emtedad
- bon
- jan
- awareness
- self_awareness
- tahigah
- conditions
- factor
- pattern
- direction
- majal
- change
- suffering
- vitality
- acceptance
- other
- between
- ethics_of_majal
- emergence
- causality
- horizontal_emtedad

Do not hard-code this list as exhaustive.

Create:

core.ayin_principles
- id
- stable_key
- statement
- discourse_type
- canon_version_id
- status
- source_passage_id

core.ayin_distinctions
- id
- left_concept_id
- relation
- right_entity_type
- right_entity_id nullable
- right_label nullable
- explanation
- discourse_type
- canon_version_id
- source_passage_id

Relations:
- IS_NOT
- DISTINCT_FROM
- DEPENDS_ON
- DOES_NOT_IMPLY
- CAN_COEXIST_WITH
- OPEN_RELATION

Example:
Bon IS_NOT personality
Pattern IS_NOT identity
Acceptance IS_NOT surrender
Majal IS_NOT freedom_outside_causality

Create:

core.ayin_relations
- id
- subject_concept_id
- relation_type
- object_concept_id
- explanation
- canon_version_id
- source_passage_id
- status

Create:

core.ayin_open_questions
- id
- stable_key
- question
- context
- canon_version_id
- source_passage_id
- status
- resolution_notes nullable

Statuses:
- open
- under_review
- partially_addressed
- retired

Open questions must be retrievable explicitly.

======================================================================
7. MODEL AYIN'S FOUR DISCOURSE TYPES
======================================================================

Create enum:

discourse_type =
- CONCEPTUAL
- DESCRIPTIVE
- ETHICAL
- OPTIONAL_METAPHYSICAL

Every structured Ayin assertion/principle should carry a discourse_type.

Generation rules:

CONCEPTUAL
Defines or distinguishes concepts internal to the framework.
Do not present as scientific proof.

DESCRIPTIVE
Describes experience, conditions, patterns, or observations.
Do not inflate into causal science without evidence.

ETHICAL
States orientation, norms, rights, responsibilities, consent, harm, power.
Do not describe these as experimentally proven facts.

OPTIONAL_METAPHYSICAL
Must always remain optional unless a future approved canon explicitly changes its status.
Never phrase it as a compulsory conclusion of the general framework.

Create validators that flag discourse-type leakage.

Example failure:
"Science proves Bon exists."
→ reject/flag.

Example failure:
"Jan is the soul."
→ reject/flag unless clearly labeled as one optional interpretation.

======================================================================
8. TERMINOLOGY REGISTRY FOR PERSIAN / ENGLISH / ARABIC
======================================================================

Persian is currently the primary source language of the canonical documents, but the architecture must not assume that only Persian can ever have canonical material.

Create:

core.terms
- id
- concept_id nullable
- stable_key
- status

core.term_forms
- id
- term_id
- language
- script
- form
- form_type
- explanation
- approval_status
- version
- notes

form_type:
- preferred
- transliteration
- explanatory_gloss
- alias
- historical
- deprecated
- forbidden_equivalent

For important terms such as:
- امتداد
- بُن
- جان
- مجال
- میان
- تهیگاه

do not auto-finalize translations.

The system must allow:
- retaining a transliterated term;
- adding an explanatory gloss;
- specifying misleading translations to avoid.

Example conceptual policy:
Bon may be kept as "Bon" in English and explained, rather than silently mapping it to "soul", "self", "personality", or "essence".

Do NOT hard-code this exact translation as final.
Store and human-review it.

Add terminology QA to every localization.

======================================================================
9. MANASEK AS THE EXPERIENTIAL LAYER
======================================================================

Represent Manasek separately from ordinary lectures.

The canonical ritual architecture currently includes three families:

1. GATE RITUALS
   Five symbolic gates:
   - Earth / خاک
   - Water / آب
   - Fire / آتش
   - Wind / باد
   - Pull/Relation / کشش

2. BETWEEN / RELATIONAL RITUALS
   Examples include:
   - presence
   - confrontation
   - repair
   - distance
   - exit

3. LIFE RITUALS
   Examples include:
   - beginning
   - transition
   - mourning
   - celebration
   - service
   - ending

Create:

ritual.families
ritual.gates
ritual.stages
ritual.rituals
ritual.ritual_versions
ritual.ritual_concept_links
ritual.ritual_safety_rules
ritual.ritual_localizations

======================================================================
10. FIVE GATES
======================================================================

Model the current philosophical role of the gates.

Earth:
- determination
- boundary
- position/place
- here-ness
- weight

Water:
- change
- transformation
- continuity without repetition
- flexibility

Fire:
- actuality
- force/intensity
- choice
- effect
- responsibility

Wind:
- passing
- movement
- transmission
- impermanence

Pull/Relation:
- relation
- direction
- desire
- distance
- consent
- the Other

IMPORTANT:
The gates are NOT components of Bon.
They are NOT five metaphysical elements of reality.
They are symbolic attentional perspectives.

Encode this as canonical distinctions so generative systems cannot casually distort it.

======================================================================
11. SEVEN-STAGE INDIVIDUAL MANASEK ARCHITECTURE
======================================================================

Represent the seven current stages:

1. Contact
2. Distinction
3. Continuity in Change
4. Temporal Emtedad
5. Effect and Responsibility
6. The Other and Breadth of Presence
7. Integration

Each stage:
- contains five gate sessions;
- is followed by Return;
- is not defined by calendar days;
- preserves sequence rather than daily cadence.

Current individual architecture:
5 gates × 7 stages = 35 gate pieces
+ 7 Return pieces
= 42 individual pieces

Represent this structurally, not just as text.

IMPORTANT:
Return is NOT a sixth gate.

Return:
- reviews;
- reduces interpretive intensity;
- reorients toward ordinary life;
- creates distance between experience and interpretation;
- does not announce attainment/enlightenment.

Collective ritual has its own architecture.
It is NOT a compressed version of the 42 individual pieces.

======================================================================
12. HORIZONTAL EMTEDAD
======================================================================

Model Horizontal Emtedad explicitly as an Ayin concept/relation.

In collective/relational context:
- uniqueness is not erased;
- persons do not merge into one;
- relation becomes possible only in the presence of another;
- shared presence does not cancel difference.

Do not represent Horizontal Emtedad as mystical fusion unless explicitly stored as an optional, non-canonical interpretation.

======================================================================
13. RITUAL SAFETY AS MACHINE-ENFORCED POLICY
======================================================================

Create structured ritual safety rules.

Examples of REQUIRED behavior:
- closing eyes is optional;
- movement is optional;
- touch is optional;
- speaking is optional;
- writing is optional;
- sharing is optional;
- direct gaze is optional;
- the participant may stop;
- the participant may leave;
- silence is a valid response;
- "nothing special happened" is a valid experience;
- after high intensity, support grounding/ordinary reorientation;
- do not encourage major decisions immediately after intense ritual experience.

Examples of FORBIDDEN or FLAGGED behavior:
- forced screaming
- forced catharsis
- hyperventilation
- breath retention as pressure
- sleep deprivation
- coercive disclosure
- unwanted touch
- "breaking resistance"
- forced intimacy
- sacred-frequency pseudo-scientific claims
- diagnosis from ritual experience
- claiming to know another person's Bon/Jan
- treating intensity as truth
- treating refusal as spiritual failure
- presenting exit as betrayal

Implement:
RitualSafetyValidator

No ritual-generation or ritual-localization output may be publishable without passing it.

======================================================================
14. EXTERNAL KNOWLEDGE INGESTION
======================================================================

Support many channels and creators.

Do NOT create Mokri-specific tables.

Initial source types:
- youtube_video
- podcast_episode
- pdf
- book
- paper
- article
- webpage
- lecture
- manual_upload

Create:

knowledge.creators
knowledge.channels
knowledge.sources
knowledge.source_segments
knowledge.people
knowledge.works
knowledge.organizations
knowledge.external_concepts
knowledge.mentions
knowledge.external_claims
knowledge.claim_evidence
knowledge.external_relations
knowledge.external_identifiers
knowledge.resolution_candidates
knowledge.media_assets

Preserve:
- source URL
- exact transcript text
- timestamps
- page numbers
- speaker
- language
- source version/hash
- ingestion metadata

Raw text is immutable.

======================================================================
15. REFERENCE RESOLUTION
======================================================================

Implement provider adapters:
- Crossref
- OpenAlex
- Open Library
- Wikidata

Potential future:
- other lawful/appropriate bibliographic sources

LLM extraction produces candidates, not truth.

Resolution flow:
mention
→ normalized candidate
→ provider searches
→ candidate list
→ deterministic + fuzzy/contextual scoring
→ resolved / review / unresolved
→ canonical external entity

Never invent:
- DOI
- ISBN
- journal
- year
- publisher
- identity

Store candidate provenance.

======================================================================
16. EXTERNAL CLAIMS AND EVIDENCE
======================================================================

Create:

knowledge.external_claims
- id
- source_segment_id
- claimant_person_id nullable
- claim_text
- normalized_claim_text
- claim_domain
- claim_type
- extraction_run_id
- extraction_confidence
- verification_status
- created_at

Create evidence links.

Do not equate:
"speaker said X"
with
"X is established".

Possible verification statuses:
- unverified
- attributed_only
- supported
- mixed
- contradicted
- insufficient
- not_applicable

Use "supported" only after actual evidence evaluation.

======================================================================
17. AYIN ↔ EXTERNAL KNOWLEDGE DIALOGUE LAYER
======================================================================

This is a central part of the platform.

Create:

knowledge.ayin_external_links
- id
- ayin_concept_id nullable
- ayin_principle_id nullable
- ayin_open_question_id nullable
- external_entity_type
- external_entity_id
- relation_type
- scope
- explanation
- confidence
- review_status
- created_by
- created_at

relation_type:
- empirically_relevant_to
- supports_empirical_subclaim
- conceptual_parallel
- historical_parallel
- illustrates
- compatible_with
- tension_with
- challenges
- counterexample_to
- alternative_explanation
- not_equivalent_to
- unresolved_relation

scope:
- conceptual
- empirical
- ethical
- metaphysical
- historical
- illustrative

Never allow an AI to label a metaphysical claim as scientifically proven merely because related empirical work exists.

======================================================================
18. SOURCE QUALITY / EVIDENCE METADATA
======================================================================

Do not reduce source quality to a single magical score.

Store descriptive attributes:

knowledge.source_quality
- source_id
- publication_type
- peer_reviewed nullable
- primary_or_secondary
- publisher/journal metadata
- author credentials metadata if known
- publication_date
- retraction_status if known
- citation metadata if available
- review_notes
- retrieval_weight configurable

Ranking may use policy weights, but UI/data must preserve the underlying attributes.

A YouTube lecture may be valuable as:
- interpretation,
- educational framing,
- reference discovery,
- intellectual context,
without automatically being treated as primary scientific evidence.

======================================================================
19. MEDIA ASSETS
======================================================================

Keep binaries outside PostgreSQL.

Initial local storage abstraction; later S3/MinIO/R2/Azure Blob compatible.

Store:
- book covers
- portraits when lawful/provenance-aware
- directly accessible paper PDFs
- first-page renders
- source thumbnails
- canonical Ayin diagrams/images if rights permit
- ritual media metadata later

knowledge.media_assets:
- id
- owner_type
- owner_id
- media_type
- storage_key
- source_url
- mime_type
- width
- height
- byte_size
- sha256
- license
- attribution
- status

Deduplicate by SHA-256.

Never bypass paywalls/access controls.

======================================================================
20. RETRIEVAL CHUNKS
======================================================================

Raw source segments and retrieval chunks are different.

Create:

retrieval.chunks
- id
- corpus_zone
- source_kind
- source_id
- parent_chunk_id nullable
- start_segment_id nullable
- end_segment_id nullable
- canon_passage_start_id nullable
- canon_passage_end_id nullable
- text
- normalized_text
- language
- section_title
- token_count
- content_hash
- discourse_type nullable
- metadata JSONB

Chunking:
- preserve semantic coherence
- preserve exact provenance
- use sentence/paragraph/topic/speaker boundaries
- configurable overlap
- roughly 300–700 tokens as an initial target, not a hard rule

For canonical Ayin material, preserve chapter/section hierarchy.

For external videos, preserve timestamp expansion.

======================================================================
21. MULTILINGUAL SEARCH NORMALIZATION
======================================================================

Preserve raw text.

Create separate normalized search forms.

Persian/Arabic:
- normalize common Arabic/Persian character variants for retrieval
- handle zero-width characters carefully
- optionally maintain diacritic-stripped search form
- preserve original diacritics/text separately

Latin:
- case-fold appropriate search forms
- transliteration aliases where approved

Exact identifiers:
- DOI
- ISBN
- OpenAlex IDs
must support exact lookup independent of language.

Do not apply English stemming assumptions to Persian/Arabic.

======================================================================
22. EMBEDDING REGISTRY
======================================================================

Create:
retrieval.embedding_models
retrieval.chunk_embeddings

Version:
- provider
- model
- dimensions
- distance metric
- language capability
- parameters

Support multilingual embeddings.

Do not tie the database permanently to one embedding model.

Cache by:
content_hash + embedding_model_version

Re-embedding with a new model must not alter raw/canonical text.

======================================================================
23. HYBRID RETRIEVAL — IMPORTANT REDESIGN
======================================================================

Do NOT put AYIN_CANON and EXTERNAL knowledge into one flat ranking and assume the top score should define the lecture.

They have different roles.

Implement a multi-lane retrieval system.

LANE A — AYIN CANON RETRIEVAL
Purpose:
determine what Ayin actually says.

Methods:
- exact concept lookup
- distinction lookup
- canonical passage FTS
- semantic search
- relation graph expansion

LANE B — MANASEK RETRIEVAL
Purpose:
find approved experiential/ritual relations where relevant.

LANE C — EXTERNAL KNOWLEDGE RETRIEVAL
Purpose:
research evidence, parallels, criticism, examples, and references.

LANE D — COUNTEREVIDENCE / ALTERNATIVE RETRIEVAL
Purpose:
actively seek tension, criticism, alternative explanations, contradictory evidence, or boundary cases.

Within each lane use:
- lexical FTS
- dense pgvector
- entity/concept lookup
- metadata filters
- RRF
- reranker

Do not use a single raw cross-corpus vector score to decide philosophical authority.

======================================================================
24. HYBRID RETRIEVAL ALGORITHM
======================================================================

Create:

LexicalRetriever
DenseRetriever
EntityRetriever
CanonicalAyinRetriever
RitualRetriever
ExternalEvidenceRetriever
CounterEvidenceRetriever
FusionService
Reranker
ContextExpander

Suggested within-lane flow:

query
→ lexical top N
+ dense top N
+ entity matches
→ RRF
→ top candidates
→ reranker
→ context expansion

All N values configurable.

Return complete provenance:
- source
- creator
- title
- URL
- page/timestamp
- chunk IDs
- matched concepts
- lexical rank
- dense rank
- fusion score
- reranker score

======================================================================
25. AYIN SPINE — REQUIRED FOR EVERY AYIN LECTURE
======================================================================

Before external research, generate a typed AyinSpine.

content.ayin_spines:
- id
- lecture_project_id
- canon_version_id
- primary_concept_id
- secondary_concept_ids
- central_human_question
- canonical_question
- core_principle_ids
- required_distinction_ids
- open_question_ids
- discourse_types
- prohibited_conflations
- optional_ritual_links
- created_at

Pydantic conceptual example:

{
  "central_human_question": "...",
  "primary_concept_ids": [...],
  "secondary_concept_ids": [...],
  "core_principle_ids": [...],
  "required_distinction_ids": [...],
  "open_question_ids": [...],
  "research_questions": [...],
  "prohibited_conflations": [...]
}

No Ayin lecture proceeds to external research unless the Ayin Spine is valid.

Ayin Spine must be grounded in canonical Ayin passages.

======================================================================
26. LECTURE TYPES
======================================================================

Support distinct lecture types instead of forcing every episode into one template.

Examples:

FOUNDATION
Explain one core Ayin concept/distinction.

HUMAN_QUESTION
Begin with a lived question and interpret it through Ayin.

DIALOGUE
Place Ayin in dialogue with a thinker/research field.

APPLICATION
Apply Ayin carefully to family, relationships, work, migration, society, illness, technology, AI, etc.

OPEN_QUESTION
Explore a question Ayin intentionally leaves unresolved.

CRITIQUE
Present a serious challenge to an Ayin idea and examine it.

RITUAL_COMPANION
Explain the conceptual background of a ritual without replacing the ritual.

REFERENCE_DEEP_DIVE
Explore a book/paper/researcher because it illuminates an Ayin question.

All types still require an Ayin Spine.

======================================================================
27. LONG-TERM CONTENT STRATEGY
======================================================================

Do not generate random topic lists.

Create a curriculum/content graph.

Content axes may include:

A. AYIN CONCEPT
- Emtedad
- Bon
- Jan
- awareness
- self-awareness
- Tahigah
- conditions
- pattern
- direction
- Majal
- change
- suffering
- vitality
- acceptance
- Other
- Between
- ethics
- emergence
- causality
- death
- Horizontal Emtedad
- open questions

B. HUMAN DOMAIN
- self
- family
- romantic relationship
- parenting
- friendship
- work
- migration
- poverty/class
- society
- illness
- grief
- creativity
- technology
- AI
- death
- community

C. LECTURE ANGLE
- definition
- distinction
- human question
- empirical dialogue
- philosophical dialogue
- criticism
- boundary case
- application
- story/example
- open question

D. RITUAL RELATION
Optional:
- relevant gate
- relevant ritual family
- relevant stage
- none

Create:
content.topic_graph
content.topic_relations
content.series
content.series_items

Topic recommendation should optimize:
- conceptual coverage
- continuity
- novelty
- audience progression
- unanswered questions
- evidence availability
- previously published content

Do NOT automatically equate the seven ritual stages with lecture progression.

======================================================================
28. RESEARCH PLANNER
======================================================================

Given AyinSpine, create ResearchPlan:

- what must be established from Ayin canon?
- what empirical questions arise?
- what philosophical questions arise?
- what external concepts may be analogous?
- what must NOT be conflated?
- which references should be sought?
- what counterarguments should be sought?
- whether Manasek is relevant
- what cultural adaptation may later be needed

Research questions should be narrower than the lecture topic.

Example:

Lecture question:
"Why do I repeat reactions I dislike?"

Ayin Spine:
Pattern + Conditions + Majal + Change

Research questions:
- what does learning research say about repeated responses?
- what role does context play?
- what does psychotherapy literature say about insight versus behavioral change?
- what evidence challenges overly individual explanations?
- which findings are only analogies and do not prove Ayin concepts?

======================================================================
29. RESEARCH PACKAGE V2
======================================================================

Create a typed immutable snapshot:

content.research_packages
- id
- lecture_project_id
- ayin_spine_id
- canon_version_id
- ritual_version_id nullable
- retrieval_config_version
- created_at

ResearchPackage should contain:

- Ayin canonical passages
- Ayin concepts
- required distinctions
- principles
- open questions
- external passages
- external people
- external works
- external claims
- empirical evidence
- counterevidence
- alternative explanations
- conceptual parallels
- tensions
- ritual links
- media assets
- citation records
- unresolved issues
- retrieval metadata

Do not let the writer query arbitrary databases after the package is frozen unless a new package version is created.

This makes generation reproducible.

======================================================================
30. EPISTEMIC EVIDENCE CLASSIFIER
======================================================================

Before writing, classify each candidate item.

For every item determine:
- source type
- source role
- discourse relevance
- evidentiary role
- confidence
- applicable scope
- whether it can support a factual sentence
- whether it is only illustrative/parallel
- whether it challenges the Ayin framing

The classifier must explicitly prevent:
"related paper" → "science proves Ayin".

======================================================================
31. SEMANTIC MASTER LECTURE
======================================================================

Create a semantic master BEFORE language realization.

content.lecture_master_versions:
- id
- lecture_project_id
- ayin_spine_id
- research_package_id
- status
- version
- created_at

The semantic master is structured, not a supposedly language-neutral essay.

It should contain:

- title intent
- central human question
- thesis/central Ayin movement
- argument steps
- concept IDs
- principle IDs
- distinction IDs
- external evidence IDs
- counterargument IDs
- examples
- open-question handling
- ritual relation if any
- conclusion intent
- statement-level citation bindings
- mandatory uncertainty language
- forbidden claims
- target duration
- audience profile

This is the semantic contract shared by FA/EN/AR.

======================================================================
32. LECTURE ARGUMENT GRAMMAR
======================================================================

Default shape, flexible rather than mandatory:

1. HUMAN ENTRY
A concrete question, tension, image, or experience.

2. AYIN OPENING
Introduce the relevant Ayin concept/distinction.

3. DEEPENING
Show how the concept reorganizes the question.

4. DIALOGUE WITH KNOWLEDGE
Bring external research/thinkers into dialogue.

5. TENSION / LIMIT
Show what the evidence does not establish.
Include relevant criticism or alternative interpretation.

6. RETURN TO AYIN
Clarify what Ayin adds: conceptually, ethically, or as an open question.

7. RETURN TO LIFE
A reflection, question, or ordinary-life implication.

8. OPTIONAL EXPERIENTIAL BRIDGE
Only when genuinely relevant:
link to an approved ritual/reflection.

Not every lecture requires all eight sections.

Do not produce formulaic repetition.

======================================================================
33. STATEMENT-LEVEL CITATION GRAPH
======================================================================

Create:

content.lecture_claims
- id
- lecture_master_version_id
- stable_key
- claim_intent
- discourse_type
- epistemic_status

content.lecture_claim_evidence
- lecture_claim_id
- evidence_type
- evidence_id
- relation_type
- required_for_publication

content.lecture_sections
content.lecture_section_claims

Every external factual claim should be traceable.

Every Ayin definition should trace to:
- concept version
- principle/distinction
- canonical passage

Every optional metaphysical statement must be labeled as such.

======================================================================
34. THREE-LANGUAGE STRATEGY
======================================================================

The system publishes one lecture identity in three language realizations:

FA
EN
AR

Create:

content.lecture_localizations
- id
- lecture_master_version_id
- language
- locale
- version
- status
- script_text
- title
- description
- terminology_registry_version
- localization_notes
- created_at

Statuses:
- draft
- terminology_review
- citation_review
- approved
- published
- retired

The localization is NOT allowed to modify:
- core concept relations
- lecture thesis
- evidence meaning
- epistemic status
- citation binding
- open-question status

It MAY adapt:
- idioms
- examples
- sentence rhythm
- cultural references
- explanatory glosses

If a localized example introduces a new factual claim, it needs its own evidence.

======================================================================
35. CORE EVIDENCE VS LOCALIZED ENRICHMENT
======================================================================

Use two evidence layers.

CORE EVIDENCE
Shared across all language versions.
It supports the master lecture.

LOCALIZED ENRICHMENT
Optional language/culture-specific:
- literary example
- regional history
- locally familiar analogy
- locally relevant source

Localized enrichment must:
- not contradict the semantic master;
- have provenance;
- be separately reviewable;
- never redefine an Ayin concept.

======================================================================
36. TERMINOLOGY QA
======================================================================

Implement TerminologyValidator.

For every localized script:
- identify all Ayin core terms
- verify preferred form
- check first-use gloss requirements
- detect forbidden equivalents
- detect inconsistent transliteration
- detect drift in definitions
- detect accidental theological/scientific redefinition

Produce a QA report.

Critical terminology failures block publication.

======================================================================
37. TRANSLATION / LOCALIZATION FIDELITY QA
======================================================================

Do not evaluate translation only by sentence similarity.

Create structured checks:

- every master claim represented?
- every uncertainty preserved?
- every optional-metaphysical label preserved?
- every distinction preserved?
- every citation still attached to the same claim?
- any factual addition?
- any factual omission?
- any stronger certainty introduced?
- any weaker safety language?
- any ritual instruction altered materially?

Use concept/claim IDs to compare translations.

======================================================================
38. RITUAL CONNECTION IN LECTURES
======================================================================

Ritual linking is OPTIONAL.

Create:

content.lecture_ritual_links
- lecture_master_version_id
- ritual_version_id
- relation_type
- explanation
- approved

Possible relations:
- experiential_companion
- related_gate
- related_life_ritual
- related_between_ritual
- reflection_only

Lecture writers must not invent a new ritual just because the topic has a symbolic similarity.

Use only approved ritual material for direct Manasek recommendations unless the user explicitly creates a new draft ritual.

======================================================================
39. SEPARATE RITUAL-GENERATION WORKFLOW
======================================================================

If later implementing ritual drafting, create a dedicated workflow:

conceptual intent
→ approved Ayin concept retrieval
→ approved Manasek pattern retrieval
→ draft
→ RitualSafetyValidator
→ philosophical fidelity validator
→ human review
→ localization
→ localized safety validation
→ approval

Never route ritual generation through the ordinary lecture writer.

======================================================================
40. LECTURE WORKFLOW
======================================================================

Implement as LangGraph-compatible workflow, but avoid unnecessary autonomous agents.

Nodes:

1. TopicIntake
2. AyinSpineBuilder
3. AyinSpineValidator
4. ResearchPlanner
5. AyinCanonRetriever
6. ExternalEvidenceRetriever
7. CounterEvidenceRetriever
8. OptionalRitualRetriever
9. EvidenceClassifier
10. ResearchPackageBuilder
11. LectureArchitect
12. SemanticMasterWriter
13. CitationBinder
14. AyinFidelityValidator
15. EpistemicValidator
16. CitationCoverageValidator
17. PersianLocalizer
18. EnglishLocalizer
19. ArabicLocalizer
20. TerminologyValidator
21. LocalizationFidelityValidator
22. OptionalRitualSafetyValidator
23. FinalEditorialReport

These are workflow roles/nodes.
They do NOT have to be 23 different model calls.

Optimize by:
- deterministic code where possible;
- batching;
- shared model calls;
- cached outputs;
- skipping unchanged stages.

======================================================================
41. AYIN FIDELITY VALIDATOR
======================================================================

Implement structured checks.

Flag:
- Bon = personality
- Bon = soul as mandatory definition
- Jan = intelligence
- Jan = consciousness
- Pattern = identity
- Acceptance = surrender
- Majal = freedom outside causality
- ritual gate = component of Bon
- five gates = metaphysical elements
- collective ritual = compressed individual sequence
- Return = sixth gate
- intense experience = proof
- another person = role in protagonist's story only
- metaphysical interpretation = general canonical fact
- science = automatic proof of Ayin

The validator should cite the canonical rule violated.

======================================================================
42. COUNTERARGUMENT REQUIREMENT
======================================================================

For substantial lectures, ResearchPackage should normally include at least one of:
- counterargument
- competing theory
- alternative explanation
- boundary case
- unresolved question

Exceptions:
- very short introductory lecture
- purely definitional glossary content
- approved special format

Store the reason when counterevidence is omitted.

The final lecture need not turn into a debate, but the writing process should know what the strongest tension is.

======================================================================
43. HUMAN REVIEW / EDITORIAL GOVERNANCE
======================================================================

AI may automate:
- ingestion
- extraction
- resolution candidates
- retrieval
- draft relation proposals
- draft lectures
- draft translations

AI must NOT autonomously finalize:
- changes to Ayin concept definitions
- new canonical principles
- deletion of canonical distinctions
- final translations of key philosophical terms
- changes to ritual safety rules
- canonical Manasek revisions
- metaphysical status changes

Add approval fields and audit logs.

======================================================================
44. CANON REVISION WORKFLOW
======================================================================

Because Ayin is designed to remain revisable:

draft proposal
→ source/reason
→ affected concepts
→ affected distinctions
→ affected rituals
→ affected term translations
→ impact analysis
→ editorial review
→ new canon version
→ old version retained
→ optional lecture stale-analysis

Implement:
"which published lectures rely on a concept definition that has changed?"

This must be queryable.

======================================================================
45. STALENESS / IMPACT ANALYSIS
======================================================================

When:
- Ayin canon changes
- ritual version changes
- source is retracted
- external paper metadata changes
- reference resolution is corrected

mark dependent artifacts as potentially stale.

Create dependency graph / materialized dependency records.

Do not silently rewrite old published lectures.
Store their original pinned versions and optionally schedule review.

======================================================================
46. LECTURE SERIES / LONG-TERM PUBLISHING
======================================================================

Create publication planning tables:

content.series
content.series_items
content.editorial_calendar
content.publication_channels
content.publications

One conceptual lecture may have:
- FA publication
- EN publication
- AR publication

with separate:
- title
- thumbnail
- publication date
- description
- voice/video assets
- status

The conceptual identity remains shared.

======================================================================
47. RAG ANSWERING VS LECTURE GENERATION
======================================================================

These are separate use cases.

GENERAL RAG
May answer questions across the knowledge base.

AYIN RAG
Must distinguish:
- "According to Ayin..."
- "External research says..."
- "A possible relation is..."
- "This remains open..."

LECTURE RAG
Must follow Ayin-first pipeline and semantic master workflow.

Do not let generic chat RAG rules control lecture generation.

======================================================================
48. RESEARCH SNAPSHOTS AND REPRODUCIBILITY
======================================================================

Store:
- query text
- filters
- retrieval config
- embedding model
- reranker model
- retrieved IDs
- ranks/scores
- retrieval date
- canon version
- external source versions

A lecture should be reproducible from its ResearchPackage snapshot even if indexes later change.

======================================================================
49. CACHE / COST OPTIMIZATION
======================================================================

Optimize recurring AI cost.

Cache by deterministic hashes.

Cache:
- transcript extraction
- normalized windows
- LLM extraction
- entity resolution
- concept linking
- embeddings
- reranking where appropriate
- ResearchPackage
- semantic master
- translations when inputs unchanged
- QA reports when dependencies unchanged

Recompute only when dependencies change.

Do NOT send entire corpora to LLMs.

Use retrieval first.

======================================================================
50. POSTGRESQL + PGVECTOR
======================================================================

Canonical store:
PostgreSQL 17.

Use:
- relational constraints
- JSONB for flexible provider metadata only
- pgvector for dense retrieval
- PostgreSQL FTS for lexical retrieval
- pg_trgm for fuzzy name/title lookup if useful

Qdrant:
do NOT introduce initially.

Provide retriever interfaces so a dedicated vector engine can be added later.

PostgreSQL remains the source of truth.

======================================================================
51. MULTILINGUAL RAG EVALUATION
======================================================================

Create a gold evaluation set for FA/EN/AR.

Include:
- exact concept queries
- paraphrased concept queries
- names/titles
- cross-language names
- distinction traps
- optional-metaphysical traps
- ritual safety traps
- external evidence questions
- counterargument questions

Metrics:
- Recall@k
- MRR/nDCG where useful
- citation correctness
- concept fidelity
- distinction fidelity
- evidence role correctness
- localization semantic fidelity
- terminology accuracy

Do not optimize only for embedding benchmark scores.

======================================================================
52. CONTENT QUALITY METRICS
======================================================================

Create evaluation reports per lecture.

At minimum:

AYIN_FIDELITY
0–1 or pass/fail dimensions:
- concepts correct
- distinctions preserved
- epistemic types preserved

EVIDENCE_QUALITY
- evidence relevance
- evidence role correctness
- claim coverage
- counterargument coverage

CITATION_QUALITY
- factual claim citation coverage
- canonical concept provenance
- citation/source match

MULTILINGUAL_FIDELITY
- semantic master coverage
- terminology consistency
- certainty preservation

RITUAL_SAFETY
- only if ritual content exists

STYLE
- separate from factual correctness

Do not collapse everything into one opaque score.

======================================================================
53. INITIAL EXTERNAL INGESTION: YOUTUBE
======================================================================

Implement YouTube first behind an adapter.

Input:
- video URL/ID
- later channel URL

Flow:
1. discover source
2. metadata
3. transcript
4. immutable timestamped segments
5. normalization
6. extraction windows
7. cached structured extraction
8. entities/references/claims
9. resolution
10. media enrichment
11. retrieval chunks
12. FTS
13. embeddings
14. readiness status

No creator-specific table or path.

The current pilot video may be used as a test fixture/config example, but never hard-coded throughout the application.

======================================================================
54. EXTERNAL EXTRACTION
======================================================================

Extract:
- people
- books
- papers
- studies
- organizations
- theories/concepts
- explicit claims
- quotations where identifiable
- references
- relations

Store:
- exact surface text
- segment IDs
- timestamps
- confidence
- extraction run

Do not ask the LLM to invent bibliographic metadata.

======================================================================
55. CODEX CLI PROVIDER
======================================================================

Implement generic LLMProvider interface.

Implement CodexCliProvider for the current workflow.

Use non-interactive `codex exec`.

Requirements:
- structured output/schema
- timeouts
- no shell=True
- no secrets in logs
- cache by input hash + task + prompt version + provider/model config
- retry failed windows independently
- reuse successful cached windows

Do not require an OpenAI API key for a ChatGPT-authenticated Codex CLI workflow.

Do not hard-wire the application to Codex.

======================================================================
56. STORAGE EFFICIENCY
======================================================================

Design for thousands of videos.

Use:
- streaming downloads
- batch DB inserts
- batch embeddings
- SHA hashes
- media dedup
- canonical entity dedup
- extraction caching
- pagination
- incremental indexing

Do not:
- store media as BLOBs
- load full corpus into RAM
- repeat LLM calls for unchanged material
- create duplicate works per mention
- create duplicate person records per channel

======================================================================
57. IDEMPOTENCY
======================================================================

Every stage is safe to rerun.

Examples:
same source hash
→ do not re-ingest raw content

same extraction input hash + prompt/model
→ reuse extraction

same chunk hash + embedding model
→ reuse embedding

same media SHA
→ reuse asset

same ResearchPackage dependencies
→ reuse package

Use stage state + hashes, not file-existence hacks alone.

======================================================================
58. PIPELINE STATE
======================================================================

For external source ingestion:
- discovered
- metadata_ingested
- content_ingested
- normalized
- extracted
- resolved
- enriched
- chunked
- embedded
- indexed
- ready
- failed

For lecture:
- idea
- ayin_spine
- researching
- research_ready
- master_draft
- master_review
- localization
- qa
- approved
- published
- retired

For canon:
- draft
- review
- approved
- superseded
- deprecated

======================================================================
59. API
======================================================================

FastAPI endpoints/services should include:

System:
- health
- job status

Canon:
- canon versions
- concepts
- distinctions
- principles
- open questions
- terminology

Ritual:
- ritual families
- gates
- stages
- ritual lookup
- concept→ritual links

External knowledge:
- source
- entity
- work
- reference
- claim

Retrieval:
- generic search
- Ayin canon search
- external hybrid search
- counterevidence search

Research:
- create ResearchPlan
- create ResearchPackage
- inspect package

Lectures:
- create lecture project
- build Ayin Spine
- generate semantic master
- localize
- QA report
- publication package

Business logic stays out of route handlers.

======================================================================
60. PROJECT STRUCTURE
======================================================================

Use approximately:

app/
  api/
  core/
    ayin/
    terminology/
    canon/
    config/
  knowledge/
    ingestion/
    extraction/
    resolution/
    evidence/
    media/
  ritual/
    models/
    repository/
    safety/
    localization/
  retrieval/
    chunking/
    lexical/
    dense/
    entity/
    fusion/
    reranking/
    evaluation/
  research/
    planner/
    package/
    evidence_classifier/
  lectures/
    spine/
    architecture/
    master/
    citations/
    localization/
    validators/
    publishing/
  db/
    models/
    repositories/
    migrations/
  ops/
    jobs/
    cache/
    logging/
    audit/

alembic/
tests/
  unit/
  integration/
  retrieval/
  fidelity/
storage/
scripts/
docker-compose.yml
Dockerfile
pyproject.toml
.env.example
README.md

Adapt intelligently to the existing repo.

Do not mechanically duplicate equivalent modules.

======================================================================
61. TESTING
======================================================================

Add tests for:

CANON
- approved versions immutable
- version pinning
- concept version retrieval
- distinction integrity
- open-question status
- discourse type persistence

TERMINOLOGY
- preferred term
- forbidden equivalent detection
- multilingual alias lookup

RITUAL
- Return is not a sixth gate
- seven stages × five gates mapping
- collective architecture separate
- safety-rule enforcement
- ritual concept links
- stop/exit/consent language preservation

INGESTION
- source idempotency
- raw transcript preservation
- timestamp provenance
- reference dedup
- cache reuse

RETRIEVAL
- Ayin canon lane
- external lane
- counterevidence lane
- hybrid RRF
- parent expansion
- multilingual retrieval
- filters

LECTURE
- Ayin Spine required
- canonical grounding required
- external source cannot redefine concept
- counterargument retrieval
- ResearchPackage immutability
- claim/evidence mapping
- citation coverage

MULTILINGUAL
- semantic claim preserved FA/EN/AR
- uncertainty preserved
- terminology preserved
- optional metaphysical status preserved
- no new unsupported claims

STALE DEPENDENCY
- canon revision marks dependent lecture for review
- source correction marks relevant research package stale

======================================================================
62. IMPORTANT DATABASE CONSTRAINTS
======================================================================

Use real relational integrity.

Do not create dangling generic owner IDs without strategy.

Prefer:
- typed relation tables where important;
- entity registry only if necessary and carefully constrained.

Use:
- FK
- unique constraints
- check constraints
- explicit cascade rules
- partial indexes
- GIN/GiST/HNSW/IVFFlat only where justified

Document important indexes.

======================================================================
63. HUMAN-FACING REVIEW QUEUES
======================================================================

Create review queues for:

- uncertain entity resolution
- proposed Ayin↔external relation
- key terminology translation
- canon revision
- ritual change
- lecture fidelity failure
- citation gap
- localization drift
- source contradiction/retraction impact

The system should make ambiguity visible, not hide it.

======================================================================
64. README REQUIREMENTS
======================================================================

Document:

- project mission
- why Ayin canon is separate from external knowledge
- why Manasek is separate from lecture content
- corpus zones
- database schemas
- setup
- Docker
- migrations
- Codex CLI
- ingest a YouTube source
- ingest Ayin canon document
- ingest Manasek canon
- inspect concepts
- build embeddings
- hybrid search
- build Ayin Spine
- create ResearchPackage
- generate lecture master
- localize to FA/EN/AR
- run validators
- publish package
- canon revision workflow
- staleness workflow
- known limitations
- roadmap

Include Mermaid architecture diagrams.

======================================================================
65. LONG-TERM SYSTEM ARCHITECTURE
======================================================================

Conceptually:

                  AYIN CANONICAL CORE
            concepts / distinctions / principles
             ethics / open questions / terms
                         │
                         │ governs
                         ▼
              ┌──────────────────────┐
              │     AYIN SPINE       │
              └──────────┬───────────┘
                         │
                research questions
                         │
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
     MANASEK        EXTERNAL KNOWLEDGE  COUNTEREVIDENCE
   experiential      papers/books/      criticism/
   companions        creators/etc.      alternatives
         │               │                │
         └───────────────┼────────────────┘
                         ▼
                 RESEARCH PACKAGE
                         ▼
                 SEMANTIC MASTER
                         ▼
             philosophical/epistemic QA
                         ▼
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       Persian         English         Arabic
          │              │              │
     terminology     terminology     terminology
     + fidelity      + fidelity      + fidelity
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                  PUBLICATION PACKAGE

External knowledge NEVER replaces Ayin Canon.
Manasek NEVER becomes proof of Ayin.
Lecture output NEVER becomes canon automatically.

======================================================================
66. IMPLEMENTATION PHASES
======================================================================

PHASE 0 — REPOSITORY AUDIT
- inspect current scraper/pilot
- inspect DB/code/tests
- identify reusable components
- identify obsolete assumptions
- produce concise migration plan

PHASE 1 — PLATFORM FOUNDATION
- PostgreSQL 17 + pgvector
- Docker Compose
- SQLAlchemy
- Alembic
- schemas/namespaces
- config
- logging
- storage abstraction
- core tests

PHASE 2 — AYIN CANON
- canon documents/versions/passages
- concepts
- concept versions
- distinctions
- principles
- open questions
- discourse types
- terminology registry
- import command
- initial tests

PHASE 3 — MANASEK
- ritual families
- five gates
- seven stages
- Return
- collective architecture
- ritual versions
- concept links
- safety rules
- import command
- validators

PHASE 4 — EXTERNAL KNOWLEDGE INGESTION
- generic adapters
- YouTube first
- transcript preservation
- extraction
- claims
- references
- resolution
- media

PHASE 5 — RETRIEVAL
- chunks
- multilingual normalization
- FTS
- pgvector
- model registry
- lane-specific retrievers
- RRF
- reranker
- context expansion

PHASE 6 — AYIN↔EXTERNAL DIALOGUE
- relation taxonomy
- evidence classifier
- review queue
- counterevidence support

PHASE 7 — RESEARCH ENGINE
- Ayin Spine
- ResearchPlan
- retrieval orchestration
- frozen/versioned ResearchPackage

PHASE 8 — LECTURE MASTER
- lecture types
- argument architecture
- statement-level claim/citation graph
- Ayin fidelity validator
- epistemic validator
- citation validator

PHASE 9 — THREE LANGUAGES
- FA/EN/AR localizations
- terminology QA
- localization fidelity QA
- localized enrichment
- publication states

PHASE 10 — CONTENT STRATEGY / PUBLISHING
- topic graph
- series
- coverage analysis
- publishing channels
- publication package
- stale-content review

PHASE 11 — EVALUATION
- retrieval gold set
- lecture fidelity fixtures
- multilingual test set
- ritual safety tests
- benchmark command/report

After every phase:
- run tests
- fix failures
- show changed files
- document commands
- keep app runnable

======================================================================
67. END-TO-END ACCEPTANCE TEST
======================================================================

The platform is not complete unless it can demonstrate:

A. CANON
1. ingest/version Ayin canonical PDF/text;
2. extract/store exact passages;
3. create/retrieve Ayin concepts/distinctions/principles;
4. preserve discourse types;
5. version terminology.

B. MANASEK
6. ingest/version Manasek;
7. represent five gates;
8. represent seven individual stages;
9. represent seven Returns;
10. preserve Return as not a sixth gate;
11. preserve separate collective architecture;
12. run ritual safety validator.

C. EXTERNAL KNOWLEDGE
13. ingest a YouTube video;
14. preserve timestamps;
15. extract references/people/claims;
16. resolve books/papers/people;
17. cache extraction;
18. deduplicate canonical references;
19. store media provenance.

D. RETRIEVAL
20. search Ayin canon;
21. search external knowledge;
22. search counterevidence;
23. run multilingual hybrid retrieval;
24. return exact provenance.

E. LECTURE
25. create lecture topic;
26. build canonical Ayin Spine;
27. produce ResearchPlan;
28. retrieve external evidence + criticism;
29. create frozen ResearchPackage;
30. produce semantic master;
31. bind citations;
32. pass Ayin fidelity/epistemic/citation QA.

F. THREE LANGUAGES
33. generate Persian;
34. generate English;
35. generate Arabic;
36. run terminology QA;
37. run cross-language fidelity QA;
38. preserve citations;
39. produce publication package.

G. VERSIONING
40. change a canonical concept version in a test fixture;
41. verify dependent lecture is marked for review without rewriting history.

======================================================================
68. NON-NEGOTIABLE GENERATION RULES
======================================================================

Every Ayin lecture:
- has an Ayin Spine;
- is grounded in current pinned canon;
- keeps Ayin as conceptual center;
- distinguishes Ayin claims from external claims;
- names external references where relevant;
- preserves uncertainty;
- does not pretend external evidence proves metaphysics;
- includes counterevidence/limits when substantively appropriate;
- may link to Manasek only when conceptually justified;
- never turns ritual intensity into truth;
- can exist in FA/EN/AR without concept drift.

Every language version:
- refers to same lecture master;
- preserves concept IDs;
- preserves claim IDs;
- preserves epistemic status;
- preserves citations;
- passes terminology QA.

Every ritual:
- remains optional;
- preserves right to stop/leave;
- preserves non-interpretation;
- passes safety validation.

======================================================================
69. CODING STYLE
======================================================================

Use:
- Python type hints
- concise docstrings
- short explanatory comments for non-obvious logic
- focused functions/classes
- Pydantic schemas
- dependency injection where useful
- repository/service boundaries pragmatically
- structured logging
- explicit exceptions
- transactions
- tests

Avoid:
- huge god files
- fake tests
- swallowed exceptions
- premature microservices
- hard-coded creator/channel
- hard-coded pilot video
- hard-coded final translations of philosophical terms
- magic strings for critical statuses
- hidden LLM side effects

======================================================================
70. START NOW
======================================================================

First inspect the existing repository.

Then report briefly:
- what is reusable;
- what needs refactoring;
- what must be replaced;
- database migration implications;
- whether existing data can be migrated safely.

Then begin implementation.

Do NOT stop at recommendations.

Do NOT redesign Ayin's philosophy yourself.

Treat the current approved Ayin and Manasek source files as the authoritative project basis for the version being ingested, while preserving the project's explicit ability to revise them later.

Where a concept or translation is unclear:
- preserve ambiguity;
- mark for review;
- do not invent certainty.

Where external research conflicts with Ayin:
- store the conflict;
- do not suppress it;
- do not rewrite canon automatically.

Core implementation principle:

AYIN DEFINES THE QUESTION.
MANASEK OPENS AN EXPERIENTIAL DOOR.
EXTERNAL KNOWLEDGE ENTERS INTO DIALOGUE.
THE DATABASE PRESERVES PROVENANCE.
RAG RETRIEVES BY ROLE, NOT JUST SCORE.
THE LECTURE SYNTHESIZES WITHOUT CONFUSING EPISTEMIC LEVELS.
THE THREE LANGUAGES SHARE ONE SEMANTIC MASTER.
NOTHING BECOMES CANON WITHOUT EDITORIAL APPROVAL.

# Agent handoff: integrating the Ayin-e Emtedad curriculum and the continuity system

## 1. What was prepared (the files)

| File | What it is | How to use it |
|---|---|---|
| `Ayin_Emtedad_100_Dars.md` / `.docx` | 100 lessons in Persian, 16 chapters, in learning order. Each lesson has a level, prerequisites, body text and a "relationships to other lessons" section. 22 lessons are core concepts. | Human-readable master copy. Do not parse it at runtime; use the JSON files. |
| `lessons.json` | The same 100 lessons as structured data: `lesson_id, chapter, chapter_title_fa, order_in_chapter, level, title_fa, is_core_concept, prerequisites[], text_fa, relations_section_fa` | Seed the `lessons` table. |
| `lesson_relations.json` | 837 directed links: `from, to, is_prerequisite, explanation_fa`. The same relationship may appear in both directions. | Seed the `lesson_relations` table. This is the lesson graph. |
| `Channel_Memory_Spec_v2.md` | The optimized version of the owner's continuity prompt. | Architecture spec. Implement it. |
| `Ayin_Emtedad_200_Mazmoon.md` | An earlier 200-theme extraction. | Optional extra canon chunks for RAG. |

Lessons are grounded only in the book. The lesson text is the canon: it defines concepts, and nothing else may redefine them.

## 2. Optimization of the owner's original prompt (summary)

The original idea is kept: previous scripts are never a content source. What changes:

1. **Do not retrieve old script prose into generation at all.** "Retrieve it but don't use it" is not reliable, because models paraphrase whatever is in their context. Replace it with a structured **Channel Ledger** entry, extracted once per published video.
2. **Review references from the lesson graph after drafting, not by similarity.** Candidates are the prerequisites and related lessons of the current lesson that are already published. Similarity only breaks ties. Retain 0–2 references per video.
3. **Track examples, metaphors and hook types,** not just concepts. These are what viewers actually notice being repeated.
4. **Track forward promises** ("we'll cover this later") and make later videos fulfil them.
5. **Keep four roles separate.** The direct Lesson Content Package is the Ayin core, external RAG supplies ideas and facts but not redefinitions, the ledger supplies continuity only, and the published-script archive is checker-only.
6. **Standalone rule.** A reference is one sentence of fresh re-grounding plus the exact current title. It never assumes that the viewer knows the earlier video.
7. **Run automatic checks after generation.** Similarity against old scripts and against external sources, reference validity (the title must exist and be published), at most 2 references, concept fidelity against the locked definitions, and no forbidden repeats.
8. **Planning step.** Before writing, the model produces a "video brief" that answers the owner's 7 questions. Store the brief.
9. **Persona document and AI-avatar disclosure.**

Full details are in `Channel_Memory_Spec_v2.md`.

## 3. Storage proposal

Keep canon, generated content and memory in **separate stores**, so that retrieval can never mix them by accident.

### 3.1 Relational tables (Postgres or SQLite)

```
lessons(lesson_id PK, chapter, chapter_title_fa, order_in_chapter, level,
        title_fa, is_core_concept, text_fa, relations_section_fa)
lesson_prerequisites(lesson_id FK, prereq_id FK)
lesson_relations(from_id FK, to_id FK, is_prerequisite, explanation_fa)
concepts(term_fa PK, core_lesson_id FK, locked_definition_fa)
      -- 22 core concepts; the definition comes from the core lesson

videos(video_id PK, lesson_id FK, status [planned|drafted|approved|published],
       current_title_fa, youtube_id, published_at, version)
video_briefs(video_id FK, brief_json, created_at)
script_versions(video_id FK, version, text_fa, created_at, is_final)
      -- archive: used ONLY by the post-generation checks
ledger_entries(video_id FK, concepts_json, core_claims_json, examples_json,
               metaphors_json, hook_type, references_json,
               forward_promises_json, open_questions_json)
promises(promise_id PK, made_in_video FK, target_lesson_id FK,
         text_fa, fulfilled_in_video FK NULL)
title_history(video_id FK, title_fa, valid_from)
```

### 3.2 Direct canon and separate vector collections

| Store | Content | Used by |
|---|---|---|
| Lesson canon JSON | Structured current lesson package plus selected locked core definitions | **Writer, loaded directly; never vector-retrieved** |
| Ayin source corpus/index | Full source passages and provenance | Audit, verification, canon revision, citations, and specialist research; **not ordinary script generation** |
| `external_chunks` | External sources, with metadata `source_id, url, license_note` | Writer (content, ideas only) |
| `script_archive_chunks` | Paragraphs of final scripts, with metadata `video_id` | **Checker only.** Never passed to the writer. |

The ledger is **not** vectorized or passed to the writer. Query it with SQL only
after drafting: already explained concepts, forbidden repeats from the last N
videos, and open promises become review findings or revision constraints.

### 3.3 Pipeline per video

1. Pick a lesson whose prerequisites are published, or that the owner chose.
2. Load the canonical Lesson Content Package directly; retrieve only `external_chunks` (hybrid search and reranking).
3. Planning call → `video_brief`, using generation inputs only.
4. Writing call → draft, stored in `script_versions`.
5. After drafting, collect review signals with SQL on the ledger and lesson graph: candidate references, what is already explained, forbidden repeats, and open promises.
6. Check against `script_archive_chunks`, external sources, the ledger, lesson relations, and locked definitions. Revise on failure without exposing archived prose to the writer.
7. Approve, produce the voice and avatar, and publish.
8. On publish: extract the ledger entry, update `promises` and `title_history`, and add the final script to `script_archive_chunks`.

**Important:** a draft becomes part of the memory (ledger and archive) only when it is **published**. Unpublished drafts must never be referenced.

The ordinary writer input is exactly:

```text
CANONICAL LESSON CONTENT
+ CORE CONCEPT REGISTRY
+ EXTERNAL RESEARCH
```

The Channel Ledger, Published Script Archive, and lesson relations are queried
only after drafting. The full Ayin book remains stored but is never ordinary
writer context. When a lesson already has a complete canonical explanation,
that explanation is the Ayin core; do not ask a model to create another seed.

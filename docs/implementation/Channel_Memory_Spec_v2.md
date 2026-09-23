# Channel memory and continuity system (v2)

## 1. Four sources, four roles

| Source | Role | May contribute content to the new script? |
|---|---|---|
| **A. Canonical Lesson Content Package** | Directly supplies the current lesson's approved Ayin core | **Yes, directly; never through vector retrieval** |
| **B. Ayin source corpus** | Intellectual origin, provenance, audit, lesson verification, revision and citations | **No** during ordinary script generation |
| **C. External Knowledge RAG** | Evidence, examples, perspectives, research | Yes, but as ideas and facts only, never as prose |
| **D. Channel Ledger + Published Script Archive** | What has already been said and how | **No.** Post-draft review only |

**Priority rule.** If an external source uses a concept differently from the canon (for example it equates جان with روح, or treats مجال as free will), the canon definition wins. The external material may be presented as another view, but it may not redefine the term.

## 2. The Channel Ledger: never feed old scripts into generation

Do not retrieve old script passages into the generation context at all. Telling a model "don't use this prose" is unreliable, because models paraphrase whatever is in their context.

Instead, when a video is **published**, run one extraction step that turns its final script into a structured ledger entry. Keep the full scripts in a separate archive that is used only for checking finished drafts (section 5).

```json
{
  "video_id": "YT_abc123",
  "lesson_id": "5.1",
  "current_title": "تهیگاه: پرسشی که از پیش پر نمی‌شود",
  "published_at": "2026-10-02",
  "concepts": [
    {"term": "تهیگاه", "depth": "full"},
    {"term": "بُن", "depth": "mentioned"}
  ],
  "core_claims": ["تهیگاه با بُن یکی نیست", "اشغال تهیگاه دیگری مرز قدرت را می‌شکند"],
  "examples_used": ["جملهٔ آرمان دربارهٔ اینکه نمی‌داند چیست"],
  "metaphors_used": ["جای خالی‌ای که نباید با زور پر شود"],
  "opening_hook_type": "question",
  "references_made": ["3.1"],
  "forward_promises": [{"lesson_id": "13.3", "text": "دربارهٔ نقش شاهد بعداً صحبت می‌کنیم"}],
  "open_questions_raised": ["آیا راهنما می‌تواند اصلاً بی‌طرف باشد؟"]
}
```

Why this is better:
- There is no prose in the entry, so there is nothing to recycle.
- Viewers notice repeated **examples, metaphors and hooks** more than repeated concepts. The ledger tracks exactly those.
- `forward_promises` lets the channel keep its word ("as I promised in…"). Nothing signals a real author more strongly.
- Titles live in one place. YouTube titles often change for click-through, so a reference always uses `current_title`, looked up by `video_id`.

## 3. Reviewing references: use the lesson graph, not similarity

After the first draft, the 100-lesson graph and Channel Ledger may be queried to
validate references or prepare explicit revision constraints. They are not
writer inputs. Apply these rules in the review stage:

1. **Candidates** = the prerequisites of the current lesson that are **already published**, plus the published lessons listed in its "relationship to other lessons" section.
2. **Rank** them: direct prerequisite > same chapter > cross-chapter relation. Semantic similarity is only a tie-breaker.
3. **Keep 0–2 references.** A revision may retain a reference only when the argument genuinely builds on the earlier idea.
4. **Handle unpublished prerequisites.** Flag an unpublished reference; a reviewed revision may re-ground the idea briefly or create a forward promise.
5. **Check open promises.** A reviewed revision may fulfil a matching promise explicitly: «در ویدیوی «…» قول دادم که…».

Similarity-only retrieval tends to produce references that sound plausible but add nothing. The graph already captures why two lessons are connected.

## 4. Generation context (what the writer model receives)

```
CURRENT_LESSON: {direct canonical Lesson Content Package}
LOCKED_DEFINITIONS: {canon definitions of every core concept that appears}
EXTERNAL_EVIDENCE: {retrieved chunks, each with source id}
VIDEO_BRIEF: (produced in a planning step before writing, see below)
```

Do not include raw Ayin-book retrieval, Channel Ledger data, lesson relations,
or Published Script Archive prose in this context. When the lesson package
already contains a complete conceptual explanation, that explanation is the
AYIN CORE; do not create another model-authored Ayin seed.

**Planning step (a separate call, run before writing).** Answer your seven questions as structured output, the "video brief", using only the three generation inputs. Save it with the video record, not the Channel Ledger. The brief makes the channel's direction explicit and can be reviewed later; the ledger entry is still created only after publication.

**Standalone rule.** Every video must still work for a first-time viewer. A reference therefore means one sentence of re-grounding in new words, plus the link. The reference must never assume knowledge the new viewer lacks.

## 5. Checks after generation (automatic, before voice and avatar)

Only at this stage query the Channel Ledger, Published Script Archive, and
lesson relations for continuity, promises, valid references, duplication, and
contradiction.

- **Self-plagiarism:** compare the draft with the old-scripts archive using embedding similarity per paragraph and n-gram overlap. Flag anything above a threshold.
- **Source plagiarism:** run the same check against the external sources. Transcripts of other channels are the biggest copyright risk in this pipeline.
- **Reference validity:** every title referenced must exist in the ledger and be published. The model may invent titles, so this check is needed.
- **Reference count:** at most 2. Remove any reference whose "why" is weak.
- **Concept fidelity:** check the draft against LOCKED_DEFINITIONS. For example, جان must not become intelligence or the soul, and مجال must not become the number of options. The integrity checklist in the book's closing chapter can serve as the checklist here.
- **Repetition:** no example, metaphor or hook type that appears in `forbidden_repeats`.

## 6. Persona consistency (the "real person" effect)

Cross-references alone do not make a channel feel human. Also keep a short, fixed **persona document**: the speaker's voice, typical sentence rhythm, a few recurring phrases (rationed), their stance toward uncertainty (the book's «نمی‌دانیم» fits well here), and how they open and close videos. Every generation call gets this document.

## 7. Disclosure

The speaker is an AI avatar. Tell viewers this: in the channel description, and with YouTube's synthetic-content label wherever it applies. Hiding it risks the platform's policies and the channel's credibility. It would also contradict the channel's own ethic of not claiming authority over another person's inner truth (تهیگاه). The strategy, the curation and the author are real, and the channel can say so openly.

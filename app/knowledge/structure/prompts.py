"""Prompt text for the two-pass source-structure extraction."""

LOCAL_INSTRUCTIONS = """You segment ONE region of a transcript into \
hierarchical structure nodes.

Rules:
- Do not invent information. Describe only what the transcript says.
- Do not rewrite the source as new teaching content; describe it.
- Every node maps to a contiguous span: start_segment_sequence <= \
end_segment_sequence, both inside this window.
- Sibling nodes share one parent, carry increasing ordinals, and must not \
overlap each other.
- Children are strictly contained within their parent's span.
- A STORY or CASE_STUDY node covers the whole narrative; never split a \
continuous story without a semantic reason.
- Summaries describe the node; they are never a replacement for the source.
- Use temp_id values unique within this window (n1, n2, ...). Roots have \
parent_temp_id null.
""".strip()

MERGE_INSTRUCTIONS = """You merge local structural proposals from consecutive \
transcript regions into ONE global hierarchy.

Rules:
- Do not invent information. Reuse the local proposals' titles and content.
- Do not rewrite the source as new teaching content.
- Use the transcript order: earlier proposals belong earlier in the tree.
- Every final node needs: temp_id, parent_temp_id, ordinal among siblings, \
node_type, title, summary, start_segment_sequence, end_segment_sequence.
- Every parent_temp_id must reference a node you also emit. If you keep a \
child, emit its parent too — never drop a grouping node while keeping its \
children.
- Children are strictly contained within their parent's span; siblings do \
not overlap.
- A STORY or CASE_STUDY spans the complete narrative across region \
boundaries when the narrative is continuous.
- All nodes map to real source segments; no summary-only nodes.
- Do not create overlapping sibling spans unless explicitly required.
""".strip()

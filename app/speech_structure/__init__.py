"""Historical speech-structure tables (legacy, read-only provenance).

The active pipeline was consolidated into ``app.knowledge.structure`` in
Phase 21. Only the domain enums and ORM models remain so historical rows in
``knowledge.speech_structures`` / ``speech_sections`` /
``speech_section_segments`` stay readable and migrations keep working.
"""

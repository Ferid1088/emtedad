# Phase 11 topic analysis persistence fix

The owner topic detail page was showing a fabricated first Ayin concept because
`save_topic` selected the first concept in sort order. The analysis form result
was also discarded, and the detail route passed a bare ORM row to a template
whose relationship fields did not exist. As a result, sources, works, people,
and overlap were always empty.

The fix stores a grounded `analysis_json` snapshot on the existing
`content.content_topics` record, makes the primary concept nullable, and uses
lexical matching over the stored Ayin ontology and external corpus. The route
now builds a dedicated detail view model and exposes **Analyse aktualisieren**;
this only refreshes topic associations and never starts research.

No ResearchProject, ResearchPackage, lecture, localization, or Canon record is
created or changed by topic analysis.

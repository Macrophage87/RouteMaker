# Round 7 — Access control / sign-in / privacy — REVISE (1 blocking)

Reviewed at `21a44b2` (the wave-5 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-6 disposition of every item is in `../../../handoff.md` §3.


All round-6 items closed by reversion (exact edits recorded; §7 closure row closed on the record).
Wave-5 choices weighed and upheld: no non-POST path logs out (OPTIONS → 200, row survives); the
ast walk's remaining blind spots are `from os import environ as E` (aliased) and non-literal keys,
none present today; the hostname posture is coherent end to end; bootstrap id to api alone;
bot token still scoped behind the profile; healthcheck widens no secret; run_rebuild_now is the
right phase-1 surface. Permission matrix re-derived with three clients over 13 changelists; seven
guild-admin writes all 403 with +1 refused row; ten listing query shapes, no oracle.

**B-1. JurisdictionAdmin uses GeoDjango's default OSMWidget.** Executed: the add/change pages
reference cdn.jsdelivr.net (OpenLayers 7.2.2, no SRI, no CSP) and emit `ol.source.OSM()`, i.e.
tile.openstreetmap.org. PLAN:15 "Do not use the public OpenStreetMap tile servers"; PLAN:52 the
widget "configured against the self-hosted basemap rather than its default"; PLAN:299 "the map
widget" is phase 1. Not in §7, docs, or tests. Surviving mutation: drop GISModelAdmin entirely →
2731 passed. Independent weight: an unpinned third-party script executes on the most privileged
page with the admin's session.

**SHOULD-FIX.** SF-1 the rebuild container mounts the WHOLE data volume (caddy/ TLS keys,
postgres/ PGDATA, backups/) and prepare_data_root.sh ends with `chown -R 10001:10001 "$DATA_ROOT"`
— re-run on a live host it hands the edge's private key and PGDATA to the rebuild's uid; narrow
the mount to the five directories the rebuild writes and chown per directory. SF-2
ConfiguredGuildAdmin.has_change_permission's docstring says every field is read-only; `name` and
`admin_contact_email` are editable (executed, audited), and PLAN:206/:212 put the contact address
at guild scope — narrower than the plan, unrecorded. SF-3 rollback_rebuild --confirm writes no
audit row (no module under pipeline/ or commands/ imports core.audit).

**NIT.** N-1 "four lines" vs five (= deployment S-2). N-2 aliased `environ` import invisible to
the walk. N-3 `<admin>/password_change/done/` answers 200 to a signed-in admin (only
password_change/ is overridden to 404).

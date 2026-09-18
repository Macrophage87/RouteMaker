# Round 5 — Routing engine / tile pipeline — REVISE (1 blocking, 4 should-fix)

Reviewed at `9601c34` (the wave-3 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-4 disposition of every item is in `../../../handoff.md` §3.


All round-4 items closed by reversion (22 mutations; SF3 under six independent ones); SF5 closed
by its §7 row. Every wave-3 judgment call accepted with the Valhalla premise verified against
3.5.1 source (argparse_utils.h:59-66 logging subtree; logging.cc std_out/std_err; adminbuilder.cc:373
reads mjolnir.admin; valhalla_build_timezones cats to stdout; skadi HGT_DIM; LIT table entry for
entry) — except the admin-source half (below).

**B-1. No producer for the source extract; FETCH_EXTRACT only checks existence.** ORCHESTRATOR
CONFIRMED (git grep: no geofabrik/osmium-extract/merge step anywhere; only pyosmium reads in
extract.py; settings.REBUILD_SOURCE_PBF read once; COVERAGE_BBOX is the only coverage shape).
PLAN:13: Geofabrik DC+MD+VA merged then `osmium extract -s smart -S types=any`; admins from the
MERGED extract before clipping. Consequences: first rebuild fails at FETCH_EXTRACT with no document
saying how to produce the file; every weekly rebuild re-derives from the same frozen snapshot (drift
report reads near-zero = "healthy"); tiles.py:164-165 cites PLAN:13 as endorsing admins from
context.source_pbf, which is the CLIPPED extract. Round-3 domain S8's "no osmium extract" half,
never given a §3 row.

**SHOULD-FIX.** S-1 `_least_grade_across_variants` min→max → 1590 passed (one variant's elevation
answers for three; FakeBinaries returns one grade for every variant). S-2 `_run_command` returning
`CommandOutput(stdout, "")` → 1590 passed (the production runner's stream split is unpinned; would
silently make assert_no_rule_violations inert). S-3 rm:bridge_bicycle=yes widens access with no
allowlist (executed: primary bridge bicycle=no + yes → bike_forward true; bicycle=dismount rewritten
to yes) — latent on today's data (all eight true rows OSM allows); = domain SF-2. S-4 post-swap
container restart lives only in DEVELOPMENT.md:180-184; not in OPERATIONS.md, no §7 row for the
blue/green half (PLAN:290), run.detail says nothing; routers serve build N−1 indefinitely.

**NIT.** N-a build_logs completeness guard unasserted (near-equivalent). N-b traffic_extract
reasoning depends on the file being absent: graphreader.cc:141-146 resets the ROUTING archive if
the traffic tar loads with no usable tiles; valhalla_build_extract -t writes exactly that path —
never pass -t; write it down. N-c timezone db check is is_file + nonzero size; upstream's
error_exit does not exit on geos 3.9.x so a partial db passes — query tz_world count or a size
floor. N-d valhalla_build_admins runs three times per rebuild (identical output).
Unverified: Docker re-resolving a replaced symlink bind source; sentinel edges snapping; GDAL
accepting .hgt.part; which binaries the pipeline image carries (no Dockerfile).

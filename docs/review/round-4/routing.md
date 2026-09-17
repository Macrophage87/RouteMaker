# Round 4 — Routing engine / tile pipeline — REVISE (2 blocking, 5 should-fix)

Reviewed at `66ccb03` (the wave-2 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-3 disposition of every item is in `../../../handoff.md` §3.


All round-3 items closed, each verified by reverting (B1 access allowlist: 5 mutations; B2 per-variant
tile dirs: 28 failed on TILE_ROOT revert; B3 SWAP stage: 16 failed; B4 elevation: 2+2; S1 key placed at
top-level additional_data.elevation per elevationbuilder.cc:318; S3 sentinel: 3 lua + 4 py; S4 gate
cost: 2+2; forbidden-key guard: 4; lua-path comparison: 1). S2 partially closed (names populated,
matcher only tested against names it was handed). S5 admins/timezones still open (SF3).

**B1. `trace_attributes` parses `stdout + stderr` as if the log came first.** ORCHESTRATOR
CONFIRMED against src_valhalla_service.cc:42-44 (`logging::Configure({{"type","std_err"}})`, response
on std::cout) and graphreader.cc:110 (LOG_INFO on tile_extract load — fires on the success path) plus
two LOG_WARNs from the traffic_extract key every generated config carries. `stdout + stderr` is JSON
first, log after; `json.loads(output[start:])` → Extra data. validate() calls sample_grade first →
RebuildFailed at VALIDATE on every fire. Same class as round-3 item 7, one stage later. Suite green
because tests/test_tiles.py:174 and rebuild_fixtures.py:268 both put the log BEFORE the JSON.

**B2. Bridge sidepath inherits the roadway's bicycle=no.** Same as domain B2 (in the domain fix
agent's scope). Reviewer adds: PLAN:68 says "per roadway or sidepath way" and one osm_names list per
row cannot express it; `if is_trail_class(way.tags): continue` → 945 passed (mutation survives).

**SF1** `rm:lit` derivation is `== "yes"`, flipping 24/7, automatic, dusk-dawn, sunset-sunrise that
upstream maps to true (vendored lua :414-423; pbfgraphparser.cc:1909); run.py:535 collapses the same
into the segment column. `!= "no"` → 945 passed; deleting the write → 945 passed. **SF2**
ROUTEMAKER-VIOLATION prefix is documented as asserted by validate() and nothing reads it (grep empty;
validate() passes on a violation-laden log). **SF3** valhalla_build_admins / valhalla_build_timezones
never run; `mjolnir.admin`/`timezone` are retargeted into the dated build dir nothing populates; 3.5.1
LOG_WARNs and continues (graphenhancer.cc:1293, graphbuilder.cc:431) so date_time.type:3 has no tz.
**SF4** elevation.py SUPPORTED_SIDES accepts 1201; skadi has `HGT_DIM = 3601` only (sample.cc:27,:74)
and logs "Corrupt elevation data"; rebuild_fixtures.py:232 defaults hgt_side to 1201. **SF5**
rm:reviewer_surface (PLAN:69) has no producer — overrides.py supports access/stress/jurisdiction only;
not in handoff §7.

**NIT** N1 assert_lua_script_was_loaded satisfied by first match across concatenated variant logs.
N2 remap_node maxwidth gsub reads "3'" as 3 and "1,5" as 15. N3 configured_paths omits landmarks,
traffic_extract, transit_dir, transit_feeds_dir (source of the two stderr warns in B1).

Notes: rm:bridge_bicycle can widen access (owner decision, disagreement recorded); cycleway=track +
bicycle=no on one way is cosmetically wrong only. Unverified: sentinel coordinates snap as intended;
Docker re-resolving a replaced symlink bind source.

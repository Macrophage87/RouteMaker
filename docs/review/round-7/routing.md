# Round 7 — Routing engine / tile pipeline — ACCEPT (0 blocking)

Reviewed at `21a44b2` (the wave-5 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-6 disposition of every item is in `../../../handoff.md` §3.


Round-6 B-1, SF-1 and the guard/volume NITs closed by reversion; SF-2 text corrected but the
docs mutation survives (no test reads the lines). Every wave-5 call upheld against upstream source
(io.cpp:178-186 -f registration in with_osm_output; ot_extract.cpp:492-506 ignores -f only under
--config; strategy_smart.cpp:66-103 `types=any` clears m_types; valhalla_build_admins.cc:28-57;
adminbuilder.cc:372-403; ot_merge.cpp:167-170 the multi-version warning). settings.py importing
pipeline.source not contested (AST: stdlib only; api image carries src). SpatiaLite row-count
question settled by execution: stock sqlite3 reads `admins` with the virtual SpatialIndex present.

**SHOULD-FIX.** SF-1 `_run_command` uses capture_output=True, check=True and nothing reads
CalledProcessError.stderr; source.py discards CommandOutput — every first-rebuild failure reports
argv + exit status only, the osmium multi-version warning that source.py:46-49 and OPERATIONS.md
:230-236 name as the detection mechanism is dropped, and the "Could not detect file format"
diagnosis in OPERATIONS.md:220-228 can never appear. SF-2 the docs' osmium lines are held by
nothing (strip -f pbf → 2731 passed). SF-3 the rebuild container's 8 GB has never been measured
against read_ways + segment rows held simultaneously: measured ~369 B per referenced node on a
synthetic build; the DC clip's node count is a guess (6–15 M → 2.2–5.5 GB before WKT rows); an
OOM kills the worker in the cgroup and presents as a vanished rebuild — §7 row at minimum.

**NIT.** N-1 test_source.py:330 splits volume strings on ":" from the left; `${VAR:-x}:/data/…`
escapes (mutation survives). N-2 OPERATIONS.md step 6 bare relative GeoJSON names (= deployment
S-5). N-3 LUA_SCRIPT_PATH duplicated; assert_lua_script_was_loaded could read graph_lua_name from
the build config. N-4 no test pins pipeline.source as Django-free. N-5 SpatiaLite settled.

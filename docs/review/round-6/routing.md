# Round 6 — Routing engine / tile pipeline — REVISE (1 blocking)

Reviewed at `00ee400` (the wave-4 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-5 disposition of every item is in `../../../handoff.md` §3.


Round-5 S-1, S-2, N-a, N-c/F_RUN3 closed by reversion on the full suite; S-4 and the reviewer
surface honest in §7; the two schema leaks closed and verified by per-test instrumentation in
both directions (zero residue on the clean tree; exactly the three round-5 nodeids when the
fixture is removed). GDAL `.hgt.part` settled by source (srtmhgtdataset.cpp:611-615 warns only;
gdalwarp_lib.cpp:1238-1249 routes CreateCopy-only drivers). bbox covers all 15 GPX files and both
sentinels (tightest margin 0.176° at the east edge). Every wave-4 judgment call accepted, each
premise read against source (vba.cc, adminbuilder.cc, graphbuilder.cc:423-446, osmium man pages).

**B-1. osmium cannot detect an output format from `merged.osm.pbf.part` / `source.osm.pbf.part`.**
libosmium io/file.hpp:179-254 detect_format_from_suffix inspects only the LAST dot-element; `part`
→ unknown → check() throws "Could not detect file format" during argument setup (io.cpp:157-170,
command_merge.cpp:85, command_extract.cpp:488,518-525; identical at v1.16.0/v2.20.0). Neither
command passes -f/--output-format. The first rebuild downloads three files then dies at merge —
row 31's original failure one message later, recorded Closed. tests/test_source.py:143,159 pin the
defective argv (adding `-f pbf` → 2 failed). Fix: `-f pbf` on both (or `<name>.part.osm.pbf`),
tests, and OPERATIONS.md:211-214 which restates the lines verbatim (SF-2).

**SHOULD-FIX.** SF-1 valhalla_build_admins parses the merged 3-state PBF three times per rebuild
for identical databases while the timezone db is built once and copied (round-5 N-d, not built,
not in §7); two redundant parses of ~1.5 GB against a 6 h terminal budget. SF-2 docs restate the
broken command lines.

**NIT.** pipeline.Dockerfile guard checks spatialite/unzip but not spatialite_tool (which the
timezone script calls; noble's spatialite-bin ships it). Dockerfile header cites stale tiles.py
line numbers. osmium merge warns about inputs from different points in time (Geofabrik's three
state extracts are separate runs); docstring silent. LUA_SCRIPT_PATH duplicated in run.py and
the config generator (drift fails loudly). check_disk_gate measures TILES_DIR while the extract
lands under DATA_ROOT/extracts; one volume in compose but nothing asserts it.
Reasoned/unexecuted: Python sqlite3 counting rows in a SpatiaLite table without the extension
(plausible); Geofabrik slugs live; smart-strategy memory (~4 GB est.) vs the 8 GB limit.

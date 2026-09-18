# Round 10 — Routing engine / tile pipeline — REVISE (1 blocking)

Reviewed at `0d79759`. All twelve wave-8 items closed by reversion and by execution through the
real handlers, the PBF reader, luajit over the vendored transform, and the shell; the merge-order
equivalence holds with its premise asserted.

**What would change my verdict:** the fixture's legality surviving the direction an approved row
did not overrule — scope the withholding to the keys the row wrote, or refuse a directional-only
row on a fixture bridge — or the wholesale rule recorded in §7 with its consequence named.

## BLOCKING
**B-1.** `apply_access` reports a way as superseding the fixture if a row wrote any of `bicycle`,
`bicycle:forward`, `bicycle:backward`, and `inject_tags` then withholds `rm:bridge_bicycle`
wholesale on every variant. The fixture's legality column is bidirectional and its `true` half
exists to correct OSM's own `bicycle=no` on those bridges, so a row writing only
`bicycle:forward=no` discards the grant entirely. Executed end to end and through luajit: as built,
`bike_forward=false bike_backward=false` (no crossing at all); with the grant kept,
`bike_forward=false bike_backward=true`, the reviewer's intent. The row shape is deliberately
supported and the wholesale behaviour is pinned as intended while its consequence is stated
nowhere. Round 9's B-1 with the sign flipped, introduced by the fix for it.

## SHOULD-FIX
- **SF-1.** `sample_cycle_lane` filters `none` and absent edges before the agreement test, so the
  half-transformed block it exists to catch answers "separated"; the documented behaviour passes the
  whole suite.
- **SF-2.** `OverrideReport` reaches nothing: declared and assigned, never logged, never in the run
  detail; the per-way INFO line is the whole audit trail.
- **SF-3.** `valhalla_build_timezones`' `error_exit` exits only when geos is 3.9, so a failed
  download leaves an empty file the `&& mv` promotes; caught later, terminally, after all three
  tile builds. Validate the part file before the move.

## NIT
A source PBF's `_jurisdictions` key survives into every extract (the filter governs only keys the
pipeline adds); two contradictory approved rows on one way resolve silently by id; the elevation
fetch cache is never validated on reuse nor pruned.

Weighed and upheld: an exit-0 exception body is impossible; `OverrideRefused` terminal is right;
an override on a sidepath supersedes nothing; the border-control node insertion end to end against
the 3.5.1 source; a partial 3DEP download is safe; retention after a rollback then a rebuild;
the serving configs against `promote()`. Verified 41 / source-read 9 / guess 0.

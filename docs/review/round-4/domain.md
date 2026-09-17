# Round 4 — Cycling / DC-region domain — REVISE (4 blocking)

Reviewed at `66ccb03` (the wave-2 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-3 disposition of every item is in `../../../handoff.md` §3.


All round-3 findings verified closed by reversion (item 13: 104 failed; S1 relief; S2 trunk; grade5
track; bare maxspeed; S3 trail exclusion, tie-break, run.py flag; item 14 OR, is_trail_class,
rm:bridge_bicycle emitter; item 15: eleven boundary mutations all caught; Purple Line 51.3% measured
from the GPX). is_trail_class under-counting: none found. 945 passed.

**B1. The provision-hierarchy inversion survives through the volume modifier.** ORCHESTRATOR
CONFIRMED. The gate `if aadt is not None and lanes <= 1 and not has_facility` reads cycleway tags
only, so a shoulder takes the bike-lane table's credit AND the volume credit while a painted lane
takes only the first:
    30 mph 1/dir, 8ft shoulder,      AADT 900  -> LTS1   (= separated track; better than a painted lane at LTS2)
    Snickersville posted 35, 5ft shoulder, AADT 1100 -> LTS2 vs bike lane LTS3
    MacArthur Blvd 35, 8ft shoulder, AADT 12000 -> LTS4 vs bike lane LTS3   (inversion the other way -> is_top_tier)
`TestTheProvisionHierarchy` sweeps speed × lanes × width × parking and never passes aadt; with
aadt ∈ {900, 12000} added: 26 failed. The handoff's own named pattern.

**B2. `resolve_bridge_bicycle_legality` has no way-class filter.** ORCHESTRATOR CONFIRMED. A
cycleway/path/footway carrying the bridge's name (the ordinary OSM case) resolves illegal, run.py
emits rm:bridge_bicycle=no on every variant, the remap writes bicycle=no — deleting the Woodrow
Wilson Bridge path and the 14th Street path from all three graphs. The is_trail_class guard on the
cycleway=track write, and the trail exclusion conflate() got this round, are both absent here; the
docstring says "per-way ROADWAY legality" and the filter the name implies is missing.

**B3. The 14th Street rows misidentify the structures.** Arland D. Williams Jr. Memorial Bridge is
the 1950 HIGHWAY span (Air Florida 90; I-395), not the Metro bridge — that is the Charles R. Fenwick
Bridge, absent from the fixture. The Mount Vernon Trail path is a sidewalk on a highway span
(reviewer: George Mason Memorial, medium-high confidence), which the fixture marks sidepath_only:false
"bar-outright". Five structures, not three (+ Long Bridge rail, Fenwick Metro). With B2 this is a
live routing defect: the span carrying the path asserts roadway-illegal and the path way inherits it.

**B4. Nothing pins the fixture's content — third round on this file.** `osm_names: ["Ponte
Vecchio"]` → 945 passed; Key/Chain flipped back to roadway-illegal (the exact round-3 error) → 945
passed; every osm_names array deleted → 945 passed. `extract_from_fixture` builds the extract's
name from the fixture under test, so matching is tautological on the one thing that has failed three
rounds running.

**SHOULD-FIX.** S1 `install_reference_data.py --volume` is single-valued and overwrites, so DDOT
then VDOT leaves one agency; and it writes agency names (`ddot`,`vdot`) where SOURCE_PRECEDENCE
expects `locality`/`state`, so every source falls to lowest precedence and the locality-over-state
rule can never fire — measured two tiers apart on one way. S2 the door-zone width threshold is
applied to a shoulder (`beside_parking = parking is not False`; parking untagged everywhere rural),
so below 35 mph the shoulder credit is inert unless someone tagged parking:lane=no. S3 the two Furth
width thresholds (4.1 / 1.7 m) are inline magic numbers; 2.1/0.7 → 945 passed. S4 Purple Line
crosses the line FOUR times into two Maryland counties (PG at 8.84/18.90 mi, Montgomery at
20.20/28.16); README and PLAN:322 say "twice". S5 `urban_way_ids` marks a way urban on any
intersection with no length fraction — errs LOW, against the module's rule, and run.py already has
MIN_JURISDICTION_FRACTION for the same shape. S6 authority columns: Wilson omits PG County and MPD
and `row_owner: MDTA` is doubtful (toll-free; MDOT SHA); Chain lists Fairfax but the VA abutment is
Arlington; Key/Chain police split is wrong — the DC–VA boundary is the 1791 Virginia shoreline so
those spans lie entirely in the District (Memorial's "one authority end to end" is the right shape
for all Potomac spans). S7 PLAN:100's Mass Ride crossing report ("names the ones that are") is
unimplemented and not in handoff §7.

**NIT.** `shoulder:width` with no presence key earns nothing; `shoulder=no` short-circuits
`shoulder:right=yes`. "George Kennan Memorial Bridge" alias for American Legion is unplaceable, and
aliases merge into one flat dict with no uniqueness check. `is_boundary_street` misses "Eastern Ave
NE"/"Western Ave". README gain 2361 vs test 2360 (carried from round 3).

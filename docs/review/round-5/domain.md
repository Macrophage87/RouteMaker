# Round 5 — Cycling / DC-region domain — REVISE (2 blocking)

Reviewed at `9601c34` (the wave-3 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-4 disposition of every item is in `../../../handoff.md` §3.


All round-4 items closed by reversion (33 mutations, 31 caught; S4 count confirmed 4 transitions,
50.9% outside). 22 real DC road profiles through classify land where a rider would put them.

**B-1. `cycleway=separate` in SEPARATED_CYCLEWAY rates the ROADWAY LTS1.** ORCHESTRATOR CONFIRMED:
primary 45 mph 6 lanes cycleway=separate → LTS1 "separated track alongside" (bare road → LTS4).
`separate` means the facility is mapped as its own way; the sidepath already carries LTS1 as trail
class, so the provision is counted twice and the second lands on the arterial (MacArthur, Rockville
Pike, Georgia Ave corridors). Also shuts the volume gate. tags.py:133 reads the same value the
opposite (correct) way for parking. Removing "separate" → 1590 passed (survives). Orphaned comment
block above the set (stress.py:142-150) is how it got in without an argument.

**B-2. Shoulder credit with parking DECLARED PRESENT.** ORCHESTRATOR CONFIRMED: residential 25 mph
parking:both=parallel + shoulder 2.4 → LTS1; same road with cycleway=lane width 2.4 → LTS2.
stress.py:414 passes parking=False unconditionally; for parking unknown the wave-3 call stands
(reviewer would not overturn), for parking present the strip is occupied or a door zone. Sweep with
aadt ∈ {None,900,1500,8000,12000} and parking present: 80/640 cases the shoulder beats the painted
lane (25/30 mph, widths 1.8/2.4). The property forces parking:both=no on the painted comparison for
EVERY parameter incl. parking="parallel". Lua remap writes cycleway=track on that street.

**SHOULD-FIX.** SF-1 resolve_sidepath_bridge_ids has no trail-class guard: two footways named
"Francis Scott Key Bridge" satisfy the match, `unmatched` stays silent, and the Key Bridge ROADWAY
stays in the no-trail graph (executed). §7's "harmless" covers inject() only. SF-2 the bicycle=yes
half of the bridge write has no access guard (motorway bicycle=no + legal=true → bicycle=yes;
service access=no → bicycle=yes) where cycleway=track has access_is_unrestricted; only the `no`
direction is tested. SF-3 Purple Line: 4 crossings confirmed but the re-entry at 18.89 is Eastern
Ave at Silver Spring/Takoma = MONTGOMERY, not PG; DC→PG→MoCo→DC→MoCo→DC is five jurisdiction
transitions; PLAN:322 and README misattribute. SF-4 distinct_authorities drops also_authority (no
consumer anywhere) so an Eastern Ave ride reports DC end to end. SF-5 parse_width_m: "8 feet" →
8.0 m (errs low-stress); "2.4m", "1,5", 5'6" → None; Lua parser handles them — two parsers
disagree. SF-6 authority columns unpinned: every round-4 S6 correction reverted → 1590 passed.
SF-7 Sousa row name "Sousa Bridge (Pennsylvania Avenue SE)" is a label (OSM: John Philip Sousa
Bridge), no osm_names, and EXPECTED_CROSSINGS now entrenches the label. SF-8 11th Street Bridges one
row, note says local span carries bikes and freeway spans do not; name match + bicycle=yes could
grant an I-695 span. SF-9 measure.revisits grid uses latitude degrees for both axes: misses a
revisit at 22.5 m parallel offset (proximity 25 m); brute-force cross-check equal on all 15 GPX.

**NIT.** American Legion police split contradicts the shoreline rule (Virginia v. Maryland 2003:
span essentially in Maryland). README Wilson owner contradicts itself (MDTA at line ~146). Long
Bridge denied a row by a rationale Fenwick refutes. Williams/George Mason DIRECTIONS likely swapped
(Williams = northbound I-395 into DC, the span Flight 90 struck; George Mason = southbound, carries
the path) — orchestrator concurs, medium-high. "Maryland SHA" vs "MDOT SHA". --volume-source
defaults to "vdot" silently. README line 6 "seeds the override table" is false. PAINTED_CYCLEWAY
has "left"/"right" (inert).

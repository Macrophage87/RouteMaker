# Round 7 — Cycling / DC-region domain — ACCEPT (0 blocking)

Reviewed at `21a44b2` (the wave-5 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-6 disposition of every item is in `../../../handoff.md` §3.


All thirteen wave-5 items closed by reversion (exact edits recorded; two prose items by reading).
Fresh pass 77 mutants, 66 killed, 11 survivors (85.7%). Provision property re-run over 388,800
cases: zero inversions; the 63,936 shoulder-below-lane cases fall into two argued families (the
Furth narrow-lane-worse-than-bare case, and the door-zone-ignorance asymmetry pinned by name) —
record both so a round-8 sweep does not read the second as new. All four judgment calls upheld:
bridge:name (residual: the narrowing write can now reach a ramp deck carrying the parent
structure's bridge:name — Overpass checklist item); 0.5 urban majority (containment would put an
ordinary 25 mph District street at LTS4 where its last block leaves the polygon); the border guard
unreachable (confirmed against graph.lua:125-146, remap:431-519, upstream:2125). The revisit §7
row's numbers are wrong: measured 0.50% / arithmetic 0.94% not 0.3%, and min-cosine alone leaves
0.11% because the axis uses 111,320 m while haversine uses π·R/180 = 111,194.9 m. Transient:
test_a_cold_worker_runs_a_deferred_job failed once under contention, passes alone.

**SHOULD-FIX.** SF-1 lanes_per_direction returns the first directional key present, not the
higher: lanes:forward=1/backward=3 → LTS3 "single lane"; mirrored → LTS4 (top-tier line decided
by which direction carries more lanes); mutation survives 2731. SF-2 cycleway width chain takes
the first key present while shoulder_width_m takes min for the stated reason; left 2.0 + right
1.2 → LTS1 "adequate"; precedence unpinned (reversed chain survives). SF-3 max_grade has no test;
test_reference_fixtures' docstring cites `test_grade_is_regenerated_not_reproduced`, which never
existed (git log -S); deleting `anchor = i` moves recorded grades 6.24→1.97% etc. and
GRADE_MIN_RUN_M 30→10 survives; the README prints those figures and PLAN:100's 6% cap is argued
from them.

**NIT.** 1 has_shoulder's contradiction reading pinned by nothing. 2 remap_node BICYCLE_ACCESS_KEYS
`access`/`foot` halves unpinned (a cycle_barrier with access=yes keeps tagged_access=1). 3
IMPLICIT_MAXSPEED "US:rural" 55 and "DC:urban" 20 unpinned. 4 rural fallback for an unrecognised
highway unpinned. 5 §7 revisit numbers (above). 6 urban_way_ids ratio in degrees is orientation-
biased (±13% at 39 N on an L-shaped way at the threshold) and the unary_union double-count guard is
unpinned. 7 MIN_OVERLAP_FRACTION comment states the claim _overlap says was wrong. 8 assign_way
ORDER BY lacks the j.name tiebreaker route_crossings has. 9 three unpinned tie boundaries
(crossings.py:60 >=, measure.py:119 >, shape.py:38 default 60).

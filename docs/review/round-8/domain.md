# Round 8 — Cycling / DC-region domain — ACCEPT (0 blocking), third round running

Reviewed at `60436a6`. All sixteen wave-6 items closed by reversion, each with a named failing test:
the higher directional lane count, the narrower cycleway width, `max_grade` per file and the
regenerated-grade test, `GRADE_MIN_RUN_M`, `has_shoulder`'s contradiction pin, `remap_node`'s
`access`/`foot` halves, the implicit maxspeeds, the unknown-class fallbacks, the minimum-cosine cell
and `DEGREE_OF_LATITUDE_M`, the ground ratio and union guard, the overlap comment, `assign_way`'s
name tiebreaker, the three tie boundaries, the §7 revisit numbers, the four conflate rank terms and
`REVISIT_PROXIMITY_M`. Two notes: zeroing `precedence` survives `test_conflation.py` alone and is
killed at suite level by the two-agency install test; `DEGREE_OF_LATITUDE_M` was closed only by a
module-level `assert` that aborts collection.

The five judgment calls are upheld: the higher lane count (one tier per way, ridden both ways); the
narrower width (the build does not know which side the route uses); the regenerated grade (both
directions of the Loudoun loop recomputed at 16.9% and 19.0%, 2.1 points apart, against the supplied
4.7% and 19.0%); `y ÷ cos` (an affine transform, the unit cancels); the minimum-cosine cell
(measured 25.25 m against a 25 m radius at the northernmost point of every reference route).

**What would change my verdict:** the `graph.lua:69` sign being wrong rather than untested; SF-3
reaching LTS4 (it does not).

## SHOULD-FIX
- **SF-1.** `graph.lua:69` `kv["rm:bridge_bicycle"] == "yes"` → `~= "yes"` survives both Lua suites
  and 1860 Python tests. Both sides of the join are pinned; the join is not. Inverted, `bicycle=no`
  lands on Memorial, Sousa, the 11th Street local span, Douglass, Whitney Young and Benning on all
  three variants.
- **SF-2.** The `lit` write in `routemaker_remap.lua` has no test: `~= nil` → `== nil` and both
  and/or swaps survive.
- **SF-3.** The painted-lane branch has no floor against mixed traffic while the shoulder branch
  does: `residential, 20 mph, lanes=2, parking:both=no` is LTS1 bare, LTS1 with a 1.3 m shoulder,
  LTS2 with a 1.3 m bike lane, against the module docstring's claim. The ordering property excluded
  280 of 1,440 combinations behind a silent `if painted <= bare:`. Bounded: one tier, never LTS4.

## NIT
Nine, from a fresh sweep of 320 Python mutants (80.6% killed) and 95 Lua mutants (71.6%):
`REVISIT_ALONG_ROUTE_M`, `DEFAULT_MIN_CROSSING_M`, `BEARING_TOLERANCE_DEG` and
`TURN_MIN_TRACE_SPACING_M` unpinned; the bollard tie and conjunction in the remap; the module-level
assert; `BOUNDARY_STREETS`' comment describing behaviour the set does not have; `is_boundary_street`
matching by name alone; `measure.py:243`'s `and` → `or` surviving.

**Wave 7:** every item closed. SF-1 and SF-2 pinned through the vendored transform (170 + 90 Lua
checks). SF-3: owner call taken not to add the floor — Furth's tables really score a narrow lane at
LTS2 where calm mixed traffic is LTS1, and the shoulder floor is the local deviation — with the
docstrings narrowed, the asymmetry pinned by name, the 280 excluded combinations asserted explicitly
(exactly one tier, never `is_top_tier`) and a §7 row naming all three argued families. All nine nits
and F37/F47/F33/F34/C-DM13 pinned; the routing reviewer's e-bike clause added to
`bridge_may_be_granted`, guarding on the tag because one Lua script serves all three variants.

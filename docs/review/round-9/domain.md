# Round 9 — Cycling / DC-region domain — REVISE (2 blocking), after three accepts

Reviewed at `17a912b`. Twenty-one of twenty-two wave-7 items closed by a named failing test; the
one-way lane floor `max(1, total)` is an equivalent mutant with proof (only `<= 1`/`> 1` is ever
read). The three owner calls weighed: the shoulder floor upheld, with the bound recomputed
independently (280 of 1,440 combinations, at most one tier, never LTS4, shoulder equal to bare);
the `electric_bicycle` guard right in direction and wrong in placement and breadth (SF-2); the
partial-elevation skip right and silent (SF-3).

**What would change my verdict:** a rule under which a road provisioned on both sides never scores
worse than the same road provisioned on one; and a §7 row for volume provenance with the two guides
amended.

## BLOCKING
**B1.** Presence is the union over the road's two sides while width is the minimum, so provisioning
the second side is a penalty. Executed on `secondary, 25 mph, lanes=2, parking:both=no`: a 2.0 m
lane on the left with `cycleway:right=no` → LTS1; lanes on both sides at 2.0 and 1.2 m → LTS2; bare
→ LTS2. The shoulder mirror at 30 mph does the same. And a one-sided track on a 35 mph four-lane
two-way secondary → LTS1, three tiers below bare. Every existing side-key test is a one-way case;
`cycleway:right=no` is discarded outright.

**B2.** `aadt_by_way` stores the precedence *tier*, not the agency, and drops the year; the segment
table has no aadt, year or agency column; `write_segments`' and `StressResult`'s docstrings claim
the derivative can identify a conditionally licensed source's influence. PLAN.md:16, :17, :31-34
and :40; MDOT SHA and VDOT are indistinguishable; both guides tell an operator to install Maryland.
Not in §7.

## SHOULD-FIX
- **SF-1.** `graph.lua:70`'s `rm:lit` join is untested (deletable, `~=` survives), one line below
  the line wave 7 closed.
- **SF-2.** The `electric_bicycle` guard is wider than the injection it protects and in the one
  layer that cannot see the variant.
- **SF-3.** `max_grade` under-reports silently on partial elevation (30% missing: 18.99% → 13.43%)
  while `elevation_gain` stays within 0.5%.

## NIT
N-1 the `rm:reviewer_surface` join; N-2 two jurisdiction constants and the `av` alternative unpinned;
N-3 the Lua `cycleway=track` guard reads the bare key only; N-4 the equivalent floor.

**Wave 8:** B1 closed by one rule for both provisions — score the worst side a rider may be made
to use; on a two-way street a side without a facility is no facility and the road's provision is
the weaker side's, on a one-way street the union stands — with the three executed cases pinned
(one side, both sides and bare now all LTS2; the two-way one-sided track LTS4, LTS1 when one-way).
B2 closed in code: the agency, the count and its year travel through `AgencyFeature`, `Match`
and `classify` into `volume_source` (now the agency), `volume_aadt` and `volume_year`, with a §7
row for what remains (identifiable, not excludable; Maryland not installed) and both guides
amended. SF-1 and N-1 pinned through the vendored transform; SF-2's Lua clause removed with the
protection in `inject_tags`; SF-3 adds `elevation_coverage` and `grade_reliable` at complete
coverage (a maximum is lost, not diluted, by a gap); N-2 and N-3 pinned.

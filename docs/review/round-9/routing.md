# Round 9 — Routing engine / tile pipeline — REVISE (1 blocking)

Reviewed at `17a912b`. All twelve wave-7 items closed by reversion with a named failing test (the
`source_tags` snapshot as an alias, the diff against the working copy, the comparison's sense, the
underscore filter, `CommandFailed ∉ terminal_causes()`, the missing-config guard by wording, the
tail-lines literal, each multiple-versions marker and the fold, the two blank-line rules, the
`electric_bicycle` clause); `promote()`'s write order survives as the accepted docstring answer.
Weighed and upheld: nothing constructs a `Way` with corrected tags; the EBIKE rule survives an
override (executed); an override equal to the source is correctly not diffed; one underscore
filter is enough; the jurisdiction stage kept with a §7 row is right.

**What would change my verdict:** make an approved `access` override outrank the crossings fixture
on the way it names, or record the precedence in §7 and correct `overrides.py`'s docstring.

## BLOCKING
**B-1.** New since wave 7: now that an access override reaches the extract, it collides with the
crossings fixture there, and the transform resolves the collision the wrong way. `inject_tags`
emits `rm:bridge_bicycle` for every fixture way regardless of overrides; `remap_way` writes
`bicycle=no` unconditionally on an illegal row and `bicycle=yes` on a legal one whenever
`bridge_may_be_granted`, which reads `access`/`vehicle` only by design. Executed through the real
handlers: Memorial Bridge, fixture-legal, with `Override("access", …, {"bicycle": "no"})` → the
extract carries `bicycle=no` and `rm:bridge_bicycle=yes`, and under luajit the remap writes
`bicycle=yes`. The mirror holds on the ten illegal rows. An `access=no` override survives, which
makes the shape harder to spot. The `OverrideReport` counts the row as applied. PLAN.md:18 and :28
put the audited table above a checked-in file; `overrides.py`'s docstring said "the sole path";
no test combined the two.

## SHOULD-FIX
- **SF-1.** `tiles.sample_cycle_lane` requests `edge.way_id` and ignores it; any edge in the trace
  answers, and `CycleLane` "none" is truthy. Two mutations survive.
- **SF-2.** An approved override with an unhandled `kind` is a silent no-op.
- **SF-3.** A sentinel edge map-matching cannot find is a retryable `CommandFailed` (five rebuilds)
  rather than a terminal `ValidationFailed`.

## NIT
N-1 the `electric_bicycle` coarseness not in §7; N-2 `valhalla_build_extract -v` unpinned; N-3
`VALHALLA_CONFIG_DIR` baked in the image while `/conf/lua` is bind-mounted; N-4 `promote()` order.

Verified 36 / source-read 8 / guess 0.

**Wave 8:** B-1 closed — `apply_access` returns the ways an approved row wrote a bicycle key onto,
the handler keeps those the fixture has an opinion about, `inject_tags` withholds
`rm:bridge_bicycle` on them on every variant, the report counts them as `fixture_rows_superseded`
with an INFO line, and the docstring states the precedence; tested end to end both ways. The e-bike
protection moved into `inject_tags` on the EBIKE variant alone (`variants.bars_electric_bicycle`),
with the Lua clause removed on the domain branch. SF-1 filters to the sentinel's way and refuses
disagreement (the way id itself is a §7 row until a real rebuild names it); SF-2 refuses unknown
kinds and `OverrideRefused` as `ValidationFailed`; SF-3 recognises the `valhalla_exception_t` body
and raises `ValidationFailed`; N-2 pinned; N-3 a sentence beside the setting.

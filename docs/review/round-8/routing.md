# Round 8 — Routing engine / tile pipeline — REVISE (1 blocking)

Reviewed at `60436a6`. Round 7's ACCEPT was correct for the eight items it named: all eight wave-6
changes are closed by reversion, each with a named failing test (`CommandFailed`'s tail and WARNING;
`source.py`'s per-command stderr and the multiple-versions marker at WARNING; the shared-volume test
on the rendered config, killed by the exact escape that survived in round 7; `graph_lua_name` read
from the build config, with the generator/config pair compared and `LUA_SCRIPT_PATH` gone; the
stdlib-only pin; the five directory binds; admins built once). The one sub-claim no test held was
`CommandFailed` staying retryable — adding it to `terminal_causes()` survived (N-1).

**What would change my verdict:** close B-1, or record it in §7 as an owner decision and correct
`overrides.py`'s docstring, which states the opposite.

## Weighed
`CommandFailed` retryable: right, and the cost (a deterministic five-hour crash retried five times)
destroys nothing. Twenty lines of tail: right size, ≤ ~42 labelled lines, and it reaches the job row.
The narrowed binds cover everything written under `/data`: settings derive seven paths, five are
bound on `rebuild`, `backups` is the maintenance worker's and `static` the api's; the four
`/data/valhalla/…` paths the configs name are upstream read-only defaults whose absence is benign and
tested. §7's memory row is accurate.

## BLOCKING
**B-1.** An approved `access` override never reaches any variant extract. `apply_access` rewrites
`Way.tags` in memory; `inject_tags` computes `changes = {k: v … if way.tags.get(k) != v}` where
`variants.inject` returns a copy of those same tags for STANDARD and NO_TRAIL, so `changes` is always
empty for them and carries only the e-bike rule for EBIKE; `write_extract` rebuilds tags from the
source PBF and applies only `way_tags`. Executed through the real handler set on the toy extract:
`Override("access", 100, {"bicycle": "no"})` holds in memory and the written PBF has no `bicycle`
key, on all three variants and in both directions. The segment table has no access column either.
PLAN.md:28 names access corrections as applied during preprocessing; :18 rests an argument on the
table being "the sole audited path for access corrections"; round 4's #4 referred widening to it;
§7's one row touching `overrides.py` implies it works. Deleting `apply_access`'s write loop fails
exactly three tests, all asserting the in-memory dict. The `stress` kind does reach the graph.

## SHOULD-FIX
- **SF-1.** `TAG_JURISDICTIONS` and `apply_jurisdiction` write `_jurisdictions`, which nothing reads:
  it cannot reach the tiles and the segment table has no jurisdiction column. One in-memory test.
- **SF-2.** `compose.yaml:314, :343, :372, :426` still say the rebuild "mounts the whole data volume".

## NIT
- **N-1.** Nothing pins `CommandFailed` as non-terminal.
- **N-2.** `bridge_may_be_granted` can revert the e-bike variant's `bicycle=no` to `yes` (executed
  under luajit); narrow reachability.
- **N-3.** `promote()`'s two symlink writes are unordered by any test; equivalent, recorded.

Fresh sweep: 30 mutations, 28 killed. Verified 28 / source-read 7 / guess 0.

**Wave 7:** B-1 closed — `extract.Way` snapshots `source_tags` and `inject_tags` diffs against
them, with an end-to-end test reading the produced PBFs back; underscore keys are filtered at the same
comprehension and pinned (SF-1's tag can never reach a PBF), the stage kept and its docstrings made
honest, with a §7 row. N-1, F14, F08, F01–F03, F05 and F17 pinned. SF-2 corrected on the deploy
branch; N-2 closed on the domain branch with an `electric_bicycle` clause. N-3 is a docstring.

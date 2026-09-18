# Round 10 — Test quality by mutation — REVISE (1 blocking)

Reviewed at `0d79759`. 170 mutants, 170 verdicts: 144 killed, 26 survived, none discarded; every
survivor re-run serially and reproduced. Coverage 97% over `src/`. Round 9's blocking survivor and
all 27 should-fix survivors are closed (29 mutants, 27 killed, the two survivors being the two
equivalents wave 8 recorded, re-proved). The five accepted equivalents re-proved, with F30's
sibling on the enclave sort killed, which identifies it. **Sampled wave-8 claims: 38 of 38
reproduce.** Fresh pass over the wave-8 code: 98 mutants, 78 killed (79.6%); the new side rule's
every comparison 17 of 18 killed, the provenance path's every hop 15 of 16. Both reversal orders
green; the per-test hookwrapper, now also counting the Procrastinate job tables, recorded only
pytest-django's own boundaries, and the wave-8 fixture change is load-bearing and pinned.

**What would change my verdict:** one assertion that a trace spanning two different ways which
agree on the lane answers nothing.

## BLOCKING
**B10-1.** `sample_cycle_lane`'s "one and the same way" guard — `if len(way_ids) != 1 or None in
way_ids` → `if None in way_ids` — survives the whole suite, twice. With `DERIVED_SENTINEL_WAY_ID`
still `None` (a §7 row), this comparison *is* the check on the only shipped configuration; deleted,
a trace that snapped onto a neighbouring way carrying its own OSM `cycleway=track` answers
"separated", VALIDATE passes, and a graph in which the transform derived nothing is promoted. The
existing spanning test's two edges also disagree about the lane, so the function returns `None`
for the second reason: three ways of not knowing, two exercised. Round 4's masking lesson in one
test.

## Should-fix survivors
- `is_oneway` widened to "any `oneway` value" survives: `oneway=no` then reads as one-way and the
  side rule falls back to the union on exactly the streets that state they are two-way; no test
  uses `oneway=no`. The finding to fix first after the blocker.
- `HANDLED_KINDS` gaining a member survives — the refusal is pinned, the set is never enumerated:
  the third instance of "a set read by name and never enumerated".
- The `- {Stage.SWAP}` exclusion in `stages_after_swap()` survives: a failure at SWAP would be
  abandoned with "the swap completed", which is false.
- `prune_backups`' two clamps survive: with fewer dumps than `keep`, the mutant dooms the oldest.
- `disk_usage(tiles_dir)` → `disk_usage("/")` survives: the path is reported and the measurement
  is not pinned, row 66 one layer in.
- `.env.example`'s `DISCORD_REDIRECT_URI` path survives: the sign-in test pins the scheme, host,
  origin and port and never the path.
- `prepare_data_root.sh`'s env-file parser: three of its four rules (last occurrence wins, CR
  strip, quote stripping) untested.
- `valhalla_exception`'s body scan: a refusal preceded by any stdout line stops being recognised.
- The doc rule's own regex has two dead alternations; the shipped `PGDATABASE`, the documented
  HSTS age and `repr=False` are nits.

## Equivalent — accepted with proof
The entrypoint's zero-period and unreadable-file guards (the shell fails the same way without
them); `/ max(len(points), 1)` under the empty guard; `.lower()` on an object id that is always a
decimal; round 9's two.

## The pattern
Three of this round's survivors are one habit: **the conjunction pinned by only one of its
conjuncts** — the spanning test's edges also disagree, the kind refusal pinned while the set is
not, a four-rule parser with one rule's test, a URI with four parts pinned and not the path. The
rule to add beside "mutate the whole expression you edited": when a test asserts that a value is
refused, make the input fail for exactly one reason at a time.

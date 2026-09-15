### Test quality by mutation — REVISE (4 blocking)

**173 mutants applied, 123 killed, 50 survived (71% kill rate).** Line coverage is 95% (2249
statements, 121 missed), so this is not a coverage problem — it is a problem of what the assertions
say about the lines they execute.

Round-2 items verified genuinely fixed, not cosmetic: the Lua remap (13/15 killed), conflation
(12/15), borders (5/5), the stress classifier (20/26 against 9/9 previously surviving), the swap's
lock (killed by contention, not source-reading), test_compose.py, the crossings fixture, the
override table, task registration, and test_reference_fixtures.py.

**B1. The weekly rebuild raises on every fire.** Same as routing B3 / database B2, found
independently. The test that exists to catch it is docstringed "Registered is not the same as
wired" and then monkeypatches `run_rebuild` — it stubs out the one function that would have
noticed.

**B2. Six admin authorization guards and both allowed-audit paths survive deletion.** Seven
mutants, all survived: both `AuditedAdmin.save_model`/`delete_model` audit calls;
`ConfiguredGuildAdmin` add/delete; `CachedMembershipAdmin` add/delete; `AuditLogEntryAdmin`
module permission. `cachedmembership` is NOT in `INSTANCE_ADMIN_ONLY_MODELS`, so the ModelAdmin
override is the only thing between a guild admin and the table that "grants any role in any
guild" — driven through with a real guild admin: `has_add_permission: True`, backend
`has_perm add_cachedmembership: True`. The test asserts all three write verbs on
`BorderCrossingAdmin` (no security consequence) and one verb each on the two authorization tables.

**B3. Open redirect.** Same as security B1, found independently. No test in the suite mentions
`next` or `redirect_after`.

**B4. Three of five paths to LTS4 are untested.** `>= 35` → `>= 45`, 30 mph multilane LTS4 → LTS3,
the high-volume bump, and `VOLUME_BUSY` 8_000 → 800_000 all survive. 35 mph is the LTS3/LTS4
boundary and the most common arterial posting in the region. The e2e test asserts `>= 3`.

**SHOULD-FIX:** F1 NIT 19 not fixed (11 failed with the documented invocation). F2 the writers'
live-schema guard compares a literal, and both its tests share the literal — the kill is
tautological. F3 the segment key is protected by nothing: `row["ordinal"] → 0`, the UNIQUE
constraint, and the `stress_tier BETWEEN 1 AND 4` CHECK all survive. F4 ten plan-named durations
unpinned, all computing their boundary from the constant under test — this already cost
`IDLE_SESSION_LIFETIME` (14 days vs the plan's 30). F5 `sweep_memberships`' most carefully argued
rule survives deletion — restoring the exact bug its docstring spends a paragraph on leaves the
suite green; also `sweep_priority`'s active-session ordering and `last_login` being written at
login. F6 `REBUILD_TIMEOUT_S`/`SWEEP_TIMEOUT_S` reach no job; no `retry=` anywhere. F7 compose
worker count `"2"` → `"64"` survives — the one rule PLAN singles out as not "merely asserting a
limit exists". F8 the crossings fixture's two legality columns are perfectly correlated so the
disjunct is inert, and the test recomputes the production expression. F9 `schema.py`'s injection
guard survives deletion and its comment's premise ("they come from settings today") is now stale.
F10 two consecutive swaps are never tested, so `DROP SCHEMA ... CASCADE` only ever runs as a no-op.
F11 single rules surviving: `is_rough`'s tracktype/smoothness clauses, the federal-enclave sort
order, the conditional-access precedence, `MAX_SPAN_REUSE`, unmatched-count reporting, the state
layer filter, and `User.is_staff`'s ban check (masked by a duplicate check in the admin site).
F12 `routemaker/cards.py` is a phase-4 surface with no production caller.

**NIT:** stale-session `row.delete()`; `RebuildReport.failed_at` is unobservable dead state;
gdalwarp `-r bilinear`; the bollard width threshold; `logout_view` accepting GET; the feet branch of
`parse_width_m` untested (US shoulder widths are commonly tagged in feet, and it feeds the LTS
shoulder credit); `check_compose_limits.main()` reading a CWD-relative default.

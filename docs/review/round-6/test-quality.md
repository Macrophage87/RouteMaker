# Round 6 — Test quality by mutation — REVISE (1 blocking)

Reviewed at `00ee400` (the wave-4 merge). The wave-5 disposition of every item is in `../../../handoff.md` §3.


144 mutants, 144 verdicts, 114 killed, 30 survived, 0 discarded; every survivor re-run serially.
Coverage 97%. Fresh-pass kill rate 75.5% (74/98) — selection (argued constants, tie boundaries,
one-clause guards), not regression. All seven round-5 blockers and six should-fixes closed as
literal edits; F_VAR2 closed by deletion; F_AUD2/F_RUN7/prune-symlink-1 confirmed equivalent;
F_ROLL_C (`link is None`) a fifth, subsumed clause — equivalent. Both schema leaks closed (schema
list = public after each). Sampled wave-4 claims 26: 25 killed; IMG2 off-target (reviewer's
error; IMG2b kills). Reverse order 2590 passed; per-test instrumentation over 2589 boundaries:
only pytest-django's own session teardown. Exact edit recorded beside every verdict.

**BLOCKING FR57/FR57c.** `InstanceAdminListingAdmin.ALLOWED_LOOKUPS` gaining `is_banned` or
`session_epoch` survives: the refusal test parametrises five SUFFIXED lookups and the positive
test asserts only that discord_user_id is answered. Demonstrated over the test client as a guild
admin: `?session_epoch=7` → rows {2}, `?session_epoch=3` → {} — an oracle over every instance
admin's revocation counter. Fix: pin the frozenset member for member + a bare-name refusal case.

**SHOULD-FIX (unpinned argued rules/constants).** FR87 remap node guard `access == "no"` half
(PLAN:72). FR03 zero-byte `.part` renamed into place; FR04 stale `.part` unlink. FR16
_least_grade completeness clause. FR28 DUMP_NAME missing `$` → part files count toward
BACKUP_KEEP. FR86 least_restrictive `>` → `>=`. FR42 RIDEABLE_SHOULDER_M tie (`>=`). FR89
MIN_RIDABLE.Road. FR80 COVERAGE_BBOX corners. FR76 settings SOURCE_EXTRACT_MAX_AGE_DAYS default 6.
FR77 FORCE_REFRESH == "1". FR70 WEEKLY_REBUILD_CRON day-of-week discarded by the test. FR66
RUN_ROW_RETENTION_S. FR96/IMG2 WORKDIR vs PYTHONPATH=/app/src unpinned against each other. FR64
ABANDON_GRACE_S. FR29 prune_tile_builds symlinked variant dir. FR19 "(and 0 more)". FR10
ESTIMATED_BYTES (near-equivalent). FR32 gate `>=` (near-equivalent).
**Equivalent, accept.** FR18 timezone chain vs fan-out; FR27 keep>0 vs >=0; FR45 shoulder_present
conditional; FR99 dead default.

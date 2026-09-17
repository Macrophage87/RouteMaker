# Round 4 — Database and rebuild pipeline — REVISE (1 blocking, 7 should-fix)

Reviewed at `66ccb03` (the wave-2 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-3 disposition of every item is in `../../../handoff.md` §3.


Every round-3 finding in this area verified closed by execution AND by reverting the fix:
worker startability (3 mutations), rebuild completion (bare swap_schemas instead of perform_swap),
crossings in the swapped schema (migration 0005 DROP → SELECT 1; crossings to live + guard removed),
staging literal, backup session exclusion (real pg_dump + pg_restore --list), all three timeout
enforcement points, disk gate. Migration 0005 round-trips; rebuild fired twice succeeds and reports
drift 5→4. 945 passed on a private database.

**B1. `pipeline/promotion.py` leaves, and creates, the half-swapped states its docstring says it
never leaves.** Four holes, all reproduced against a real database; ORCHESTRATOR CONFIRMED all four
structurally (promotion.py:77-88, :70, :107; tiles.py:161-163):
(a) `rows_before = repoint_upstreams(...)` binds only on full success and `repoint_upstreams` is
not atomic — a failure on the third variant's row leaves two rows naming a build no tile dir and no
schema describes, and the wrapped RuntimeError is retryable so the partial repoint repeats ×5.
(b) `tiles.demote` returns None with no `previous`, so on the FIRST rebuild a swap_schemas failure
leaves `current` pointing at an unpromoted build while `restore_upstreams` blanks every row.
(c) `restore_upstreams` writes `previous_build_id=""` unconditionally, destroying the only thing
`rollback()` reads.
(d) `rollback()` has no precondition that a swap happened. After the first-ever swap it silently
promotes the empty schema: live goes 5 → 0 segments, every settings row blanked, tiles untouched.
After a rebuild that failed at the swap it dies on a raw `schema "staging" already exists`.
(e) `rollback_swap` lacks the in-transaction refusal `swap_schemas` has.

**SHOULD-FIX.** S1 a rebuild killed by its own deadline (`TimeoutExpired`/`RebuildTimedOut` inside a
stage) is not a terminal cause and is retried ×5 — and a retry re-runs SWAP, whose DROP live_old
destroys the rollback target. S2 the maintenance queue is one slot (`--concurrency` default 1) and
`pg_dump` has no timeout, so a blocked dump holds it forever while 5-minute ticks are DROPPED
(procrastinate skips on queueing lock) — the 5-minute bound is not achievable. S3
`degraded_guild_sweep` is not in `STALE_AFTER`; two tests pin the omission. S4 nothing consumes the
alert — `stale_tasks` has no caller, no failed-jobs admin page, no worker heartbeat (PLAN:58,
PLAN:292 all phase 1, none wired, not in handoff §7). S5 nothing prunes build directories — N kept,
one per week; PLAN sizes for two; the disk gate will eventually refuse every rebuild permanently with
"grow the volume" as the only remedy. S6 backup is local-only, never expires, and lands on the volume
the disk gate measures (S3 upload/SSE-KMS/30-day retention unbuilt, not in §7). S7 the abandoned
deadline thread DOES hold a DB connection (proven: pytest could not tear down); up to six sweep
copies resident. S8 still no measured size table (PLAN:290).

**NIT.** N1 migration 0005's reverse recreates `public.border_crossing` without its GiST index.
N2 build ids are second-resolution; two fires in one second → `current` and `previous` both point
at one dir, overwritten in place. N3 `rollback_swap` exhausting attempts raises the raw psycopg error.
N4 ScheduledRun/procrastinate_jobs/events grow unpruned (~105k rows/yr from the 5-min task alone).

# Round 7 — Database / scheduler / rebuild operations — REVISE (2 blocking)

Reviewed at `21a44b2` (the wave-5 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-6 disposition of every item is in `../../../handoff.md` §3.


All round-6 items and four wave-5 designs closed by reversion (19 mutations + 4 probes, exact
edits recorded); two survivors recorded not re-opened (`of=("self",)` narrowing; `- {None}`).
Design questions answered: refuse_unswappable_schema covers live, <live>_old (derived as
swap._retired_name does) and public; the refused first rebuild's finally prune cannot touch
extracts/; ReferenceDataMissing terminal by reversion; a queued rebuild waits for the rebuild
worker (procrastinate 3.9.0's periodic deferrer runs on every worker regardless of --queues).

**B-1. run_rebuild_now does not refuse while a rebuild is RUNNING.** The queueing-lock index is
`WHERE status = 'todo'` (schema.sql:100); the docstring, --help, OPERATIONS.md:291-302 and the
test all claim "queued or running". Executed: defer, set doing, call → "queued … as job 2". Worse:
procrastinate_retry_job puts the running job back to todo, which now collides on the index —
executed: "duplicate key … procrastinate_jobs_queueing_lock_idx_v1" — so a transient
RebuildFailed becomes an error in the job-finishing path instead of a retry, misreported. Also
falsifies "a hand-fired run in flight on a Tuesday means that tick is dropped" (periodic skips only
on AlreadyEnqueued). What keeps two rebuilds apart today is --concurrency=1, not the lock.

**B-2. The postgis healthcheck probes the unix socket** (`pg_isready -U … -d …`, no -h), which is
exactly what the image's init-phase server listens on (docker-entrypoint.sh:290-306 starts it with
listen_addresses=''); TCP is closed. Executed against a socket-only cluster: probe rc=0, TCP
refused; with -h 127.0.0.1 rc=2. `-d` buys nothing (PQPING_OK without touching the database).
So `migrate` can still race the first boot; self-heals on a second `up`; not documented; not in §7.

**SHOULD-FIX.** S-1 a RebuildTimedOut at the SWAP→RECONCILE boundary (rebuild.py:126-128 raises
RebuildTimedOut, not RebuildFailed) is abandoned with "time budget ran out" — no swap, no router
restart named (executed: live_old exists, message silent). S-2 the runtime schema guard fronts one
DDL site of three: swap_schemas' DROP retired and rollback_swap's drop of staging rely on the
settings layer alone.

**NIT.** N-1 no length bound in validate_schema_name; at 63 bytes `<live>_old` truncates back to
the live name and the swap drops what it is about to rename (executed). N-2 reserved set is
`public` only; information_schema passes. N-3 check_operations has no opinion on a job wedged in
`doing`. N-4 `of=("self",)` unpinned.

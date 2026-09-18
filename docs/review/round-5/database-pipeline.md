# Round 5 — Database / scheduler / rebuild operations — REVISE (3 blocking)

Reviewed at `9601c34` (the wave-3 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-4 disposition of every item is in `../../../handoff.md` §3.


All round-4 items closed by reversion (37 mutations) except three unpinned: the operations page's
stale list (`"stale": []` → 1590 passed), the nightly prune wiring (literals → 1590 passed), and
prune_run_rows' newest-successful clause (redundant). B1(a) before-state binding is an equivalent
mutant now that the repoint is atomic; rollback_target's four clauses survive individually
(composite killed). Migration round-trip test snapshotted identical before/after (65 migrations,
25 tables, 73 indexes, 160 columns); randomized order 1590 passed. Procrastinate 3.9.0 concurrency
model read (semaphore over sync_to_async threads); nothing on the maintenance queue found unsafe
to run concurrently.

**B-1. worker has no DATA_ROOT** → BACKUP_DIR resolves under the image's BASE_DIR, the dump lands
on the ephemeral layer, prune_backups prunes the wrong dir, the run row says success. Verified by a
failing assertion on SERVICES["worker"]["environment"]. (Closed on the wave-4 security branch,
which delivers DATA_ROOT: /data to worker and pins it.)

**B-2. A dump that fails without timing out, or that the verifier rejects, stays on disk under the
ordinary name.** ORCHESTRATOR CONFIRMED structurally (only the TimeoutExpired branch unlinks).
Probes: pg_dump exit non-zero → archive left; verification failure → the rejected archive (which
may carry cached_membership data) is kept and, being newest by name, is what a restore picks.

**B-3. prune_tile_builds runs only after a successful run_rebuild and downstream of the disk
gate.** ORCHESTRATOR CONFIRMED structurally. DiskGateRefused is terminal, so a refusal is
self-perpetuating even with prunable builds present; a failure after BUILD_TILES leaves a third
tile set until the second following success (executed on a simulated tree).

**SHOULD-FIX.** SF-1 perform_swap's undo is not best-effort: restore_links raising on variant 1
skips variants 2–3 and the row restore. SF-2 rollback() has no undo of its own after
rollback_swap. SF-3 a retry after a completed SWAP re-runs SWAP (DROP live_old) — RECONCILE
failures are retryable ×5; no test exercises a post-swap failure. SF-4 run_with_deadline calls
raw.close() (PQfinish, unlocked in psycopg 3.3.5) after a 0.5 s join while the abandoned thread may
still be inside libpq → segfault of the maintenance worker; gate on transaction_status != ACTIVE.
SF-5 operations page stale list unasserted. SF-6 nightly prune wiring unasserted. SF-7 rollback
has no invocation surface and OPERATIONS.md has no rollback section. SF-8 OPERATIONS.md "Build ids"
says unique_build_id is not wired (it is).

**NIT.** check_operations --failed-job-limit help text false (summary prints the truncated count).
OPERATIONS.md heading "one slot" contradicts its body. rollback_target clauses unisolated (retired-
schema-holds-segments clause is the one the 5→0 story turns on). prune_run_rows newest-successful
clause redundant. Backup-timeout test has no outer watchdog (hangs on revert). _retired_holds_a_graph
full count(*). new_build_id reads settings.TILES_DIR not context.tiles_dir.

# Round 6 — Database / scheduler / rebuild operations — REVISE (1 blocking)

Reviewed at `00ee400` (the wave-4 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-5 disposition of every item is in `../../../handoff.md` §3.


All round-5 items closed by reversion (26 mutations, each with the exact edit recorded). Two
equivalent survivors recorded so round 7 does not re-open them (rollback_target's `link is None`
and `schema_exists(retired)` clauses, each dominated by the next). The `.part` half of B-2
survives (S3). Every wave-4 design agreed with, each read against the code: the finally prune is
safe before write_build_config (build_id fixed in __post_init__); the pre-gate prune reclaims
nothing in the three-set case but the refused run's finally prune reclaims the orphan, so a
refusal is not self-perpetuating; stages_after_swap correctly derived; rollback re-swap is the
exact reverse; procrastinate 3.9.0 sync tasks run under sync_to_async(thread_sensitive=False) so
the PQfinish hazard was real and --concurrency=4 is really four.

**B1. OPERATIONS.md runs rollback_rebuild in `api`**, which has no DATA_ROOT and no data mount →
"there is no previous build to go back to" on a deployment that has one (executed through two
real rebuilds). = deployment B-2; assigned to the wave-5 deploy agent.

**SHOULD-FIX.** S1 reset_segment_schema (first thing FETCH_EXTRACT does; DROP SCHEMA CASCADE) has
no refusal for a staging name that collides with live/public/<live>_old, while the additive writers
do (executed: staging = live name → served graph gone). S2 the post-swap-terminal RebuildAbandoned
message says "the new build is being served" and does not name the router restart (false until
restarted; the one path an operator is least likely to run the post-rebuild step). S3 the backup's
`.part` staging name is unpinned (`part = destination` survives 70 tests) — the case it exists for
(OOM/kill mid-dump) is one Python never sees.

**NIT.** retention.py:125 set comprehension puts None in the set (harmless). Stray backup `.part`
files accumulate on the volume with nothing removing them (documented as safe to delete).
apply_due_instance_admin_removals is called by two tasks that can now run concurrently with no row
lock → possible duplicate audit row, idempotent outcome.

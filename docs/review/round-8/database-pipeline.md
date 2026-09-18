# Round 8 — Database / scheduler / rebuild operations — REVISE (2 blocking)

Reviewed at `60436a6`. All sixteen round-7 items closed by reversion with the edit recorded beside
each: both halves of B-1 (the pre-flight over `todo`/`doing`; the in-task `RebuildAlreadyRunning`),
the TCP healthcheck, `RebuildTimedOut` carrying its stage (both tests), both DDL guards (the reserved
case really executed `DROP SCHEMA information_schema CASCADE` under the mutant), the 59-character
bound and its `_old` exception pinned independently, the reserved set, wedged jobs on both surfaces
and the per-task budget table, `of=("self",)`, both audit rows, and the deployment-epoch rule. The
cold-worker flake was closed by a probe reproducing its shape rather than by a clean reversion.

**What would change my verdict:** a deployment epoch that exists with no run rows, and a pre-flight
on `rollback_rebuild`, each with a confirmed-failing mutation.

## BLOCKING
**B8-1.** `first_run_at()` is the oldest `ScheduledRun` of any task, and with no rows nothing is ever
stale; `wedged_jobs` reads `doing` only and `failed_job_count` is zero. Executed: four jobs deferred
`todo`, zero run rows, `check_operations` → `ok`, rc 0. So a maintenance worker that never dequeues
a job — a `--queues` typo, a crash loop — is reported healthy for ever, which is the one outage the
heartbeat alert exists for. `django_migrations.applied` is an epoch that exists on every deployment
by the time the worker should start.

**B8-2.** `rollback_rebuild` goes from `rollback_target` straight to `rollback`, and `rollback_swap`
drops any staging schema CASCADE as "left behind by a rebuild that did not swap". Executed with a
`doing` rebuild and ten staging rows: rows gone, job still running, the rebuild later fails at a
pre-swap stage as `RebuildFailed` and is retried. The worse interleaving — a `rollback_swap` landing
between `perform_swap`'s repoint and its `swap_schemas` — leaves the tile links and the served
schema naming different builds, and neither procedure raises.

## SHOULD-FIX
- **S8-1.** A refused `RebuildAlreadyRunning` finishes the job `failed`, which pages for thirty days
  with nothing to clear it.
- **S8-2.** The runbook overstates what the in-task check buys on `--concurrency=1`: the tick's job
  waits `todo` and runs a second full rebuild afterwards.

## NIT
- **N8-1.** `first_run_at` drifts forward under `prune_run_rows` (at most ~30 days old).
- **N8-2.** A SIGKILL mid-dump leaves `routemaker-<instant>.dump.part` for ever.

Weigh-ins: the pre-flight raising before `record()` is right; the retry exclusion right; `pass_context`
right (`worker.py:294`); the 59-character bound right; budgets fine; the `-h 127.0.0.1` probe safe —
`postgres:16-bookworm` patches `listen_addresses = '*'` at image build and only the init-phase server
overrides it.

**Wave 7:** B8-1 closed — `deployment_epoch()` is the earlier of the oldest run row and
`MAX(django_migrations.applied)`, which also removes N8-1's drift. B8-2 closed — the command reads
`jobs_in_flight("weekly_rebuild")` before anything, dry run included, and the runbook says so. S8-1:
`RebuildAlreadyRunning` subclasses `JobAborted`, so the row lands `aborted`. S8-2 corrected in the
merge. N8-2: `prune_backups` reclaims parts older than the newest kept dump. Plus the deployability
blocker's other half, `manage.py unwedge_job`, the free-space check, the prunes in a `finally`, the
dry run's restart hint, and F73/F58/F50/F57/F54 pinned.

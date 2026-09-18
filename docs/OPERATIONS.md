# Operations

What is watched, where an operator sees it, and what removes the things that
would otherwise fill the data volume. The plan's alert list is the source for
every number here; this document is where the mechanism behind each one lives.

## Where the alerts are

Two surfaces, one computation. Both read `core.runs.stale_task_details` and
`core.runs.failed_jobs`, so they cannot disagree about what is broken.

- **The operations page**, in the admin, at `<DJANGO_ADMIN_PATH>core/scheduledrun/`
  — with the default path, `/internal-8f3a/core/scheduledrun/`. It lists the
  stale tasks with the window each one missed, the failed Procrastinate jobs
  with their attempt counts, and the last 25 runs. Instance admins only, and
  read-only to them as well: these rows are the evidence for an alert, so an
  admin who could edit them could silence one by hand. Anyone else gets the same
  404 the rest of the admin gives an unadmitted request.
- **`./manage.py check_operations`**, for anything that cannot log in. It prints
  one line per stale task and per failed job and exits 1 if there is anything to
  print, 0 otherwise. A cron entry is the intended caller:

  ```sh
  */10 * * * * docker compose exec -T api ./manage.py check_operations || mail-the-ops-channel
  ```

There is no paging integration and no scraper yet; the plan records both as
follow-ups. What exists is the thing that has to exist first — the state is
computed, and it is visible.

## What is watched, and for how long

`core.runs.STALE_AFTER` is the whole list. A task is stale when its most recent
**successful** run started longer ago than its window; a failure is not a
success, and neither is a run that is still going.

| Task | Schedule | Window | Why |
| --- | --- | --- | --- |
| `weekly_rebuild` | Tuesdays 08:00 UTC | 8 days | One missed run is not an alert; two are. |
| `nightly_backup` | 07:00 UTC daily | 26 hours | The plan's own number, at a day's cadence. |
| `membership_sweep` | every 6 hours | 12 hours | Two missed runs. |
| `degraded_guild_sweep` | every 5 minutes | 30 minutes | Six missed ticks. |
| `worker_heartbeat` | every 5 minutes | 10 minutes | The plan's "worker heartbeat silent for 10 minutes". |

The two five-minute tasks are windowed at six missed ticks rather than one
because a single dropped tick is ordinary: Procrastinate skips a periodic job
whose predecessor is still queued or locked, so any job ahead of it on the
maintenance queue drops the tick that falls under it, and a worker restart drops
one too. Six consecutive misses is a worker that stopped.

The heartbeat is the tightest window on the list on purpose. It is the one alert
that fires when the component that writes every *other* alert row has died — a
stalled worker stops writing the backup and sweep rows as well, but their
windows are 26 and 12 hours. It is honest about what it measures: the row says
the worker dequeued and finished a job, not that its process is alive.

## The maintenance queue has four slots, and every task on it is bounded

Procrastinate's default `--concurrency` is 1, and until wave 3 `compose.yaml`
ran the maintenance worker with that default. Every periodic task except the
rebuild queues there, so with one slot exactly one of them ran at a time and
anything ticking under a long job was dropped rather than delayed —
Procrastinate skips a periodic job whose predecessor is still queued or locked.

Two things follow, and both are in place now:

1. **Every task on that queue is bounded.** The membership sweep runs under
   `core.runs.run_with_deadline` (30 minutes) and the backup now runs under
   `BACKUP_TIMEOUT_S` (30 minutes, the same bound), so the worst case for the
   slot is half an hour rather than forever. Before this, `pg_dump` had no
   timeout at all: a dump blocked on a lock held the slot for the life of the
   process, and every five-minute degraded-guild tick under it was dropped.
   A backup killed at its budget is recorded as a failure and **not retried** —
   the same budget and the same lock would consume the next attempt too, and
   five retries would hold the slot for two and a half hours more. The nightly
   schedule is the retry, and the 26-hour window is what notices.
2. **The five-minute bound is not restored by that timeout**, and cannot be from
   inside the application: on one slot a tick falling inside a legitimate
   twenty-minute dump is still dropped, and a job holding the slot past ten
   minutes shows up as a heartbeat gap. The plan asks for the heartbeat to be
   "independent of the backup alert", which one slot cannot be. That part is a
   deployment setting, and it is one line in `compose.yaml`, on the `worker`
   service:

   ```yaml
   command: ["./manage.py", "procrastinate", "worker", "--queues=maintenance", "--concurrency=4"]
   ```

   (or `WORKER_CONCURRENCY: "4"` in its `environment:`, which Procrastinate reads
   for the same option). `compose.yaml` carries it and `tests/test_compose.py`
   pins it, so the heading above is four slots rather than one; a deployment
   that drops it is back to one slot and should expect a heartbeat gap for the
   duration of any maintenance job that runs longer than ten minutes.

The rebuild has its own queue and its own worker for an unrelated reason: it
needs the container with the Valhalla binaries and the data mounts, and a
six-hour build must not sit in front of a five-minute tick.

## Retention

Nothing pruned anything before this. Every item below was kept forever, on the
volume the rebuild's own disk gate measures — and that gate is a hard refusal,
so the end state was not a full disk with a warning on it but a rebuild
declining every week with "grow the volume" as the only remedy.

| What | Kept | Where |
| --- | --- | --- |
| Dated tile build directories | Whatever `current` and `previous` point at, plus the build of the run that is in progress | `pipeline.retention.prune_builds`, run by the rebuild task before the disk gate and again on its way out |
| Database dumps | 7 (`BACKUP_KEEP`) | `pipeline.retention.prune_backups`, run by the backup task after a verified dump |
| `scheduled_run` rows | 30 days, plus the newest row and the newest successful row per task | `core.runs.prune_run_rows`, run nightly |
| Finished `procrastinate_jobs` and their events | 30 days | `core.runs.prune_job_rows`, run nightly |

Three rules are load-bearing rather than incidental:

- **A promotion symlink protects its target whatever its age.** After a rollback
  `current` points at the *older* directory, and a plain newest-N rule would
  delete the graph being served.
- **A failed build's directory survives the run that made it, and no longer.**
  The rebuild prunes twice: once before the disk gate, with the ordinary
  two-set rule, and once in a `finally` that keeps what the symlinks name plus
  the build this run wrote. So after a failed rebuild the volume carries the
  two served sets and the failed one — there is something to look at — and the
  next run reclaims it on its way out, so two bad weeks do not leave four tile
  sets. The prune before the gate is the half that matters most: the gate is a
  hard refusal, so with retention downstream of it the first week the volume
  was too full refused every week after it, with prunable builds sitting there
  and "grow the volume" as the only remedy the operator was offered.
- **The newest run row per task is never pruned**, nor the newest successful
  one. They are what `stale_tasks` reads; pruning them would turn "this task has
  not run in a year" into "this task has no history", which reads exactly like a
  task that was never registered.

A job row still `todo` or `doing` is live state the worker owns and is never
pruned, whatever its age, and neither is a job a `procrastinate_periodic_defers`
row still points at — that reference is how the scheduler knows it has already
fired for a tick.

## Backups

`pg_dump -Fc` to `<DATA_ROOT>/backups/routemaker-<UTC instant>.dump`, excluding
the session table and the cached membership table, verified by reading the
archive's own table of contents back with `pg_restore --list` — an archive with
no table data at all is a dump of nothing, which is what a wrong database name
produces while `pg_dump` exits zero.

**A file under that name is a dump that was written whole and verified.** It is
written as `routemaker-<UTC instant>.dump.part` and renamed only once the
listing has been read back and accepted, and the part file is removed on every
failure path. Before that, only a dump killed by its timeout cleaned up after
itself: a `pg_dump` that exited non-zero and a dump the verification rejected
both stayed on the volume under the ordinary name — newest by name, so the one
an operator restoring last night's picks up, and in the second case possibly
carrying the very rows the exclusion exists to keep off the disk. A stray
`.part` file is safe to delete; nothing reads one and the pruning ignores them.

Local only, and that is the gap to close next: the plan's S3 upload with SSE-KMS
and 30-day remote retention is **not built**, so today every copy of the database
sits on the same volume as the database. The nightly EBS snapshot of the data
volume is what stands between this deployment and a lost host until that lands.

## The rebuild's own budget

A rebuild has six hours. It hands whatever remains of that budget to every
binary it runs and checks it between stages, and a rebuild that runs out is
**abandoned rather than retried**, in either shape it arrives in
(`RebuildTimedOut` from the stage boundary, `subprocess.TimeoutExpired` from a
killed binary). It will not finish faster on the next attempt, and a retry runs
the whole rebuild again including the swap — whose `DROP SCHEMA live_old`
destroys the schema a rollback would have put back. Five retries of a timed-out
rebuild would have dismantled its own rollback target, one attempt at a time.

## Deployment actions

- Add a `check_operations` cron entry, or point an existing monitor at it.
- The operations page is at `<DJANGO_ADMIN_PATH>core/scheduledrun/`; it is not
  linked from anywhere public and the admin path is not advertised.

## Build ids

`pipeline.run.new_build_id` is second-resolution, which is a directory name an
operator can read and is enough for a weekly job right up until two builds land
in the same second — a retry, a hand-fired rebuild, a test. Two builds sharing
an id share a directory, so the second writes its tiles into the first's tree
and `previous` ends up naming a mixture of the two — which is the rollback
target.

That is wired, and has been since wave 3: `new_build_id` asks
`retention.unique_build_id` for an id that is not already taken under the tiles
root, and the second build inside one second takes a `-1` suffix that sorts
after the bare form.

```python
def new_build_id(now=None, tiles_dir=None):
    root = Path(tiles_dir if tiles_dir is not None else _setting("TILES_DIR"))
    return retention.unique_build_id(now or datetime.now(UTC), retention.taken_build_ids(root))
```

The root is the caller's when the caller has one — `RebuildContext` passes its
own `tiles_dir`, so the id is chosen against the directory the build is about to
be written into rather than against whatever `TILES_DIR` says.

A collision that gets past all that is still caught rather than silently
merged: `tiles.write_build_config` refuses a build directory that already
exists.

## Rolling back a rebuild

`./manage.py rollback_rebuild` puts the previous deployment back: the retired
schema becomes live again, each variant's `previous` tiles become `current`,
and the settings rows name the build being served again. It is dry by default —
run with no arguments it prints the build each variant would go back to and
changes nothing — and `--confirm` is what performs it.

```sh
docker compose exec -T api ./manage.py rollback_rebuild            # what would happen
docker compose exec -T api ./manage.py rollback_rebuild --confirm  # do it
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike
```

The restart is part of the procedure, not an afterthought: `valhalla_service`
does not reload tiles at runtime, so until the containers restart they are
still serving the build that was rolled away from.

It refuses unless **all three parts** of a previous deployment are there: a
settings row per variant naming a previous build, a `previous` tile link per
variant naming the same build, and a retired schema with segments in it. The
refusal names which part is missing. The most common one is a first-ever
rebuild, where the schema the first swap retired is the empty one that swap
created on its way past — rolling back to that used to promote an empty schema
over the served graph in silence.

What keeps that rollback target there:

- **A rebuild that fails after the swap is not retried.** A retry re-runs the
  whole rebuild including the swap, and the swap begins by dropping
  `<live>_old` — the schema this command puts back. So a `RECONCILE` failure is
  terminal, and its message says so: the new build is being served correctly
  and what is missing is the drift report, which is worth a hand-run or next
  week's rebuild rather than five more swaps.
- **Retention never removes what `current` or `previous` points at**, whatever
  its age and whatever the keep count is.

After a rollback there is no build before the one being served: `previous` is
removed and `previous_build_id` is cleared, so a second rollback refuses. The
way forward from there is a rebuild.

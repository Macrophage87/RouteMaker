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

## The maintenance queue is one slot

Procrastinate's default `--concurrency` is 1, and until wave 3 `compose.yaml`
ran the maintenance worker with that default.
Every periodic task except the rebuild queues there, so exactly one of them runs
at a time and anything ticking under a long job is dropped rather than delayed.

Two things follow, and only the first is fixed in the code:

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
2. **The bound is not restored to five minutes by that timeout**, and cannot be
   from inside the application. A tick falling inside a legitimate twenty-minute
   dump is still dropped, and a job holding the slot past ten minutes shows up
   as a heartbeat gap. The plan asks for the heartbeat to be "independent of the
   backup alert", which one slot cannot be. The deployment change that makes it
   true is one line in `compose.yaml`, on the `worker` service:

   ```yaml
   command: ["./manage.py", "procrastinate", "worker", "--queues=maintenance", "--concurrency=4"]
   ```

   (or `WORKER_CONCURRENCY: "4"` in its `environment:`, which Procrastinate reads
   for the same option). `compose.yaml` carries it and `tests/test_compose.py`
   pins it; a deployment that drops it should expect a heartbeat gap for the
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
| Dated tile build directories | 2 per variant, plus whatever `current` and `previous` point at | `pipeline.retention.prune_builds`, run by the rebuild task after the swap |
| Database dumps | 7 (`BACKUP_KEEP`) | `pipeline.retention.prune_backups`, run by the backup task after a verified dump |
| `scheduled_run` rows | 30 days, plus the newest row and the newest successful row per task | `core.runs.prune_run_rows`, run nightly |
| Finished `procrastinate_jobs` and their events | 30 days | `core.runs.prune_job_rows`, run nightly |

Two rules are load-bearing rather than incidental:

- **A promotion symlink protects its target whatever its age.** After a rollback
  `current` points at the *older* directory, and a plain newest-N rule would
  delete the graph being served.
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

## The source extract

The rebuild's first stage produces the map it builds from, rather than expecting
to find one. Until this existed nothing anywhere made `source.osm.pbf`: the
first rebuild on a new deployment stopped at stage one with "source extract
missing", and wherever somebody had made the file by hand every later weekly
rebuild re-derived the whole map from that one frozen snapshot — a weekly
refresh that refreshed nothing.

What is downloaded, per PLAN:13, is Geofabrik's three state extracts:

```
https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf
https://download.geofabrik.de/north-america/us/maryland-latest.osm.pbf
https://download.geofabrik.de/north-america/us/virginia-latest.osm.pbf
```

**Roughly 1–2 GB in total at today's sizes** — Virginia and Maryland are most of
it, the District is small — and approximate by nature, since these files grow
with the map. They are merged and then clipped, and **both** results are kept
under `<DATA_ROOT>/extracts/`:

| File | What it is | Who reads it |
| --- | --- | --- |
| `<region>-latest.osm.pbf` | the three downloads as they arrived | the merge |
| `merged.osm.pbf` | the three states, merged, **not** clipped | `valhalla_build_admins` |
| `source.osm.pbf` | that file clipped to the coverage region | every other stage |

The merged file is kept because admin data is built from it *before* the clip.
A clip cuts boundary relations at the coverage edge, so an admin database built
from `source.osm.pbf` describes administrative areas that stop where this
deployment's box does, and the graph is then charged a state- or
country-crossing cost along a line no boundary follows.

`curl` and `osmium` run in the `rebuild` container, so the pipeline image has
to carry both (`curl` and Debian's `osmium-tool`) alongside the Valhalla and
GDAL binaries; a rebuild on an image without them fails at stage one with a
`FileNotFoundError` naming the binary.

The commands are `curl -fsSL --retry 3 -o <file>.part <url>`, then
`osmium merge --overwrite <three files> -o merged.osm.pbf.part`, then
`osmium extract --overwrite -s smart -S types=any --bbox W,S,E,N -o
source.osm.pbf.part merged.osm.pbf`. Everything is written to a `.part` name and
moved into place only on success: a 1–2 GB transfer killed partway would
otherwise leave a truncated file under the real name, and nothing downstream can
tell a truncated PBF from a smaller region — osmium reads what is there and the
rebuild carries on with part of Virginia missing. A `.part` found on disk is
deleted and re-fetched, never resumed or renamed into place.

**The freshness rule.** The extract is rebuilt when either file is missing or
more than `SOURCE_EXTRACT_MAX_AGE` old, which defaults to **six days** —
deliberately just under the weekly cadence. At seven or more the ordinary weekly
run would accept last week's snapshot and the map would age by a week every
week; below it, a rebuild re-run in the same week (a retry, a hand-fired run, a
second attempt after a validation failure) reuses what is on disk instead of
pulling 1–2 GB again.

**Forcing a refresh**, when a rebuild must start from today's Geofabrik build:

```sh
rm <DATA_ROOT>/extracts/source.osm.pbf        # or set the variable and restart
SOURCE_EXTRACT_FORCE_REFRESH=1
```

Either works and there is no third mechanism. `SOURCE_EXTRACT_URLS` (a
comma-separated list) points the download at a mirror.

**The disk gate runs before the download, not after it.** The extract is the
largest single thing a rebuild puts on the data volume and it lands on the
volume the gate measures, so a gate placed after the extract had been produced
would be a gate on a volume the rebuild had already filled. With no extract on
disk there is nothing to measure, so the gate is sized from
`pipeline.source.ESTIMATED_BYTES` (2 GiB, which `check_disk_gate` multiplies by
four for the build's own three variant extracts and its scratch); once there is
one, its real size is what the gate charges. A rebuild refused by the gate has
downloaded nothing.

## After a rebuild: restart the routers

**`valhalla_service` does not reload tiles.** It opens `mjolnir.tile_extract`
once at start and serves that graph for the life of the process, so replacing
the `current` symlink promotes a build the running containers cannot see. The
swap is complete in the database and on disk, `valhalla_upstream` names the new
build id, and the three routers keep answering from last week's tiles until they
are restarted:

```sh
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike
```

Nothing in the rebuild does this, and there is no check that notices it has not
been done: the symptom is a deployment whose routes disagree with its own
segment table, which reads like a conflation bug rather than a missed restart.
Run it after every successful rebuild and after a rollback, which moves the same
symlink back.

The restart is a few seconds of 502s per variant, taken one at a time. Starting
the new containers against the new build before stopping the old ones — the
blue/green arrangement the plan describes, which would make the swap invisible
to a request in flight — is phase 2; it is recorded in the handoff rather than
built here.

## Deployment actions

- Add a `check_operations` cron entry, or point an existing monitor at it.
- The operations page is at `<DJANGO_ADMIN_PATH>core/scheduledrun/`; it is not
  linked from anywhere public and the admin path is not advertised.

## Build ids

`pipeline.run.new_build_id` is second-resolution, which is a directory name an
operator can read and is enough for a weekly job right up until two builds land
in the same second — a retry, a hand-fired rebuild, a test. The sub-second
answer lives in `pipeline.retention.unique_build_id`, and wiring it in is one
line in `new_build_id`:

```python
return retention.unique_build_id(
    now or datetime.now(UTC), retention.taken_build_ids(_setting("TILES_DIR"))
)
```

Until that lands, a collision is caught rather than silently merged:
`tiles.write_build_config` refuses a build directory that already exists.

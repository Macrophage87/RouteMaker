# Operations

What is watched, where an operator sees it, and what removes the things that
would otherwise fill the data volume. The plan's alert list is the source for
every number here; this document is where the mechanism behind each one lives.

## Where the alerts are

Two surfaces, one computation. Both read `core.runs.stale_task_details` and
`core.runs.failed_jobs`, so they cannot disagree about what is broken.

- **The operations page**, in the admin, at `<DJANGO_ADMIN_PATH>core/scheduledrun/`
  — with the default path, `/internal-8f3a/core/scheduledrun/`. It lists the
  stale tasks with the window each one missed, the jobs still running past the
  budget their own task enforces, the failed Procrastinate jobs with their
  attempt counts, and the last 25 runs. Instance admins only, and
  read-only to them as well: these rows are the evidence for an alert, so an
  admin who could edit them could silence one by hand. Anyone else gets the same
  404 the rest of the admin gives an unadmitted request.
- **`./manage.py check_operations`**, for anything that cannot log in. It prints
  one line per stale task, per wedged job, per failed job and per volume short
  of room for the next rebuild, and exits 1 if there is anything to print, 0
  otherwise. A cron entry is the intended caller:

  ```sh
  */10 * * * * cd /srv/routemaker && docker compose exec -T rebuild ./manage.py check_operations || mail-the-ops-channel
  ```

  It runs in `rebuild` and not `api` because of the fourth line: the free-space
  check is a `statvfs` on `TILES_DIR`, and `rebuild` is the one container that
  mounts the tiles. In `api` the same call would measure the container's own
  writable layer and report room that the rebuild does not have. The line names
  the path it measured, so a check run in the wrong container is visibly about
  the wrong filesystem rather than silently reassuring.

  **The `cd` is the entry, not decoration.** `docker compose` finds its project
  by looking for a compose file in the working directory and then upwards, and
  cron runs a job from the owner's home directory with a minimal environment.
  Without the `cd` the command is `no configuration file provided: not found`
  and exit 1 on every tick — which the `||` turns into a page every ten
  minutes, from the monitor, saying nothing about the stack it is monitoring.
  The path is wherever this repository is checked out on the host;
  `docker compose --project-directory /srv/routemaker exec -T api ...` does the
  same job without changing directory. And the `&&` is deliberate: a `cd` that
  fails — a checkout moved, a volume not mounted — pages too, rather than
  silently running nothing.

**Wedged jobs** are the third row because the first two miss the same outage.
Both lists are built from `status="failed"`, and a worker killed mid-job never
writes that status — the process that would have written it is gone, so the row
stays `doing` for ever. A rebuild killed at hour three was therefore on no
surface at all until `weekly_rebuild` went stale, eight days later, while the
job holding the rebuild queue's only slot was never going to move. A job still
`doing` longer ago than the budget its own task enforces (`REBUILD_TIMEOUT_S`
for the rebuild, the task's own figure otherwise — one table, in
`core.runs.job_budgets`) is reported as wedged, on both surfaces, and
`check_operations` exits non-zero on it.

There is no paging integration and no scraper yet; the plan records both as
follow-ups. What exists is the thing that has to exist first — the state is
computed, and it is visible.

## What is watched, and for how long

`core.runs.STALE_AFTER` is the whole list. A task is stale when its most recent
**successful** run started longer ago than its window; a failure is not a
success, and neither is a run that is still going.

A task that has never succeeded at all is measured from the deployment's own
first run row instead — the oldest `ScheduledRun` of any task — and on a
database with no rows at all nothing is stale. **So the cron entry pages once a
window has genuinely passed and not before.** It used to page immediately: on a
fresh deployment `check_operations` exited 1 with all five tasks named in its
first minute, because "has never run" and "has not run for long enough to
matter" were the same missing row. The first alert an operator ever saw was
therefore a false one, on the morning of the install, from the entry they had
just added — and an alert that is wrong the first time it fires is an alert
that gets muted. The windows are unchanged: a task that is genuinely never
scheduled is still named, eight days later for the rebuild and ten minutes
later for the heartbeat, which is the same lateness every other silent failure
here gets.

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

**A stack that is down across a scheduled tick loses that run rather than
catching it up.** The schedules in the table are Procrastinate periodic tasks,
and its deferrer ignores any tick it finds further in the past than
`procrastinate.periodic.MAX_DELAY`, which is 10 minutes: on start it defers
what is due now and drops what was due while nothing was running. So a host rebooted, or a stack
left down, for more than ten minutes across Tuesday 08:00 UTC skips that week's
rebuild silently, and the first thing that says so is `weekly_rebuild` going
stale eight days later. The catch-up is a hand-fired one —
`./manage.py run_rebuild_now`, "Firing a rebuild by hand" below — and it is
worth firing after any maintenance window that covered a scheduled time. The
five-minute tasks catch up on their own within the window; the weekly one is
the one that costs a week.

**A job left `doing` by a worker that died is not one any of these windows
notices in time**, which is what the wedged-job row above is for and what
`./manage.py unwedge_job <job_id>` moves back to `todo`.

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
to carry both (`curl` and Ubuntu's `osmium-tool`) alongside the Valhalla and
GDAL binaries; a rebuild on an image without them fails at stage one with a
`FileNotFoundError` naming the binary.

The commands are `curl -fsSL --retry 3 -o <file>.part <url>`, then
`osmium merge --overwrite -f pbf <three files> -o merged.osm.pbf.part`, then
`osmium extract --overwrite -f pbf -s smart -S types=any --bbox W,S,E,N -o
source.osm.pbf.part merged.osm.pbf`. Everything is written to a `.part` name and
moved into place only on success: a 1–2 GB transfer killed partway would
otherwise leave a truncated file under the real name, and nothing downstream can
tell a truncated PBF from a smaller region — osmium reads what is there and the
rebuild carries on with part of Virginia missing. A `.part` found on disk is
deleted and re-fetched, never resumed or renamed into place.

**`-f pbf` is what makes the `.part` names usable.** osmium takes the output
format from the file name’s last dot-separated element, and `part` names no
format, so both commands exited non-zero during argument setup — before reading
a byte — with *Could not detect file format for filename*. `-f`
(`--output-format`) is the documented override for exactly that case and both
subcommands accept it. A rebuild that fails at the merge with that message on an
image that has `osmium`, having already downloaded all three state extracts, is
this flag having gone missing.

The merge assumes the three downloads are the same day’s data, which is what
Geofabrik publishes: `osmium merge` is not for files from different points in
time, and given them it keeps every version of an object rather than one. It
says so itself — a merge of mismatched snapshots warns about multiple versions
of the same object, in the rebuild’s own build log. That warning after a
refresh is the thing to look for when geometry or admin polygons come out wrong,
and it usually means `SOURCE_EXTRACT_URLS` points at mirrors that are out of
step with each other.

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

## Firing a rebuild by hand

```sh
docker compose exec -T rebuild ./manage.py run_rebuild_now
```

This document has referred to a hand-fired rebuild in three places since wave 3
— the build-id collision above, the freshness rule's list of reasons a rebuild
re-runs inside the same week, and the RECONCILE failure that is "worth a
hand-run" — and until this command there was no way to fire one. The rebuild is
a Procrastinate periodic task on its own queue, so the only route to it was
`python -c` inside the right container with Django set up by hand.

It **queues** a job and returns; it does not run the rebuild. The `rebuild`
service is what picks the job up, because that is the container with the
Valhalla binaries, the data mounts and the six-hour budget, and it takes it
within seconds while that service is up. Follow it with
`docker compose logs -f rebuild`, or on the operations page.

Run it in `rebuild` or in `worker`, not in `api`: the queue is in the database
so any Django container could defer the job, but the command prints what it
queued and the two that matter are the ones an operator is already exec'ing
into for the rest of this document.

**A second call while one is queued or running is refused**, with a non-zero
exit and a message naming the job in flight by id and status. Two things do
that, and it is worth knowing which does which, because the first was once
described as doing both.

`weekly_rebuild` carries `queueing_lock="weekly_rebuild"`, and Procrastinate's
queueing-lock index is partial: `WHERE status = 'todo'`. It deduplicates jobs
that are **queued** and has no opinion at all about one that is **running**.
Deferring a second rebuild while the first was `doing` therefore succeeded — and
then cost the running one its retry, because `procrastinate_retry_job` puts a
retried job back to `todo`, straight onto the row the second deferral had
inserted: a transient failure in the rebuild became a unique violation inside
the job-finishing path instead of a retry.

So the command reads the job table before it defers and refuses if any
`weekly_rebuild` is `todo` **or** `doing`, naming the job. The lock is still
there and still does the half it can: it settles the race between the read and
the insert — two operators, or an operator and the Tuesday tick — and that
arrives as `AlreadyEnqueued` and is reported as a refusal too. Both refusals
are reported rather than swallowed because an operator who fires a second
rebuild under the impression the first has stalled must not be told it worked.
Two concurrent rebuilds would write the same staging schema and the same dated
tile directory.

The task refuses as well, on the way in: `weekly_rebuild` will not **start**
while another `weekly_rebuild` is `doing`. That is the half the periodic
deferrer needs. A tick is skipped only on `AlreadyEnqueued`, which the `todo`
index raises and a running job does not, so a hand-fired rebuild still in
flight on a Tuesday morning is **doubled** by that tick rather than dropping
it. What has been serialising the two in practice is `--concurrency=1` on the
`rebuild` service — one slot, so the second job waits rather than being refused
— and that is a slot count, not a guarantee. The in-task check is the guarantee
for the case the slot count does not cover: a second rebuild that reaches a
worker while another is running — a second `rebuild` replica, or a raised
`--concurrency` — is refused on the way in, without retrying, names the job it
deferred to, and finishes **aborted** rather than failed, so it does not page.
On the shipped single slot it never fires, because the second job cannot reach
a worker while the first holds the slot: the tick's job waits in `todo` and
runs a **second full rebuild** the moment the hand-fired one finishes. That is
the doubling to expect on a Tuesday, and its one lasting consequence is that
`<live>_old` and the `previous` links then name the hand-fired build from an
hour earlier rather than last week's, which is what `rollback_rebuild` would
put back.

Rebuilds started by hand are recorded in the audit log, as `run_rebuild_now`
with the job id, with no actor — there is no request and no session behind a
shell in a container, and a null actor is what the log means by the host
operator. `rollback_rebuild --confirm` writes one the same way.

## First rebuild on a fresh host

A new deployment serves no routes at all until this has been done once: nothing
but a rebuild creates the tiles the three Valhalla containers mount, and the
`current` symlinks they read do not exist yet. The order below is the order the
code forces, not a preference — each step exists because the one after it fails
without it.

**None of this has been executed.** There is no Docker daemon in the
development environment and registries are blocked, so no image in this
repository has been built and this stack has never been started. What has been
run here is the suite, which covers the pieces: the rebuild task against its
real handler set with the binaries stood in for, a cold worker in a subprocess
running a deferred job, `run_rebuild_now` against a real database (it queues one
job, and a second call is refused), and the compose configuration rendered from
`.env.example`. The sequence itself is read out of the code, step by step, and
the first host to run it is the first test of it.

1. **Prepare the data volume, before the first `up`.**

   ```sh
   set -a; . ./.env; set +a
   sudo -E sh scripts/prepare_data_root.sh
   ```

   Ordering, not hygiene: Docker creates a missing bind-mount source itself, as
   a root-owned directory, and both images run as uid 10001. See
   docs/DEPLOYMENT.md, "`${DATA_ROOT}` and the order it has to be prepared in".

2. **Set the bootstrap admin id, then build and start.**

   ```sh
   # in .env, before the first up:
   BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID=<your Discord id>
   ```

   ```sh
   docker compose build
   docker compose up -d
   ```

   The id goes in **before** the first `up` because compose reads `.env` when
   it creates a container and not afterwards: a value added later reaches the
   running `api` only when that container is recreated, which is
   `docker compose up -d api` and specifically not `docker compose restart api`
   — a restart restarts the process with the environment it was created with,
   and the sign-in that follows it gets a 404 from the admin with nothing in
   any log to explain it. Step 4 is the rest of that bootstrap; what it needs
   from here is the id already in the container's environment.

   `bot`, `renderer` and `photon` are behind the `unbuilt` profile and are
   skipped: the first two have no source and no image, and photon's pinned
   image would download a 61 GB planet index onto the root volume on first boot
   (docs/DEPLOYMENT.md, "Photon"). `migrate` waits for the database's health
   check and runs every migration, and `api`, `worker` and `rebuild` wait for
   it to have completed.

   **On a host that is already serving, check first whether a rebuild is
   running.** `docker compose up -d`, `restart` and `down` all stop the
   `rebuild` container, and stopping it during a build is a wedge: the worker
   gets a SIGTERM, Procrastinate waits for the running job rather than
   abandoning it — `shutdown_graceful_timeout` is unset, so the wait has no
   bound — and the `stop_grace_period: 60s` on that service expires into a
   SIGKILL that leaves the `weekly_rebuild` row `doing` with nothing behind it.
   Nothing retries it, the next Tuesday's tick refuses on the job that is still
   `doing`, and the alert arrives eight days later. `docker compose ps rebuild`
   and `docker compose logs --tail=20 rebuild` are the check;
   `./manage.py unwedge_job <job_id>` is the repair if it has already happened.
   A build takes up to six hours from 08:00 UTC on Tuesdays and no grace period
   can cover it, so the answer is to wait or to accept the unwedge, not to
   lengthen the grace.

   If this first `up` reports that `migrate` failed, run `docker compose up -d`
   again before debugging anything. The health check gates `migrate` on a
   database answering on TCP, and its start period is 60 seconds; a slow host
   doing initdb, the PostGIS extension scripts and the first start on an empty
   volume can take longer than the retries allow. The second `up` starts
   `migrate` against a database that is by then up, and the three services
   gated on it having completed follow. Nothing is left half-applied by the
   first attempt: `migrate` either connects or does not.

3. **Collect the static assets**, the deploy step in docs/DEPLOYMENT.md. Until
   this runs the admin renders unstyled, which is the surface the next step
   uses.

4. **Claim the first instance admin.** There is no `createsuperuser` here and
   no password login. With the id from step 2 already in the `api` container's
   environment, sign in at `/auth/login` with that Discord account and open the
   admin: the first admin request under that id writes it into the
   instance-admin list, audits the claim and spends the path for good. Unset it
   afterwards, at your leisure — it is inert once claimed.

   If you skipped step 2 and are editing `.env` now, the container has to be
   recreated for the new value to reach it: `docker compose up -d api`.
   `docker compose restart api` does not re-read `.env` and leaves you signing
   in against the environment the container was created with.
   docs/DEVELOPMENT.md has the whole mechanism.

5. **Fetch the extract by running the rebuild once, and expect it to stop.**

   ```sh
   docker compose exec -T rebuild ./manage.py run_rebuild_now
   ```

   This is not a wasted run and there is no way to skip it. The rebuild's first
   stage, `FETCH_EXTRACT`, is the only thing in the deployment that produces
   `<DATA_ROOT>/extracts/source.osm.pbf` — it downloads the three Geofabrik
   state extracts, merges them and clips the merge to the coverage box — and the
   *second* stage, `LOAD_REFERENCE_DATA`, is what needs the reference files. So
   this run downloads 1–2 GB, writes `merged.osm.pbf` and `source.osm.pbf`, and
   then fails at stage two with "reference data missing".

   That failure is terminal rather than retried (`ReferenceDataMissing` is in
   `config.procrastinate.terminal_causes`), so it costs one run, not six. The
   extract it wrote stays on the volume and the freshness rule — six days —
   means step 7 reuses it rather than pulling it again.

6. **Install the reference data, pointed at the extract step 5 just wrote.**

   The GeoJSON inputs are not in this repository and the stack cannot download
   them, so put them on the host first, under a directory the `rebuild`
   container actually binds — it binds five, not the whole volume, so a file
   dropped anywhere else under `${DATA_ROOT}` is not visible to it.
   `${DATA_ROOT}/reference/inputs/` is the one this document uses, and the
   container sees it at `/data/reference/inputs`:

   ```sh
   set -a; . ./.env; set +a
   sudo install -d -o 10001 -g 10001 "$DATA_ROOT/reference/inputs"
   # then copy tl_2024_us_uac20.geojson, vdot-aadt-2024.geojson and
   # ddot-aadt-2024.geojson into "$DATA_ROOT/reference/inputs"
   ```

   ```sh
   docker compose exec -T rebuild python3 scripts/install_reference_data.py \
       --data-root /data --extract /data/extracts/source.osm.pbf \
       --urban-areas /data/reference/inputs/tl_2024_us_uac20.geojson \
       --volume /data/reference/inputs/vdot-aadt-2024.geojson \
           --volume-source vdot --volume-year 2024 \
       --volume /data/reference/inputs/ddot-aadt-2024.geojson \
           --volume-source ddot --volume-year 2024
   ```

   **Every input path is absolute and inside the container.** A bare
   `tl_2024_us_uac20.geojson` resolves against the image's working directory,
   `/app`, where the file is not and cannot be: the script would exit on a
   missing file, and the only thing to debug would be a name that looks right.

   **Both agencies, not one.** `--volume` and its two companions repeat and are
   matched up in order, and installing a single agency is the case the
   conflation step has nothing to do: its whole job is to arbitrate between two
   publishers on a road they both cover, and with one file in the input the
   locality-over-state precedence rule has nothing to choose between. VDOT's is
   the traffic-volume export from the Virginia Roads portal; the District's is
   DDOT's AADT layer from the District's open-data portal. Maryland's arrives
   the same way and can be added as a third pair. docs/DEVELOPMENT.md,
   "Reference data", has what each one is and how the counts have to be
   normalised before they get here.

   `--extract` is the clipped `source.osm.pbf`, and the clipped one is right:
   the script reads ways out of it to decide which way ids fall inside a Census
   urban area, and a way outside the coverage box is a way this deployment does
   not route over. (`merged.osm.pbf`, the unclipped file kept beside it, exists
   for `valhalla_build_admins`, which needs boundary relations the clip cuts.)
   The crossings fixture is in the image and is copied for you.

   Run with `--data-root` alone it installs the crossings and exits non-zero
   naming whichever of the other two is still missing, which is the cheap way to
   check this step before spending step 7 on it.

7. **Run the rebuild for real.**

   ```sh
   docker compose exec -T rebuild ./manage.py run_rebuild_now
   docker compose logs -f rebuild
   ```

   The elevation cache fills here rather than in a step of its own: `ELEVATION`
   is a stage of the rebuild, and it downloads a one-arcsecond 3DEP tile for
   every one-degree cell the coverage box touches and resamples each with
   `gdalwarp` into `<DATA_ROOT>/elevation`. It is the slowest part of a first
   rebuild and the cheapest part of every later one, since the cache is checked
   rather than refilled. It is also the stage with the most external surface: the
   3DEP fetch has never been executed in this environment — the host is blocked
   from that bucket — so a first host should expect to debug it before it expects
   it to work.

   Budget six hours, which is also the point at which the rebuild abandons
   itself.

8. **Restart the routers.** `valhalla_service` opens its tile extract once at
   start, so until this runs the three containers are serving the empty
   directories they started against.

   ```sh
   docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike
   ```

After that the weekly schedule carries it: Tuesdays 08:00 UTC, with the alert
windows in the table above watching that it keeps happening.

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

## Wedged jobs

A job stuck in `doing` with nothing running it. Procrastinate marks a job
`doing` when a worker picks it up and writes its terminal status from that
worker's own process, so a worker killed with **SIGKILL** — `docker compose
down`, an `up -d` that recreates the container, a host reboot, the OOM killer —
leaves the row `doing` for ever. Nothing in the library repairs it:
`prune_stalled_workers` deletes stalled *worker* rows and the job's `worker_id`
is `ON DELETE SET NULL`, so the job is disowned rather than requeued, and
`get_stalled_jobs` reports such jobs and is called by nothing.

For the rebuild that is not a cosmetic leftover. Both single-flight checks read
that row: `run_rebuild_now` refuses with "a rebuild is already in flight", and
`weekly_rebuild` refuses to start every Tuesday. **A deployment whose rebuild
was killed once never rebuilds again** until the row is cleared.

The operations page and `manage.py check_operations` both name it — a job
`doing` for longer than the budget its own task enforces
(`core.runs.job_budgets`) is reported as wedged, and `check_operations` exits
non-zero on it. Each line carries the job id and the remedy:

```sh
docker compose exec -T worker ./manage.py unwedge_job <job id>
```

`unwedge_job` puts the job back to `todo` through `procrastinate_retry_job`,
which is the same function the retry strategy calls, and writes an audit row
with a null actor — the convention for the worker or the host operator, the
same as `run_rebuild_now` and `rollback_rebuild --confirm`. It refuses in three
cases, all of them by design:

- **The job is not `doing`.** A `todo` job is already queued and a terminal one
  is finished; neither is wedged, and a fresh run is `run_rebuild_now`.
- **The worker is still alive.** A running worker updates
  `procrastinate_workers.last_heartbeat` every 10 seconds from its own asyncio
  task, and a sync task body runs in a thread, so a worker six hours into a
  rebuild is still beating. Procrastinate's own stalled threshold is 30
  seconds and that is the number used here. Requeueing a job that is genuinely
  running is how two rebuilds end up writing the same staging schema.
- **Another job already holds the same queueing lock in `todo`.** Procrastinate
  allows one `todo` job per lock, so moving this row back would be a unique
  violation inside the retry function. The queued job is the next run; let it
  run.

After it succeeds the rebuild service picks the job up within seconds while it
is running (`docker compose logs -f rebuild`). If that service is not up, start
it, or queue a fresh rebuild with `run_rebuild_now` once the row has cleared.

**The fallback, if the command is not available** — an older image, a container
that will not start — is Procrastinate's own shell, which is what this
procedure was before there was a command and is documented here so it is
written down somewhere:

```sh
docker compose exec -T worker ./manage.py procrastinate shell
> retry <job id>
```

It does the same UPDATE and none of the checks: it will happily requeue a job
whose worker is alive, so confirm the worker is gone first.

## Rolling back a rebuild

**Not while a rebuild is in flight.** The command refuses, by job id and
status, if any `weekly_rebuild` is `todo` or `doing` — on the dry run as well
as on `--confirm`, because the dry run's whole output is advice about an action
that is not safe to take yet. A rollback drops any staging schema `CASCADE`,
which is the schema a running rebuild is writing into, and repoints the
`ValhallaUpstream` rows the swap is about to repoint itself; neither collision
raises at the time. The rebuild fails hours later as an ordinary
`RebuildFailed` and is retried five times, or — if the rollback lands between
the swap's repoint and its schema rename — it succeeds having left the tiles
naming one build and the live schema another, with no error anywhere. To tell
what is in flight: `docker compose logs -f rebuild` shows a running one, and
the operations page or `manage.py check_operations` names a queued one, a
running one and a wedged one. Let it finish, stop it, or clear it with
`unwedge_job` (above), then run this again.

`./manage.py rollback_rebuild` puts the previous deployment back: the retired
schema becomes live again, each variant's `previous` tiles become `current`,
and the settings rows name the build being served again. It is dry by default —
run with no arguments it prints the build each variant would go back to and
changes nothing — and `--confirm` is what performs it.

```sh
docker compose exec -T rebuild ./manage.py rollback_rebuild            # what would happen
docker compose exec -T rebuild ./manage.py rollback_rebuild --confirm  # do it
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike
```

**In `rebuild`, not in `api`.** This command reads and rewrites the promotion
symlinks under `settings.TILES_DIR`, which is `<DATA_ROOT>/tiles`. The `api`
service mounts no part of the data volume and sets no `DATA_ROOT`, so inside
that container `DATA_ROOT` is the module's fallback `BASE_DIR / "data"` and
`TILES_DIR` is `/app/data/tiles` — a path on the container's own writable layer
with nothing in it. Run there, `rollback_target` finds no `previous` link for
any variant and the command refuses with "no previous tiles", which reads like
a deployment that has never rebuilt rather than like a command in the wrong
container. `rebuild` is the service that binds the tile directory — along
with `elevation`, `extracts`, `reference` and its own work directory — under
`/data` and sets `DATA_ROOT=/data`, so the paths it resolves are the ones the
swap wrote. (`worker` sets `DATA_ROOT=/data` too, but mounts only `backups`, so the
tiles are equally absent there.)

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

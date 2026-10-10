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
  of room for the next rebuild — or that it could not measure — and exits 1 if
  there is anything to print, 0 otherwise. A cron entry is the intended caller:

  ```sh
  */10 * * * * cd /srv/routemaker && docker compose exec -T worker ./manage.py check_operations || mail-the-ops-channel
  ```

  **It runs in `worker`.** Three of the four checks read the database only; the
  fourth is a `statvfs` on `TILES_DIR`, so the container has to be able to see
  the tiles — `worker` binds `${DATA_ROOT}/tiles` at `/data/tiles` read-only
  for exactly this caller. In a container with no tiles volume that path does
  not exist at all, and the check does not guess: it prints `not measured`,
  names the path that is missing and exits 1, rather than measuring the
  container's own writable layer and reporting room the rebuild does not have.
  A check that cannot see the volume is not a check that passed.

  `rebuild` also has the tiles and is the wrong container for a different
  reason. This entry fires every ten minutes, and `docker compose exec` runs
  the process **inside the target container's cgroup**: in `rebuild` that is
  144 spawns a day of a ~95 MiB Django process inside the 8 GB limit the
  eight-hour build is sized against, and six of them land inside every hour of
  that build. `worker` is a 2 GB service whose own tasks run for seconds a day,
  and it is up whenever the stack is — including while `rebuild` is the
  container an `up -d` is recreating.

  **The `cd` is the entry, not decoration.** `docker compose` finds its project
  by looking for a compose file in the working directory and then upwards, and
  cron runs a job from the owner's home directory with a minimal environment.
  Without the `cd` the command is `no configuration file provided: not found`
  and exit 1 on every tick — which the `||` turns into a page every ten
  minutes, from the monitor, saying nothing about the stack it is monitoring.
  The path is wherever this repository is checked out on the host;
  `docker compose --project-directory /srv/routemaker exec -T worker ...` does
  the same job without changing directory. And the `&&` is deliberate: a `cd`
  that fails — a checkout moved, a volume not mounted — pages too, rather than
  silently running nothing.

  **Expect one page per `docker compose up -d`.** The entry runs against a
  named container, and an `up -d` that recreates `worker` — a `TAG` bump, an
  edit to `compose.yaml`, a changed environment value — leaves a window of a
  few seconds in which `docker compose exec -T worker` has nothing to attach
  to and exits non-zero. That is one tick's `||`, from a deploy, and it is
  cheaper to know about than to design around.

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
**epoch** instead: the earlier of its oldest `ScheduledRun` row and its last
applied migration (`MAX(django_migrations.applied)`). `migrate` runs before any
worker starts, so that epoch exists on a stack where no job has ever been
dequeued — which is exactly the outage (a `--queues` typo, a worker in a crash
loop) that the rule this replaced reported as healthy for ever. There is no
longer any state in which nothing is stale: a database with no run rows at all
still has migrations, and the windows run from when they were applied.

**So the cron entry pages once a window has genuinely passed and not before.**
It used to page immediately: on a fresh deployment `check_operations` exited 1
with all five tasks named in its first minute, because "has never run" and "has
not run for long enough to matter" were the same missing row. The first alert an operator ever saw was
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
eight-hour build must not sit in front of a five-minute tick.

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
| `rate_limit_window` rows (keyed client addresses) | 1 day idle, so at most about 30 hours | `core.ratelimit.purge_expired`, run by the six-hourly membership sweep |

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

## The public routing API: its limits, and clearing a client

`POST /api/route` plans a route for anyone, signed in or not (the owner's
amendment of 2026-09-26 in PLAN.md, The anonymous surface); its schema is at
`/api/openapi.json`, and there is no interactive docs page. What bounds it, in
the order a request meets it:

| Check | Limit | Answer |
| --- | --- | --- |
| Content type, declared body size | `application/json`, at most 8 KB | 400 |
| Requests per client | 60 per fixed 60 s window, per address (IPv6 per /64) | 429, `Retry-After` the rest of the window |
| Routes in flight per client | 1; a second only while at least 2 of the api's slots would stay free after it (so never, on the default pool of 3) | 429, `Retry-After: 2` |
| Routes in flight, whole api | `WEB_CONCURRENCY` less 2, less `GEOCODE_CONCURRENCY` (3 at compose's default of 7 workers) | 503, `Retry-After: 5` |
| Points, coverage, preset | 2 to 25 points, each inside `COVERAGE_BBOX`; `default`, `group-ride`, `mass-ride` | 400 |
| Long ride | Past 93 mi (150 km) of straight line between consecutive points, a signed-out request without `"confirm_long": true` | 409 `{"error", "code": "confirm_long", "span_km"}`, the router not called |
| Long rides in flight | 1 per client and 1 for the whole api, signed in or not, on top of the slots above | 503 (the deployment's slot is taken first, so the per-client 429 does not arise on a long pool of 1), `Retry-After: 5` |
| Length ceiling | 200 km of straight line, however asked | 400 "too long" |
| Time | 40 s for the whole request from its arrival, a long ride 50 s; the router calls get all but the last 3 s, at most 35 s per call (45 s on a long ride) | 502 if the router does not answer, 503 with `Retry-After: 30` if the budget runs out before `/route` answers (on a long ride with `"code": "long_ride_timed_out"`, which the planner shows at once instead of resending); a trace cut short leaves its legs' stress `unknown` |

Place search and place names (`GET /api/geocode`, `GET /api/reverse`,
signed out; the contract is in docs/DEVELOPMENT.md) have their own limits, in
`core/ratelimit.py`:

| Check | Limit | Answer |
| --- | --- | --- |
| A browser's own word that another site sent it | `Sec-Fetch-Site` `cross-site` or `same-site` | 403, not counted |
| Searches per client | 5 per fixed 1 s window, then 60 per 60 s (PLAN.md:65); a request the first refuses does not spend the second | 429, `Retry-After` |
| Names per client | 30 per fixed 10 s window (a shared plan's 25 points at once), then 60 per 60 s, counted apart from search | 429, `Retry-After` |
| Geocoding in flight per client | 1, search and names together; a request waits up to 1 s for it | 429, `Retry-After: 2` |
| Geocoding in flight, whole api | `GEOCODE_CONCURRENCY`, 2 (the owner's answer of 2026-09-28); names may take only one of them, so a plan being named always leaves one for search; a request waits up to 1 s for a slot, at most 1 waiting across the api | 503, `Retry-After: 5` (at once when one is already waiting) |
| Photon | 4 s per request (`PHOTON_TIMEOUT_S`); Photon's own query timeout is 3 s | 502 |
| The router's locate, for a name | 3 s (`geocode.LOCATE_TIMEOUT_S`); past it the name is "near" a place | - |

The counts are rows in the same `rate_limit_window` table as routing's, under
the scopes `geocode-s`, `geocode`, `reverse-10s` and `reverse`, and are cleared
the same way (below).

The content type is checked before the count on purpose: a page on any site
can make a visitor's browser send a `text/plain` or form POST here without a
preflight, and counting those would let it spend that visitor's budget.

**How the workers are shared.** Compose runs 7 gunicorn workers (on 3 cpus;
the owner's answer of 2026-09-28 raised them from 5 so place search could
have two lookups at once). Four pools take them, each an advisory-lock slot
held for the length of a request:

| Pool | Slots on 7 workers | Held for at most |
| --- | --- | --- |
| Routes (`ROUTING_CONCURRENCY`, the workers less two less the geocoding slots) | 3 | 40-50 s (the time budget) |
| Geocoding (`GEOCODE_CONCURRENCY`) | 2 | Photon's 4 s, plus the router's 3 s for a name |
| Geocoding waiting room (`GEOCODE_IN_FLIGHT.max_waiters`) | 1 | 1 s (the wait), then served or refused |
| Stress tile draws (`TILE_CONCURRENCY`, the workers less one less routes less geocoding) | 1 | the 2 s draw timeout (one cold draw on a busy host ran to 5.46 s) |

So at worst all 7 are held at once - 3 + 2 + 1 + 1 - and a worker is free
again within about a second, when the waiter is served or refused. That is
the owner's answer of 2026-09-28, "Free within ~1 s (Recommended)", refining
the earlier "a worker always free for /healthz" after routing, tiles and
search merged; `/healthz`'s 5 s healthcheck waits out that second. Without the
waiter, routes, lookups and draws leave one worker free outright; that is
what `tests/test_tile_cache.py` holds for every worker count from 5 to 16,
with the waiter as the only thing that may take it. Below five workers the
pools can hold every worker between them.

**Geocoding waiters.** A geocoding request that finds both slots busy waits up
to a second for one, polling every 50 ms, and a waiting request holds a
gunicorn worker without holding a slot. So the waiting room is capped at one
(counted like the slots with advisory locks): with one already waiting across
the deployment, a request is refused at once with 503. Uncapped, 12 waiters
pushed `/healthz` to 5.4 s during a Photon stall (round-2 review); with two,
both spare workers were held and it still waited 5.45 s; with one, the
round-3 stall probe (3 routes held, Photon paused, 12 searches) had `/healthz`
answer in 0.13-0.33 s.

**Setting `WEB_CONCURRENCY` by hand.** The routing pool follows it: 5 workers
give 1 routing slot (5 - 2 - 2) and 1 tile draw, not the 3 routes they gave
before geocoding had two slots; 7 (compose's default) gives 3 and 1; each
worker above 7 is one more routing slot. The routing, geocoding and tile
pools keep distinct scope ids (routing 1, long rides 2, tiles 3, geocoding 4);
`tests/test_ratelimit.py` fails on a clash. Without the routing
limit a burst
of long routes inside one client's per-minute budget held every worker and
`/healthz` went unanswered for 19 s, past compose's 5 s healthcheck. It is a
PostgreSQL advisory lock held on the worker's connection for the length of the
request, so a killed worker's slot is released with its connection, and a
slot that cannot be unlocked closes the connection, which releases it too.

**Long rides.** The owner's decisions of 2026-09-26 (PLAN.md, Moderation and
abuse limits): a request longer than 93 mi (150 km) of straight line is planned, but a
signed-out visitor is first asked to confirm it - the 409 carries the span,
and the front end resends with `confirm_long` - and a signed-in one is not;
nothing past 200 km is planned, signed in or not; and a long ride may take up
to 50 s where an ordinary one keeps 40 s. Signed in means a current session
of an account that is not banned or deleted; a forged or stale session cookie
is treated as signed out. Reading the session changes nothing about CSRF: the
endpoint changes no state, and a cross-site page cannot send it
`application/json` without a preflight, which is never granted. Every long
ride, signed in or not, holds one of the long slots for as long as it runs, so
at most one is planned at a time across the api and ordinary plans carry on
beside it; those slot figures (one per client, one for the api) are the
implementation's choice, not the owner's. The longer limit is there because a
single long leg whose graph tiles are not yet in the router's cache is one
slow search: Culpeper to Baltimore (150.4 km of straight line, 183 km routed)
took 43.9 s cold on a loaded host and 9.5 s warm.

**The time budget and gunicorn's timeout.** A request's budget - 40 s, 50 s
for a long ride - runs from when it reaches the api (Django's first middleware,
`core.middleware.RequestClockMiddleware`, stamps it), so the other middleware,
the count, the slots, the router calls, the stress join and the answer are all
inside it; only gunicorn's reading of the request comes before it. The router
calls get all of it but the last 3 s (`ANSWER_RESERVE_S` in
`core/routing.py`), and one call at most 35 s (45 s on a long ride). A request
whose `/route` has not answered by then is 503 with `Retry-After: 30`; on a
long ride that 503 also carries `"code": "long_ride_timed_out"`, and the
planner shows it at once rather than resending it after the Retry-After as it
does other 503s, since the same ride would most likely hold the one long slot
for its whole budget again ("Try again" still waits the 30 s out). One
whose traces run out of time is answered with the rest of its stress
`unknown`. gunicorn kills a worker whose request passes `GUNICORN_TIMEOUT`
(`docker/api-entrypoint.sh`, default 60 s) and Caddy then answers an empty,
non-JSON 502, so that timeout must stay at least ten seconds above the long
budget; a test reads the entrypoint's default and fails if it does not. Do not
lower `GUNICORN_TIMEOUT` below 60 without lowering the budgets in
`core/routing.py` first. When the api gives up on a router call the router
does not: Valhalla finishes the search and the answer is dropped, so the long
slot bounds the api's workers, not the routers' CPU.

**What the slots do not stop.** They are counted per address, so a few
coordinated addresses can still fill the pool: three on the default of three
slots, each holding one long-running route. Every other request then gets 503
for as long as they keep it up, though `/healthz`, the tiles, sign-in and the
admin still answer. That is inherent in identifying clients by address, and no
limit keyed on it removes it; what it bounds is the cost, at most one worker
for 40 s per request (50 s for the one long ride), and the reach, the routing
endpoint alone. An account
or a proof-of-work step would be the next lever, and neither is built.

**Who a client is.** The last `X-Forwarded-For` entry, which Caddy writes from
the peer it saw, replacing whatever the client sent. That is only true while
Caddy is the one proxy in front of the api. Put a CDN or a load balancer in
front of it, or give Caddy a `trusted_proxies` list, and the last entry becomes
that proxy's address: every visitor would then share one budget and one pair of
in-flight slots. Configure the proxy's real-client header through to the api
before doing either.

**What is stored.** `rate_limit_window` holds one row per client per limit: a
keyed digest of the address (HMAC with `SECRET_KEY`), the window's start and
the count. No address is stored, so a row cannot be looked up by address with
SQL; compute the key first. To clear one client who has been refused - the
count resets on its own at the end of the minute, so this is rarely needed:

```sh
docker compose exec -T api python manage.py shell -c "from core.models import RateLimitWindow; from core.ratelimit import client_key; print(RateLimitWindow.objects.filter(client=client_key('198.51.100.7')).delete())"
```

An IPv6 client is keyed by its /64, written as the network, for example
`client_key('2001:db8:1:2::/64')`. Rotating `SECRET_KEY` changes every key, which
simply starts every client's count afresh. Rows idle for a day are deleted by
the membership sweep every six hours, and the table's data is not in the
nightly dump.

The table arrives with migration `core.0008_rate_limit_window`, which the
`migrate` one-shot applies before the api starts; nothing else is needed on
deploy.

## Intersection costs and the calm search: what to watch

FOLLOWUP-INTERSECTIONS (2026-10-01, revised 2026-10-02; docs/DEVELOPMENT.md, "Intersection costs,
the calm search and the detour warning" is the long form). What an operator
needs:

**Nothing new to deploy, one new column set to build.** The route's junctions
are read from the live `segment` table and the existing routers (`/locate` and
`/trace_attributes` are among the endpoints the config already serves), so the
code works the day it is deployed. The segment table gains `road_speed_mph`,
`road_lanes` and `road_oneway` (`pipeline.schema.SEGMENT_DDL`) with the next
rebuild; until a rebuilt table is promoted the junction reasons name the road's
LTS and not its lanes and speed ("Crossing a heavy-traffic road (LTS 4), no
signal mapped"), and nothing else changes. `core.junctions.has_trait_columns` reads the live schema
once and remembers the answer, as `core.routing` does for the facility columns,
so no restart is needed after the swap beyond the one that restarts the routers
anyway.

**Cost per plan.** Every plan asks `/locate` once for each 50 junctions where a
busy-class road meets the route, with a 3 ft (1 m) radius, and again, with a
100 ft (30 m) radius, for each 50 of those whose control is not already a signal, to
read the signals and stop signs OSM puts on the stop lines up the approaches
(review r2; `core.junctions.APPROACH_RADIUS_M`): about 2 to 12 calls a plan.
Measured on the live router, a batch of 50 at 100 ft (30 m) took 0.1-0.3 s and
2.6 MB, against 0.04-0.15 s and 0.5 MB at 3 ft (1 m). A plan with a red junction
1,640 ft (500 m) or more from both ends asks the router for one more route (crossing
avoidance, `core.refine`: only red junctions, from 2,000 ft, are worth a second
route), one `/trace_attributes` for it and its `/locate`s, and one more route for
the detour warning when the route is at least twice the straight line, or above
Default when it is longer than the allowance. Above 80 on the stress slider a
plan can make about 20 router calls (5 rounds of a route, a trace and `/locate`s,
and the detour probe), and Trailmaxxing starts at 100 (OWNER-DECISIONS 194), so
every Trailmaxxing plan is one of these unless the rider moves the slider down.
Since OWNER-DECISIONS 435 such a plan with a start and an end also asks once for the
router's own alternatives (one `/route` with `alternates` 3; on the live router a warm
7.5 mi [12 km] route took 1 to 2 s with them against 0.2 s without, the climb
search's measurements) and reads each (a trace and its `/locate`s): up to about 30
calls in all. The ask and its readings end `refine.ALTERNATES_ROUND_RESERVE_S` (6 s)
before the search's own 14 s, so a round is always left, and a plan whose hills
slider already asked for them reuses them. Not yet measured from the live router:
after the deploy that carries it, compare plan times at 100 with the figures below,
and count the answers whose `calm_search.alternates.limited` is `time` (the log says
"did not answer the calm search's ask for alternatives").
Measured through the review harness (docs/DEVELOPMENT.md, "Round 1,
re-measured" and "Round 2, re-measured"): Default plans 0.1 to 1.5 s (0.3 to
2.9 s in round 2, with the second `/locate` pass) and plans at 100 up to the
figures there. The budget is unchanged (40 s, 50 s for a long ride). If the api's
workers are saturated, the search is the first thing to drop: it does not start
with less than 11 s left (`REFINE_ROUND_MIN_S` plus `REFINE_TRACE_RESERVE_S`)
and a round is not begun with less than 5 s, and the answer then says
`calm_search.limited` is `time`. Where the rider asked for the calm detour, the
planner says so under the route: "The calmer-route search ran out of time, so
there may be a calmer route than this one."

**Concurrency.** The search has no limit of its own. It runs only inside an
api routing request, and each of those holds one of the deployment's routing
slots, `ROUTING_CONCURRENCY` (3 on compose's 7 workers; the PostgreSQL
advisory-lock pool in `core.ratelimit`, in "The public routing API: its
limits, and clearing a client" above). A long ride, the one request with a
pool of its own, never runs the search. So at most
`ROUTING_CONCURRENCY` searches run at once across the whole deployment, however
many api containers there are, and each makes its router calls one after
another. Each router serves with two workers per stage: the second argument of
its `command` in `compose.yaml` (`valhalla_service /conf/valhalla-<variant>.json
2`). `mjolnir.concurrency` (4) in `valhalla/*.json` is used by neither: the
routers take their worker count from that argument, and a tile build takes its
thread count from `REBUILD_TILE_CONCURRENCY` ("Tile build threads"). So three routing slots can have three
plans asking one router at once against its two workers, and the third waits
inside Valhalla. A calm plan at the top of the slider, with the trail seek's up
to six asks a leg one after another, is the case where that shows: it costs
latency inside the 40 s budget, not errors (a call that waits past its own
deadline is a `time` limit like any other). After a deploy that turns the seek
on, watch the route p95 in the api's request log for a few days; if it
climbs, the remedies are a third router worker (`"3"`, within the router's CPU
limit) or `ROUTING_CONCURRENCY` held at 2, not more api workers. If
`ROUTING_CONCURRENCY` is raised (more workers), keep it at or below the routers'
worker count, or calm plans can queue inside the routers. Round 1's per-container lock files
(`CALM_SEARCHES_PER_HOST`, `/tmp/routemaker-calm-search`) are gone, and so is
`calm_search.limited` `busy`; a `routemaker-calm-search` directory left in a
container's or host's temporary directory by round 1 may be deleted.

**The trail seek (FOLLOWUP-TRAIL-SEEK, OWNER-DECISIONS 194, 201).** From a calm rate
of 10 (stress 100: Trailmaxxing's start and the slider's top) a plan, after the
exclusion rounds, reads the segment table once a leg and may ask the router for up
to six more routes a leg (`core.trailseek`; docs/DEVELOPMENT.md, "The trail seek"):

- **One query a leg.** `SELECT ... FROM live.segment` for the paths, protected
  ways and car-free roads at LTS 1 or 2 within 0.9 to 2.5 mi (1.5 to 4 km) of the
  leg's straight line and its best route so far, at most 30,000 rows. The band is
  read a strip at a time (`trailseek.band_cells`: 0.6 mi (1 km) cells, each row's run one
  index scan), not over the guide's bounding box, under its own statement timeout
  (at most 2.5 s, and never past the leg's time); a read cancelled by the timeout
  ends the seek as `limited: "time"`. On today's live table (no facility column) it
  reads through `segment_overview_geom_idx`; after the rebuild through
  `segment_seek_geom_idx` (below). Measured, read-only, on the live table (1,357,800
  rows, a 20 mi diagonal with a 400-point route and a 2.5 mi band): 42-61 ms
  warm, against 349-386 ms for the one-geometry query it replaced; on a copy with
  the facility column and the seek index, 15-42 ms against 740-1,442 ms
  (docs/DEVELOPMENT.md, "Round 1 revision").
- **Up to six router routes a leg**: up to three candidates, each of which may be
  asked a second time without the search's exclusions (when the router has no
  route with them, or the route with them is more than 15% and 1,640 ft (500 m) longer than
  the leg and the corridor's detour), each with its `/trace_attributes` and its
  junctions' `/locate`s, about 1 to 2.5 s each on the live host. Only the kept
  exclusions within the leg's band are sent. The seek has
  its own 6 s budget past the exclusion search's 14 s, and does not start a
  candidate (or a second ask) with less than 2 s of it left; so a plan at the top
  of the slider is at most 20 s of searching in the budget of 40 s, the same
  ceiling as before plus the seek. Measured, the seek's own time was within about
  1 s on most trips and up to 4.8 s on Rockville to Silver Spring at Trailmaxxing.
  Without the trail credit it asks nothing on a route with no busy road on it (6 of
  12 trips at Default's costing); with Trailmaxxing's credit it may also ask on a
  quiet route, for a corridor that adds 1,300 ft (400 m) of trail. There is no
  limit of its own: it runs inside the plan's `ROUTING_CONCURRENCY` slot, so
  at most that many seeks run at once, as for the search; the router calls are
  the same one-after-another calls, so the thread notes under "Concurrency"
  hold.
- **Bounded.** The corridor search refuses a trail step that does not cost
  something positive and finite, walks back from a corridor's exit at most its
  network's node count, and reads the clock every 1,024 nodes; any of these ends
  the seek (`limited: "error"`, logged at error level as "the trail seek's corridor
  search failed", or `"time"`), and the plan is answered without it.
- **Reading it.** `calm_search.seek` in the answer says `corridors` found,
  `asked` (proposals) and `routes` (router routes: a proposal asked again without
  the exclusions is two), `taken`, why it stopped short (`points`, `span`, `time`,
  `table`, `error`, `unread`, `busier` - a plan with stops whose spliced whole trip
  was past the Traffic-wins allowance - or `roadway_only`, a ride on the no-trail
  graph, which is not seeked), `whole_trip` (on a plan with stops whose legs were
  spliced: `taken`, `busier` or `unread`, shown even when `limited` is an earlier
  `time`) and one row in `tried` per route asked, with its
  `outcome` (a second ask without the exclusions has `retry: "longer"`). A run of `table`
  is a database problem, not a routing one (the log says "the trail seek could
  not read the segment table" at warning level). A run of `no_route` outcomes
  means the router refuses the through points (an entry on a way a bicycle
  cannot use); the plan is unaffected.
- **The seek on plans with stops** (OWNER-DECISIONS 203; docs/DEVELOPMENT.md, "The
  trail credit and the seek leg by leg"). The trail credit of item 202 is gone: item
  257 dropped it on 2026-10-03, so no ride type has one, a candidate's reading has
  no extra join for a trail rule, and `calm_search` no longer carries
  `trail_credit`, `trail_before_m` or `trail_after_m`. A plan with stops runs the
  seek once per leg of at least 1.2 mi: one table read per leg (each up to 30,000
  rows) and, per candidate, one route for the leg alone with its trace and `/locate`s,
  within the same 6 s as before, plus each leg's reading of its own route (at most
  2 s a leg, `refine.SEEK_LEG_READ_S`, added to the budget and never into the time
  kept for the answer's traces; measured 0.45-0.6 s), plus one reading of the whole
  trip when a leg is taken. A leg that runs out of its share leaves the rest to the
  legs after it (until the combined correctness review it ended the seek, which on
  Bethesda - Silver Spring - College Park meant the seek never asked anything); the spliced trip is then held to the whole trip's Traffic-wins allowance
  (2% and 164 ft, 50 m), as each leg is to its own. Measured one stop +4.8 s and three
  stops +4.8 s over a plan without the seek
  (three stops: the exclusion search had used the time, and the seek added only its
  reads). Still no limit of its own: it is inside the plan's `ROUTING_CONCURRENCY`
  slot. `calm_search.seek.legs` and each `tried` row's `leg` say which legs it ran
  over. A leg's own candidates are never offered as routes to choose from: every
  route offered is the whole trip (release review, correctness B1).
- **Not applicable** to a long ride, to
  a Mass Ride, to a span over 18.6 mi (the search's own limit), or to one under
  1.2 mi.
- **Facility.** On a table without the facility column (the live table until
  the rebuild) the trails are found by their recorded stress rule, so a cycle
  track mapped on the road itself, which is not trail class, is not a corridor
  until the rebuild.


**Reading the log.** `core.refine` logs at warning level, "the intersection
events could not be read", when the segment query or `/locate` failed for a
reason other than the budget; the route is answered without its junction list
(`intersections` null or empty). A `/locate` batch that fails leaves its
junctions unknown: nothing is counted as crossed there, and only a turn onto or
off a busy road on the route itself is priced. `core.junctions` logs "intersection
nodes: N of M matched" at info level when some junctions' answers did not have
the route's own edge (measured 96 to 100 per cent matched). `core.routing` logs
the same "took ... past its budget" line as before.

**The routers.** The search sends `exclude_locations` (the config's
`max_exclude_locations` is 200; `scripts/build_valhalla_configs.py` sets it) and
`/locate` with `verbose`. Both are in the configs this repository builds, and
`tests/test_valhalla_config.py` holds the limit above what the search sends; a
hand-made config that lowers `max_exclude_locations` below 150 makes a calm
round refuse (400, the search ends with `no_route`), which is safe but quiet.

**Where the markers over-warn.** Not one place, several, each a known gap
(docs/DEVELOPMENT.md, "Known gaps"):

- A signal tagged on a stop line more than 100 ft (30 m) up an approach, or
  only on an approach the junction's arms do not lead to (the far
  carriageway's, where the route crosses one carriageway alone), is not read,
  and the junction is priced as having none. Round 1 read signals only at the
  junction node, and this was the commonest cause of a false red at a
  signalized junction (review r2: 8 of 15 reds in its sample); from round 2 the
  approaches are walked to 100 ft (30 m) and the nodes of one junction share its
  strongest control. Of the 95 junctions the review found priced as having no
  signal, 66 had a signal flag of some kind within 100 ft (30 m) and 59 of those now
  read as signalized (re-measured at gate 1; 63 in round 2). The four fewer
  are the two lefts off 17th St SW 60 ft (18 m) past the Constitution Ave
  signal, which is not theirs (review r3), Plyers Mill Rd across Metropolitan
  Ave (next bullet), and a straight-on along MD 450 that is no event either
  way.
- One junction mapped as two named ones a few metres apart can lose its
  signal (review r3). Plyers Mill Rd (MD 192) straight across Metropolitan Ave
  reads orange, 1,200 ft, where it was 150 ft: MD 192 is divided west of the
  junction, Concord St crosses between its carriageways 50 ft (16 m) back,
  and the signal is on the Concord St node, which the walk takes for Concord
  St's own junction. It is the safe direction (a warning at a light). Telling
  it from a driveway just past a signalized junction would need the rider's
  riding straight through a minor road's T junction on the junction's own
  road, which would bring that driveway's under-warning back.
- Signalized trail crossings tagged `crossing=traffic_signals` away from any
  signalized road junction read as unsignalized until the tag transform derives
  the signal. They are orange at most and say "no signal mapped"
  (OWNER-DECISIONS 185), so a rider may see an orange marker at a crossing that
  has a light.
- A stop sign on a cross road's stop line short of the junction is not read as
  the cross traffic's (it may be another junction's), so a junction where only
  the cross traffic stops can be priced as if nobody does: the rider's crossing
  is then the stopped side's.
- Any junction whose signal or signs OSM does not have reads "no signal mapped".
- It under-warns near signals: a side street or driveway within 100 ft (30 m)
  of a signalized junction can be priced as signalized, and its red or orange
  not drawn, where the signal is on a stop line of the road it joins with no
  other named road at that node, or where the other junction's road has no
  name in OSM. For a rider arriving on a road, a driveway, a parking aisle or
  a drive-through, a signal at a node up an arm that a road of another name
  joins, or one facing away from the junction, is not taken (review r3; gate
  1 for driveways and parking aisles, which took it until then); nor is a
  signal or stop sign on the rider's own approach beyond a junction already
  passed. A rider arriving on a path (a footway, path, cycleway, crossing way,
  steps or track) does take such a signal: a trail crossing a few metres from
  a road junction is crossed on that junction's signal (the Green Trail,
  Virginia Ave cycletrack and Custis crossings).
  Junctions within 150 ft (45 m) about one named road also share a signal where the
  rider crosses that road at one of them and does not ride along it between
  them, so a staggered junction whose two nodes the rider links by a short
  side street can read as one. A turn's crossing of its own two-way road's
  opposite lanes is not counted as crossing it (gate 1), so a signalized left
  off a road and an unsignalized left back onto it 100 ft (30 m) on stay two junctions
  and the second keeps its red; a one-way carriageway crossed still counts,
  so a divided road's crossover shares its signal.
- That path exception has a named residual risk. A cycleway's left onto
  Georgia Ave 50 ft (15 m) from Wayne Ave, and onto Colesville Rd 25 ft (7 m)
  from Second Ave and Wayne Ave, take the neighbouring junction's signal:
  450 ft where without it they would be 4,500 ft, red. They are probably the
  corner sidepaths at the signal, ridden onto the road on its crossing, so the
  reading is defensible; but a trail that meets a busy road a few metres from
  a signal it does not use would be under-warned the same way, and the markers
  cannot tell the two apart.
- A slip lane the route crosses is orange (items 169 and 195) whether or not
  the channel has its own signal or a raised crossing, which are not read.
  Riding straight past one along the road is not flagged, except in a painted
  or separated bike lane past a channel leaving on the right (the right hook).
- An unnamed divided road's two carriageways are counted as two roads (half the
  second added), not once with the refuge credit.

**The rolling stress chart** (OWNER-DECISIONS 460.12; docs/DEVELOPMENT.md "The rolling
stress chart"). The route answer's `profile.calm` is worked out from the sections and
junctions the answer already reads: no router call, no database read, no migration and no
router restart; it ships with the API image and the front end, in either order (an older
front end ignores it, and the new one draws the old stress strip where it is missing). A
WARNING "the rolling stress score could not be built" means one answer went out with
`calm: null`: its chart fell back to the strip and the route itself is unaffected. It adds
at most about 10 KB to an answer (one figure a profile sample, up to 2,000) plus the
sections and the flagged junctions; live serves route JSON uncompressed (the Caddyfile
compresses only tiles and the front end), so a long ride with candidates grows by tens of
KB. `calm.estimate` is true while each stretch is priced by its tier.

## The stress tiles

`GET /tiles/stress/{z}/{x}/{y}.pbf` (`core/stress_tiles.py`) draws the traffic
stress overlay from the live segment table with PostGIS's `ST_AsMVT`, for
anyone, signed in or not. Zooms 10 to 16 are drawn; any other zoom, and any
tile outside `COVERAGE_BBOX`, is an empty 200, and a tile straddling the box's
edge is drawn from its segments clipped to the box, so nothing is drawn in the
map's grey area. A coordinate that is not a tile is 400, and a deployment with
no live segment table yet is 404 with `no-store`, which the front end reads as
"no overlay".

| Zoom | What is drawn | Measured on a copy of a promoted build |
| --- | --- | --- |
| 10-11 | only the long traffic-free paths and trails: the long trails below, roadside trails and roads closed to cars at set times among them (`pipeline.schema.trails_predicate`, then `long_trails_predicate`); one feature per class, simplified | miles of path drawn region-wide (in the Columbia and Patapsco box): every trail 5,461 (311), z11 1,037 (17), z10 894 (15); a read-only measurement on a full-size copy of the 2026-10-03 build, with the rebuild's own code filling the columns |
| 12-13 | the ride layer (391, 402a): long and connected traffic-free paths, calm roads in a continuous run of 2 mi (LTS 1 and 2, ended at every junction with a busy road), and roads closed to cars at set times; no road at LTS 3 or above (`pipeline.schema.ride_layer_predicate`, on `calm_run_m`); one feature per class, simplified. On a table without the column, what it drew before: the paths and the roads at LTS 3 and above (`busy_predicate`) | region-wide 6,812 mi against 25,017 before, with 391's 1,787 mi of calm streets (402a's calm roads are 1,642 mi: "Calm roads", below); the Annandale-Alexandria box 83.9 mi against 272.6; z12 over the box 48 KB against 127 KB ("The ride layer", below) |
| 14-16 | every segment, the quiet streets (LTS 1-2) and footways too | z14: 8,190 tiles, 49 MB, at most 125 KB (2026-09-28) |

The owner, 2026-09-29: "Zoom less than 12, show just bike paths and the
metro/MARC. 12 and 13, show LTS 3+, 14+ show show the quiet streets."
(OWNER-DECISIONS 73; before it, "Zoomed out just show the trails.", 65, and
"Show roadside trails (Recommended)", 66). The zooms are
`core.stress_tiles.RIDE_LAYER_MIN_ZOOM` (12) and `QUIET_STREETS_MIN_ZOOM`
(14), paired with `STRESS_ZOOMS.ride` and `.quiet` in
`frontend/src/lib/mapStyle.ts` (a test fails while they differ): change both,
rebuild the api image and the front end, and run the pre-draw. The rail
stations draw from z8 over everything, so zoomed out the map is the paths
and the Metro and MARC stations; the app has station points, not rail lines.
**The long trails (z10-11).** The owner, 2026-10-04: "Also zoomed out, can we
stick to mostly the longer trails, it's getting messy." (OWNER-DECISIONS 375),
then "Car free roads stay. The point at this zoom is to see what would be a
great long distance trip." and "Local trails only at higher zooms. Basically,
at birds eye view I want to see a bicycle version of the interstate routes."
(377), "Patapsco Traverse appears to be a mountain bike trail. Make sure to
not include those." (378), for the z11 paved bar of 3 mi that dropped the
Grist Mill Trail (2.54 mi), "Yes, bring it in." (380: 2.5 mi), and of the
roads closed to cars for good, "I think off is fine here. Nobody routes
around the tiny roads." (381). A path or trail is drawn at z10-11 only when
it is part of something long:

- its `segment.trail_route`, the OSM route relation it is in, is at least 2
  for a paved way and 3 for an unpaved one (1 is a local bicycle route or one
  with no network, which qualifies nothing; 2 a long walking route, US:NST or
  an iwn, nwn or rwn network; 3 a bicycle route at an icn, ncn or rcn
  network; a relation whose `route` lists several values, such as
  `hiking;mtb`, is read as each of them); or
- its `segment.trail_run_m`, the length of its named run, is at least:

  | | paved | unpaved |
  | --- | --- | --- |
  | z11 | 2.5 mi (4.0 km) | 5 mi (8.0 km) |
  | z10 | 5 mi (8.0 km) | 8 mi (12.9 km) |

  A run is the drawn trail ways of one name (case-blind, and without a
  trailing parenthetical or bracket, Extension, Extn, Connector or
  Connection) that chain within 1,300 ft (400 m) of one another. A way with
  no name of its own takes the name of the long route (level 2 or 3) it is
  in; a local route's name is not used, so a local route cannot keep a way
  through it (377).

A road closed to cars at set times (`car_free_when` set) is kept whatever its
length (377). A road closed to cars for good is not exempt: it is a path,
judged like any trail by its route and its named run, and otherwise shown
from z12 (381). A mountain-bike way (in a route relation that is an mtb one,
or tagged `mtb:scale` 1 or more, `mtb=designated` or `mtb:type`, unless the
way is paved) is written with route 0 and no name, so it never qualifies and
adds nothing to a run. The paved exemption is for the tags only (Upper Rock
Creek, Northwest Branch and the Cross County Trail carry an `mtb:scale` on
asphalt); on the 2026-10-03 extract it changes nothing, since every flagged
drawn way is flagged by its relation. An unknown surface is paved. The bars
are the named constants in `pipeline.schema` (`Z11_PAVED_RUN_MI` and its
siblings). The z10 and z11 tiles are two levels (`core.stress_tiles.TRAILS`
and `TRAILS_NEAR`), and the front end draws the lines and rails thinner
there (`ZOOMED_OUT_SCALE` in `frontend/src/stressStyle.js`), never with a
casing edge, a rail or an unpaved mark under a pixel.

**Short bridges** (the orchestrator's decision, not the owner's, after the
Grist Mill Trail's two wooden bridges left holes in a paved trail at z11). A
drawn trail way tagged bridge=* other than no is a candidate. Candidates
whose ends meet (a bridge and its boardwalk, or one bridge OSM splits in two)
are one chain, judged as one: at most `TRAIL_BRIDGE_MAX_M`, 330 ft (100 m),
in all, and each of its outer ends must meet a drawn trail way that is not a
candidate (the same-named one first, then the one on the highest route, with
the longest run, nearest). Each way of the chain takes the greater of its own
route and run and the lower of its ends' (an end on a route that keeps its
trail sets no bar on the run), and is judged on its trail's surface, not its
deck's: `segment.trail_bridge` is 1 between paved ways and 2 where an end is
unpaved. So it keeps no bridge on its own and lowers none. A bridge whose end
meets another bridge in that bridge's middle, not at its end, is not chained
to it, and is judged on its own deck.

**The columns are the rebuild's** (`trail_name`, `trail_route`, `trail_run_m`,
`trail_bridge`). `pipeline.trail_routes` reads the route relations from the
source extract (one relations-only pass), the writer stores a name only on a
way the zoomed-out map draws, and `derive_trail_runs` ANALYZEs the staging
table, chains the runs and judges the bridges (10 s on the full
table). VALIDATE then refuses a build whose columns came out wrong
(`pipeline.run.assert_long_trails`): the Washington & Old Dominion Trail
(OSM way 8810729) and the C&O Canal towpath (10595312),
`settings.REBUILD_SENTINEL_LONG_TRAIL_WAYS`, must each be on a long bicycle
route in a run of 8 mi (12.9 km) or more; at least
`settings.REBUILD_LONG_TRAIL_FLOORS` rows, 6,000 and 2,200,
must be on a long route and in a run of 2.5 mi (4.0 km) or more (about half
of the 2026-10-03 build's 12,503 and 4,402); and no bridge may be
left unjudged. If a later extract splits or replaces a sentinel way, move the
sentinel; don't drop it.

Until a rebuild has promoted the columns the tiles keep every path and trail
at z10-11, as before: the rule applies only to a live table that has all of
`trail_route`, `trail_run_m` and `trail_bridge`, which the ETag names (`t`,
`l`, `b`). FORMAT_VERSION 7 (5 was the long trails; 6 was claimed by both the ride layer
with the surface-unknown trails and the Mass Ride capacity, on branches that never shipped
alone; 7 is the rebuild bundle, which carries both) must reach the api and the pipeline images
together: build both under one TAG (`docker compose build`, or `build api
rebuild` as in the format-change steps below), never `build api` alone. The
pre-draw evicts every format but its own, so an api and a rebuild at
different formats leave the api's z10-14 cache cold after every weekly
rebuild. Recreate `rebuild` only while no rebuild is running. Deploying both
and running the pre-draw before the data rebuild draws the same tiles as
before, only thinner (every cached tile is drawn again, as the format
changed); the next rebuild's pre-draw draws the long trails only. Route
relations and names are OSM's, cited with the rest of the map's data.

**The ride layer (z12-13, OWNER-DECISIONS 391).** The owner, 2026-10-05, on
a screenshot of Annandale and Alexandria: "I'm more concerned with the places
to ride than the places not to." Busy roads: "Hide them until zoom 14." Ride
layer: "Long and connected paths as well as similar long calm streets." At z12
and z13 the stress map is a "where to ride" view:

- **Not drawn:** LTS 3, LTS 4, Avoid and the roads bikes may not use, and the
  junction warning markers. They come in from z14 with the quiet streets. (The
  only junction markers on the map are a planned route's own, and the route
  keeps its own busy stretches and junctions at every zoom, so nothing changes
  there.)
- **Drawn:** the long and connected traffic-free paths, the calm roads worth a
  long ride (402, 402a), and the roads closed to cars at set times, whatever their length
  (377). One feature per class, simplified, as before
  (`core.stress_tiles.RIDE_LAYER`; `pipeline.schema.ride_layer_predicate`).

The rule reads one new column, `segment.calm_run_m`, written by the rebuild
(`pipeline.trail_routes.derive_calm_runs`, 12 s on the full table, right after
`derive_trail_runs`). Its value is the length in metres of:

- for a path or trail the zoomed-out map draws (`trails_predicate`): the
  connected network of such paths, whatever their names, joined within 100 ft
  (30 m, `CALM_PATH_GAP_M`; a road crossing does not break a trail), or its
  named run (`trail_run_m`) if that is longer, so a long named trail keeps
  whatever its gaps. Short isolated stubs come out under the bar and wait for
  z14;
- for a named road at LTS 1 or LTS 2 that is not a trail, of any class: its calm
  run, the continuous line of such roads it is part of, ended at every junction with
  a road at LTS 3 or above ("Calm roads", below). A road with no name has no run;
- null on every other way, and on a mountain-bike trail (a way in a route=mtb
  relation, one tagged `mtb:scale` 1 or more, `mtb=designated` or `mtb:type`
  unless paved, or one the no-bike-paths rules call mountain-bike only), so
  those wait for z14 as well.

The writer marks the candidates (a `calm_run_m` of 0, `trail_routes.is_calm_candidate`)
and the derive sets them; a road's name is written to `trail_name` for the
same reason a trail's is. Names and routes are OSM's, cited with the rest of the
map's data.

**Calm roads (OWNER-DECISIONS 402, 402a).** The owner, 2026-10-05, on the first
round's calm streets: "For calm streets, I'm thinking more calm roads. Places someone
would likely want to ride for a while. In the cities that's just too dense." Then: "LTS2
counts. Suburban streets would rarely qualify because they tend to have a lot of
intersection stress rather than roadway stress." A road's calm run
(`pipeline.calm_roads`) is:

- made of the named roads at LTS 1 or LTS 2 the map draws (not a trail, not a
  mountain-bike way, `map_class` road), of any class: a residential street counts
  as much as a rural road. An unnamed road has no run and does not join one;
- continuous, across changes of name: where only two calm roads meet (a way split
  for a tag, a name that changes) the run always goes on; at a junction of three or
  more it goes on along the road of its own name if that turns no more than 100
  degrees (`SAME_NAME_TURN_DEG`), else along the straightest road that turns no more
  than 45 degrees (`STRAIGHT_ON_DEG`), and the other roads there start runs of their
  own. A run is a line, not a network, so a grid of quiet streets is many short runs;
- ended at every stressful junction: any node it shares with a road at LTS 3 or
  above (Avoid and the roads bikes may not use included; the greater of the tier and
  the unsmoothed tier, as the junction model reads it), crossed or joined, whatever
  the control. That is 396's rule ("the crossed or joined road is rated LTS 3 or
  higher" or "the junction itself carries a stress rating"): the junction model
  (`routemaker.intersections`) rates a junction of its own only where a road of its
  `BUSY_TIER` (3) is in it, so on the map's data the one test is both. A bridge or an
  underpass shares no node with the road it passes and does not end a run.

The junctions are read in SQL from the rows' shared vertices (OSM joins roads at a
shared node) and the runs put together in Python. A way a busy road crosses in its
middle is in two runs and keeps the longer. On a copy of the 2026-10-03 build it reads
473,290 junctions in 34 s, puts 171,316 rows' runs together in 1 s, and peaks at about
400 MB in a process of its own (the derive reads through a server-side cursor).

**The thresholds** are named constants in `pipeline.schema`, tunable and held by
tests: `RIDE_PATH_RUN_MI` 0.25 mi (1,320 ft, 0.4 km), the owner's own figure for a
stub, and `RIDE_ROAD_RUN_MI` 2 mi (3.2 km), the owner's bar for a calm road (402a,
confirmed by 410: "Let's do 2 mi"), the one setting to move if the owner changes it. Measured read-only: the live table's 1,359,547
segments copied with a read-only `COPY` into a private database, names read from the
2026-10-03 source extract, the areas being OpenStreetMap's boundaries of the District
(relation 162069), Montgomery County (936970) and Baltimore City (133345), a segment
counting where its middle is. The roads closed to cars (for good or at set times) are
paths in the layer under both rules and are left out of these figures.

| Area | Before (391): LTS 1 streets, same name, 0.5 mi | After (402a): LTS 1-2 roads, continuous, 2 mi |
| --- | --- | --- |
| Region | 4,716 ways, 1,793 mi, about 1,971 runs | 2,398 ways, 1,642 mi (1,319 of it LTS 2), about 555 runs |
| District of Columbia | 1,214 ways, 184 mi, 241 runs | none |
| Montgomery County | 106 ways, 26 mi, 37 runs | 49 ways, 38.5 mi, 16 runs |
| Baltimore City | 137 ways, 9.9 mi, 14 runs | none |

Miles of calm road kept by the new rule at other bars:

| bar | 0.5 mi | 1 mi | 1.5 mi | 2 mi | 2.5 mi | 3 mi | 5 mi |
| --- | --- | --- | --- | --- | --- | --- | --- |
| region | 11,530 | 4,831 | 2,676 | 1,642 | 1,048 | 658 | 174 |
| DC | 223 | 33 | 9 | 0 | 0 | 0 | 0 |
| Montgomery County | 760 | 184 | 81 | 38 | 18 | 10 | 0 |
| Baltimore | 283 | 38 | 3 | 0 | 0 | 0 | 0 |

At 2 mi the layer's calm roads are rural: in Montgomery County all of them are in the
Agricultural Reserve (Hawkins Creamery Road 3.5 mi, Elmer School Road 3.2, Peach Tree
Road 3.1, Griffith Road 2.9, Batchellors Forest Road 2.6, Black Rock Road 2.5,
Woodfield School Road 2.5). The near misses show what the junction rule does: Oregon
Avenue NW, along Rock Creek Park, is a 1.99 mi run; Beach Drive in Montgomery County
(6.8 mi of LTS 1-2) is cut into runs of 1.6 mi at most by the busy roads that cross
or meet it; Sligo Creek Parkway (5.5 mi of LTS 2)
into runs of 0.8 mi; Roland Avenue in Baltimore (4.2 mi) into 1.3 mi. The first
round's DC streets drop out: 4th Street NW (a 1.9 mi run of its name) is 0.8 mi between
busy crossings, 8th Street NW 1.3 mi, Madison Street NW 0.6 mi. Of the region's named
calm candidates, 5,164 mi are LTS 1 and 24,485 mi LTS 2.

The paths' rule is unchanged, and so is its bar (region, Annandale-Alexandria box
-77.20,38.79 to -77.04,38.86): 0.1 mi 5,267 and 74.0; 0.25 mi 5,025 and 66.8; 0.5 mi
4,725 and 60.3; 1 mi 4,276 and 51.1; 2 mi 3,730 and 47.1 (every candidate path is 5,233
and 75.3; 152 mi of mountain-bike trail are left out). Before and after pictures of
central DC, Bethesda and Chevy Chase, the Agricultural Reserve and Baltimore, with the
same rule at 1 mi for comparison, are in reports/ride-layer-before-after.html
(`rmdata/demo/reports`). Re-measure on a copy before moving a bar, and update
`RIDE_RUN_MI` in `frontend/src/lib/stressLegend.ts` with it (a test holds them equal).

The first round's measurement (391's calm streets, LTS 1 of one name chained within 330
ft, 0.5 mi), against the busy roads it replaced, for the record:

| | Region: ways, miles | Annandale box: ways, miles |
| --- | --- | --- |
| z12-13 before (paths, and roads at LTS 3 and above) | 144,190, 25,017 mi (paths 5,454; LTS 3 5,432; LTS 4 12,610; Avoid 1,515) | 3,928, 272.6 mi (paths 75.3; LTS 3 93.4; LTS 4 103.9) |
| z12-13 after (the ride layer) | 35,961, 6,812 mi (paths 5,019; calm streets 1,787; timed car-free roads of LTS 3 and up 1.7) | 682, 83.9 mi (paths 66.8; calm streets 17.0) |
| z12 tiles over the box, bytes | before 126,726 (6 tiles) | after 48,188 |
| z13 tiles over the box, bytes | before 81,637 (12 tiles) | after 29,220 |


**VALIDATE** (`pipeline.run.assert_calm_runs`, following `assert_long_trails`):
no named candidate may be left at 0 (the derive ran to the end); the path
sentinels, the W&OD (OSM way 8810729) and the C&O towpath (10595312),
`settings.REBUILD_SENTINEL_CALM_PATH_WAYS`, must each be in a network of 8 mi
(12.9 km) or more; the road sentinel, Elmer School Road in Montgomery County's
Agricultural Reserve (OSM way 5968951, in a 3.2 mi calm run),
`settings.REBUILD_SENTINEL_CALM_STREET_WAYS` (the setting keeps its first name), must
be in a calm run of 2 mi or more; and at least `settings.REBUILD_CALM_RUN_FLOORS`
rows, 15,000 path rows in a run of 0.25 mi and 1,200 road rows in a calm run of 2 mi
(about half of the copy's 31,712 and 2,398), must exist. As with the long
trails, if a later extract splits or replaces a sentinel way, move the sentinel;
don't drop it.

**Tiles, ETag and fallback.** `core.stress_tiles.level_for(z, optional)` returns
`RIDE_LAYER` for z12-13 on a live table that has `calm_run_m`, and `BUSY` (what z12-13
drew before: the paths and the roads at LTS 3 and above, faint, with the front end's
`FAINT` rules) on one that does not, so a table promoted before this rebuild draws
today's z12-13 until the data rebuild promotes the column. The ETag names it with
`k` (`+kcfrmwoesbtl-v7"` with all twelve optional columns, `e` being 403's `roadside` and
`w` the Mass Ride width, about 37 characters, inside the cache's 64) and `FORMAT_VERSION` is 7
(the rebuild bundle's format, with the surface-unknown properties below and the Mass Ride
capacity: the tile cache key changes, so run the pre-draw as the steps
below say). The ride layer has its own partial index,
`segment_ride_geom_idx` (`RIDE_INDEX_PREDICATE`), which the query is proved to imply
(a test); the busy-road layer keeps the overview index.

**FORMAT_VERSION 7 and the ETag letters** (resolved in the rebuild bundle). wip/massride-map
and this branch each moved `FORMAT_VERSION` to 6 and each took the letter `r`. In the bundle
the format is 7, past both, so neither branch's cached tiles are taken for the other's; `r` is
`is_rough`'s, the Mass Ride width column (`MASS_WIDTH_COLUMN`) is `w`, `k` is `calm_run_m`'s
and `e` is `roadside`'s, one letter per column (a test holds them distinct).

**Decision 390 at z12-13.** "Solid is probably fine" for LTS 3 and 4 below zoom
14 is moot where no busy road is drawn there. On a live table without
`calm_run_m` the busy roads still draw at z12-13 and are still faint, as they did. The
solid-below-14 change (390, `SOLID_MIN_ZOOM` 14) is in the rebuild bundle with this, and
applies to that fallback only.

**What the front end says** (`frontend/src/lib/stressLegend.ts`, `STRESS_ZOOMS` in
`mapStyle.ts`: `{ min: 10, ride: 12, quiet: 14, max: 14 }`): the zoom notice for z12-13,
"Zoom in to see busy roads and every street. This is the where-to-ride view: connected
paths and trails and long calm roads. Busy roads and short paths show from zoom
14."; and the standing hint, which gives the two runs in feet and miles (kilometres
in brackets), says the busy roads, shorter paths, the other streets and the junction
warnings on the map show from zoom 14, and mountain-bike trails too when their layer
is on (OWNER-DECISIONS 454),
and that a planned route shows its own busy stretches and junction warnings at every
zoom. On a table without the column the text is ahead of the tiles until the rebuild.

**Surface unknown (OWNER-DECISIONS 376; PARK-TRAILS-investigation.md).** "A and
C". *A, style only:* a trail-class feature with no surface tag (the tile carries no
`unpaved`, since a null is left out; no new property is needed) draws as its own
line: LTS 1's colours in short even dashes (`UNKNOWN_SURFACE_DASH`, 2 on and 1.5
off in line widths), the edge dashed to match so the gaps show the base map, and no
path rails and no continuous dark edge. The dashes are the cue that is not colour,
and the legend has a "Surface unknown" row in words: "A path or trail with no
surface mapped in OpenStreetMap, so it may be paved or unpaved: short dashes in the
LTS 1 colors, with no edge lines. A trail beside a road with no surface mapped
shows as a paved path." (403, below). Nothing is closed; roads with no surface tag
(nearly every street) draw as before. *C, a pipeline change:* `routemaker.stress.inferred_unpaved`
reads `highway=track` with no `surface` as unpaved unless `tracktype=grade1`, so
the stored `is_unpaved` makes it brown, with the unpaved mark, and open (the
classifier's own unpaved speed cap still reads the raw tag, so no tier moves; the
unpaved-surface ranking and the trail seek read the stored column, so a track with
no surface now counts as unpaved there). *Not B* (no untagged path is closed) *and
not D* (`SHORT_PATH_M` stays 150 m). The investigation counted about 3,145 such
tracks (763 mi) region-wide; a rebuild's log is the place to read the real figure.

**Built bike paths with no surface (OWNER-DECISIONS 448).** The owner, 2026-10-07, on
the Marvin Gaye Trail drawn dashed: "Where did these weird dashed bike paths come from" /
"They are deemphasizing what should be a main route". 19 of its 23 ways are
`highway=cycleway` with no surface tag. `routemaker.stress.inferred_unpaved` now reads a
built bike facility (`highway=cycleway`, or a `path` or `footway` with
`bicycle=designated`) with no `surface` as paved (False), so the stored `is_unpaved`, the
tiles' `unpaved=false`, the unpaved ranking and the trail seek treat it as paved, like a
roadside trail (403); no front-end rule changed, because the tile now carries the
property. 376 A's dashes stay for other trails with no surface (park footpaths, `path` or
`footway` without a bicycle designation). Access is untouched. Measured on the
2026-09-25 extract against the live table: 4,384 ways, 352.5 mi (567 km) of them
cycleway or designated path with no surface, all stored unknown now; 350.5 mi
(564 km) are not roadside by their own tags (a way beside a road by geometry already shows
paved, and the rebuild log has the exact count). The owner is advised to tag these
`surface=asphalt` or `concrete` in OpenStreetMap too.

**Trails beside a road (OWNER-DECISIONS 403).** The owner, 2026-10-05: "Most trails
near a road are paved. There are minor exceptions." A trail beside a road with no
surface mapped keeps the paved path's look, its rails and edge; 376 A's dashes stay for
the trails away from roads (park trails). The exceptions are for a surface tag in
OpenStreetMap or a surface override, not for the default. The rebuild writes
`segment.roadside` (`pipeline.trail_routes.derive_roadside`, after the calm runs), true
on a drawn trail that is beside a road:

- by its own tags (`routemaker.facility.roadside_by_tags`): `footway`, `path` or
  `cycleway` = `sidewalk`, `is_sidepath=yes`, or any `is_sidepath:of*`; and
  `is_sidepath=no` says it is not, whatever the geometry;
- by its facility: a trail already classed the protected facility beside a road (a
  designated sidewalk, a physical separation, one along a road that maps its facility
  `separate`);
- else by its geometry: at least 60% (`ROADSIDE_FRACTION`) of the points 66 ft (20 m,
  `ROADSIDE_SAMPLE_M`) apart along it lie within 82 ft (25 m, `ROADSIDE_M`) of a road (a
  way that is not a trail, drawn or barred; a parking aisle or driveway does not count).

The tiles carry it as `roadside` (true or left out, as `mtb` and `rough` are; ETag letter
`e`), and the front end's surface-unknown filter (`stressStyle.js`) leaves a roadside
trail to the paved path's own layers. A table without the column carries nothing, and
every surface-unknown trail stays dashed until the rebuild. The legend's row says "A
path or trail away from roads with no surface mapped in OpenStreetMap ... A trail beside a
road with no surface mapped shows as a paved path."

Measured on the copy (a drawn trail with no surface; the share of samples within each
distance of a road at least 60%):

| | trail with no surface | by tags or facility | within 50 ft | 66 ft | 82 ft (the rule) | 98 ft | 131 ft |
| --- | --- | --- | --- | --- | --- | --- | --- |
| region, mi | 1,233 | 18 + 3 | 258 | 366 | 456 | 568 | 757 |
| DC | 12 | 6 | 9 | 9 | 10 | 10 | 11 |
| Montgomery County | 198 | 2 | 60 | 77 | 90 | 104 | 142 |
| Baltimore | 24 | 10 | 11 | 12 | 14 | 15 | 19 |

The rule bears the owner out on the trails whose surface is mapped: 78.5% of the
roadside ones are paved against 37% of those away from roads (DC 95% against 60%,
Baltimore 92% against 72%, Montgomery County 81% against 40%). Named trails with no
surface mapped that go back to the paved look include 0.9 mi of the Capital Crescent
Trail, 0.35 mi of the Anacostia Riverwalk Trail and the Silver Spring Greenway; ones that
stay dashed include 1.0 mi of the Marvin Gaye Trail, the North Germantown Greenway Trail,
the Tree Farm Trail and Baltimore's Stony Run Walking Path (most roadside trails with no
surface are unnamed sidepaths). The 82 ft bar is a judgment within the table: the count
keeps climbing past it with no plateau, so the nearer bar is kept and a trail the rule
is unsure of stays dashed, as 376 A drew it.

**The Mass Ride capacity column** (FOLLOWUP-MASSRIDE-MAP part 1, OWNER-DECISIONS 325-327,
387). `segment.mass_usable_width_m` is the usable width in metres `routemaker.massflow`
gives each segment from its way's tags, the classifier's lanes and, in DC, the Roadway Block
blocks it lies along (the narrower direction, parked cars out; OWNER-DECISIONS 404); `routemaker.flow` makes flat-ground riders a minute of it (changing its constants needs no rebuild), and the tiles carry that as `rpm`
(rounded down to ten; ETag letter `w`, since `r` is the rough surface's), the route's coloured sections carry it for a Mass Ride,
and the Mass Ride map is coloured by it. It is the rebuild's: VALIDATE refuses a build whose column
came out wrong (`pipeline.run.assert_mass_capacity`): under 98% of the road rows, or of the path
rows, with a figure; a road row under 44 or over 1,181 riders a minute; or a median road outside
`settings.REBUILD_MASS_CAPACITY_MEDIAN_RANGE` (60 to 200 since OWNER-DECISIONS 404, which gives a
ride its own direction's lanes less parked cars, from DC's Roadway Block in the District: about 90
on DC's blocks, 99 for an untagged two-lane street; 405 and 407 did not move the median: reversible lanes count as zero and a 16 ft lane with no parking is read at 11 ft, `settings.MASS_RIDE_DC_*`). Until a
rebuild has promoted the column, a Mass Ride keeps the stress map: the tiles carry no `rpm`, so the
map keeps its stress layers (the Mass Ride layers switch on only once a capacity has been seen),
and its legend and panel are the stress ones, with no error and nothing to do. The grey outside DC
and the "DC only for now" words (418) follow the ride type and show either way. FORMAT_VERSION 7 (the rebuild bundle's tile format) must reach the api
and the pipeline images together, as the note above says: build both under one TAG (`docker
compose build`, or `build api rebuild`), never `build api` alone, or the weekly pre-draw evicts
the api's cache every week. The data takes effect after the next rebuild; the front end and the
api that read it are safe before it. Every street shows on the Mass Ride map from zoom 14; at zoom 12-13
only the long calm roads do, because those tiles are the ride layer (391, 402a), which carries no
busy road; trails, paths and alleys never.

Below zoom 10 nothing of the overlay is drawn. The map asks for nothing past
z14 (the source's `maxzoom`): it draws z15-16 from the z14 tile, whose 4,096
units a side are half a pixel each at z16. z15-16 are still served, for the
contract.

**How the busy roads draw** (the front end's `stressStyle.js`; the tiles are
the same whatever the style decides):

- faint - 40% opacity and 60% width (`FAINT`) - at z12-13 (only on a table that still
  draws busy roads there: from the ride layer's rebuild none is drawn below z14), and solid from
  `SOLID_MIN_ZOOM` (14): "The high LTS roads aren't that important because
  you aren't going to route around them." - "Show them faintly", then "Make
  solid at 14" (OWNER-DECISIONS 76, 77);
- a road whose own tags say its bike facility is mapped as a way of its own
  beside it (`segment.separate_bikeway`: 15th Street NW, Pennsylvania Avenue
  NW) is not drawn until `BESIDE_ROAD_MIN_ZOOM` (15, of the owner's "15-16")
  and then faint at every zoom, so the cycle track is the main line (73, and
  "Keep it faint if it parallels a protected bike path.", 78);
- only a road (`segment.map_class = 'road'`) is drawn at all. A public road a
  bicycle may not use (`'barred'`: a motorway, a trunk road with
  `bicycle=no` such as the George Washington Parkway, `motorroad=yes`,
  `bicycle=use_sidepath`) is left to the base map, unmarked ("You can just
  leave the public roads where bikes aren't allowed as unmarked, using the base
  map", OWNER-DECISIONS 89, which replaced 73's white line); "legal but avoid"
  (US 340) is a road and keeps its colour. A way no typical rider could use
  (`'hidden'`) is not drawn either:
  - no road or path at all: BWI's terminal hallways (`highway=corridor` +
    `indoor=yes`), any `indoor` way, an elevator, a platform, a road or trail
    under construction ("For some strange reason BWI has TLS 3 inside the
    terminal.", 80);
  - sidewalks and crosswalk lines that are not a trail's (a named trail's
    sidewalk stretch open to bicycles, the Anacostia Riverwalk Trail's, stays,
    and so does a sidewalk open to bicycles that carries a `segregated` tag, a
    shared-use sidepath mapped with care: "Keep tagged sidepaths", 115),
    parking aisles, driveways and drive-throughs, and unnamed footways and
    paths not designated for bicycles shorter than
    `routemaker.facility.SHORT_PATH_M` (150 m) unless both their ends touch a
    trail the map keeps ("There's a lot of side paths and parking lots that
    probably don't need to show up." - "Sidewalks + small paths", 82);
  - a road or path the public may not enter - `access` or `vehicle` of no,
    private, military, restricted or permit, unless a bicycle or foot tag
    opens it - and every road inside an area tagged `landuse=military` or
    `military=*` (`pipeline.military`: the Pentagon, which is
    `landuse=military` + `military=base`, way 916068128, and whose inner roads
    - Connector Road, North Rotary Road - carry no access tag of their own;
    Joint Base Anacostia-Bolling, Joint Base Myer-Henderson Hall, Fort McNair,
    Joint Base Andrews, the Navy Yard). A trail is not tested by area, so the
    Mount Vernon Trail past the Pentagon, the Anacostia Riverwalk past
    Bolling and through the Navy Yard along the water (a designated cycleway
    with no access tag: "There's a trail that open near the water.", 94) stay ("Don't show roads that most typical people can't ride on,
    such as within military bases, or the pentagon", 88). On the dials
    pipeline's box extract: 61 military areas, 2,715 roads inside them.

  - every road and path inside a cemetery (`landuse=cemetery`,
    `amenity=grave_yard`: Arlington National, Congressional, Rock Creek,
    Glenwood, Oak Hill, Mount Olivet) but a trail signed for bicycles ("There's
    a lot of cemetary roads, such as arlington national cemetary. We shouldn't
    have these roads on here, even if some of them can be technically ridden. I
    don't want to encourage a cemetary cut through as it's disrespectful.",
    98), and a parking lot's own unnamed service roads, footways and paths
    (`amenity=parking`, `parking=surface` or `multi-storey`; "Also, no need to
    stripe through all the parking lots.", 99). All of these by place are
    `pipeline.restricted_areas`: a way counts as inside when half its vertices
    are, so a trail or street that only borders the area stays. On the dials
    box extract: 86 cemeteries (1,466 ways, 93 mi), 12,067 lots (17,749 ways,
    762 mi before named ways inside lots were kept).

  Alleys (`service=alley`, `map_class = 'alley'`) are in the z14 tiles only,
  marked `alley`, and the map draws them from `ALLEY_MIN_ZOOM` (16) and faint
  ("Alley cut throughs should only be used if the roads are very problematic
  nearby. Cut down on showing them, and only use them if nessicary. Because
  people don't think of these as intersections, alley dodging is dangerous.",
  100): 5,263 ways, 390 mi on the box extract.

  Routing: a way inside a cemetery is **destination-only** - the rebuild writes
  `rm:cemetery=yes`, and the transform (`lua/routemaker_remap.lua`) makes it
  `access=destination` where its own access leaves it open, upstream's
  destination-only flag, so a route enters only to reach a point inside. The
  rest of this is map only.

  Route-relation membership is not read: an unnamed short piece of a signed
  route is left out like any other. Routing is unchanged: Valhalla reads the
  ways' own access tags.

`map_class` and `separate_bikeway` are **segment columns the rebuild writes**
(`routemaker.facility.map_class`, `has_separate_bikeway`): they reach the map
only after a rebuild with this code. On a table without them a road a bicycle
may not use is a motorway alone (its recorded rule, and it is not drawn),
nothing else is left out, and no road is known to have a bikeway beside it.

**The colours** (`PALETTES` in `stressStyle.js`, the one place they are kept).
The owner, 2026-09-29: "I like LTS 1 and 2. Maybe yellow and orange for LTS 3,
orange and red for LTS 4, and red and black for Avoid." (OWNER-DECISIONS 74).
LTS 1 and 2 are as they were in colour (their edges changed with items 356 and
357: LTS 1 #2f5d47, LTS 2 a slate blue #1a2638 with steel-blue gaps #7a8fa3).
Two readings were built for the owner to choose between, and since item 351
("2 tone is better", "Make two-tone the default") the default is `twotone` (the
first colour as the line, the second as its casing: LTS 3 yellow #f2c21b on
orange #f28c28, LTS 4 orange on red #c81e1e, both ringed in near-black #1c1917 since item
371, which also lightened the yellow to #f3c81a; Avoid red #d42020 on #111111),
which needs no address parameter. `blended`, the default before (LTS 3 amber,
#bf730b, over a dark amber-brown casing, #45290a; LTS 4 a saturated red,
#c80018, over white; Avoid a near-black, #14040a, over a coral-red casing,
#ee3b2c, since item 274), is still there as `?palette=warm`, and the
High contrast switch's palette (formerly "Accessibility") is still `cvd` (`?palette=cool`). The two-tone
LTS 3 and LTS 4 reach 3:1 on the base map by their ring; the greyscale order is lost; the
owner's colours are kept and the breaks reported (docs/DEVELOPMENT.md, "The
default palette (351)"). The blended palette keeps every tier 3:1 on the base map
and the greyscale order; LTS 2 and 3 are only 1.17:1 apart in grey and one olive
to a deuteranope, told apart by their dashes. The tiers' dashes, widths and casings, the facility rails and the
high-stress painted-lane switch are in docs/DEVELOPMENT.md, "Stress salience:
the tiers' shapes and the facility rails".

These choices are for the main ride types. The owner, 2026-09-29: "We might
need to change things for mass rides, but let's focus on the main use cases."
(OWNER-DECISIONS 79). A Mass Ride rides the roadway and ignores facilities, so
for it the faint busy roads and the road hidden beside its cycle track hide
exactly the roads it uses: a backlog item, not built.


**Trails.** The rebuild records on each trail-class way what a bicycle may do
on it (`routemaker.classes.trail_kind`, in the text of `stress_rule`): open to
bicycles, a sidepath for bicycles, or not open to bicycles, by the routing
lane's rule for trails. A trail barred to bicycles - the Appalachian Trail,
the Potomac Heritage Trail, the Bull Run-Occoquan Trail, 3,831 ways in the
2026-09-25 extract - is not a path and is not on the zoomed-out map. A table
promoted before this was recorded has only the plain texts, which cannot tell
a hiking trail from a bike trail: there only a cycleway is a path (1,659 mi
of the 2026-09-28 live table's 6,857 mi of cycleways, paths and bridleways),
until the next rebuild records the kinds or writes the facility.

**Bike facilities.** Until the live table has a `facility` column the tiles
derive one (`pipeline.schema.TRAIL_NETWORK_FACILITY`): a trail open to bicycles
is a path, a sidepath is protected, and nothing else carries one. Where the
live table has the column (path, protected, lane or none - the routing lane
adds it) every feature carries it as `facility`, and z13 also keeps the
paths and protected lanes whatever their kind of way
(`pipeline.schema.keeping_facilities`). The zoomed-out tiles are its paths -
a car-free road such as Beach Drive in DC included - and its protected ways
that are trails of their own (`is_trail_class`): a sidewalk or path
designated for bicycles, an `is_sidepath`, a cycleway along a road whose tags
say its facility is mapped separately. A protected lane tagged on the road
way itself (`cycleway=track`, a lane with posts) waits for z13 with the roads.
The table records no more than that, so a cycle track in DC's roadway mapped
as a way of its own (15th Street NW, Pennsylvania Avenue NW) is drawn zoomed
out like a trail beside a road. On a copy of the dials pipeline's box table
(2026-09-29) the roadside trails added 82 mi to the 871 mi of paths: the
Cross County Trail's sidewalk stretches, the Old Georgetown Road sidepath,
parts of the Anacostia Riverwalk, Rock Creek, Rhode Island Avenue Trolley and
Bethesda Trolley trails, and DC's separately mapped cycle tracks. The Custis,
Capital Crescent and Mount Vernon trails are paths there already. Without the
column, the stand-in's sidepaths (`trail_kind`) are the roadside trails.
**Car-free roads.** The owner, 2026-09-29: "One note: Car-free roads should
be regarded the same as an off-road path on a map." (OWNER-DECISIONS 67). A
road closed to motor traffic for good (Beach Drive NW in Rock Creek Park, the
Capitol grounds drives) is a path in the table - the rebuild writes it so, at
tier 1 - and draws as one at every zoom. A road closed only at set times
(`segment.car_free_when`: Sligo Creek Parkway and Beach Drive in Montgomery
County on weekends) follows the ride time the map is set to - the one chosen
in the panel, or the moment's for "when I'm planning" (`lib/rideTime.ts`, as
`routemaker.ridetime.when_at`): the owner chose "Path on weekends only", so
on Weekend it draws as an off-road path, zoomed out too, and otherwise as the
road it is. The tiles carry the ride times as a property (`car_free`, and
`car_free_only` in a zoomed-out tile, which holds such a road for those times
alone) and the map's style decides (`stressStyle.js`, `stressFilters`): one
tile serves every ride time, so the pre-draw draws each tile once and the
cache and ETags are unchanged. A weekday-rush closure (Clark Place) follows
the same rule on Weekday rush. On the dials pipeline's box table the timed
closures are 3 mi of 20 segments, all weekend.

The overview index is built on the facility's predicate
only once `pipeline.schema.SEGMENT_HAS_FACILITY` says the schema declares the
column (a test fails while the two disagree); with it, the index also holds
the timed closures (`cardinality(car_free_when) > 0`).

**The tile cache.** A tile, once drawn, is kept in the `stress_tile_cache`
table (`core/tile_cache.py`, migration `core.0009`) under its ETag and z/x/y,
and served from there without a draw. Every tile the map asks for - z10-14,
each one the coverage box reaches, 11,068 tiles and 66 MB, empty ones included
so their requests are lookups too - is drawn ahead after every promotion (the
owner, 2026-09-28: "It takes a very long time to load those roads.", where:
"Zoomed in (street level)"; OWNER-DECISIONS 63). The weekly rebuild does it
after the swap and says so on its run row ("Stress tile cache pre-drawn: N
drawn, M already there"), and the tiles are kept. A z15-16 tile drawn on
request (the map does not ask for them) is kept too, up to 256 MB of them,
oldest out first. Rows for an older table or tile format are deleted by the
next pre-draw or eviction. The table is left out of the nightly dump; it
refills itself.

**The Mass Ride tiles** (`GET /tiles/mass/{z}/{x}/{y}.pbf`, `core/mass_tiles.py`;
OWNER-DECISIONS 415, 417, 418) share this cache under their own ETag,
`W/"mass-<oid>+fmw-<boundary digest>-v2"` (33 characters with a ten-digit oid; never
equal to a stress tag, so neither tile set's rows are read as the other's). They are
the Mass Ride map's: the roads with a capacity at z10-14 by band (OWNER-DECISIONS
421, 422: z10-11 only Wide open, 200 riders a minute and up, in a run of at least
0.5 mi; z12-13 Good and up, 120 and up; z14 every band), clipped to the District of
Columbia with the border roads drawn whole (420: a line within 22 m of the boundary),
empty outside the District's box and past z14. The pre-draw draws them
too, after the stress tiles: every z10-14 tile the District's box reaches, a few
hundred (under 300; `tests/test_mass_tiles.py`), on a table that has
`mass_usable_width_m` (none on an older table), counted in the same run-row line.
Measured read-only on the live 2026-10-03 table with a stand-in width (2026-10-05, load
from another agent's run): the z10 tile over DC 1.0-3.0 s and about 100 KB, z11 0.8-6.2 s
and 96 KB, z12 0.6 s and 73 KB, z13 0.3 s, z14 0.25 s; well inside the pre-draw's 20 s,
but a cold z10-11 can pass the 2 s on-request draw timeout and be answered 503 with
Retry-After until the pre-draw has run. Format 2 (2026-10-05, 421, 422) works out the
Wide open runs over the whole District in each z10-11 query: measured the same way,
z10 0.7-0.8 s warm (5.5 s the first, cold), z11 0.45-0.6 s, z12 0.26 s. Its tiles
are new tiles (the tag's `-v2`), drawn by the next pre-draw.
An eviction keeps both the stress and the Mass Ride tags of the live table
(`tile_cache.evict(..., also_keep=...)`), so neither evicts the other. Their own
format is `core.mass_tiles.FORMAT_VERSION` (2), apart from the stress tiles' 7: a
change to one re-draws only its own tiles. A new DC boundary file changes the
digest, so its tiles are new too; re-run the pre-draw after deploying one. The
draw slots, the draw timeout, the per-address limit and the Retry-After answers
are the stress tiles' (below). The edge needs no change: Caddy and the beta's nginx
send every `/tiles/*` path to the api, and Caddy compresses the vector-tile type
whatever the path.

Run the pre-draw by hand on a deployment whose live table was promoted before
the cache existed (the first deploy of this change), after a deploy that
changes `core.stress_tiles.FORMAT_VERSION` (every cached tile is then stale:
3 was the zoomed-out tiles becoming the paths and trails alone, 4 the busy
roads at z12-13 and the quiet streets from z14, 5 the long trails only at
z10-11), and after
`rollback_rebuild`, which puts back a table the last pre-draw cleared the tiles
of. The weekly rebuild's own pre-draw runs in the `rebuild` service, so a
change to what it draws reaches it with the pipeline image. It skips what is
already cached, so it is safe to re-run:

```sh
docker compose exec -T api python manage.py predraw_stress_tiles
```

It draws `STRESS_PREDRAW_WORKERS` tiles at once (default 2), each on a
database connection of its own. It runs in the worker or in this command,
never in gunicorn, so it takes none of the api's draw slots below; what it
takes is a PostgreSQL core per draw. The whole box took 155 s with one worker,
89 s with two and no less with three or four, on a copy of the promoted build
at load 4-6 (2026-09-28), and a route and `/healthz` meanwhile answered as
fast as with no pre-draw (the FOLLOWUP-TILES-ZOOM report has the figures).
Its default budget is an hour; in the weekly rebuild it gets whatever is left
of the rebuild's eight hours if that is less, and the run row says when it
stopped short ("stopped at its time budget with N left", "N timed out"), in
which case run it by hand. Until it has run, a tile is drawn on request
through the one draw slot, and a street-level screen takes 20-30 s: see the
next paragraph.

**Deploying a change to what the tiles draw** (a new `FORMAT_VERSION`, as
format 3 was; corrected by the FOLLOWUP-TILES-ZOOM review). Never a plain
`docker compose up -d`: api, worker and rebuild depend on migrate and
postgis, and a plain `up` would recreate them too.

0. Check first, read-only: no job is queued or running
   (`SELECT id, task_name, status FROM procrastinate_jobs WHERE status IN
   ('todo', 'doing')` prints nothing); the last `weekly_rebuild` in
   `scheduled_run` has finished; it is not the 07:00 UTC backup. And whether
   the live table has the facility column (`SELECT count(*) FROM
   information_schema.columns WHERE table_schema = 'live' AND table_name =
   'segment' AND column_name = 'facility'`): without it the zoomed-out map
   shows the cycleways alone until the next rebuild writes it - deploy after a
   rebuild that has, or accept that.
1. Tag the running images for a rollback
   (`docker tag ghcr.io/macrophage87/routemaker-api:dev
   ghcr.io/macrophage87/routemaker-api:pre-<change>`, and the same for
   `routemaker-pipeline`), then `docker compose build api rebuild`.
2. `docker compose up -d --no-deps api worker`. No migration comes with a
   format change; migrate is not run.
3. At once, the pre-draw: `docker compose exec -T api python manage.py
   predraw_stress_tiles` (about 11,000 tiles in 1.5-3 min). After it,
   `SELECT version, count(*) FROM stress_tile_cache GROUP BY 1` shows only the
   new format. Until it ends, tiles are drawn on request through the one slot.
4. Re-run step 0's job query (it must print nothing), then
   `docker compose up -d --no-deps rebuild`, so the next rebuild's own
   pre-draw is the new code's.
5. The overview index: nothing (see "The overview index" below). Caddy: not
   recreated.
6. The front end last, as in docs/DEPLOYMENT.md, "The public front end".
7. Check: a z11 tile answers 200 with an ETag ending in the new format
   (`-v7"`, or `+kcfrmwoesbtl-v7"` with all twelve optional columns) and a repeat
   with `If-None-Match` is 304; a
   z14 tile is a cache hit; the map at z11 shows only paths and trails with
   the zoomed-out notice, and z13 the full colours.

**Draw slots and the draw timeout.** A tile not in the cache is drawn under an
in-flight slot (`core.ratelimit.TILES_IN_FLIGHT`): at most `TILE_CONCURRENCY`
draws in the deployment - what routing's and geocoding's slots leave of the
worker count less one, at least one: one at compose's seven workers (three
routes, two lookups, one draw; `config.settings.tile_concurrency`), which with
the one geocoding waiter can hold all seven, a worker free again within about a
second - see "How the workers are shared" above).
A draw that finds no slot is refused at once: 503 (the deployment's slot) or
429 (the client's), with `Retry-After: 1` and `no-store`. A draw runs under a
2 s statement timeout (`DRAW_TIMEOUT_MS`), inside the promotion swap's 3 s
lock timeout, so a swap waiting for its lock behind a tile draw normally gets
it on its first attempt. That is not a hard bound - PostgreSQL acts on the
cancel between steps, and one cold draw on a busy host ended at 5.46 s - and
the swap's five attempts cover it. A draw cut off is 503 with `Retry-After: 1`.

The map fetches tiles through a protocol of its own
(`frontend/src/lib/stressProtocol.ts`): at most two tile requests from a page
at once, and a refused tile waits the longer of its Retry-After and 1, 2, 4,
8, 8... seconds, each stretched at random by 0.5-1.5, for up to 30 s before
MapLibre is left to show the parent tile there. The map's availability check
at load goes the same way.

What this bought, measured on a copy of the first promoted build (5 workers, 2
CPUs; one route every 2 s and `/healthz` every second from other addresses,
alongside the ops review's session - 10 views of 20 tiles over 6 connections
from one address - and hammer - the z10 downtown tile 120 times over 32
connections from one address):

| | routes p50 / max | `/healthz` p50 / max |
| --- | --- | --- |
| No tile load | 0.19 s / 1.36 s | 0.006 s / 0.83 s |
| Round 1 (no cache, no index), session | 1.07 s / 14.3 s | 0.08 s / 15.2 s |
| Round 1 (no cache, no index), hammer | 10.8 s / 13.5 s | 9.7 s / 11.9 s |
| No index, empty cache, session | 0.19 s / 0.71 s | 0.006 s / 0.11 s |
| No index, empty cache, hammer | 0.43 s | 0.015 s / 0.09 s |
| No index, pre-drawn, session | 0.29 s / 1.02 s | 0.007 s / 0.51 s |
| No index, pre-drawn, hammer (120 tiles in 1.1 s, all 200) | 0.31 s | 0.03 s / 0.06 s |
| Index, pre-drawn, session | 0.12 s / 0.22 s | 0.005 s / 0.06 s |
| Index, pre-drawn, hammer (120 tiles in 0.8 s, all 200) | 0.29 s | 0.03 s |

(The round-1 rows are the ops review's, on the same copy and hardware; the host
here was at load 5-10 from other work. These runs used round 2's pool of two
draws; the pool is now one, with the page queue and backoff below. The ops
review of round 2 measured the same shape at load 10-27, its worst sustained
case - 32 connections for 30 s on the z10 downtown tile, no index, empty cache
- at routes max 4.5 s and `/healthz` max 3.9 s, against round 1's 13.5 s and
11.9 s.)

**Limits.** Counted per address like routing, under a scope of their own
(`core.ratelimit.TILES`): 600 per 60 s window (owner decision of 2026-09-27),
429 with `Retry-After` past it. A map fetches tiles by the screenful - a
vigorous minute of zooming and panning a 1920x1080 window fetched 87 - so the
figure is several people's worth behind one address. Cache hits are counted
like any other request.

**Caching in the browser.** `Cache-Control: public, max-age=3600` and a weak
ETag naming the live table (its oid, which a promotion changes), the optional
columns it has, and the tile format version, so after the hour a client
revalidates and gets a 304 without the tile being drawn or read, and a column
added in place is not a 304.
Caddy compresses the tiles (an `encode` in the api's block matched on the
vector-tile content type); nothing else the api answers is compressed.

**The overview index.** The zoomed-out tiles read through a partial GiST index,
`segment_overview_geom_idx`, holding only the paths and trails
(`pipeline.schema.OVERVIEW_INDEX_PREDICATE`), which
`pipeline.schema.create_segment_schema` creates with the rest of the schema on
every rebuild. It speeds the pre-draw: without an index the z10 downtown tile
took 0.27 s rather than 0.06 s, and z10-12 took 8.7 s rather than 5.9 s. A live
table promoted before this change has the index built on the old predicate
(busy roads and the trail network). **Do nothing, and do not drop it:** it
serves the new query too - on a table without the facility column the trails'
rules are a subset of the old predicate's, and `EXPLAIN` shows a bitmap
index scan on it (FOLLOWUP-TILES-ZOOM review, round 1). The next rebuild
creates the index on the facility's predicate.

**The seek index.** The trail seek's table read (above) goes through a partial
GiST index, `segment_seek_geom_idx`, holding only its corridors
(`pipeline.schema.SEEK_INDEX_PREDICATE`: path or protected at LTS 1-2, or any
car-free road), which `create_segment_schema` creates with the rest of the schema;
the query carries the predicate word for word so the planner can use it. It is not
a Django migration: the segment schema's DDL is the pipeline's (docs/DEVELOPMENT.md,
"What migrations do and do not create"). **At a rebuild** it is built in staging,
on the empty table before the load, and promoted by the swap: nothing runs on the
live table. **On today's live table** (no facility column) it is not needed and
cannot be built (its predicate names the column); the seek reads that table by the
trail rule through `segment_overview_geom_idx`. **A table promoted with the facility
column but without this index** (a rebuild from code before it) still works, through
the whole geometry index (about 0.2 to 0.3 s a leg read strip by strip: 227 to 329 ms
measured on a 1.36M-row copy, inside the statement timeout); to add it in place
without blocking reads or writes, measured at 1.6 s and 648 kB on a 1.36M-row copy:

    docker compose exec -T postgis psql -U routemaker -d routemaker -c \
      "CREATE INDEX CONCURRENTLY IF NOT EXISTS segment_seek_geom_idx ON live.segment
       USING gist (geometry) WHERE (facility IN ('path', 'protected') AND stress_tier <= 2)
       OR cardinality(car_free_when) > 0"

A `CONCURRENTLY` build that fails (cancelled, or the connection lost) leaves an
INVALID index of that name behind, which the planner does not use and which `IF NOT
EXISTS` then skips without a word. So check `indisvalid` before the build and after
it; if it is false, drop the index and build it again:

    docker compose exec -T postgis psql -U routemaker -d routemaker -c \
      "SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
       WHERE c.relname = 'segment_seek_geom_idx' AND c.relnamespace = 'live'::regnamespace"
    docker compose exec -T postgis psql -U routemaker -d routemaker -c \
      "DROP INDEX CONCURRENTLY IF EXISTS live.segment_seek_geom_idx"

**The covered area.** `GET /api/coverage` answers the area routes may be
planned in as a GeoJSON polygon feature - `settings.COVERAGE_BBOX`, the box the
route endpoint's validator enforces - with an hour's `Cache-Control`, limited
to 60 a minute per address (`core.ratelimit.COVERAGE`). The map greys out
everything outside it. Should the region become a drawn polygon, the validator
and this endpoint change together (`core.api.coverage_ring`).

## Backups

`pg_dump -Fc` to `<DATA_ROOT>/backups/routemaker-<UTC instant>.dump`, excluding
the data of the session table, the cached membership table and the rate-limit
table (`BACKUP_EXCLUDED_TABLES` in `config/procrastinate.py`), verified by reading the
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
volume is what stands between this deployment and a lost host until that lands,
and it is in the deployment actions below because nothing in this repository
takes it.

## Restoring one

**Restore into an empty database, before the rest of the stack is up.** That is
the whole runbook, and the ordering is the only part of it that is difficult to
get right afterwards.

```sh
export DATA_ROOT=/srv/routemaker/data   # the same value as DATA_ROOT in .env

docker compose down                     # 1. nothing else talking to it
sudo rm -rf "$DATA_ROOT/postgres"       # 2. an EMPTY PGDATA
sudo sh scripts/prepare_data_root.sh --env-file ./.env
docker compose up -d --wait postgis     # 3. postgis alone, healthy: no migrate, no worker
docker compose exec -T postgis dropdb -U routemaker routemaker
docker compose exec -T postgis createdb -U routemaker -T template0 routemaker
docker compose exec -T postgis \
  pg_restore --no-owner -U routemaker -d routemaker \
  < "$DATA_ROOT/backups/routemaker-<instant>.dump"
docker compose up -d                    # 4. now the rest
docker compose run --rm api ./manage.py collectstatic --noinput
```

`routemaker` everywhere after `-U` and `-d`, and as the database name, is
`PGUSER` and `PGDATABASE` from `.env`, which ship as that and are the compose
defaults; substitute your own if you changed them. The redirection is on the
host because the dump is not visible inside `postgis` — that service binds
`postgres/` and nothing else, and `backups/` is bound into `worker` — so
`exec -T` and standard input is how the archive gets there.

Step 3 is `up -d postgis` and not `up -d`, and the difference is measured
rather than stylistic. Every figure here was measured on this stack's own
`postgis/postgis:16-3.4` image with a dump in the backup's form. A restore run
into a database that `migrate` had already populated produced **172 errors and
exit 1**. The exit status is honest and it arrives too late: `pg_restore` does
not stop at a failing statement, it carries on, puts the rest of the archive in
around every failure, and only then prints `errors ignored on restore: 172` and
exits 1. By the time the status says something went wrong the database is a
mixture of the dump and what `migrate` wrote, with nothing to undo it; the
repair is to start again from step 1. What collides is everything `migrate`
creates and the dump also carries: `django_content_type`, `auth_permission` and
`django_migrations` all have their rows twice over, and the `COPY` for each
fails on the unique index while the rest of the archive goes in around it.

An empty PGDATA does not give an empty database, which is why step 3 drops and
recreates it. On a first boot the image creates `postgis`, `postgis_topology`,
`fuzzystrmatch` and `postgis_tiger_geocoder` in `PGDATABASE`, and the dump
carries the `tiger`, `tiger_data` and `topology` schemas those made; restored
straight into the image's database it gave **3 errors** (each of those schemas
"already exists") **and exit 1**. Dropped and recreated from `template0` first,
the same dump gave **0 errors and exit 0**, with the same five extensions, every
table and row count equal to the source database's, and an identical schema
dump. (The one difference is the order of `tiger` and `topology` in the
database's default `search_path`, which the extension scripts set; the
application sets its own on every connection.) So with step 3 as written a
non-zero exit is never noise, and the thing to do with one is to stop.
`--wait` because the image's first boot runs its init scripts before the server
takes connections: without it, measured, `dropdb` ran while the socket did not
exist yet and every command after it failed. `--no-owner` because the role in
the dump and the role in this deployment need not be the same name.

There is no `docker compose down -v` in that list on purpose: every stateful
path here is a host bind mount and `-v` has nothing of this deployment's to
remove. What empties PGDATA is `rm`, which is why step 2 is spelled out.

### What the restored deployment actually has

- **No standing, until the membership cache is rebuilt.** The dump excludes the
  cached membership table, the session table and the rate-limit table (whose
  counts are worthless after a restore anyway), and phase 1 has no bot, so
  nothing refills the cache — the sweep that would is unbuilt (handoff.md
  section 7). Until it exists, a restored deployment grants **no** guild-derived
  standing at all: everyone is signed out (sessions went with the dump's
  exclusion) and signs in to an account with no memberships behind it. Instance
  admins are unaffected: `is_instance_admin` is a column on the user row and it
  is in the dump.
- **No tiles.** `${DATA_ROOT}/tiles` is not in the database and not in the dump.
  If the volume survived, the routers come back on the build they were serving;
  if the host did not, there are no tiles until the first rebuild finishes, and
  `valhalla_upstream` will name a build id that is not on disk. Fire one by hand
  (`run_rebuild_now`, below) rather than waiting for Tuesday.
- **Collected static assets** are on the data volume too and not in the dump,
  which is why `collectstatic` is the last line above.
- **An empty stress tile cache.** `stress_tile_cache` is in the dump without
  its rows, and the restored segment table is a new relation, so every cached
  tile would be stale anyway. Until the pre-draw has run, every tile is drawn
  on request through the api's one draw slot, and a street-level screen takes
  20-30 s to fill. Draw them: `docker compose exec -T api python manage.py
  predraw_stress_tiles` ("The stress tiles", above).

### It will page for the first few hours, and that is the restore

**After a restore, expect the operations page to be red for a while, and check
the clock before acting on it.** A dump is taken from inside `nightly_backup`'s
own run row, which is opened before `pg_dump` starts and closed after it
finishes — so the dump never contains the success of the run that produced it.
A database restored from last night's dump therefore comes up with
`nightly_backup`'s last success a day and a bit old, and with
`worker_heartbeat`, `degraded_guild_sweep` and `membership_sweep` stale by
however long the outage and the restore together took. All four clear
themselves on their own schedule once the worker is up: the heartbeat and the
degraded-guild sweep within five minutes, the membership sweep within six
hours, and **`nightly_backup` not until the next 07:00 UTC**. A
`check_operations` that names only `nightly_backup` in the hours after a
restore is the restore, not a second fault.

## The rebuild's own budget

A rebuild has eight hours (six until the owner's "Yes, 8 hours (Recommended)"
of 2026-09-28, for the fourth graph). It hands whatever remains of that budget to every
binary it runs and checks it between stages, and a rebuild that runs out is
**abandoned rather than retried**, in either shape it arrives in
(`RebuildTimedOut` from the stage boundary, `subprocess.TimeoutExpired` from a
killed binary). It will not finish faster on the next attempt, and a retry runs
the whole rebuild again including the swap — whose `DROP SCHEMA live_old`
destroys the schema a rollback would have put back. Five retries of a timed-out
rebuild would have dismantled its own rollback target, one attempt at a time.

## Tile build threads

Each graph is built by one `valhalla_build_tiles` run, and the five run one
after another (standard, no-trail, ebike, weekend, offroad). How many threads a
run uses is `mjolnir.concurrency` in that variant's
`<DATA_ROOT>/tiles/<variant>/<build id>/build-config.json`, and the rebuild
writes it from **`REBUILD_TILE_CONCURRENCY`** (in `.env`; unset means **2**).
The serving configs' own `"concurrency": 4` is not what a build uses.

Why it is a setting: Valhalla 3.5.1 can abort a multi-threaded tile build with

```
double free or corruption (fasttop)
```

on stderr and `valhalla_build_tiles exited -6` (SIGABRT) in the rebuild's log,
usually a few seconds after `Building <n> tiles with <threads> threads...`. Each
build thread frees its spatialite connections to the admin and timezone
databases when it finishes, that cleanup calls a libxml2 function that is not
thread-safe, and two threads finishing together can free the same memory.
Upstream fixed it in 3.6.0 ([valhalla/valhalla#5005](https://github.com/valhalla/valhalla/pull/5005),
reported as [#4904](https://github.com/valhalla/valhalla/issues/4904)). It is a
race, not bad data: the same inputs build on the next try, and which graph it
hits is luck.

**The pinned image is 3.9.1 now (2026-10-10), which has that fix**: from 3.6.0
Valhalla takes a process-wide lock around the cleanup (`Sqlite3::~Sqlite3`,
src/mjolnir/sqlite3.cc:78-91 at 3.6.3, unchanged at 3.9.1). Both guards below
stay until rebuilds on this host with the fix have shown no abort; the default stays 2 for memory as
much as for the race. Once a few rebuilds are clean, 4 (the measured 4.5 h row
below) is the setting to try. A `retry 1 of 1` line under 3.9.1 is no longer
the known race: keep the log and report it.

Two things keep it from failing a rebuild:

- **Fewer threads.** 2 rather than 4 means fewer threads finishing at once,
  and less memory. **1 cannot hit it at all**, and is the setting to use if
  aborts keep happening; it makes the tile stage slower (the figures below).
- **One retry of the crashed graph.** A `valhalla_build_tiles` that dies with
  SIGABRT is run once more, for that graph only, logged as
  `valhalla_build_tiles aborted (SIGABRT); running it again, retry 1 of 1: <command>`.
  That line means the retry is running and nothing needs doing now. The rerun
  starts from scratch in the same build directory (Valhalla purges the tile
  level directories first) and gets whatever is left of the budget. Any other
  failure, or a second abort, fails the rebuild as before; a second abort is
  reported as `valhalla_build_tiles exited -6 (after 1 retry): <command>`.

What it costs, measured on attempt 3 of job 8023 (2026-10-08, 4 threads, no
abort): preprocessing up to the first build config took 2 h 37 min, the tile
stage 1 h 15 min (5.6 to 20.6 min a graph; standard is the longest, since it
also builds the admin and timezone databases), and VALIDATE 27 min. From those:

| Threads | Whole rebuild |
|---|---|
| 4 | about 4.5 h |
| 2 (the default) | about 6 h; about 6.8 h if one graph is retried |
| 1 | about 6.6 to 8.3 h |

At 1 thread the top of that range is past the eight-hour budget ("The
rebuild's own budget", above), and a rebuild that times out is abandoned, not
retried. So set 1 only after an abort that the retry did not cure (the `(after
1 retry)` failure), or after the retry line has shown up in more than one
rebuild, and watch the next one against the budget.

The setting is read when the settings load: a value that is not a whole number
of at least 1 (`0`, `-1`, `2.5`, `x`) keeps the rebuild service from starting:
under `restart: unless-stopped` the container keeps restarting, and
`docker compose logs rebuild` shows
`REBUILD_TILE_CONCURRENCY must be a whole number of at least 1`. Empty counts
as unset.

To change it: set `REBUILD_TILE_CONCURRENCY=1` (or another whole number of at
least 1) in `.env` and, with no rebuild job `todo` or `doing`, recreate the
rebuild service (never a plain `up -d`):

```sh
docker compose up -d --no-deps --no-build --force-recreate rebuild </dev/null
docker compose exec -T rebuild ./manage.py shell -c "from django.conf import settings; print(settings.REBUILD_TILE_CONCURRENCY)" </dev/null   # the new value
```

The value a build actually used is in its `build-config.json` under
`/data/tiles/<variant>/<build id>/`. (Valhalla's `Building <n> tiles with
<threads> threads...` line is not in `docker compose logs rebuild` on a build
that succeeds: the rebuild captures the output and logs it only when a command
fails.)

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
five for the build's own four variant extracts and its scratch); once there is
one, its real size is what the gate charges. A rebuild refused by the gate has
downloaded nothing.

## The base map

The public map's background is self-hosted, per PLAN.md "Base map": no request
from a page on this site goes to a third-party tile server. Three things live
under `<DATA_ROOT>/basemap/`, bound read-only into Caddy at `/srv/basemap` and
served at `/basemap/`:

| Path | What it is | Source |
| --- | --- | --- |
| `region.pmtiles` | the Protomaps basemap (v4 layers) over `settings.COVERAGE_BBOX`, about 300 MB | `pmtiles extract` of `https://build.protomaps.com/<YYYYMMDD>.pmtiles` |
| `fonts/<fontstack>/<range>.pbf` | MapLibre glyphs (Noto Sans) | `https://github.com/protomaps/basemaps-assets`, pinned commit |
| `sprites/v4/<flavor>[@2x].{json,png}` | the style's icons | the same commit |

### Licences, and the credits every map must carry

PLAN.md "Licensing" asks for each external source's licence, URL and refresh
procedure. For the base map:

| Source | Licence | Credit on the map | Refresh |
| --- | --- | --- | --- |
| `region.pmtiles`: Protomaps basemap, built from OpenStreetMap (and Natural Earth at low zooms) | the data is OpenStreetMap's, **ODbL 1.0** (<https://www.openstreetmap.org/copyright>); an extract of it is a produced work of that database. Natural Earth is public domain | **"© OpenStreetMap contributors"** and **"© Protomaps"**, both, on every map view | monthly (below) |
| `fonts/`: Noto Sans glyphs | **SIL Open Font License 1.1**, shipped beside them as `fonts/OFL.txt` | none required | with `ASSETS_COMMIT` |
| `sprites/v4/`: icons | **MIT**: basemaps-assets' README at the pinned commit (installed as `sprites/README.md`) says the sprites are derived from MIT-licensed tangrams/icons, <https://github.com/tangrams/icons/blob/master/LICENSE.md> | none required | with `ASSETS_COMMIT` |
| go-pmtiles 1.31.2, the build tool (not served) | **BSD-3-Clause**, © Protomaps LLC, <https://github.com/protomaps/go-pmtiles> | n/a | with `PMTILES_VERSION` |

The archive's own metadata attribution credits OpenStreetMap only, not
Protomaps, so a style that shows the archive's attribution field shows half of
what is owed. The front end has to set both credits itself, and does:
`BASEMAP.attribution` in `frontend/src/stressStyle.js` carries both, on the base
map's source and in the map's attribution control.

The rail stations drawn over the base map carry one more credit on every map
view, "Metro stations and entrances: District of Columbia (Open Data DC),
CC BY 4.0" (`RAIL_CREDITS` in `frontend/src/lib/mapStyle.ts`). Their sources,
licences and the refresh by hand are in `frontend/src/rail-data/README.md`;
the MARC Penn Line's stations, and the elevators taken from OSM where DC lists
none, are OpenStreetMap's and need nothing beyond the ODbL credit.

The Mass Ride map's federal-land shading carries one more credit on every map
view, "Federal land on the Mass Ride map: National Parks, Reservations and
Military Bases, District of Columbia (Open Data DC), adapted, CC BY 4.0"
(`FEDERAL_CREDITS` in `frontend/src/lib/mapStyle.ts`). The three Open Data DC
items (National Parks `14eb1c6b576940c7b876ebafb227febe`, Reservations
`0ac4302b2e354fad986f07199e73a19e`, Military Bases
`21ee426eddc14014b80535cd6b8316e7`) are CC BY 4.0, merged, clipped and
simplified into `frontend/src/federal-data/federal-land.json` (so "adapted"); the
Capitol grounds in it are the Architect of the Capitol boundary already credited
above. Sources, licence text verbatim, retrieval times and digests are in
`fixtures/datasets/README.md`, "Federal land". The file is a hashed asset under
`/assets/`, served and compressed with the rest of the front end and fetched
only when a Mass Ride is open; no edge, compose or deploy change.

The water and restrooms layer (`frontend/src/lib/waterRestrooms.ts`) is
OpenStreetMap data and needs nothing beyond the ODbL credit. Its file,
`frontend/src/amenity-data/water-restrooms.json`, is a committed snapshot built
by `scripts/build_water_restrooms.py` from the extract; the weekly rebuild does
not refresh it (the refresh by hand is in `frontend/src/amenity-data/README.md`).
It is a hashed asset under `/assets/` (about 35 KB compressed), served like the
federal-land file and fetched when the layer is on, which it is by default; no
edge, compose or deploy change. A release that first carries it adds to its
checks: the hashed `water-restrooms-*.json` asset gives 200, `immutable`,
compressed, and is named by the published front end's script.

Three more credits ride with the agency layers (`docs/DEVELOPMENT.md`,
"Agency street layers"; sources and licences in `fixtures/datasets/README.md`),
in `routing.ATTRIBUTION` and `VOLUME_CREDITS`:

- "Street speeds, lanes, one-way streets, bike lanes, parking and traffic counts
  in the District: Roadway Block, District Department of Transportation (DDOT) /
  DC GIS (Open Data DC), adapted, CC BY 4.0". The layer is parsed and combined
  with OSM, so it is "adapted", and the licence is linked; its AADT fills where
  no count layer reached a street.
- "Street speeds, one-way streets, bike facilities and trails in Baltimore: City
  of Baltimore, Open Baltimore". Open licence by Baltimore City Code Art. 1
  §9-1(h); the line is the owner's (OWNER-DECISIONS 159), since the items carry
  no credit of their own. It covers the centerline's speeds (only where OSM has
  none) and one-way streets, and the facility and trail rows of
  `fixtures/overrides/2026-10-01-owner-baltimore-facilities.json`.
- "Roads to avoid in Montgomery County: Bicycle Level of Traffic Stress,
  Montgomery County Planning Department". The layer's licence asks for
  "attribution to the Montgomery County Planning Department"; the line went in
  with the Avoid rows derived from it,
  `fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json` (OWNER-DECISIONS
  181), and the three-question ODbL gate it passed is recorded in
  `fixtures/datasets/README.md` and PLAN.md. **The credit and the rows travel
  together**: deleting the rows does not make the credit wrong for the graph
  until the next rebuild, but a rebuild without them should drop the line.

Arlington's Bike Comfort Index and Alexandria's Transport Streets are internal
comparison only and are never credited because nothing of them is published.

DDOT's Central Business District boundary (Open Data DC, CC BY 4.0), which
decides the sidewalks bicycles may not ride (`routemaker.cbd`, OWNER-DECISIONS
104), shares DDOT's traffic-volume line in both credit lists: "Stress tiers use
traffic volume, and routing the Central Business District boundary, from the
District Department of Transportation, adapted, CC BY 4.0"
(`routing.ATTRIBUTION`, `VOLUME_CREDITS`). The Architect of the Capitol's
jurisdiction polygon (Open Data DC, DC GIS, CC BY 4.0), which exempts the
Capitol grounds from that rule (OWNER-DECISIONS 113), has its own line in both
lists: "Routing the Capitol grounds: Architect of the Capitol boundary,
District of Columbia (Open Data DC), CC BY 4.0". Their sources, retrieval and
refresh by hand are in `fixtures/cbd/README.md`.

### Fetching it

`scripts/fetch_basemap.sh` makes all of it and pins every input at its top: the
go-pmtiles release and its sha256, the basemaps-assets commit and the sha256 of
its archive, the Protomaps build date and the bounding box (which
`tests/test_basemap.py` holds equal to `COVERAGE_BBOX`). Both downloads are
checked before anything is unpacked, and everything is assembled in
`basemap/.work` and moved into place only when complete, so a failed or
interrupted run leaves the previous files serving. The region has no published
digest to check; `pmtiles verify` runs on it instead. Each finished part leaves
a stamp (`.region.source`, `.assets.source`) naming what it was made from, and a
run whose pins match the stamps does nothing and makes no request. A run needs
about 330 MB free on the data volume beyond what is already there: the new
archive and both tarballs sit in `basemap/.work` until the swap.

It has to run as the directory's owner, uid 10001 after `prepare_data_root.sh`,
and that uid has no account on the host and usually cannot read the checkout
(a home directory is `750`). So it runs in a container as 10001, with only the
script and the one directory mounted, and `DATA_ROOT` spelled out rather than
read from `.env`, which holds every secret the stack has. The image is
`curlimages/curl`, pinned by digest, which carries curl, tar, sha256sum and cut;
no sudo is needed, only the docker group. From the repository root:

```sh
docker run --rm -u 10001:10001 -e DATA_ROOT=<DATA_ROOT> \
  -v <DATA_ROOT>/basemap:<DATA_ROOT>/basemap \
  -v "$PWD/scripts/fetch_basemap.sh:/fetch_basemap.sh:ro" \
  --entrypoint sh \
  docker.io/curlimages/curl@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777 \
  /fetch_basemap.sh
```

Run as shown on the development host on 2026-09-26: the first run downloaded
312 MB and took about 40 s, and its `region.pmtiles` was byte-identical to one
made earlier the same day from the same build; the second printed "is
current" and fetched nothing.

### Refresh

PLAN says monthly, by the worker. That job does not exist yet; until it does the
refresh is by hand: the same command with `--build <YYYYMMDD>` appended, naming
a newer day, then bump `PROTOMAPS_BUILD` in the script to that date and commit
it, so the repository says what is being served. Until the pin is bumped, a
plain re-run treats the newer archive as stale and goes back to the pinned day.
build.protomaps.com keeps daily builds for a limited time only, so an old pin
is a 404 and the script says so; there is no mirror to fall back to. Caddy reads
the files per request, so nothing is restarted: the next request gets the new
archive, and `Cache-Control: no-cache` on it means browsers revalidate rather
than mixing old and new byte ranges. The glyphs and sprites change only when
`ASSETS_COMMIT` is bumped. There is no lock: two runs at once over the same
directory delete each other's work directory, which the future worker job has
to prevent.

### What the edge enforces

Preset links: `/<ride-type-id>` (for example `/trailmaxxing`, any case, with or without a trailing slash) is a 302 to `/#preset=<id>`, for exactly the nine ids in `frontend/src/lib/presets.ts`; adding or renaming a ride type means editing the Caddyfile's `@preset-*` list too, and `tests/test_preset_links.py` fails until it matches.

`/basemap/*` answers only `region.pmtiles`, `fonts/*` and `sprites/*` (anything
else under it is a 404, the stamps and the work directory included), and only to
requests whose `Origin` is this site or, with no `Origin`, whose `Referer` is a
page on it; anything else is a 403, sent `no-store` so a browser does not keep
it. That is a hotlinking guard, not access control, and it has two
consequences: a browser that strips a same-origin `Referer` (a privacy
extension, a page served with `Referrer-Policy: no-referrer`) gets a blank map,
and the rule assumes Caddy is the TLS edge, because behind another
TLS-terminating proxy Caddy sees `http` and refuses every `https` page.

**The per-IP range-request limit PLAN asks for is not in place**: the stock
`caddy:2.8-alpine` image has no rate-limit module, and adding one means building
Caddy with a third-party module. Until then nothing bounds how fast one address
can read the archive, and that is a gate on opening the site to anything beyond
this machine (docs/DEPLOYMENT.md, "Build").

## Applying a Caddyfile change

`compose.yaml` binds `./Caddyfile` into the caddy container as a single file,
so the checkout's file is the live one. A `git pull`, `merge` or `checkout`
that changes it does not edit it in place. Git writes a new file and renames it
over the old one, which gives it a new inode, and a single-file bind follows
the inode it was created with. Measured under Docker Desktop on WSL:

- the running container goes on seeing the old content, so a `caddy reload`
  inside it reloads the stale config and reports success;
- `docker compose restart caddy` (a `docker restart`) then fails to mount the
  source at all (`error mounting ... no such file or directory`) and leaves the
  container exited. The `unless-stopped` restart after a crash is the same
  restart, so it can fail the same way;
- plain `docker compose up -d` does nothing, because the compose config has not
  changed. The site goes on serving the old routes.

Only a new container picks up the new file. After any git update that touches
the Caddyfile, from the checkout compose runs from, validate the new file in a
throwaway container of the same image (this is what `tests/test_preset_links.py`
does), then recreate caddy alone:

```sh
docker run --rm -e CADDY_SITE_ADDRESS=:80 -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile
docker compose up -d --no-deps --no-build --force-recreate caddy
```

Validation runs on the `:80` posture because the site address is the one value
that differs between postures, and it only changes the address, not the routes.
If `validate` fails, stop: the running container still has the old file
and is still serving. Fix the file before recreating anything. Certificates
survive the recreate, because they are in `${DATA_ROOT}/caddy`. Never use `caddy reload` or
`docker compose restart caddy` after a git update of this file.

The Caddyfile is the only single-file bind in `compose.yaml`. Every other bind
is a directory (`./valhalla`, `./lua` and the `${DATA_ROOT}` paths). A
directory bind keeps the directory's inode, so a file git replaces inside it is
seen at once. The routers still read their config only at start; see "After a
rebuild: restart the routers". `tests/test_deploy_docs.py` fails if a second
single-file bind appears without this procedure covering it.

## Pausing the weekly rebuild

OWNER-DECISIONS 355 ("Pause until our rebuild"): set `WEEKLY_REBUILD_PAUSED=1` (or
`true`) in the deployment's `.env` and recreate the rebuild service:

```sh
docker compose up -d --no-deps --force-recreate rebuild
```

The Tuesday 08:00 UTC tick still fires (`WEEKLY_REBUILD_CRON` is unchanged), and
the job logs `weekly rebuild paused (WEEKLY_REBUILD_PAUSED)`, writes one run row marked
paused, and ends `succeeded` without a prune or a build. `check_operations` and the
operations page report the rebuild as paused, not stale, so nothing alerts; if the paused
ticks themselves stop (the rebuild worker down), it is stale again eight days after the
last one. A rebuild fired by hand
(`run_rebuild_now`, below) runs whatever the switch says. To resume, remove the
line (or set it empty) and recreate the service the same way. 355 asks for it to be
set in t9's `.env` at the release deploy; if the release is not deployed before
Tuesday 2026-10-06 08:00 UTC, the fallback is to stop the rebuild container before
then, with the owner's OK.

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

Before firing one for a deploy that changes `lua/`, `valhalla/` or the
pipeline image, run `scripts/check_tile_build_access.sh` on that commit ("Bicycle
closures in the tiles", step 1): about 2 s, and it is the only check that sees
what Valhalla's C++ parser does with the transform's output before a rebuild
spends hours on it. The rebuild's own VALIDATE gate (step 2) refuses the swap if
a closure did not hold, and the probes (step 3) follow the router restart.

It **queues** a job and returns; it does not run the rebuild. The `rebuild`
service is what picks the job up, because that is the container with the
Valhalla binaries, the data mounts and the eight-hour budget, and it takes it
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
but a rebuild creates the tiles the four Valhalla containers mount, and the
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
   sudo sh scripts/prepare_data_root.sh --env-file ./.env
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
   `docker compose up -d --no-deps --no-build api` and not `docker compose restart api`
   — a restart restarts the process with the environment it was created with,
   and the sign-in that follows it gets a 404 from the admin with nothing in
   any log to explain it. Step 4 is the rest of that bootstrap; what it needs
   from here is the id already in the container's environment.

   `bot` and `renderer` are behind the `unbuilt` profile and are skipped: they
   have no source and no image. `photon` starts, and serves place search once
   its index is imported (docs/DEPLOYMENT.md, "Photon"); until then it waits,
   unhealthy, and downloads nothing, and place search answers 502 while point
   names fall back to the router alone. `migrate` waits for the database's health
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
   A build takes up to eight hours from 08:00 UTC on Tuesdays and no grace period
   can cover it, so the answer is to wait or to accept the unwedge, not to
   lengthen the grace.

   **Also check that no proof or test container is running from this
   project's images.** A container started with `docker run` from
   `ghcr.io/macrophage87/routemaker-api:<tag>` (or any image compose built)
   inherits the image's build labels, `com.docker.compose.project=routemaker`
   and `com.docker.compose.service=api` among them, so while it runs the live
   project sees it as one more api container: `docker compose ps`, `up` and
   `down` count and act on it. Tear every such stack down before a live
   `docker compose` command - `docker ps -a --filter
   label=com.docker.compose.project=routemaker` should list only the
   project's own `routemaker-*` containers - or start proof containers with a
   label of their own, `--label com.docker.compose.project=<other>`, which
   overrides the image's (merge re-check of PUBLIC-SEARCH, 2026-09-28).

   **The command will also take a minute to return**, and that is the grace
   period being spent rather than something hanging. `down` and `up -d` send
   the SIGTERM, wait the full `stop_grace_period: 60s` because the worker is
   waiting for its job, and only then kill it. `worker` carries the same 60s
   and is stopped in the same pass, so a `down` of a busy stack is about a
   minute in total and not two.

   **`worker` wedges the same way**, for less time and with the same repair. A
   `nightly_backup` or a sweep killed mid-run leaves its row `doing` too; its
   tasks are bounded at thirty minutes rather than eight hours, so the odds of
   catching one are lower, but `unwedge_job` is still what clears it and the
   wedged-job surface still reports it.

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
   recreated for the new value to reach it: `docker compose up -d --no-deps --no-build api`.
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
   means step 8 reuses it rather than pulling it again.

6. **Install the reference data, pointed at the extract step 5 just wrote.**

   The GeoJSON inputs are not in this repository and the stack cannot download
   them, so put them on the host first, under a directory the `rebuild`
   container actually binds — it binds five, not the whole volume, so a file
   dropped anywhere else under `${DATA_ROOT}` is not visible to it.
   `${DATA_ROOT}/reference/inputs/` is the one this document uses, and the
   container sees it at `/data/reference/inputs`:

   ```sh
   export DATA_ROOT=/srv/routemaker/data   # the same value as DATA_ROOT in .env
   sudo install -d -o 10001 -g 10001 "$DATA_ROOT/reference/inputs"
   # then copy tl_2024_us_uac20.geojson, vdot-aadt-2024.geojson and
   # ddot-aadt-2024.geojson into "$DATA_ROOT/reference/inputs"
   ```

   The one variable by hand rather than `set -a; . ./.env; set +a`: sourcing
   that file puts every secret in it through the shell, where `$$` is the pid
   and a backtick runs a command, and an exported value then beats the file
   when compose reads it (docs/DEPLOYMENT.md, "`.env` is compose's input, not
   the shell's").

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
   DDOT's AADT layer from the District's open-data portal. **Maryland's arrives
   the same way, and phase 1 does not install it.** The pipeline records which
   agency published every count that reached a way — the segment table's
   `volume_source`, `volume_aadt` and `volume_year` columns — so a Maryland
   layer's influence on the published map is identifiable. It is not yet
   *excludable*: nothing in the export can withhold the segments a
   conditionally licensed source touched, so installing Maryland today means
   publishing a derivative that is influenced by it. Add the third pair once
   the waiver mechanism PLAN.md:31-34 describes exists; handoff.md section 7
   carries the row. docs/DEVELOPMENT.md, "Reference data", has what each one is
   and how the counts have to be normalised before they get here.

   **Optional, the agency street layers.** Add `--roadway-block
   /data/reference/inputs/dc-roadway-block/dc-roadway-block.geojson
   --baltimore-centerline
   /data/reference/inputs/baltimore-street-centerline/baltimore-street-centerline.geojson`
   to the same command to write `reference/roadway.json`: DC's and Baltimore's
   own posted speeds, lanes by direction, one-way streets, bike lanes and
   parking, which then take precedence over OSM's tags at the rebuild's
   classification (docs/DEVELOPMENT.md, "Agency street layers"). The files are
   fetched once with `scripts/fetch_agency_layer.py`, which refuses to fetch a
   layer twice, with the owner's go for each download. Without `roadway.json`
   the rebuild runs as before and logs `roadway.json is absent`; with it the
   log carries `agency street blocks: N of M blocks matched ways`, and each
   matched segment's `attr_sources` says which inputs came from the agency.
   Install it before the next rebuild, never after: the tiers change only when a
   rebuild runs. Reinstalling is idempotent. The owner's block corrections in
   fixtures/overrides name DC's blocks by `BLOCKKEY`, which the installer keeps
   with each block; a `roadway.json` installed by an earlier version lacks it,
   and the rebuild then warns that the corrections are not applied ("Log lines
   to read after a rebuild"), so reinstall it before the combined rebuild.

   `--extract` is the clipped `source.osm.pbf`, and the clipped one is right:
   the script reads ways out of it to decide which way ids fall inside a Census
   urban area, and a way outside the coverage box is a way this deployment does
   not route over. (`merged.osm.pbf`, the unclipped file kept beside it, exists
   for `valhalla_build_admins`, which needs boundary relations the clip cuts.)
   The crossings fixture is in the image and is copied for you. A later deploy
   that changes it has to copy it again — see "A deploy that changes the
   crossings fixture or loads access overrides" below.

   Run with `--data-root` alone it installs the crossings and exits non-zero
   naming whichever of the other two is still missing, which is the cheap way to
   check this step before spending step 8 on it.

7. **Load the access overrides**, now that the admin from step 4 has signed
   in (the loader names that account with `--actor`) and step 6 has installed
   the crossings the rows depend on. Every file in `fixtures/overrides/`, each
   dry run first, then `--confirm`, from the checkout (a file of block
   corrections only, `agency_blocks`, says it has no rows to load: the rebuild
   reads it from its image):

   ```sh
   docker compose exec -T api python manage.py load_access_overrides - \
       --actor <discord user id> < fixtures/overrides/<file>.json
   docker compose exec -T api python manage.py load_access_overrides - \
       --actor <discord user id> --confirm < fixtures/overrides/<file>.json
   ```

   Skipping this still builds a graph, without the owner's access decisions:
   on the 2026-09-26 file, the Key Bridge and 11th Street approaches stay
   barred and a mass ride detours. "About `--actor`" below says what the
   attribution is worth.

8. **Run the rebuild for real.**

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

   Budget eight hours, which is also the point at which the rebuild abandons
   itself.

9. **Restart the routers.** `valhalla_service` opens its tile extract once at
   start, so until this runs the four containers are serving the empty
   directories they started against.

   ```sh
   docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
   docker compose --profile offroad restart valhalla-offroad   # only where the off-road router runs
   ```

After that the weekly schedule carries it: Tuesdays 08:00 UTC, with the alert
windows in the table above watching that it keeps happening.

## What the stress calibration reads, and what it logs

Since the calibration (OWNER-DECISIONS 101-143) the classifier reads three
things beyond the tags, and none of them comes from the reference install:

- **The states, from the rebuild's own extract.** Each unposted way takes its
  state's speed default (the District's 20 mph, 15 in alleys; Maryland's and
  Virginia's 25/30/35 in urban areas). The states are built each run from the
  `boundary=administrative`, `admin_level=4` relations in the *merged* extract
  (`pipeline.states`; the owner, item 137: "From our OSM data
  (Recommended)"), not from the `jurisdiction` table, which stays the admin's
  and is empty on a fresh deployment. The merged extract holds only the three
  Geofabrik states, so the District, Maryland and Virginia close and West
  Virginia's and Pennsylvania's relations do not: their ways inside the
  coverage take the old class tables, and the log says so ("state WV: ... do
  not close and were dropped").
- **`fixtures/cbd/`** (the DDOT CBD boundary, the federal exemptions and the
  Architect of the Capitol's polygon) and **`fixtures/speed/`** (curated speed
  limits, OWNER-DECISIONS 131), both baked into the pipeline image
  (`COPY fixtures` in `docker/pipeline.Dockerfile`). A change to either is a
  rebuild-image deploy; there is nothing to reinstall.

The rebuild refuses, terminally (not retried), when the District, Maryland or
Virginia has no closed boundary in the merged extract, or holds no way:

    no state polygon for MD in the extract's admin_level=4 boundaries; the
    District's and the states' speed defaults (OWNER-DECISIONS 108, 112)
    cannot be applied, so the rebuild stops here

That is a broken or truncated extract, not a setting: re-fetch it
(`run_rebuild_now` after deleting `<DATA_ROOT>/extracts/merged.osm.pbf`
refreshes all three downloads) and look at the relation in OSM if it recurs.

**Adding a curated speed limit.** A row in a file under `fixtures/speed/`
(`routemaker.speed_corrections`): `osm_way_id`, `maxspeed` with its unit
(`"25 mph"`), and a `reason` quoting the decision and `evidence` naming the
extract and the way. Rows are validated when the rebuild loads them - a bad
row or two files disagreeing about one way fails the classify stage - and a
posted `maxspeed` on the way always wins.

**Log lines to read after a rebuild** (the classify and facility stages):

| Line | What to look for |
|---|---|
| `state polygons from .../merged.osm.pbf: DC, MD, VA in N s` | all three; 150-400 s on this host (384 s measured under memory pressure, peak 234 MB) |
| `state DE: 1 outer chain(s) do not close and were dropped` (and KY, NC, PA, TN, WV), then `state DE: no closed outer ring; not placed` | expected every rebuild: neighbouring states' relations reach the three-state merge only in part |
| `way states: DC 33,xxx, MD ..., VA ...; N of M ways outside every state; N s` | the District around 34,000 road ways; the outside count is the WV/PA edges |
| `divided roads: N carriageways in N s` | about 46,000 on the region, under 30 s |
| `curated speed limits not applied (posted, or no such way): [...]` | should not appear; a way listed was posted since or left the extract, and its row can go |
| `owner's block correction not applied (fixtures/overrides agency_blocks): block <BLOCKKEY> (...) is not among the installed agency street blocks; ...` | should not appear; the owner's correction (OWNER-DECISIONS 197) is not applied and DC's value is read. A `roadway.json` installed before the street blocks kept DC's BLOCKKEY says this for every block: reinstall them (`--roadway-block`, above) and rebuild. A block DC has dropped or rekeyed, or one on another street, wants its entry in fixtures/overrides corrected |
| `facility classes: ...; N CBD sidewalks barred to bicycles, N singletrack ways avoided` | about 2,000 CBD sidewalks; singletrack in the hundreds |

`manage.py check_weekday_trails` (acceptance A7) is **report-only**: it prints
the weekday trips along the weekend-car-free parkways in feet, metres in
brackets, and lists findings; it does not fail, because the owner has not
approved it as a gate.

## The route description needs the street names in the trace

`POST /api/route`'s `description` (item 220) is built from the plan's own trace.
It reads one attribute, `edge.names`, which `trace_attributes` returns on any
router version, so a deploy needs nothing: no rebuild, no migration, no
configuration. If the router answers a trace without names the description is
still built, with every street "unnamed road" or "unnamed path"; it is null only
if building it raised, which is logged as "the route description could not be
built" (look for it after a deploy that changes `core.routing.Piece` or
`routemaker.describe`). It makes no router call and no query; a plan that is
slow is not slow because of it.

## A deploy that changes the crossings fixture or loads access overrides

**The rebuild reads the installed crossings, not the image's.**
`ReferenceData.load` reads `<DATA_ROOT>/reference/crossings.json`, which only
`scripts/install_reference_data.py` writes, by copying the image's
`fixtures/crossings/potomac-anacostia.json`. Deploying a rebuild image with a
changed fixture therefore changes nothing by itself. The weekly task checks: it
hands the image's fixture to `LOAD_REFERENCE_DATA`, which compares the two as
parsed JSON and, if they say anything different, refuses the rebuild — terminal,
not retried, run row failed, nothing built or promoted — with a message that
gives the command below. So a missed reinstall now costs one refused Tuesday
and an alert, not a promoted graph built from last week's rows.

Reinstall, from the new rebuild image (with `--data-root` alone it copies the
fixture and exits non-zero only if `urban-areas.json` or `volume.json` is
missing, which on a running host they are not):

```sh
docker compose exec -T rebuild python3 scripts/install_reference_data.py --data-root /data
```

**When the change comes with access overrides, the order matters.** Access
overrides (`fixtures/overrides/`, loaded by the `load_access_overrides` management command)
can depend on crossings rows. The 2026-09-26 file is the example: it opens Key
Bridge's Virginia approaches to every rider, and only the new fixture's
`roadway_mass_ride_only` on Key Bridge keeps ordinary riders off its roadway. A
rebuild that runs with the rows loaded and the old crossings installed — either
the old rebuild image, or the new image before the reinstall — sends standard
and e-bike routes over the Key roadway. The guard above covers the new image. It
cannot cover the old one, which has no check. So:

1. **Deploy both images from the merged branch**, api and rebuild together —
   merge first, so the deploy does not drop work that is live but not on the
   branch. `docker compose up -d --no-deps --no-build api worker rebuild` after the build
   (`--no-deps`, or compose also runs `migrate` and may touch the services
   these depend on).
2. **Reinstall the crossings** with the command above.
3. **Load the override file**, dry run first, then `--confirm`:

   ```sh
   docker compose exec -T api python manage.py load_access_overrides - \
       --actor <discord user id> < fixtures/overrides/<file>.json
   docker compose exec -T api python manage.py load_access_overrides - \
       --actor <discord user id> --confirm < fixtures/overrides/<file>.json
   ```

4. **Rebuild**: `run_rebuild_now` ("Firing a rebuild by hand" above), then
   restart the routers.

Do steps 1 to 3 together, and all of them before the next Tuesday 08:00 UTC run
(`WEEKLY_REBUILD_CRON`), which fires on its own and promotes whatever is in
place. Never load the rows while the old rebuild image is still deployed.

**The deploy of the traffic and hills sliders (PUBLIC-DIALS, 2026-09-27)** is
one of these. Its fixture drops the `ordinary_ride_penalty_way_ids` column
(the owner retired the 11th Street penalty), so step 2 is required: the new
rebuild image refuses an installed copy that differs, and one that still has
the column is refused by name (`variants.MalformedCrossingRow`). Step 3 loads
`fixtures/overrides/2026-09-27-owner-stress.json`, the owner's curated stress
tiers, which the owner approved for loading on 2026-09-27 ("Yes, load it"):

```sh
docker compose exec -T api python manage.py load_access_overrides - \
    --actor <discord user id> < fixtures/overrides/2026-09-27-owner-stress.json
docker compose exec -T api python manage.py load_access_overrides - \
    --actor <discord user id> --confirm < fixtures/overrides/2026-09-27-owner-stress.json
```

Its stress rows name ways the 2026-09-26 access file opens (the 11th Street
landing), so that file is loaded first if it is not already.
`fixtures/overrides/2026-09-28-owner-beach-drive-nw.json` (car-free Beach
Drive NW) is loaded the same way at this deploy, after the stress file: the
owner approved it on 2026-09-28 ("Yes, load it").

The rebuild of step 4 builds four graphs, the weekend one among them, and needs
the fourth router this deploy adds ("The weekend graph (a fourth router)"
below). Before it, and before `up` can create them as root, make the router's
directories and start it once the rebuild has promoted a build:

```sh
sudo sh scripts/prepare_data_root.sh --env-file ./.env   # creates tiles/weekend and tiles/weekend/current
docker compose up -d --no-deps --no-build valhalla-weekend    # after the rebuild has promoted a build
```

The planner's front end changes too (the sliders, the ride-type dialog, the
facility breakdown): publish it as docs/DEPLOYMENT.md, "The public front end",
describes, after the api image, so the page never asks an api that does not yet
take the new fields.

**About `--actor`.** The rows are attributed to the account named by the
Discord user id on the command line. The command checks that the account exists
and is an active instance admin, but nothing authenticates the person typing:
anyone with `docker compose exec` on the host can name any admin. That is the
same trust boundary as the rest of this document, and it departs from
`run_rebuild_now` and `rollback_rebuild`, which record no actor. Every audit
entry the command writes says so in its `detail` ("named on the command line,
not authenticated"). On a fresh host the account exists only after that admin
has signed in once (`BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` makes the first one;
docs/DEPLOYMENT.md, "Adding a second instance admin"), so on a fresh host the
load is step 7 of "First rebuild on a fresh host", after the first sign-in and
the first install, which copies the new fixture.

Two `--confirm` runs at the same moment can both create the rows: there is no
lock and no unique constraint. The rows are identical, so the result applies
the same way, but delete one of each pair in the admin (below).

**Undoing a loaded row.** `approved` is read-only in the admin, so a row cannot
be un-approved there. Delete it: in the admin under Overrides, or with the
delete action on a selection. Both deletions are audited as `delete` with the
actor who clicked. The graph changes on the next rebuild, not before — the
running routers keep the access they were built with. Rerunning the loader on
the same file creates the deleted rows again, so after a deliberate delete,
change the file too (remove the row, in a reviewed commit). To take back a
crossings change, revert the fixture, deploy, reinstall and rebuild, in the same
order as above.

## The weekend graph (a fourth router)

The owner's "Build the weekend graph" of 2026-09-27: `valhalla-weekend` serves
the standard graph's weekend twin (`pipeline.variants.Variant.WEEKEND`), where
the roads OSM closes to motor traffic for the weekend (Beach Drive in
Montgomery County, Sligo Creek Parkway, Little Falls Parkway, parts of Beach
Drive NW; 19 ways in the DC box) are off-road paths at tier 1. A weekend ride
on a preset whose graph is the standard one routes on it; the e-bike and
no-trail graphs have no twin. If the weekend router does not answer, the api
plans the ride on the standard graph and the answer's `variant` says
`standard`, so a stack without it degrades rather than failing. One call to it
may take at most 15 s (`routing.WEEKEND_TIMEOUT_S`) and a failure is remembered
for a minute (`WEEKEND_FAILURE_TTL_S`), so between the deploy and
`up -d valhalla-weekend` - when the name does not resolve and each attempt
cost 2.5 s - one weekend ride a minute pays for the failure and the others go
straight to the standard graph, with one WARNING a minute in the api's log.
`docker compose restart ... valhalla-weekend` exits 0 and does nothing for a
service with no container yet: `up -d valhalla-weekend` is what starts it.

The first rebuild that builds four graphs is the first that has a weekend
build at all, so `rollback_rebuild` after it goes back on the other three and
withdraws the weekend graph - no `current` link, no settings row - which is
the deployment before that rebuild; its dry run says so, and says to stop
`valhalla-weekend` rather than restart it ("Rolling back a rebuild", below).

Until the first four-graph promotion there is no weekend settings row, so a
plain `docker compose up -d` that starts `valhalla-weekend` on its empty
directory costs nothing: the api plans weekend rides on the standard graph
until a weekend build has been promoted.

What it costs, measured on 2026-09-27. On the DC box graph
(-77.22,38.78,-76.90,39.02) the weekend tile build took 530-568 s against the
standard graph's 549-555 s, and writing its extract about as long as any
other variant's. The first live build (2026-09-25) took 21 min for the
standard tiles, 7 min for no-trail and 20 min for e-bike, so the weekend
graph adds about 20-25 minutes to a rebuild of about four hours on a quiet
host, and much more on a loaded one (a box weekend build took 2365 s at load
20-30 against 530-568 s quiet), which is why the rebuild's limit is now 8
hours. On disk it is another build directory of about 1.1 GB - `tiles.tar`,
503 MB, and the loose `tiles/` it was made from, which is kept - beside each
promoted build and each one retained. Resident memory is the standard
router's again: the live standard router sat at 239-387 MiB and no-trail at
80-188 MiB when read; the box routers after a trip set were 74-199 MiB. Its
compose limit is 2 GB like its siblings, which puts the sum of limits at 29 GB
on a 12 GB host: `scripts/check_compose_limits.py` still checks against its
32 GB figure. On this host the limits are not a reservation, and one of them is
reached: the live rebuild container ran at its 8 GiB limit (`memory.peak`
8589934592, `memory.events` max 12060, no OOM kill), relying on reclaim; the
routers' share is small (the weekend one 0.1 GB on weekdays, 0.3-1 GB at the
weekend). Steady state is about 8 GB and a Tuesday rebuild takes the host to
about 15 GB, into swap - an open owner question (PLAN.md:293's 32 GB).

On weekdays the weekend router is idle; restart it with the others after a
promotion (below).

## Contraflow on the no-trail graph: what to check after a rebuild

From the rebuild that carries OWNER-DECISIONS 192 (2026-10-02), the no-trail
graph - Mass Ride, and any ride with trails off - gives a one-way street to a
bicycle with the traffic only. The standard, weekend and e-bike graphs keep
contraflow, and Group Ride with trails on may use it (item 193). Nothing is
configured: it is built into the no-trail extract by the `inject_tags` stage, so
it needs no setting and no restart beyond the usual one after a rebuild.

What an operator can see:

- The no-trail extract carries `oneway:bicycle=yes` on every non-trail one-way
  (about 137,500 ways in the 2026-09-25 region extract), where the other
  extracts carry whatever OSM says. That is expected; the tiles are not
  noticeably larger.
- On the District's contraflow streets (R Street NE, 8th Street NW, M Street NW,
  11th Street NW and the like: 192 ways, 16.0 miles in the region extract) a
  Mass Ride route runs with the traffic. The same trip on Default or Group Ride
  may run against it on the lane. A Mass Ride that detours around a one-way
  street where it used to ride the contraflow lane is this, not a fault.
- The map and the stress tiles are unchanged: the lane still draws as a lane and
  keeps its tier, because both come from the way's own tags.

To check the code against a source extract without a graph build, from the
repository root (before a rebuild, or after a new clip):

```sh
export DATA_ROOT=/srv/routemaker/data          # the deployment's, as in .env
PYTHONPATH=src python scripts/contraflow_census.py "$DATA_ROOT/extracts/source.osm.pbf"
```

It reads the source clip, not a built variant extract or a graph: it re-runs
`variants.inject` and the transform on the source's tags, so it says what the
next build will do with that source, not what the last build did. For each
one-way it asks the transform for the standard reading, the same tags without
their bicycle conditionals, and (non-trail ways) the no-trail reading. It prints
how many ways have contraflow on the standard reading, by cause, and how many
still do on the closed one. "Still open after the closure" must be 0, and so
must "shut to the traffic direction as well". It takes about four minutes and
writes nothing.

## Bicycle closures in the tiles: before, during and after a rebuild

Singletrack (OWNER-DECISIONS 90, 91, 111) is closed to bicycles on every graph,
and so is OSM's own `bicycle=no`. Until the rebuild after 2026-10-03 neither
held on a way with a mountain-bike rating: Valhalla's C++ parser (3.5.1 to 3.9.1) reads
`mtb:scale`, `mtb:scale:imba`, `mtb:scale:uphill` and `mtb:description` after
the Lua transform and reopens the way from any of them, so 753 singletrack ways
(286.6 mi [461.3 km]) and 27 rated OSM closures stayed routable while every Lua
check passed (reports/SINGLETRACK-DIAG-r0). `lua/graph.lua` now strips the
ratings from whatever upstream's transform leaves closed in either direction.
Three checks stand between a change to that and a rider on singletrack.

**1. Before the go: the preflight.** On the commit being deployed, from the
repository root on the host:

```sh
scripts/check_tile_build_access.sh
```

It builds a 27-way extract with the pipeline image's own
`valhalla_build_tiles` and the checkout's `lua/`, serves it on loopback and
checks each way's bicycle access, direction by direction, then reads the same
tiles through the rebuild's closure gate. Local image only (`--pull never`), no
network, 1 GB, a 10-minute cap, the repository read-only; about 2 s. Exit 0:
every closure held. 1: a case failed, and the line says which. 2: the image has
no Valhalla. Run it on any deploy that touches `lua/`, `valhalla/` or the
pipeline image's Valhalla version.

The same test runs under pytest as `tests/test_tile_build_access.py`. It
**skips** where the Valhalla binaries are not on `PATH`, which is CI and every
development checkout, so a green CI run says nothing about it. Set
`ROUTEMAKER_REQUIRE_TILE_BUILD=1` to force it: a missing binary then fails the
run instead of skipping. That is the documented way to run it inside the
pipeline image, and the script sets it.

**2. During the rebuild: the closure gate.** VALIDATE, after the tile build and
before the swap, reads a sample back from every staged graph: up to 40
singletrack ways and up to 20 rated OSM `bicycle=no` ways, spread evenly by way
id. It asks each graph once, with a one-shot pedestrian `valhalla_service
locate`, and reads `access.bicycle` on the probed way's own edges. Pedestrian,
because a bicycle locate finds no edge on a closed way, which a missed snap
also produces. Each read has its own 120 s timeout inside the rebuild's budget;
the four take a few seconds in all. The rebuild fails at VALIDATE, and **does
not swap**, if:

- any graph is open to bicycles on any probed way: "the weekend graph is open
  to bicycles on 3 of 60 ways it must keep closed ..., e.g. way 810382238".
  Something reopened them after the transform. Do not swap by hand; run the
  preflight on the deployed commit and read `lua/graph.lua` and
  `remap.strip_ratings_if_closed` against the Valhalla version in the image.
- a graph that keeps trails (all but no-trail) found **none** of the probed
  ways: "has no edge on any of the 60 bicycle-closure probes, so the read
  tested nothing". The probes are no longer on the graph's ways: an extract
  that changed shape, or a locate that answers differently.

The rated OSM closures are chosen narrowly: `bicycle=no`, `foot` not `no`, an
`mtb:*` key, and none of the keys upstream lets open a direction over
`bicycle=no` (`bicycle:forward`/`:backward`, `vehicle:forward`/`:backward`,
`oneway:bicycle`, `bicycle:conditional` and its `:forward`/`:backward` forms,
any `cycleway*` key, `bicycle_road`, `cyclestreet`, `service=driveway`), and
never a bridge the crossings fixture rules on. The
gate writes its probes to `<DATA_ROOT>/rebuild/reports/bicycle-closure-probes.csv`
and every singletrack way id to `singletrack-ways.txt` beside it, for step 3.

**3. After the swap and the router restart: the probes.** In `rebuild`, which
has the script, the reports and the routers' addresses:

```sh
docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py locate
```

The gate's probes against the four **serving** routers, one pedestrian locate
each. Expect `ok` on every line. Every router but no-trail finds most of the
probes; no-trail drops trails, singletrack with them, so it finds only the OSM
closures that are not trails (7 tracks in the 2026-10-03 extract: "7 found,
ok"). `OPEN:` lists ways a bicycle may use; `FOUND NONE` on a router that keeps
trails usually means it was not restarted onto the new build. Then two trips,
planned through the api as the planner plans them and map-matched on the router
that served them. `--host` is the first name in the deployment's
`DJANGO_ALLOWED_HOSTS`:

```sh
docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py trip \
  --preset default --from=-77.0063,38.8973 --to=-76.6158,39.3074 \
  --avoid-ways /data/rebuild/reports/singletrack-ways.txt --host "$HOST"
docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py trip \
  --preset mountain-goat --from=-77.3168,38.8984 --to=-77.3318,38.8798 \
  --avoid-way 810382238 --host "$HOST"
```

- Union Station to Penn Station on Default: **0 mi on singletrack**. Before the
  fix this probe measured 1.27 mi [2.04 km] of it on the live routers
  (SINGLETRACK-review-r1; that day's answer came from the weekend graph), in
  the Patapsco valley. The route is about 56 mi; expect it to move to roads and
  paved trails there.
- Mountain Goat, end to end along the Cross County Trail's way 810382238
  (`mtb:scale=2`, singletrack): **0 mi on that way**. Before the fix it rode
  1.00 mi [1.61 km] of it.

Each prints its distance and the distance on the ways to avoid, and exits 1 if
that is more than nothing. Each `trip` is an ordinary signed-out request to
`POST /api/route`, so it writes one rate-limit row and counts against the
api's per-client limits like any anonymous request ("The public routing API").

What the strip changes besides access, so it is not mistaken for a fault:

- **A way closed in one direction only is held to that.** `bicycle:forward=no`
  or `bicycle:backward=no` keeps its open direction open and its closed one
  closed, as upstream's transform reads it. With the rating left on, the
  parser reopened the closed direction, which stock Valhalla still does. A
  one-way open in its own direction keeps its rating: the parser keeps its
  reverse closed anyway.
- **The rating is also a surface.** The parser classes an edge with a rating as
  surface `path`: an open dirt path rated `mtb:scale=2` is `path`, unrated
  `dirt`. Where the rating is stripped the edge is classed by its `surface`
  tag. A way open both ways, or a one-way open its own way, keeps its ratings
  and its class: the C&O towpath above lock 21 (`mtb:scale:imba=0`, `dirt`)
  and the Green Loop Trail (one-way, `mtb:scale=3`, asphalt, `path`) are
  unchanged.
- **An untagged footway with a rating is closed**, as every other untagged
  footway is: way 481109137 (concrete, `mtb:scale=0`) was the one such way in
  the region, open only through its rating.
- `rm:no_bicycle` (singletrack, CBD sidewalks) writes `bicycle:forward=no` and
  `bicycle:backward=no` as well as `bicycle=no`, so no directional grant
  (`bicycle:forward=yes`, `oneway:bicycle=no`, `cycleway=opposite*`) reopens a
  direction. The NO-BIKE-PATHS rules get that for free by using the same mark.

## Best order needs the routers restarted once (OWNER-DECISIONS 449)

"Best order" (`POST /api/stop-order`, `core.stoporder`) asks each router for a riding-time matrix,
Valhalla's `sources_to_targets`, which the routers serve only once their config lists it in
`loki.actions` (`valhalla/valhalla-*.json`, from `scripts/build_valhalla_configs.py`). The configs
are read when a router starts, so after deploying the release that adds it, restart the routers once,
as after a rebuild (below); the beta's CD restarts them itself when a `loki` key changes. Until then
nothing fails: each press orders the stops by straight-line distance, the answer's `by` is
`straight_line`, the page says the router's riding times were not available, and the api logs "the
<variant> router gave no riding-time matrix" at WARNING (the variant and the router's error only,
never the points).

What one press costs: one matrix call (at most 26 by 26 points, far under `max_matrix_location_pairs`
of 2,500), bounded on the api by `MATRIX_TIMEOUT_S` (20 s; 15 s on a weekend or off-road router) inside
a 25 s budget, plus at most a few seconds of ordering in the worker (about a quarter of a second up to
13 stops; new local-search starts stop after 3 s). It takes a routing slot and counts toward the
per-client 60 requests a minute like a route, and the route the page asks for after a reorder counts
again, so heavy reordering can meet a 429 sooner. As with `/route`, a matrix the api gave up on keeps
running on the router until it finishes: the slot bounds the api's workers, not the router's. That is
why a ride past 93 mi (150 km) of straight line is ordered by straight line without asking the router
(`LONG_SPAN_M`, the route API's long-ride line): a matrix over that span is the long ride's search
many times over. Its time and memory on a real router have not been measured; measure one 25-point
matrix at about 90 mi (145 km) before relying on it near that line.

The nearest water, restroom or Metro search (`POST /api/nearest`, `core.nearest`) asks the same
`sources_to_targets`, one row of at most 10 places, and needs the same one restart; until then it
answers by straight line (`by` is `straight_line`, the page says so) and the api logs "the <variant>
router gave no distances to the nearest places" at WARNING, with no points. It has the same slot,
time limits and per-client 60 requests a minute as Best order and `/route` (one budget: a search and
the route a Ride here then plans count twice), and a place over 93 mi (150 km) away is measured in a
straight line without asking the router.

## After a rebuild: restart the routers

**`valhalla_service` does not reload tiles.** It opens `mjolnir.tile_extract`
once at start and serves that graph for the life of the process, so replacing
the `current` symlink promotes a build the running containers cannot see. The
swap is complete in the database and on disk, `valhalla_upstream` names the new
build id, and the four routers keep answering from last week's tiles until they
are restarted:

```sh
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
docker compose --profile offroad restart valhalla-offroad   # only where the off-road router runs
```

Nothing in the rebuild does this, and there is no check that notices it has not
been done: the symptom is a deployment whose routes disagree with its own
segment table, which reads like a conflation bug rather than a missed restart.
Run it after every successful rebuild and after a rollback, which moves the same
symlink back. Then run the post-swap bicycle-closure probes ("Bicycle closures
in the tiles", step 3): their `locate` run is also the quickest check that each
router is serving the new build.

The restart is a few seconds of 502s per variant, taken one at a time. Starting
the new containers against the new build before stopping the old ones — the
blue/green arrangement the plan describes, which would make the swap invisible
to a request in flight — is phase 2; it is recorded in the handoff rather than
built here.

### The DC-against-OSM discrepancy report

Each rebuild writes it for the owner (OWNER-DECISIONS 191: "report the
discrepancies when you see them"), from the overlay it classified with, to
`${DATA_ROOT}/rebuild/reports/dc-osm-discrepancies.md` and `.csv` on the host:
every District way where DC's Roadway Block and OSM disagree, by type, whether
the District's value was applied (item 190) and, where not, why - the
not-applied items summarised by reason, the owner's overrides (item 197) listed
in full, every item in the CSV. Nothing needs running; the rebuild log says
"DC-against-OSM discrepancy report: N items on M ways, written to ...". It
replaces last week's. A failure to write it is a warning in the log and never
fails the rebuild. Nothing in it is for importing into OSM (CC BY 4.0 against
ODbL). docs/DEVELOPMENT.md, "Agency street layers", has what it lists.

### AADT smoothing, named corridors and the override re-match

Three more reports land beside the discrepancy report, in
`${DATA_ROOT}/rebuild/reports/`, each replaced by every rebuild. Like it, a
failure to write one is a warning in the log and never fails the rebuild.

- `override-rematch.md` and `.csv` (OWNER-DECISIONS 282): every approved override
  row whose OSM way is missing from the extract, and what became of it:
  `rematched` (re-pointed at the ways that now stand for it, by stored geometry
  and street name, only when unambiguous), `covered` (those ways already carry
  the same row), `failed` (left unapplied, with the reason; the appliers still
  count it unmatched), plus `drifted` rows whose way is present but no longer
  looks like the one the row was written for. The log line is "override
  re-match: N rows, ...". A row typed into the admin has no fingerprint and can
  only fail.
- `aadt-smoothing.csv` (285, 296, 303): one line per traffic count the street's
  median replaced: the agency's count, the median the link was classified on,
  the window (ways and length), whether a volume gate lay between them, and the
  link's tier against the tier on the agency's count. The log line is "AADT
  smoothing (400 m, ...): N of M counts replaced".
- `named-corridors.md` (284-286, 294-296; and Connecticut Ave NW, 409, 411): every way an entry of
  `fixtures/corridors/` took, its tier before and after, the exempt ones and why,
  and any entry that matched no way (also a warning in the log: the extract's
  geometry moved, or the file is wrong).

**What smoothing changes, and what it does not.** Only the link's volume gate
reads the median, and it only ever lowers a count (303: "Keep it LTS 4, and only
lower ratings. In most cases, the smoothing is probably bunching by the
intersection. Given that our routing is a sum of intersection stress and route
stress, we don't want to double count."). `segment.volume_aadt` stays the
agency's count, and `segment.stress_unsmoothed_tier` keeps the tier on that
count where smoothing lowered the link; the junction model reads the greater of
the two tiers and the agency's count, so the volume bunched at an intersection
is charged there and only there. On a table from before the column the junction
reads `stress_tier` alone, until the next rebuild.

**Vetoing the smoothing.** The owner can veto it (296, as recorded: "a
data-quality fix, not a rule change; the owner can veto it"). The switch is `RebuildContext.smooth_volume` in
`src/pipeline/run.py`, `True` by default. It is deliberately not an environment
variable: it is the owner's decision, so it changes in a reviewed commit. To flip
it, set the default to `False`, commit, rebuild the pipeline image
(`docker compose build rebuild`, or the release that carries the commit), and the
next rebuild classifies every link on the agency's count; `aadt-smoothing.csv`
is then header-only. Undo it the same way.

**A missing corridor folder fails the rebuild.** `routemaker.corridors.load`
refuses a missing `fixtures/corridors/` (CLASSIFY_STRESS fails with
`CorridorRefused`), because the image copies `fixtures/` and its absence means a
broken image; the owner's corridor ratings would otherwise vanish without a
word. A folder with no file is a warning.

**Rebuild checklist: Harford Road (decision 282a).**

- [ ] Until the owner approves loading
  `fixtures/overrides/2026-10-01-owner-baltimore-facilities.json` and deletes the
  database's stress row for way 424993005 in the admin, the rebuild reports
  stress 424993005 as `failed` in `override-rematch.md` and leaves the Harford
  Road row unapplied. That is expected, not a fault: the generic re-match
  declines it because the junction was redrawn, and the re-point to ways
  1562097553, 1562097555 and 1562097556 is in the file, waiting for that
  approval. After it: load the file (`load_access_overrides`, dry first, then
  `--confirm`, as in `fixtures/overrides/README.md`), delete row 424993005 in the
  admin, and the next rebuild applies the three new rows.

## Deployment actions

- Add a `check_operations` cron entry, or point an existing monitor at it.
- **Schedule a nightly EBS snapshot of the data volume.** Nothing in this
  repository takes one, and until the plan's S3 upload is built the nightly
  `pg_dump` lives on the same volume as the database it dumps — so a lost
  volume is a lost deployment, dumps included. The snapshot is also the only
  thing that covers the tiles, the certificates and the collected assets, none
  of which are in any dump. "Restoring one" above is the database half;
  restoring the volume is the host's own procedure.
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

## After a host restart: the postgis bind race

A Windows reboot, a `wsl --shutdown` or a Docker Desktop restart can start the
containers before the WSL bind mounts behind them are ready (four races so far:
2026-09-29 twice, 2026-10-02 and 2026-10-03). `postgis` then finds an empty directory where its data
directory should be and initialises a **new, empty cluster**: the api answers,
migrations and segments are gone, and nothing says why. The real data directory
on the host is untouched. Other binds fail the same way (a router with no tiles,
caddy with no Caddyfile). Check before anything else, with api and worker
stopped so nothing writes into an empty cluster:

```sh
docker compose stop api worker
docker compose exec -T postgis psql -U routemaker -d routemaker -At \
    -c "select count(*) from django_migrations" </dev/null
```

The count is the number of applied migrations: **69** with the NO-BIKE-PATHS migration (68 on 2026-10-02, core at
0009); anything else, an error included, is the race. Recover in this order,
postgis first:

```sh
docker compose up -d --no-deps --no-build --force-recreate postgis
# check again: django_migrations 69 (68 before the NO-BIKE-PATHS migration), and the live segment count as last seen
docker compose exec -T postgis psql -U routemaker -d routemaker -At \
    -c "select count(*) from django_migrations" </dev/null
docker compose exec -T postgis psql -U routemaker -d routemaker -At \
    -c "select count(*) from live.segment" </dev/null
docker compose up -d --no-deps --no-build --force-recreate \
    caddy valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend \
    photon api worker rebuild
```

**Never name `valhalla-offroad` in an `up` on the small host** (the 10 GB WSL
machine, or the beta). Naming a service in `up` starts it whatever its profile, so
it would put a fifth router in memory there; and before the first rebuild that
builds it, Docker would create `${DATA_ROOT}/tiles/offroad` as root for its bind,
which the rebuild (uid 10001) then cannot write. Where it does run, start it
after the routers above with `docker compose --profile offroad up -d --no-deps
--no-build --force-recreate valhalla-offroad`.

**Never a plain `docker compose up -d` here.** Without `--no-deps` it starts
`migrate` against whatever postgis has, which on the empty cluster creates a
fresh schema there, and without `--force-recreate` a container whose bind came
up empty keeps it. The same restart kills any running job: a rebuild or a backup
interrupted by it sits as `doing` (Wedged jobs, below: `unwedge_job`), and one
killed during its swap may need "A `SwapUndoIncomplete` alert" below. Never
force-kill Docker Desktop and never use "Reset to factory defaults": the first
leaves stale sockets that stop the next start, the second deletes the images
and volumes.

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

It is not only the rebuild. `worker` runs the same Procrastinate worker on the
maintenance queue and takes the same SIGKILL at the end of the same 60-second
grace, so a `nightly_backup`, a `membership_sweep` or a
`degraded_guild_sweep` killed mid-run leaves a `doing` row of its own. Each of
those carries a queueing lock, so the wedged row blocks that task's next tick
the same way the rebuild's blocks Tuesday's — and the task goes stale on its
own window (26 hours for the backup, 12 for the membership sweep) with nothing
else to say why. The repair below is the same command with the same argument.

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
  task, and a sync task body runs in a thread, so a worker hours into a
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
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
docker compose --profile offroad restart valhalla-offroad   # only where the off-road router runs
docker compose up -d --no-deps --no-build --force-recreate api worker
docker compose exec -T api python manage.py predraw_stress_tiles
```

**Recreate `api` and `worker` after a rollback** to a table with fewer columns.
Each process remembers, for its life, that the live segment table has the
facility, adjustment and road-trait columns (`routing._has_facility_columns`,
`_has_adjustment_columns`, `junctions.has_trait_columns` cache a True). Rolled
back to a build from before those columns (20260927 and earlier), every route
query still names `seg.car_free_when` and `facility`, nothing catches the
database error, and every route answers 500 until the processes start again.
`--force-recreate` with `--no-deps --no-build` starts fresh processes on the
same images and touches no other service; a `restart` would do too, but the
recreate is the form the rest of this page uses. Rolling forward again (a
rebuild that adds the columns back) needs no recreate: the cached False is
re-checked.

The last line draws the stress tiles of the table put back: the pre-draw after
the rolled-away rebuild's swap cleared that table's tiles from the cache, and
until they are drawn again every tile is drawn on request through the api's
one draw slot, and a street-level screen takes 20-30 s to fill ("The stress
tiles", above).

**In `rebuild`, not in `api` or `worker`.** The command rewrites the promotion
symlinks under `settings.TILES_DIR`, which is `/data/tiles` in all three Django
services, and only `rebuild` binds it read-write. `api` binds
`${DATA_ROOT}/tiles` there read-only for the operations page's free-space line,
and `worker` does the same for `check_operations`. Run in either, the command
refuses — on the dry run as well as on `--confirm` — with a write probe of every
variant's directory, naming the directory it could not write and the container
to use, and nothing is renamed or moved. (A deployment with no previous build
to go back to says that first: it is true in every container.) `rebuild` binds
the tiles read-write, along with `elevation`, `extracts`, `reference` and its
own work directory, under `/data` with `DATA_ROOT=/data`, so the paths it
resolves are the ones the swap wrote.

**The order is tiles, settings rows, schema.** Every variant's `previous`
becomes `current`, then the settings rows are rewritten in one transaction, and
the schema rename comes last. The rename takes `ACCESS EXCLUSIVE` on the live
segment table, and any API request reading segments can hold that off; if it
cannot get the lock in its five attempts the command raises `SwapLockTimeout`
having put the tile links and the rows back, and neither the live nor the
retired schema moved. The one thing it may have changed is a `staging` schema
left behind by a rebuild that failed at its swap: the rename needs that name,
so it drops that schema before it asks for the lock. That schema is the failed
rebuild's own output, and the next rebuild drops it anyway. Run it again at a
quieter moment. (It used to rename first, which made a later failure the
expensive kind: the undo then had to rename back, under the same lock, and
losing that race left last week's rows live under this week's tiles.)

The restart is part of the procedure, not an afterthought: `valhalla_service`
does not reload tiles at runtime, so until the containers restart they are
still serving the build that was rolled away from.

**A variant on its first build is withdrawn, not rolled back.** After the
first rebuild that builds four graphs, the weekend graph has no previous build.
The rollback goes back on the other three and withdraws it - its `current` and
`previous` links and its settings row removed - which is the deployment before
that rebuild. Its router is then **stopped, not restarted**: restarted on a
directory with no `current` it stays up and answers every ride "no suitable
edges". The command prints the lines to run in that case:

```sh
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike
docker compose stop valhalla-weekend valhalla-offroad
```

The api plans weekend rides on the standard graph while there is no weekend
settings row, and also if the weekend router answers "no suitable edges"
(170/171) where the standard graph places the same points, remembering that
for a minute. A later rebuild promotes the weekend graph again; `up -d
valhalla-weekend` after it starts the router.

It refuses unless **all three parts** of a previous deployment are there: a
settings row per variant naming a previous build (or, for a variant on its
first build, none, as above), a `previous` tile link per variant naming the
same build, and a retired schema with segments in it. The refusal names which
part is missing. The most common one is a first-ever
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

## A `SwapUndoIncomplete` alert: a half-restored swap

**What it looks like.** A failed `weekly_rebuild` whose message begins "the swap
failed and its undo did not complete, so this deployment is half-restored and
is not retried", on the operations page's run row, as a failed job there and in
`check_operations`. It is terminal on purpose: nothing retries it, because a
retry would promote over a deployment no component has a consistent picture
of. Nothing fixes it on its own either, and `rollback_rebuild` is not the tool —
see below.

**What state the deployment is in.** The swap is three steps — each variant's
tile links, then the settings rows, then the schema rename — and the rename is
the last step and one transaction. The undo only runs when a step failed, so
the rename either failed and moved nothing or never ran: **the schemas are as
they were.** `live` is still the build that was being served, the retired
schema (`live_old`) is still the one before it, and `staging` holds the build
that failed to swap. What may be wrong is only what the message lists after
"Still to put back by hand":

- *`<variant>`'s tile links* — that variant's `current` may name the new build,
  and its `previous` the build `live` describes.
- *the settings rows* — the `ValhallaUpstream` rows may name the new build.

After that, "As the swap found it" gives one line per variant — its `current`
and `previous` link targets and its row's two build ids, or `no link` / `no
row` — and that is the state to put back. It is the only record of it: the
swap overwrote `previous` and `previous_build_id` on the way through, so it
cannot be reconstructed from directory names.

The routers were not restarted by the swap, so unless one of them restarted
since, they are still serving the old build and the damage is in what the
*next* restart would load and in what the API believes it is serving.

**Why not `rollback_rebuild`.** It rolls back a *completed* swap: it would
retire the graph being served and promote `live_old`, two builds back. Its
pre-flight refuses anyway on a variant whose `previous` link and settings row
disagree — which is what a half-restored variant looks like — and that refusal
is correct.

**The repair, by hand, in `rebuild`** (the one container that can write the
tiles):

1. **Fix what failed first.** The message names the original error (a
   read-only or full volume is the usual one) and the reason each restore
   failed. A repair written onto the same broken volume fails the same way.
2. **Put each listed variant's links back** as "As the swap found it" says.
   Atomically, the way the swap writes them — a new link renamed over the old
   one:

   ```sh
   # current -> <build>        (and the same with `previous`)
   docker compose exec -T rebuild sh -c \
     'cd /data/tiles/<variant> && ln -sfn <build> current.new && mv -T current.new current'
   # previous -> no link
   docker compose exec -T rebuild rm /data/tiles/<variant>/previous
   ```

3. **Put the settings rows back**, if the message lists them, to the build ids
   the same lines give (`(empty)` is the empty string):

   ```sh
   docker compose exec -T rebuild ./manage.py shell -c "from core.models import ValhallaUpstream as U; U.objects.filter(variant='<variant>').update(build_id='<build>', previous_build_id='<previous or empty>')"
   ```

   A line that says `no row` means that variant had no settings row before
   the swap, so the one the swap wrote is deleted rather than updated:

   ```sh
   docker compose exec -T rebuild ./manage.py shell -c "from core.models import ValhallaUpstream as U; U.objects.filter(variant='<variant>').delete()"
   ```

4. **Check it agrees with itself.** The first command shows the links; the
   dry run reads the links, the rows and the retired schema together:

   ```sh
   docker compose exec -T rebuild sh -c 'ls -l /data/tiles/*/'
   docker compose exec -T rebuild ./manage.py rollback_rebuild
   ```

   After a repair it prints a target per variant — the `previous` build — or,
   on a deployment whose first rebuild this was, refuses with "no previous
   build to go back to". A refusal naming a variant whose links and row
   disagree means that variant is not back yet.
5. **Restart the routers** if any of them restarted while the links were
   wrong — it will have loaded the build that failed to swap:
   `docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`, and, where the off-road router runs, `docker compose --profile offroad restart valhalla-offroad`
   (see "After a rebuild: restart the routers"). Harmless if none did.
6. **Leave `staging` alone.** It is the failed build's output and the next
   rebuild's first stage drops it. Then rebuild — `run_rebuild_now`, or wait
   for the weekly one.

### Long calm plans, the target distance, candidates and loops (FOLLOWUP-LONG-CALM, items 256 to 271)

Planner-only: nothing to rebuild or migrate. The trail credit is gone, so the OPERATIONS notes above on
the credit's extra reads (a join over the traced pieces) no longer apply.

- **What a long calm plan is.** Trailmaxxing at 100 past 19 mi (30 km) of straight line and under the
  confirm span (93 mi, 150 km), not a loop. It has the long ride's budget (`routing.LONG_PLAN_BUDGET_S`,
  50 s in all, 47 s of router and traces, gunicorn's `--timeout` is 60 s) and takes the long ride's
  in-flight slot (`ratelimit.LONG_ROUTING_IN_FLIGHT`: one per client, one in the deployment) on top of
  its ordinary routing slot, so **only one runs at a time in the deployment**; a second from the same address is refused 429
  and one from another address 503 (both with Retry-After), with the long ride's words ("A long ride is
  already being planned"), as a long ride is. Its timed-out
  503 carries `code: long_ride_timed_out`, which a client must not resend unasked. To allow two at
  once, raise `LONG_ROUTING_IN_FLIGHT.total` (it is also the long ride's pool).
- **Router calls and time, measured** (the read-only forwarder against the live routers, idle host, one
  plan at a time, weekday off-peak; every plan is bounded by its deadline whatever its work):

  | Plan | Time | /route | /trace_attributes | /locate |
  |---|---|---|---|---|
  | Union Station to Baltimore Penn, default (1.6x) | 16.8 s | 28 | 31 | 125 |
  | Union Station to Baltimore Penn, 60 mi | 11.8 s | 36 | 23 | 79 |
  | Union Station to Baltimore Penn, 50 mi | 19.3 s | 52 | 19 | 115 |
  | Union Station to Baltimore Penn, 47 mi | 29.2 s | 62 | 30 | 251 |
  | The owner's ride, its own start and end, 60 mi | 13.9 s | 45 | 27 | 80 |
  | The owner's ride, its own start and end, 47 mi | 13.8 s | 37 | 12 | 62 |
  | Bethesda to Frederick, default (1.6x) | 9.7 s | 21 | 17 | 59 |
  | Alexandria to Annapolis, default (1.6x) | 20.3 s | 27 | 28 | 132 |

  After items 267-271 (the same harness): Union Station to Penn with no target 19.1 s (28 / 31 / 123),
  at 60 mi 18.1 s, the owner's ride at 60 mi 16.0 s, Alexandria to Annapolis 24.9 s; with a target
  below the router's own route the readings of the routes past it add time: Union Station to Penn at
  50 and 47 mi 34.3 and 35.7 s (`limited: "time"`, inside the deadline), the owner's ride at 47 mi
  24.2 s.

  A long plan's calls are: one /route for the whole trip and one /trace_attributes for its stress; for
  each leg a /route and a /trace_attributes; for each exclusion round of each searched leg a /route, a
  /trace_attributes and the /locate calls of its junctions (about 2 to 4 each); each seek proposal a
  /route and its reading; at the end one reading of the whole route's junctions. With a target distance
  below the router's own route there are up to 6 more whole-trip /route calls (the fit: 3 rungs and 3
  bisections, 0.5 s each warm, 3 to 4 s on a cold router for a 40 mi route and 33 s past 19 mi cold in
  the earlier probe: each is bounded by what is left of the budget, and none is started with under
  12 s left, `routing.FIT_MIN_S`), and then a reading (trace and junctions, 1 to 3 s each) of the
  route that fits and of each route found past the target within its 1.25x ceiling, up to 8 in all, for the
  choice past the target (`routing._past_target`, item 271); a reading that does not finish in what
  is left of the budget is not chosen.
- **Worst-case plan time.** The plan's deadline is 47 s from the request's arrival; no router call
  starts after it and every call's own timeout is what is left of it; the last 6 s are kept for the
  answer's traces and the whole route's junctions (`refine.LONG_FINAL_RESERVE_S`), and 3 s for the
  stress join and the answer (`ANSWER_RESERVE_S`), so a plan that runs its whole budget is answered at
  about 50 s, 10 s inside gunicorn's kill. The slowest measured is Union Station to Baltimore Penn, target 47 mi: 29.2 s (before items 267-271). A leg whose time share is
  under 6 s is not searched and keeps the router's route; the plan says so (`calm_search.long.skipped`,
  `limited: "time"`). Cold routers (graph tiles not in cache) are the risk: the 5 to 6 whole-trip and
  leg /route calls are first, and a cold 40 km route took 33 s on the earlier probe, which would leave
  the plan the router's own route and `limited: "time"`.
- **The table reads** are the trail seek's: one per leg, bounded by `TABLE_TIMEOUT_S`, 0.2 to 0.3 s
  warm, with `statement_timeout` set and reset as TRAILSEEK r1 left them; nothing new in the database.
- **Candidates (item 265)** add no router calls except one reading of the whole route (junctions across
  the joints) for each alternate of a long plan, 1 to 3 s each, and only with at least 6 s left
  (`routing.ALTERNATE_MIN_S`). A plan searched in one piece reads them as part of the search. At most 3
  more routes, each a whole body: the answer's JSON is up to four times larger (a long route's body is
  150 to 320 KiB measured, so four are up to about 1.3 MB); Caddy and gunicorn buffer it as
  before.
- **Loops (item 266)** ask for the way back up to 4 more times (every point, then every 2nd, 4th and 8th),
  each a /route, its reading and the whole loop's reading, inside 14 s (`refine.LOOP_BUDGET_S`); the
  search then runs as for any plan up to 19 mi (30 km) of straight line in all, and not at all past it.
  A loop is never a long calm plan, and its straight line counts the way back too, so a Trailmaxxing
  loop with a 9.5 mi out-leg answers `limited: "span"` with no calm search. That is as built, not a
  fault. A Mass Ride has no loop (the owner's choice, 298(4)).
- **Reading an answer.** `calm_search.long`: `legs`, `searched`, `skipped`, `stops` (legs per plan leg),
  `answered` (`legs` or `router`) and `per_leg` (each leg's length, LTS 4 and LTS 3 metres before and
  after, the cap it was searched under, the options it offered and why it stopped).
  `calm_search.target_distance_m` / `target_distance_set` / `ceiling_m` / `fits` / `over_target_m` /
  `fitted_at` say the rider's target (null: none), whether they set it, the ceiling the search kept to
  (1.25 times the target, or 1.6 times the router's own route with none), whether the route is within
  the target, how far past it it is, and the traffic position the first route was found at where the
  router's own route was past it. `limited: "target_distance"` with `fits: false` means no route
  within the target was found and the least stressful found is answered (item 267);
  `no_fit: true` goes with it (no route within the target found; false where one was, null with no
  target), and where not even one route was within the ceiling the least stressful of all those found
  is answered, flagged the same way (item 298(2)); `limited: "ceiling"` is different: the exclusion
  search stopped because its next round found only routes past `ceiling_m`, and the answer may well
  fit;
  `seek.whole_trip: "not_worth"` means a spliced trip's extra miles did not buy enough stress (268). `loop.fallback: "out_and_back"`
  means there was no other way back. `hills_seek.limited: "calm_first"` means the Hills slider seeks
  at the top of the stress slider: the stress-order search, a long calm plan and the target ran, and
  no climb search among the router's alternatives was asked (item 298(3)). `candidates` is null where there is one route.
- **Knobs** (all in code, none needs a restart beyond a deploy): `legsplit.LEG_TARGET_SPAN_M` (12 km),
  `legsplit.CLEAR_M`, `refine.LONG_MIN_START_S` (12 s), `LONG_LEG_MIN_S` (6 s), `LONG_SEARCH_SHARE` (0.7),
  `MAXCALM_STEPS` (15, 50, 50 m), `refine.ALT_MAX`, `ALT_OVERLAP`, `ALT_DIFFERENT_M`, `ALT_TOP_BAND_M`,
  `ALT_SECOND_BAND_M`, `LOOP_OVERLAP_OK`, `LOOP_OUT_AND_BACK`, `LOOP_THINNING`, `LOOP_BUDGET_S`,
  `routing.FIT_STRESS_LADDER`, `FIT_BISECT_STEPS`, `presets.DEFAULT_CEILING_RATIO` (1.6),
  `DEFAULT_CEILING_EXTRA_M` (a mile), `TARGET_CEILING_RATIO` (1.25), `refine.WORTH_DEFAULT` (5 m added
  per metre of LTS 3 saved) and `WORTH_OVER_TARGET` (2.5, past the target), and the effort model's
  constants (`routemaker.effort`).
- **Rollback.** Redeploying the previous image removes it all: the new request fields (`target_distance_m`,
  `system_weight_kg`, `loop`) would be refused as unknown by the older API (the schema forbids extra
  fields), so an older API behind a newer front end would answer 400 to a request that carries one;
  deploy the pair together.

## The dodge pass's load (FOLLOWUP-DEDODGE)

After the search and before the answer, a plan runs one pass that takes pointless side-street dodges
out of its route (`core.dedodge`). It runs on the answer's route alone (never on a loop, never on the
routes to choose from), so its bounds are per plan: at most 8 checks (`dedodge.MAX_CHECKS`), 5 s
(`BUDGET_S`) ending 6 s before the plan's own deadline, 8 s to a call, and none at all where less than
3 s is left (`dodges.limited` is `time`, or `checks` at the cap). Dodges under 50 m, unnamed ones under
60 m and straight runs are skipped without a call.

Each check is:
- 1 or 2 `/route` calls between the dodge's two ends (the second without headings, where the router finds
  no path facing the way the route goes);
- one `trace_attributes` of the **whole spliced leg**, not of the stretch: a plan of one leg is the whole
  route, 43 mi on Bowie to Annapolis and 58.6 mi on Union Station to Penn;
- that leg's junctions read again: `/locate` in batches of 50 nodes (`junctions.LOCATE_BATCH`), twice
  (the nodes, then the approaches of those without a signal), about 10 calls a check on a 58 mi leg.

So the worst case a plan is 8 x (2 `/route` + 1 long `trace_attributes` + about 10 `/locate`) inside 5 s;
then the answer reads its changed route once, as it reads any route, within the plan's deadline (outside
the 5 s). Measured against the pass off (the harness, live routers read-only): Union Station to Penn, 8
checks, 11 more `/route`, 8 more `trace_attributes`, 35 more `/locate`; Bowie to Annapolis at
Trailmaxxing, 6 checks, 15, 8 and 67; a short trip with one check, 1 or 2, 1 and 2 to 4. No knob needs
setting: `dedodge.BUDGET_S`, `MAX_CHECKS`, `MAX_EXCLUDES`, `MIN_DODGE_M`, `MIN_UNNAMED_DODGE_M`,
`TIE_RULE_ALL_PRESETS` and `TIE_STEP_M` are code constants. The last two are the rule the owner chose
in OWNER-DECISIONS 298(1): on every ride type, Default included, a dodge that avoids no more than 50 m
[160 ft] is taken out.

A **dodge result that varies with host load** is expected. On a busy host the pass can be starved
(`dodges.limited: "time"`, 0 checked), so the same request can come back with a dodge kept on one run
and removed on another. That is not a fault and not a rollback trigger.

## Deploying a planner and front-end release: rollback points and verification

A release that changes the planner and the front end, with no migration and no graph, is deployed
from t9, the worktree that serves the stack, one heredoc per call, with `</dev/null` on every docker
command. Below, `$REPO` is that worktree's path (set it first), and each snippet exports
`DATA_ROOT` with the value in its `.env`.
The order is: pre-flight, **rollback points**, fast-forward, the api image, recreate api and worker,
the front end last, then **verify**. Keep out of 07:00-07:30 UTC (the nightly backup) and away from
the Tuesday 08:00Z rebuild. Every step is still confirmed with the owner (OWNER-DECISIONS 293).

**0.1 Rollback points, before anything is built.** Nothing else names the live image or keeps the live
`index.html`. A `docker compose build api` leaves the old image dangling under no name, and the oldest
index backup may be two releases back. `L` is the short commit t9 is on:

```sh
cd "$REPO"; D=$(sed -n 's/^DATA_ROOT=//p' .env); L=$(git rev-parse --short HEAD)   # D: never exported
docker tag ghcr.io/macrophage87/routemaker-api:dev ghcr.io/macrophage87/routemaker-api:pre-rel-$L </dev/null
docker image inspect --format '{{.Id}}' ghcr.io/macrophage87/routemaker-api:pre-rel-$L </dev/null   # the live image's id
cp $D/frontend/index.html ~/rmdata/frontend-index-$L.html
grep -o 'assets/[^"]*' ~/rmdata/frontend-index-$L.html     # the live script and stylesheet
git rev-parse HEAD > ~/rmdata/t9-head-pre-rel.txt
```

The api build looks up its base image (`python:3.11-slim-bookworm`) on Docker Hub when that tag is
not in the local store, and that network use needs the owner's approval for the deploy, as
OWNER-DECISIONS 253 gave the last one.

Steps 1 to 4 are:
1. `git merge --ff-only` to the release commit, once the owner has pushed it;
2. `docker compose build api` (worker and migrate share the image);
3. `docker compose up -d --no-deps --no-build --force-recreate api worker`, with no job todo or doing;
4. the front end's build and publish (docs/DEPLOYMENT.md, "The public front end").

**The weekly-rebuild pause (OWNER-DECISIONS 355) is not in the api image.** `weekly_rebuild`
runs in the `rebuild` container, from the pipeline image (`routemaker-pipeline`), so steps 2 and 3
do not ship it. It takes effect only once that image is rebuilt and the rebuild container is
recreated with `WEEKLY_REBUILD_PAUSED=1` in `.env`, with no rebuild job todo or doing and after a
rollback point of its own:

```sh
docker tag ghcr.io/macrophage87/routemaker-pipeline:dev ghcr.io/macrophage87/routemaker-pipeline:pre-rel-$L </dev/null
docker compose build rebuild </dev/null
docker compose up -d --no-deps --no-build --force-recreate rebuild </dev/null
```

Until that is done the pause is not in force, and the Tuesday 08:00 UTC tick runs a real rebuild.
The fallback is `docker compose stop rebuild </dev/null`, run by hand, with the owner's OK, before
the tick (and `docker compose start rebuild` to undo it). Stopping it pauses the hand-fired
rebuilds too, and the operations page reports the rebuild stale eight days after its last
success.

There is no migrate, and never a plain `up -d`.

**5. Verify.** Run both scripts and keep their logs. `verify-release.sh` takes an optional base URL
(default `http://localhost`), prints PASS or FAIL per check, and exits with the number of failures:

```sh
~/rmdata/verify-pm.sh 2>&1 | tee ~/rmdata/rel-verify.log            # the standing checks
~/rmdata/verify-release.sh 2>&1 | tee ~/rmdata/rel-verify-release.log
```

`verify-pm.sh` checks none of the release's new features. `verify-release.sh` does, with read-only
probes only (anonymous POSTs to `/api/route` and GETs of the published front end). It is read-only
apart from the rate limiter's own counter rows (`rate_limit_window`), which every anonymous
`/api/route` request upserts; it writes nothing else to the stack, the database or the data root.
A 503 from the planner ("A long ride is already being planned", a rider's plan in flight) is
reported as RETRY, not FAIL, and does not count as a failure: run the script again. A probe that
expects route candidates fails when there are none (probes 1 to 3 print the count):
- Union Station to Penn Station at Trailmaxxing 100, a long calm plan: searched in legs, answered in
  the plan's legs, `effort_m`, `no_fit` null with no target, candidates whole routes ranked from 2
  with no stop the rider never placed, and the wall time, which must be under 50 s (it is printed at
  the end against the 47 s deadline);
- the same trip at a 60 mi target: the target echoed, `over_target_m` a number, `no_fit` a boolean
  and true only with `limited: "target_distance"`, `fits` agreeing with the overage, no candidate
  further past the target than the answer;
- Silver Spring to Farragut at the top of the slider: candidates whole routes, at most 3; with the
  Hills slider seeking, `hills_seek.limited: "calm_first"` and the calm search not skipped (298(3));
- a loop: `overlap_pct`, two legs, whole-loop candidates, no dodge pass; a Mass Ride asked for a
  loop stays point-to-point (298(4));
- Bowie to Annapolis on Default: `dodges` reported with the 50 m tie step (298(1)),
  `text_lanes_hidden` and `surface` in the description and the overview, and `unpaved` on every
  `stress_spans` entry;
- the hashed federal-land asset: 200, `immutable`, compressed, and named by the published front
  end's script.

The release's API changes are all additive for an older client: besides the fields above, every
`stress_spans` entry carries `unpaved` (true, false or null) and a section ends where the surface
changes (302), and `calm_search` carries `no_fit` and the `limited` code `"ceiling"`.

**Rollback**, front end first. The new front end sends fields that the older API refuses with 400
("Long calm plans ..., Rollback", above); the old front end works against the new API.

```sh
cd "$REPO"; D=$(sed -n 's/^DATA_ROOT=//p' .env); L=<the short commit saved in step 0.1>
docker run --rm --network none -u 10001:10001 -v ~/rmdata:/bk:ro -v $D/frontend:/out \
  docker.io/library/busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662 \
  sh -c "cp /bk/frontend-index-$L.html /out/.index.html.new && mv /out/.index.html.new /out/index.html" </dev/null
docker tag ghcr.io/macrophage87/routemaker-api:pre-rel-$L ghcr.io/macrophage87/routemaker-api:dev </dev/null
docker compose up -d --no-deps --no-build --force-recreate api worker </dev/null
```

If the pipeline image was rebuilt (the pause, above), roll it back too, but only with **no
rebuild job todo or doing**: a job the new code queued (`run_rebuild_now` passes the new `manual`
argument) fails on the old image with an unexpected keyword. Check, then roll back:

```sh
docker compose exec -T api python manage.py shell -c "from core.runs import jobs_in_flight; print(jobs_in_flight('weekly_rebuild'))"   # must print []
docker tag ghcr.io/macrophage87/routemaker-pipeline:pre-rel-$L ghcr.io/macrophage87/routemaker-pipeline:dev </dev/null
docker compose up -d --no-deps --no-build --force-recreate rebuild </dev/null
```

A job left todo or doing is unwedged or cancelled first (`unwedge_job`, above), not rolled back
under. The old image has no pause: remove `WEEKLY_REBUILD_PAUSED` from `.env`, and stop the rebuild
container by hand (with the owner's OK) if the pause must still hold.

The old hashed assets are still there, because the publish's `cp -n` never deletes. Roll back on any
of these:
- `/healthz` is not 200;
- a 5xx other than the documented busy or timed-out 503s, or a Traceback in a plan;
- a Default regression on verify-pm's Silver Spring to Farragut: no route, or more LTS 4 than its
  baseline;
- a long calm plan answered past 55 s, or a gunicorn `WORKER TIMEOUT`;
- api memory over about 1.5 GiB;
- a blank front end.

These are not triggers: `dodges.limited: "time"`, `calm_search.limited: "time"` on a long plan, the
long-pool 503 while another long plan runs, and `candidates` null on most trips.

## Paths bicycles may not ride (NO-BIKE-PATHS)

OWNER-DECISIONS 278, 280, 281 and 290 to 291. Nothing here is live until the
next rebuild; nothing is written to the live database or an override table.

**What a rebuild now closes.** `pipeline.trail_closures` marks a way
`rm:no_bicycle=<reason>` and the transform closes it to bicycles (the mark is
stripped, and the singletrack strip in `lua/graph.lua` covers a rated way). The
reasons are in `routemaker.trailaccess` (private, sac_scale, informal,
foot_designated, trail_visibility, hiking_route, natural_surface, park_path, mtb,
dismount), `routemaker.zoo` and the existing `singletrack` and `cbd_sidewalk`.
The rebuild log line "facility classes: ..." carries the count per reason.

**Five graphs.** The mountain-bike class (`mtb`) is closed on the standard,
weekend, e-bike and no-trail graphs and open on a fifth, `valhalla-offroad`
(`Variant.OFFROAD`), which Gravel and Mountain Goat ride (OWNER-DECISIONS
291(2)). It has no weekend twin and falls back to the standard graph, as the
weekend one does, when it is not promoted or not answering. Start it after the
first rebuild that builds it: `docker compose --profile offroad up -d --no-deps
--no-build valhalla-offroad`; a rollback that withdraws it stops it like the weekend one.
Limits: two workers inside 1536M (not 2G), so the swap-time peak is 32.0G of the
32G the compose check allows.

**The off-road router is behind the compose profile `offroad`.** A plain
`docker compose up -d` (and the force-recreate lists above, which name services
explicitly) does not start it, so a small host, such as the 10 GB WSL machine,
runs four routers as before. The rebuild builds and promotes `tiles/offroad`
whether or not the router runs (the tiles are built in the rebuild container, from
the same extract, and the graph is validated there), and the planner answers
Gravel and Mountain Goat on the standard graph, `variant: "standard"`, while the
router is not answering: no 500, no change in the request. The planner remembers a
failure for `WEEKEND_FAILURE_TTL_S` and tries again after. Where there is memory
for it (1536M of limit; the standard router sits at about 450 MB resident here, over 1.1 GB of tiles), start it with the
command above after the swap, and `restart` it after later rebuilds as the others.
A `restart` that names `valhalla-offroad` where it has no container fails ("no such
service", with or without `--profile offroad`) and restarts none of the other
routers on the same line, so the four-router restart never names it. Restart it on
its own line, `docker compose --profile offroad restart valhalla-offroad`, and only
where it runs.

**The Zoo.** `fixtures/zoo/` holds the polygon and the spur: the Harvard Street
NW entrance to the bike racks (OSM node 9827008403), seven whole ways, written
destination-only (`rm:destination_only`; `bicycle=destination` and
`access=destination`). A trip point inside the Zoo is moved to the racks and the
answer's `moved_points` says so.

**Display.** A trail-class way routing does not open to bicycles is
`map_class='barred'` and not drawn; the mountain-bike class stays `road` with the
tile property `mtb` (and `rough`), facility `none`. The front end draws an `mtb`
trail in no routable layer but in its own not-for-routes look: a thin
mid-grey line of fine dots from zoom 14, under the routable lines (OWNER-DECISIONS 452a,
superseding 452's hiding and 290(b)'s faint drawing; `stressStyle.js` `mtb-trail`,
`MTB_TRAILS_ROUTABLE`). Since 454 it draws only while the Map layers sheet's
"Mountain-bike trails" switch is on (off by default, kept per browser under
`routemaker.mtbTrails`), in every ride type; the legend has a row "Mountain-bike trail: not
used for routes" while it is on, and the road panel says the same whatever the switch.
After the deploy that ships 454, riders who saw the dotted trails see none until they turn
the layer on (Map layers, "Trails and terrain"). `rough` draws as any unpaved trail does. Routing closes the class
for every preset but Gravel and Mountain Goat. The segment
table has two new columns, `mtb_only` and `walk_bike`; the model's migration
(core 0010) is state-only.

**Walk your bike.** A `bicycle=dismount` connector under 500 ft (150 m), counting
the ways that join it, stays and the route description gets a `walk` entry;
longer ones close.

**NPS units.** Tag rules only. A per-park "paved and designated only" rule goes
in `pipeline.trail_closures.PARK_RULES` after that park's compendium has been
read, which needs the owner's approval as a fetch.

**The gate.** VALIDATE reads back up to 8 ways of each new reason from every
graph; the off-road graph is not held to `mtb`. `scripts/probe_bicycle_closures.py`
does the same after the swap and now reads the off-road router too.

## The rebuild bundle (wip/rebuild-bundle)

One deploy and one rebuild carry NO-BIKE-PATHS and the singletrack fix, the arterial
calibration, main's front end and log changes, the route chart, the z12-13 ride layer
(calm roads at 2 mi, roadside trails), the Mass Ride capacity map and the reversible-lane
and Connecticut Ave NW changes, the Connecticut lane override and the Dupont underpass, and
the Mass Ride map's own tiles, DC mask, border roads and zoom focus (OWNER-DECISIONS 391,
394-427; reports/REBUILD-BUNDLE-integration.md; the `reports/` named here are the project's review
reports, kept outside the repository), and, from fix round 2 (reports/REBUILD-BUNDLE-fix2.md),
the military-area closure (owner report 2026-10-05), South Capitol St at LTS 4 (432) and Veirs
Mill Rd (433), and, from fix round 3 (reports/REBUILD-BUNDLE-fix3.md), the narrower military
rule and the owner's reopenings (437, 437a-c).
Nothing in it is live until the rebuild promotes the new table.

Read the post-rebuild before/after with three changes in mind. 425 counts a block's
reversible lanes in each direction, so it can raise the tiers on 16th St NW, Canal Rd NW,
Clara Barton Pkwy, Chain Bridge Rd and Independence Ave SE/SW (no measurement of it is
recorded but Connecticut's, in docs/DEVELOPMENT.md). The military-area rule closes about
2,170 mi (3,490 km) of roads and paths inside bases region-wide (Quantico, Aberdeen, Fort
Meade, Fort Belvoir, Andrews and Patuxent River the most; Joint Base Anacostia-Bolling
about 68 mi (109 km) with the older Bolling outline it overlaps), so routes that used to cut
through one go round it. Inside a base only a numbered public road, a way signed for
bicycles (`bicycle=designated`), the Pentagon's listed streets and walkways (437.5) and the
owner's reopened ways (437.6, 437a-c, 438.2: Jeff Todd Way, Russell Rd, Saint Elizabeths Rd
SE and its side path, Pentagon Connector Road) stay open, about 41 mi (66 km) in all; a few
signed paths only the base reaches stay closed (438.1, 439: until the community confirms
them); "inside" is the share of a way's
length. `<DATA_ROOT>/rebuild/reports/military-closures.csv` lists every way, closed or left
open. The same rule closes secured federal compounds OSM does not tag military (owner
report 2026-10-06; `restricted_areas.SECURED_AREAS` and a government area with its own
`access` against the public): Goddard, NIST, NIH Bethesda and its Animal Center, the
Naval Academy's Yard, the James J. Rowley Training Center, the FDA White Oak campus, the
Nebraska Avenue Complex, the White House grounds, the state prison complex at Jessup
(446b) and the correctional department's land at Sykesville (447, closed under err closed
until the owner rules), about 2,560 ways and 156 mi (252 km), `rm:no_bicycle=secured`; the
public way in to the Goddard Visitor Center (446, 0.82 mi), Goddard's two county roads,
Brock Bridge Rd's bridge at Jessup and Slacks Rd through the Sykesville land stay open.
`secured-closures.csv` beside the military report lists
them (a `facility` column for `installation`). CIA headquarters is `landuse=military` and is in
the military count. Veirs Mill Rd's former Avoid stretch comes out LTS 3 on its two-lane carriageways and
LTS 4 on the seven with three or four lanes (433, 437.4), and Saint Elizabeths Rd SE LTS 4
(437c), as is Jeff Todd Way's roadway at Fort Belvoir (439b; its side path keeps its
own rating).

The remap also takes `mtb:scale` and `mtb:scale:imba` off every paved way
(`strip_paved_ratings` in lua/routemaker_remap.lua): Valhalla's parser read the rating as
the surface, so the paved Rock Creek Trail in Montgomery County (`mtb:scale=0`), the ICC
Trail and Northwest Branch were priced as dirt and routes avoided them. 172 paved ways
carry a rating in the 2026-10-03 extract; the rebuild logs the count (`paved ways with an
mtb rating`). Access does not change. Being a lua change, it needs
`scripts/check_tile_build_access.sh` (64 cases, 0 failures on wip/pre-rebuild: the bundle's
48, 14 for hard surfaces and 2 for secured areas) and the full
graph rebuild, which step I is.

**Images, both under one TAG.** api (also the worker's and migrate's image) and pipeline
(the `rebuild` service). `docker compose build api rebuild` (or `docker compose build`),
never `build api` alone: tile format 7 must reach the api and the pipeline together, or the
weekly pre-draw evicts the api's cache every week (above, "The stress tiles"). The front end
is not a compose image: it is built and installed separately (docs/DEPLOYMENT.md, "The
public front end"), and goes last.

**Migration.** core 0010 (`segment.mtb_only`, `walk_bike`) is state only: the segment table
is unmanaged and created whole by each rebuild. `migrate` records it and runs no SQL. The
new columns `calm_run_m`, `roadside`, `stress_unsmoothed_tier`, `mass_usable_width_m` and
`bike_access_reason` (nullable; why a way is closed to bicycles, written by WRITE_SEGMENTS
and read by the road panel's GET /api/segment-info) need no migration, as `facility` and
the trail columns did not: the rebuild's DDL creates them (`pipeline.schema.SEGMENT_DDL`)
and the writer fills all 38 columns. The api reads each one only where the live table has
it, so the new api is safe on the old table.

**The order.** Run from the deployment checkout, one step at a time, with `</dev/null` on
every docker command. Steps marked **(owner)** need the owner's OK. Each step names its
rollback point; "Rollback", below, uses them. This rebuild starts from a **fresh Geofabrik
extract**, downloaded first (owner-approved, OWNER-DECISIONS 443) so the owner's OSM
edits of 2026-10-06 are in it, and its date is checked before the rebuild builds from it:
"Before E", below, checks Geofabrik's date, and step I starts the download (by moving the
clipped extract aside) and checks what came.

```sh
D=$(sed -n 's/^DATA_ROOT=//p' .env)            # the deployment's data root, read from .env
Q() { docker compose exec -T postgis psql -U routemaker -d routemaker -AtX -c "$1" </dev/null; }
```

Never `export DATA_ROOT`: compose takes the shell's value over `.env`, so a wrong one
recreates the services on an empty tree. `D` is a plain shell variable, and `Q` a shell
function: define both again in each new shell, and `ACTOR` (step H) too; an empty `$ACTOR`
fails `--actor` safely, but it stops the step.

**A. Before the day.** The commit deployed is the reviewed bundle SHA with main as an
ancestor (the main ruleset fast-forwards only), with the front-end tests and CI green on
it. Deploy that SHA, not the branch name.

**B. Pre-flight (read-only).** Start between 07:30 and about 23:00 UTC, so the 8 h budget
(`REBUILD_TIMEOUT_S`) ends before the 07:00 backup; do not recreate `worker` between 07:00
and 07:30 UTC.

```sh
free -m; docker ps --format '{{.Names}}' </dev/null; df -h /tmp   # only this stack's containers; /tmp near empty
ls -l --time-style=full-iso $D/extracts/source.osm.pbf           # 2026-10-03's; this run replaces it ("Before E", 443)
Q "select count(*) from django_migrations"                       # note it (68 before the bundle)
Q "select count(*) from live.segment"                            # note it
Q "select id,task_name,status from procrastinate_jobs where task_name='weekly_rebuild' and status in ('todo','doing')"
Q "select variant,build_id,previous_build_id from valhalla_upstream order by 1"
Q "select kind,count(*) from override where approved group by 1"
```

If `available` is under 7000 MB, stop photon (`docker compose stop photon`). **(owner)**
Close the heavy apps on the host and pause Windows Update for the run. C: wants 15 GB free.

**C. Rollback points.** Nothing changes yet; these are what "Rollback" restores.

```sh
L=$(git rev-parse --short HEAD); echo "$L" > ~/rmdata/pre-bundle-commit.txt
docker tag ghcr.io/macrophage87/routemaker-api:dev      ghcr.io/macrophage87/routemaker-api:pre-bundle-$L      </dev/null
docker tag ghcr.io/macrophage87/routemaker-pipeline:dev ghcr.io/macrophage87/routemaker-pipeline:pre-bundle-$L </dev/null
cp $D/frontend/index.html ~/rmdata/frontend-index-pre-bundle.html   # restored by "Rollback" with busybox
for v in standard no-trail ebike weekend; do echo "$v $(readlink $D/tiles/$v/current)"; done > ~/tiles-pre-bundle.txt
Q "select max(id) from override" > ~/override-maxid-pre-bundle.txt
ls -l $D/backups | tail -1                                        # last night's backup is there
```

Optional **(owner)**, if a rerun on the 2026-10-03 data might be wanted: copy the old
merged and clipped extracts aside first (about 970 MB; step I keeps only the clipped one,
and the download overwrites the merged file and the three state extracts):

```sh
mkdir -p ~/rmdata/extracts-2026-10-03 && cp -p $D/extracts/merged.osm.pbf $D/extracts/source.osm.pbf ~/rmdata/extracts-2026-10-03/
```

**D. Hold the weekly tick (S3 of the operations review). (owner: `.env` edit)** Every
Procrastinate worker runs the periodic deferrer for the whole registry, so the maintenance
`worker` queues the Tuesday 08:00 UTC `weekly_rebuild` even while `rebuild` is stopped, and
the job waits `todo`. Recreating `rebuild` (step G) would then start a full rebuild at
once, before the overrides of step H and the tile-build check of step F; and a tick queued
behind a hand-fired run promotes a **second** build straight after, whose swap drops
`live_old`, the pre-bundle rollback target. So pause it first ("Pausing the weekly
rebuild", above):

```sh
grep -q '^WEEKLY_REBUILD_PAUSED=' .env || echo 'WEEKLY_REBUILD_PAUSED=1' >> .env
grep '^WEEKLY_REBUILD_PAUSED=' .env                                # WEEKLY_REBUILD_PAUSED=1
Q "select id,status,args from procrastinate_jobs where task_name='weekly_rebuild' and status='todo'"
```

A `todo` row here (after 08:00 UTC on a Tuesday) is the waiting tick. Leave it: with the
pause in `.env` it ends "paused" as soon as `rebuild` starts in step G, and the check
there shows it gone. `run_rebuild_now` passes `manual=True`, so the pause does not hold it.

**Before E: a fresh extract (owner-approved download, OWNER-DECISIONS 443).** The owner
approved downloading a fresh Geofabrik extract for this rebuild ("yes. I approve", 443),
so that the OSM edits they submitted on 2026-10-06 (the Twinbrook Connector surfaces, the
bicycle tags of a crossing, Veirs Mill Rd's lanes, limit and side path) are in the
build; the overrides of H still apply on top, and no Twinbrook surface override is needed.
The extract on disk is 2026-10-03's and younger than `SOURCE_EXTRACT_MAX_AGE` (six days),
so the rebuild would reuse it. So step I moves the clipped extract aside just before it
fires the rebuild: the rebuild's first stage (`FETCH_EXTRACT`, "The source extract",
above) finds it absent and downloads once, and an automatic retry reuses the new files,
which are under six days old. Nothing is set in `.env`: leave its
`SOURCE_EXTRACT_FORCE_REFRESH=` line (from `.env.example`) empty, since a forced refresh
would download again on every retry. **(owner: confirm about 664 MB.)** The three state
extracts (PBF) were 21 MB, 215 MB and 428 MB at 2026-10-03, 664 MB (633 MiB) in all; the
owner was told about 300 MB. The rebuild also writes `merged.osm.pbf` (about 660 MB) and
`source.osm.pbf` (about 300 MB).

Geofabrik cuts each region's daily file at about 20:21 UTC (the 2026-10-03 files say
`2026-10-02T20:21:34Z`); an edit made after the cut arrives in the next day's file. So the
file published early on 2026-10-07 holds edits up to about 2026-10-06 20:21 UTC (16:21
EDT). First check that Geofabrik's current build is new enough (three small text files):

```sh
for r in district-of-columbia maryland virginia; do
  curl -fsS https://download.geofabrik.de/north-america/us/$r-updates/state.txt | grep '^timestamp'
done                                                             # each at or after the owner's last 2026-10-06 edit
```

Each `timestamp` (UTC, written `2026-10-06T20\:21\:02Z`) must be at or after the owner's
last OSM edit of 2026-10-06. Its time is on the owner's changeset list; if that list shows
local time, EDT is UTC less 4 h, so a 16:00 EDT edit is 20:00 UTC. If any timestamp is
older, STOP and ask the owner: the run waits for the next day's file. Note the three
timestamps; step I checks the download against them. Then check that nothing forces a
refresh:

```sh
grep '^SOURCE_EXTRACT_FORCE_REFRESH=' .env                        # SOURCE_EXTRACT_FORCE_REFRESH=  (empty), or no line
```

Nothing has changed yet, and nothing is downloaded until I.

**E. Code and images.**

```sh
git status --short                                               # empty
git merge --ff-only <reviewed SHA>
docker compose build api rebuild </dev/null 2>&1 | tee ~/bundle-build.log
```

The api build may contact Docker Hub for its base image **(owner OK)**. `lua/` is bound
live into `rebuild`, but `rebuild` is stopped and paused, so nothing builds early.

**F. The tile-build check** (about 2 s; `lua/graph.lua` and `lua/routemaker_remap.lua`
changed, "Firing a rebuild by hand"):

```sh
scripts/check_tile_build_access.sh                               # exit 0 required; the new pipeline image, --network none
```

**G. Migrate, then recreate** (no job `doing`):

```sh
docker compose run --rm --no-deps migrate </dev/null                 # applies core 0010 (state only, no SQL)
Q "select count(*) from django_migrations"                           # one more than in B
grep -q '^WEEKLY_REBUILD_PAUSED=1' .env && echo paused               # paused: check again just before the recreate
docker compose up -d --no-deps --no-build --force-recreate api worker rebuild </dev/null
docker compose exec -T api python -c "from core import stress_tiles, mass_tiles; print(stress_tiles.FORMAT_VERSION, mass_tiles.FORMAT_VERSION)" </dev/null   # 7 2
docker compose exec -T rebuild ./manage.py shell -c "from django.conf import settings; print(settings.WEEKLY_REBUILD_PAUSED)" </dev/null                       # True
docker compose exec -T rebuild ./manage.py shell -c "from django.conf import settings; print(settings.REBUILD_TILE_CONCURRENCY)" </dev/null                    # 2 (or the .env value; "Tile build threads")
docker compose exec -T rebuild ./manage.py shell -c "from django.conf import settings; print(settings.SOURCE_EXTRACT_FORCE_REFRESH)" </dev/null               # False: the fresh extract (443) comes from step I's move, not this flag
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/healthz    # 200
Q "select id,status from procrastinate_jobs where task_name='weekly_rebuild' and status in ('todo','doing')"   # empty (a waiting tick ran as paused)
```

Never a plain `up -d`, and never name `valhalla-offroad` in an `up` on this host ("After a
host restart", above). Rollback point: the images tagged in C.

**H. Reference data and overrides.** Six files, database rows that take effect only
once loaded, all **(owner OK: a live DB write)**, each a dry run first and then `--confirm`,
before the rebuild. In this load order (each later file assumes the earlier ones are in;
the military file retires two rows the east-of-the-Anacostia file leaves in place), with
the dry run each prints after `grep -v '^present:'`:

1. `2026-10-05-owner-dupont-underpass.json`, the Dupont Circle underpass (OWNER-DECISIONS
   414, 416: `bicycle=yes` and LTS 4 on the ten underpass ways OSM tags `bicycle=no`).
   Dry: 20 create (10 access, 10 stress), no conflict.
2. `2026-09-30-owner-arterials-east-of-anacostia.json`, the east-of-the-Anacostia
   arterials again (432, 445-445f): its `retire` list withdraws the five South Capitol St
   Avoid rows (MLK Jr Ave SE to Mississippi Ave SE), which outrank the new LTS 4 corridor,
   and 524 more (445, 445f: only the highway-like main carriageways stay Avoid, 248 rows, 445d
   keeping the four Benning Rd NE ways across the DC 295 interchange; the other roads go
   back to the classifier, and Minnesota Ave, one Pennsylvania Ave way and all 36 Nannie
   Helen Burroughs Ave NE ways are re-written as floors, at least LTS 4, 4 and 3
   (`"at_least": true`: the rebuild keeps the classifier's tier where it is higher), 126
   new rows, and 445d writes Avoid on the interchange's two ramps, 128 new rows in all).
   Dry: 529 retire, 128 create (90 tier 4, 36 tier 3, 2 tier 5), 248 present, no absent. VALIDATE refuses a build where
   the South Capitol stretch is not LTS 4, so this one is not optional.
3. `2026-09-30-owner-veirs-mill-sidepath.json`, the Veirs Mill sidepath (433): retires the
   two `bicycle=designated` rows on the north-side sidewalks and closes them
   (`bicycle=no`). Dry: 2 retire `{'bicycle': 'designated'}`, 2 create `{'bicycle': 'no'}`.
4. `2026-10-01-owner-moco-lts5-avoid.json`, the Montgomery Planning LTS 5 file (433):
   retires the 23 Veirs Mill Rd Avoid rows and keeps the other 386. Dry: 23 retire, 386
   present.
5. `2026-10-06-owner-military-reopenings.json`, the military reopenings (437.6, 437a-c,
   438.2, 439b): `bicycle=yes` on Jeff Todd Way (10 ways), Russell Rd (32), Saint
   Elizabeths Rd SE (2) and its side path (11) and Pentagon Connector Road (25), LTS 4 on
   Saint Elizabeths Rd SE (retiring its two east-of-the-Anacostia Avoid rows) and on Jeff
   Todd Way's 15 carriageway ways. Dry: 2 retire (Saint Elizabeths Rd SE 316866053 and
   1181165198, tier 5), 97 create (80 access `bicycle=yes`, 17 stress tier 4).
6. `2026-10-06-owner-crosswalk-links.json`, the crosswalk links (442): `bicycle=yes` on
   four crosswalk and traffic-island ways (way ids only, no names). Dry: 4 create (access,
   `bicycle=yes`), no conflict.

These counts were checked on 2026-10-06 (reports/PRE-REBUILD-fix1.md): a copy of the live
`override` table (1,783 approved rows: 232 access, 1,551 stress; max id 1783) in a private
database, the six files dry-run and loaded in this order, then the five checks below,
which gave 0, `3|36 4|90 5|252`, 126, 11 and 4; 251 rows written in all (before 445f, which retires two more rows: now `3|36 4|90 5|250`, retire 529, present 248, still 128 written). A second dry run of each file then printed only
`present` and `absent` lines. The other override files are already in the live table
(on the same copy, after the six, their dry runs printed only `present`) and are not
loaded again, except two: the Baltimore
facilities file (3 create) waits for the owner (282a, below), and
`2026-10-02-owner-canal-whitehurst.json` has no rows to load (the rebuild reads it from the
image). If a dry run here prints other counts, the live table has changed since: stop and
report.

```sh
ACTOR=$(Q "select discord_user_id from app_user where is_instance_admin")   # one row
docker compose exec -T rebuild python3 scripts/install_reference_data.py --data-root /data </dev/null   # harmless; the crossings file is unchanged
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" \
    < fixtures/overrides/2026-10-05-owner-dupont-underpass.json | grep -v '^present:'
#   dry: 20 create (10 access, 10 stress), no conflict
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" \
    < fixtures/overrides/2026-09-30-owner-arterials-east-of-anacostia.json | grep -v '^present:'
#   dry: 529 retire (the 5 South Capitol rows of 432, 522 of 445 and the 2 Kenilworth Ave NE ways of 445f), 128 create (90 tier 4, 36 tier 3, all floors; 2 tier 5 ramps of 445d), 248 present, no absent
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" \
    < fixtures/overrides/2026-09-30-owner-veirs-mill-sidepath.json | grep -v '^present:'
#   dry: 2 retire {'bicycle': 'designated'}, 2 create {'bicycle': 'no'}
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" \
    < fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json | grep -v '^present:'
#   dry: 23 retire (moco-lts5-veirs-mill-road); the other 386 present
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" \
    < fixtures/overrides/2026-10-06-owner-military-reopenings.json | grep -v '^present:'
#   dry: 2 retire (Saint Elizabeths Rd SE 316866053, 1181165198, tier 5), 97 create (80 access, 17 stress)
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" \
    < fixtures/overrides/2026-10-06-owner-crosswalk-links.json | grep -v '^present:'
#   dry: 4 create (access, bicycle=yes), no conflict
```

Any "disagrees" refusal: stop and report. Then the same six with `--confirm`, in the same
order:

```sh
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" --confirm \
    < fixtures/overrides/2026-10-05-owner-dupont-underpass.json | tail -2
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" --confirm \
    < fixtures/overrides/2026-09-30-owner-arterials-east-of-anacostia.json | tail -2
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" --confirm \
    < fixtures/overrides/2026-09-30-owner-veirs-mill-sidepath.json | tail -2
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" --confirm \
    < fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json | tail -2
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" --confirm \
    < fixtures/overrides/2026-10-06-owner-military-reopenings.json | tail -2
docker compose exec -T api python manage.py load_access_overrides - --actor "$ACTOR" --confirm \
    < fixtures/overrides/2026-10-06-owner-crosswalk-links.json | tail -2
```

Each ends `wrote N of M rows; the rest were already approved`, and each retiring file's
line before it is its `retired` count. In order: Dupont `wrote 20 of 20`; east of the
Anacostia `retired 529 rows`, `wrote 128 of 376`; Veirs sidepath `retired 2 rows`, `wrote 2
of 2`; Montgomery `retired 23 rows`, `wrote 0 of 386`; military `retired 2 rows`, `wrote 97
of 97`; crosswalk links `wrote 4 of 4`. **Then check H before
firing I**; a skipped
or failed load is otherwise found only about 3 h into the rebuild (VALIDATE runs after the
tile build), or, for the Veirs Mill and military files, never before the swap:

```sh
Q "select count(*) from override where approved and ((kind='stress' and (value->>'tier')::int=5 and osm_way_id in (468820704,590525532,455234174,468820714,1528642818,316866053,1181165198,128574906,697039269)) or (kind='access' and value->>'bicycle'='designated' and osm_way_id in (468762518,791422825)))"   # 0: every retired row gone
Q "select (value->>'tier')::int, count(*) from override where approved and kind='stress' and value->>'adjustment_id' like 'east-anacostia-%' group by 1 order by 1"   # 3|36, 4|90, 5|250: the 445 floors and the Avoid rows that stay, the interchange's six included (445d; Saint Elizabeths Rd's two are retired by the military file, so after it none are left over)
Q "select count(*) from override where approved and kind='stress' and value->>'adjustment_id' like 'east-anacostia-%' and value->>'at_least'='true'"   # 126: the 445a-c floors are minimums ("at_least")
Q "select count(*) from override where approved and ((kind='access' and value->>'bicycle'='yes' and osm_way_id in (123824236,131756393,20535693,316866053,1184926339,1311964678)) or (kind='access' and value->>'bicycle'='no' and osm_way_id in (468762518,791422825)) or (kind='stress' and (value->>'tier')::int=4 and osm_way_id in (123824236,316866053,232308625)))"   # 11: one Dupont, Jeff Todd, Russell, Saint Elizabeths road and path, Connector Road row, the two Veirs closures, three tier-4 rows (Dupont, Saint Elizabeths, Jeff Todd)
Q "select count(*) from override where approved and kind='access' and value->>'bicycle'='yes' and osm_way_id in (1189857618,1362344261,1298593479,1189857620)"   # 4: the crosswalk links (442)
```

Anything else: stop, load the missing file again (dry run, then `--confirm`), and check again.

The api image must be the bundle's (step G): the old loader does not know `retire` and
would refuse the Veirs Mill file as a conflict, nor `at_least`, and would refuse the
east-of-the-Anacostia file.

Baltimore's Harford Road (282a): see "Rebuild checklist: Harford Road (decision 282a)",
above. The Baltimore file is loaded only if the owner approves it, and the owner then
deletes the stress row for way 424993005 in the admin; without that, `override-rematch.md`
lists that row as `failed`, which is expected. Rollback point: the override max id saved
in C (rows above it are this step's).

**I. The rebuild** (about 6 h at 2 threads, about 6.8 h if one graph's tile build is
retried, from the timings measured at 4 threads in "Tile build threads"; abandoned at 8 h).
No lane work meanwhile.

First the fresh extract (443). Just before firing, move the 2026-10-03 clipped extract
aside inside the running `rebuild` container (it runs as 10001, which owns the directory),
so the rebuild finds it absent and downloads once. Name it by the date it was built: the
clipped file carries no timestamp of its own, and its state extracts' header (the first
command) gives the data's cut, `2026-10-02T20:21:34Z`, built on 2026-10-03.
**(owner OK: the 443 download starts with this run.)**

```sh
docker compose exec -T rebuild osmium fileinfo -g header.option.osmosis_replication_timestamp /data/extracts/maryland-latest.osm.pbf </dev/null   # 2026-10-02T20:21:34Z
docker compose exec -T rebuild mv /data/extracts/source.osm.pbf /data/extracts/source-2026-10-03.osm.pbf </dev/null
docker compose exec -T rebuild ls -l /data/extracts </dev/null    # no source.osm.pbf; source-2026-10-03.osm.pbf is there
docker compose exec -T rebuild ./manage.py run_rebuild_now </dev/null
docker compose logs -f rebuild </dev/null
```

Rollback point, before `run_rebuild_now` only: move the file back
(`mv /data/extracts/source-2026-10-03.osm.pbf /data/extracts/source.osm.pbf`, the same
way). The log then shows `rebuilding the source extract: the clipped extract
/data/extracts/source.osm.pbf is absent` and, about 2-3 min later, `source extract
rebuilt: /data/extracts/merged.osm.pbf (0.6 GiB) from 3 regions, clipped to
/data/extracts/source.osm.pbf (0.3 GiB)`. There are no download lines: curl prints nothing
when it succeeds. Once the second line is there, check what was downloaded in a second
shell (set `D` again), while the build carries on:

```sh
for r in district-of-columbia maryland virginia; do
  docker compose exec -T rebuild osmium fileinfo -g header.option.osmosis_replication_timestamp /data/extracts/$r-latest.osm.pbf </dev/null
done                                                             # each the timestamp checked before E, or later
ls -l --time-style=full-iso $D/extracts/source.osm.pbf           # written within the last hour (ls shows local time, EDT)
```

An older timestamp than the one checked before E, or a `source.osm.pbf` not written within
the last hour: stop the rebuild (`docker compose stop rebuild </dev/null`, with the owner's
OK) and report; nothing is promoted. An automatic retry (the job tries up to five times)
reuses the new files and does not download again; only a retry after a failed download
downloads. If `rebuilding the source extract` appears a second time in this run, stop the
rebuild and ask the owner before it goes on.

Watch for `military areas:` (about 21,690 ways closed, 2,168 mi, and about 290 left open,
41 mi, at 2026-10-03's extract, with the military file of H loaded; VALIDATE's `military
areas:` line repeats the count, and refuses an installation below its floor
(`REBUILD_SENTINEL_MILITARY_MIN_CLOSED`) or an open network through a base),
`secured federal compounds:` (about 2,561 ways closed, 156.4 mi, and 39 left open, 4.1 mi,
at 2026-10-03's extract;
VALIDATE refuses a compound below its floor, `REBUILD_SENTINEL_SECURED_MIN_CLOSED`, a
Rowley sentinel way not closed; its open-network check cannot refuse yet, since every
reason a way in a compound stays open is one of its exceptions), no warning
`secured compounds listed by OSM id ... not in the extract`, no warning
`Pentagon ways listed open ... not found`,
`curated bike lanes (fixtures/bike_lanes): 23 ways`, `SOUTH CAPITOL ST BN 38.8309-38.8357 N:
100% at tier 4`, `facility classes:`, `AADT smoothing`, `named corridors` (three corridors),
`override re-match`, `CONNECTICUT AVE NW: N% LTS 4` (at least 60% overall and 95% north of
R St NW), the Mass Ride width line (at least 98% of road and path rows with a width, the
median road 60-200 riders a minute), the calm-run floors (Elmer School Road at 2 mi), the
long trails, the closure readback on **five** graphs, and `Stress tile cache pre-drawn:
11255 drawn` (11,068 stress tiles and 187 Mass Ride tiles at 2026-10-03's counts). A
VALIDATE refusal is terminal and nothing is promoted: keep the code (the new api is safe on
the old table), hold the front end, and report.

Once the tile stage starts (about 2.5 h in), a new build directory appears under
`/data/tiles/standard/`, named with today's UTC date (build ids look like
`20261008T182100Z`). The rebuild does not log that the stage began, so check for the
directory. In a second shell, read the newest directory by name and print it with its
`build-config.json` thread count:

```sh
docker compose exec -T rebuild sh -c 'd=$(ls -d /data/tiles/standard/2*/ | sort | tail -1); echo "directory: $d"; grep -h "\"concurrency\"" "${d}build-config.json"' </dev/null   # directory dated today (UTC), then "concurrency": 2
```

If the directory it prints is not dated today (UTC), the build has not started its tiles
yet and that is an older build's value (it may well say 4): wait and run it again, and do
not conclude anything from it.

A log line `valhalla_build_tiles aborted (SIGABRT); running it again, retry 1 of 1` means
a tile build aborted and the retry is building it again: nothing needs doing during
the run. Under 3.5.1 that was the known race; the pinned 3.9.1 fixes it, so an abort now is something new. Keep the
rebuild's log and note the line in the report. "Tile build threads" says when to move to
`REBUILD_TILE_CONCURRENCY=1` (only after the `(after 1 retry)` failure, or once the retry
line has shown up in more than one rebuild). A failure `valhalla_build_tiles exited -6 (after 1 retry)` means
the retry aborted too: set 1 before the next rebuild.

**J. After the swap.** The run row's notice prints the same restart as here.

```sh
docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend </dev/null
docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py locate </dev/null
#   four "ok" lines and "offroad: not running, skipped" where the off-road router is off
Q "select variant,build_id,previous_build_id from valhalla_upstream order by 1"   # five rows; offroad has no previous on its first build
Q "select left(version,8),count(*) from stress_tile_cache group by 1"            # W/"stres and W/"mass- rows
Q "select map_class, stress_tier from live.segment where osm_way_id = 123824236" # the Dupont underpass: road, 4
Q "select stress_tier, count(*) from live.segment where osm_way_id in (468820704,590525532,455234174,468820714,1528642818) group by 1"  # South Capitol (432): 4 only
Q "select stress_tier, facility, count(*) from live.segment where osm_way_id in (128574906,968550957) group by 1,2"  # Veirs Mill two-lane (433): 3, lane
Q "select stress_tier, facility, count(*) from live.segment where osm_way_id in (724229765,724229775,1055964463,1055974099,1059851647,697039269,724229779) group by 1,2"  # three and four lanes (437.4): 4, lane
Q "select count(*) from live.segment where osm_way_id > 1562063477"   # ways newer than urban-areas.json (2026-09-25): they read as rural; note the count
Q "select (o.value->>'tier')::int, min(s.stress_tier), count(distinct s.osm_way_id) from override o join live.segment s on s.osm_way_id = o.osm_way_id where o.approved and o.kind='stress' and o.value->>'at_least'='true' group by 1 order by 1"   # 3|3|36 and 4|4|90 or so: no floor way below its floor (445a-c)
Q "select osm_way_id, map_class from live.segment where osm_way_id in (902479602,1276271654,6084740) order by 1"   # Rowley: barred or hidden, never road
Q "select osm_way_id, map_class from live.segment where osm_way_id in (521457474,165477134,78343985) order by 1"   # ICESat Rd, WMAP Rd (446), Brock Bridge Rd bridge (446b): road
Q "select osm_way_id, map_class from live.segment where osm_way_id in (436808063,1021005797,1126815407) order by 1"   # Sykesville land (447): Beef Farm Rd, a track, a service road: barred or hidden, never road
Q "select osm_way_id, map_class from live.segment where osm_way_id in (11537133,1021005795) order by 1"   # Slacks Rd through the Sykesville land (447): road
Q "select osm_way_id, map_class from live.segment where osm_way_id in (1189857618,1362344261,1298593479,1189857620) order by 1"   # crosswalk links (442): hidden (a crosswalk is not drawn), never barred
Q "select osm_way_id, map_class, stress_tier from live.segment where osm_way_id in (131756393,299021476,267730806,316866053,1001796647,346101190,32866298,345398786) order by 1"   # Jeff Todd (4), its side path (1), Russell, Saint Elizabeths (4), its path, South Fern, Connector Road: drawn; North Rotary Rd 345398786: hidden
Q "select facility, map_class from live.segment where osm_way_id = 468762518"     # the north sidewalk (433): none, barred
Q "select map_class from live.segment where osm_way_id in (193043941,97677540,99419868)"   # JBAB: barred or hidden, never road
Q "select bike_access_reason, count(*) from live.segment group by 1 order by 2 desc"   # the road panel's closure reasons (new column): mostly null, then private, bicycle_no, military and the rest; an error here means the rebuild did not write it
curl -sI http://localhost/tiles/stress/12/1171/1566.pbf | grep -i etag            # ...-v7"
curl -sI http://localhost/tiles/mass/12/1171/1566.pbf   | grep -i etag            # W/"mass-...+fmw-...-v2"
curl -s  -o /dev/null -w '%{size_download}\n' http://localhost/tiles/mass/12/1176/1562.pbf   # Baltimore: empty
```

The Veirs Mill Rd lines were measured on the 2026-10-03 extract. The owner's 2026-10-06
edits change its lanes, limit and side path and may split its ways (a split way's new
pieces read as rural and miss the id-keyed override rows), so other tiers or fewer rows
there are expected: read `override-rematch.md` for `failed` rows and report; do not roll
back for this alone. The same goes for the count of ways newer than `urban-areas.json`
(1,931 at 2026-10-03, so roughly 2,500 now): they lean to a higher tier, the stress-averse
side; regenerating the list from the fresh extract is for after this run.

If the run row says the pre-draw was cut short, run `docker compose exec -T api python
manage.py predraw_stress_tiles`. Then the two `trip` probes ("Bicycle closures in the
tiles", step 3) and verify-release. Leave `valhalla-offroad` off on this host: Gravel and
Mountain Goat answer with `variant: "standard"`. Check also: a z12 stress tile with no LTS
3+ road; a z12 `/tiles/mass/` tile over downtown DC holding the busy roads with `rpm`; a
Mass Ride's route sections carrying `rpm`.

**K. The front end, last** (docs/DEPLOYMENT.md, "The public front end"). Then check the
Mass Ride map at z10, z12 and z14, the DC mask and the outside-DC notice. Start photon
again if it was stopped. Rollback point: the `index.html` saved in C.

**L. The weekly schedule (owner).** Decide when to unpause: remove the
`WEEKLY_REBUILD_PAUSED` line from `.env` (leave `SOURCE_EXTRACT_FORCE_REFRESH=` empty), then
`docker compose up -d --no-deps --no-build --force-recreate rebuild`. Do it before
the next Tuesday 08:00 UTC, or leave it paused on purpose. While it stays paused the
rollback target (`live_old`, the `previous` links) lasts.

**M. The beta (after live is verified).** Check out on the beta the SHA deployed on live
(step E's reviewed SHA, `git rev-parse --short HEAD` in the deployment checkout), or
`receive-data.sh` refuses the bundle (its git sha must match the beta's checkout), and use
that SHA's tagged image; then
`scripts/beta/ship-data.sh --live-dir "$RM_LIVE_DIR" --build-frontend "$RM_SSH_HOST"
/data/routemaker-incoming`; it sends `tiles/offroad` too (about 1.1 GB more). On the
server, receive the bundle, restart the **four** routers (as `receive-data.sh` prints),
and run `predraw_stress_tiles`. Do **not** start the beta's off-road router: it would take
the beta over its memory ceiling. No nginx change is needed.

**Rollback.** The old table has none of the new columns, and the new api and front end
fall back on it (no ride layer at z12-13, no capacity colours, no roadside look, the old
route chart width estimate).

- **The rebuild refused, or failed before the swap:** nothing changed in the data. Keep
  the new images (the api is safe on the old table) and keep the pause on.
- **The data at fault after the swap:** with the **new** rebuild image (the old one
  ignores the off-road router's links and row):

  ```sh
  docker compose exec -T rebuild ./manage.py rollback_rebuild </dev/null              # dry: back to the saved build; offroad withdrawn
  docker compose exec -T rebuild ./manage.py rollback_rebuild --confirm </dev/null
  docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend </dev/null
  docker compose stop valhalla-offroad </dev/null                                     # a no-op where it never ran
  docker compose up -d --no-deps --no-build --force-recreate api worker </dev/null
  docker compose exec -T api python manage.py predraw_stress_tiles </dev/null
  ```

  Keep `WEEKLY_REBUILD_PAUSED=1`, or the next tick promotes the bundle again. The
  rollback target lasts only until the next swap, so no second rebuild runs before the
  decision.
- **The code at fault:** the front end first (`index.html` from C, copied back as the front
  end's owner, 10001:10001, as in "Rollback, front end first" above; set `D` and `L` again,
  since C's shell is gone):

  ```sh
  D=$(sed -n 's/^DATA_ROOT=//p' .env); L=$(cat ~/rmdata/pre-bundle-commit.txt)
  docker run --rm --network none -u 10001:10001 -v ~/rmdata:/bk:ro -v $D/frontend:/out     docker.io/library/busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662     sh -c "cp /bk/frontend-index-pre-bundle.html /out/.index.html.new && mv /out/.index.html.new /out/index.html" </dev/null
  ```

  then the images (the `pre-bundle-$L` tags from C, then `up -d --no-deps --no-build
  --force-recreate api worker`, check `jobs_in_flight('weekly_rebuild')` is empty, then the
  same for `rebuild`). Roll the data back first if it is also going back. The old images have the
  pause (355 is on main). Migration 0010 stays applied, which is harmless. The rows H
  wrote (ids above the saved max id in `~/override-maxid-pre-bundle.txt`: the 20 Dupont
  rows, the east-of-the-Anacostia file's 128 new rows, 433's two `bicycle=no` rows, the 97
  rows of the military file and the four crosswalk rows, 251 in all) stay until the owner
  deletes them in the admin. The rows H retired are gone; to bring them back, **first**
  delete these rows, or the old files are refused as a conflict: 433's `bicycle=no` rows on
  468762518 and 791422825, the military file's tier-4 rows on 316866053 and 1181165198, and
  the east-of-the-Anacostia file's 128 new rows (its 126 floor rows sit on ways the old file
  rates tier 5; its two ramp rows are not in the old file). Define `Q` again (as at the head
  of "The order"), then:

  ```sh
  M=$(cat ~/override-maxid-pre-bundle.txt)
  Q "select count(*) from override where id > $M"                                     # 251: every row step H wrote
  Q "select id, osm_way_id, value->>'tier' from override where id > $M and kind='stress' and value->>'adjustment_id' like 'east-anacostia-%' order by id"   # 128: delete these too (owner, admin) before reloading the old east file
  ```

  Then load the files as they were at `pre-bundle-$L` (`git show
  $L:fixtures/overrides/<file>.json`): the east-of-the-Anacostia, Veirs Mill sidepath and
  Montgomery Planning files. The 2026-10-03 clipped extract is kept as
  `source-2026-10-03.osm.pbf` (step I), and its merged file only if step C's optional copy
  was made. The old api ignores an `offroad` row in `valhalla_upstream`.

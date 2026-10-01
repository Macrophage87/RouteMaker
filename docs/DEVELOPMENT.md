# Development environment

The plan's deployment target is one Docker Compose stack on one AWS host. For
development the same components run natively, which is faster to iterate against
and, for the database layer, tests the real thing rather than a stand-in.

## Environment variables

`.env.example` is the full list; three of them decide whether the deployment
works at all and are explained here rather than in a comment beside a default.

**The example ships a hostname deployment over HTTPS.** `CADDY_SITE_ADDRESS`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and
`DISCORD_REDIRECT_URI` all name `routes.example.org`, which is replaced with
your own name in four places. A plain-HTTP stack on a laptop is the commented
block at the end of the file, and it is a block rather than a single variable
because `:80` on its own does not work: `settings.py` derives
`SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` from `not DEBUG`, so without
`DJANGO_DEBUG=1` every cookie is `Secure` and a plain-HTTP browser throws the
session away without saying anything. Take the five lines together or take the
hostname. `tests/test_compose_render.py` refuses any other combination.

Nothing on this page needs the compose stack: "The native loop" below is what
to develop against. If you are standing up a real host, the order
the code forces is in docs/OPERATIONS.md, "First rebuild on a fresh host" —
notably that the reference data below cannot be installed until a first rebuild
has fetched the extract it is checked against.

**How a variable reaches a container.** There is no `env_file`: one shared file
would hand the key-encryption key to Photon and Valhalla and contradict the
claim that one component alone holds the bot token. Every variable is declared
on the services that read it, in `compose.yaml`. The non-secret settings that
every Django process needs the same value of live in the `x-django-env` anchor
at the top of that file and are merged into `api`, `worker`, `migrate` and
`rebuild`; the secrets stay written out per service, so which container holds
which one is readable at a glance.

`tests/test_compose.py` derives the set of names `config/settings.py` reads from
that module's own source and fails until each one is either declared on `api` or
named in the small, commented allow-list there - so adding an
`os.environ.get("NEW_THING")` to settings without also delivering it fails the
suite rather than producing a container that quietly runs on the default. That
test exists because the stack had declared six of the twenty-four: under it,
`ALLOWED_HOSTS` was the module's `["localhost"]` fallback, so every request that
arrived through Caddy was a `DisallowedHost` 400, and the Discord authorize URL
carried an empty `client_id` and a redirect back to `localhost:8000`.

### `KEY_ENCRYPTION_KEY` — required, no default

Every process that imports `config.settings` needs it, including `migrate` and
the rebuild worker, and settings **refuse to import without it**. It keys the
ban tombstones: `settings.TOMBSTONE_KEY` is derived from it with one HMAC over
a fixed label (`routemaker/ban-tombstone/v1`), which is HKDF-Expand with a
single output block, so the key that encrypts and the key that tombstones are
two distinct values from one delivered secret.

There is deliberately no fallback. A Discord id is a structured 64-bit value
whose candidate set any guild's member list resolves directly, so an unkeyed —
or publicly keyed — digest of one gives no privacy at all against whoever holds
a dump. With a development default in the settings file, the published literal
*was* the key on every deployment that had not set the variable, and nothing
declared it. A container without the key now stops at import instead.

It comes from SSM (SecureString, KMS-backed) in production and from the
environment file locally.

**It is not rotatable in phase 1, and the failure mode is silent.** A
`BanTombstone` row holds the HMAC and nothing else — `tombstone`, `created_at`
and a free-text `reason` (`core/models.py`) — which is the property that makes
the table safe to keep in the nightly dump, and it is also the property that
makes a rotation unrecoverable: the Discord id the digest was taken over is not
stored anywhere, so there is nothing to re-derive the new digest from. This was
once written down here as "a re-tombstoning job", which implies a job exists.
None does, and none can from the data that is kept.

What a rotation actually does is **re-admit every banned account**. The ban
check computes `tombstone(discord_user_id, settings.TOMBSTONE_KEY)` at sign-in
and looks the result up; under a new key no stored row ever matches, so every
tombstoned id signs in again as if it had never been banned, the old rows sit
in the table matching nothing, and nothing logs or refuses. Treat the value as
permanent for the life of a deployment: back it up with the database rather
than rotating it, and if it has to change, the bans have to be re-entered from
whatever record exists outside this system. handoff.md section 7 carries that
as an open row.

`DJANGO_SECRET_KEY` is the opposite case and is worth stating beside it, since
both are "a random string in `.env`" and they are not alike. Rotating it is
safe and it is not free: sessions are database-backed, their payload is signed
with that key, `settings.py` sets no `SECRET_KEY_FALLBACKS`, and so every
session fails to decode on the next request and is discarded. **Every signed-in
user is signed out**, and signs back in through Discord. Nothing is corrupted
and nothing needs repair. docs/DEPLOYMENT.md, "Secrets, and what rotating one
costs", has the same two alongside `PGPASSWORD`, whose rotation is a procedure
rather than an edit.

The suite supplies its own value through `config.test_settings`, which is
`config.settings` plus that one default and nothing else. It cannot come from
`tests/conftest.py`: pytest-django sets Django up while it loads the initial
conftests, before any conftest body has run.

### `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` — how a new deployment gets its first admin

There is no password login, no `createsuperuser`, and the only surface that
writes `is_instance_admin` is an admin page only an instance admin can reach, so
a fresh database has no way into the admin at all. Set this to one Discord id
before the first start:

```sh
BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID=123456789012345678
```

Before the first `docker compose up`, and in `.env` rather than in a shell:
compose reads the environment file when it *creates* a container, so an id
added to `.env` afterwards reaches the running api only on
`docker compose up -d api`, which recreates it. `docker compose restart api`
does not — it restarts the process with the environment the container was
created with, and the sign-in that follows gets the admin's ordinary 404 with
nothing anywhere to say why. docs/OPERATIONS.md, "First rebuild on a fresh
host", puts it in the sequence.

That id grants standing **only while the instance-admin list is empty**. Sign in
with that Discord account and open the admin once: the first admitted request
writes the id into the instance-admin list, records a `bootstrap_instance_admin`
audit row, and from then on the variable is inert even if it still names
somebody. Nothing has to be unset afterwards for the deployment to be safe,
though leaving it set is pointless.

It reaches the `api` service alone, since the admin is the only reader.

**It is spent once, permanently.** The claim writes a `bootstrap_claim` row -
one row, enforced by a unique index - and from then on the environment path is
refused whatever the instance-admin list looks like. That is what "permanently
disables the environment path" has to mean: the earlier version tested the list
instead, so emptying the list re-armed the variable, and anyone who had ever
read `.env` held a standing offer of instance admin against any future moment
the list happened to be empty. A refused second claim logs at WARNING saying the
path is spent, so the 404 has a reason attached to it.

The list counts the holders who could actually sign in - banned and deleted
accounts excluded - which is the same count `check_last_instance_admin` uses, so
a deployment whose only instance admin has been banned is one both rules agree is
empty.

The consequence is worth stating plainly: **once the claim row exists, an
instance-admin list that empties cannot be refilled through the application at
all.** There is no password login and no `createsuperuser`, so the only repair is
direct database access:

```sql
-- Break glass. Run against the deployment database by whoever has access.
UPDATE app_user SET is_instance_admin = true WHERE discord_user_id = <id>;
```

`check_last_instance_admin` exists so this should never be needed: it refuses
every application path - `save()`, the admin, and `delete()` through the
`pre_delete` guard - that would remove the last instance admin. What it cannot
cover is `QuerySet.update()`, which issues one UPDATE and emits no signal, so a
management shell or a data migration can still empty the list. That is the case
the break-glass above is for.

The `bootstrap_claim` row is in the nightly dump, so a restore restores the
disabling along with everything else.

### `INSTANCE_ADMIN_REMOVAL_DELAY_SECONDS` — the removal window

Removing an *other* instance admin does not take effect immediately. It writes a
pending removal with an effective time this many seconds out (default 3600, the
plan's hour), during which any instance admin can cancel it from the "pending
instance admin removals" page; without the window, one admin removes every peer
down to themselves in a single unstoppable action. Standing down — clearing your
own flag — is immediate, and the last instance admin can never be removed by
either path.

Re-requesting a removal that is already pending updates who asked and moves the
effective time later or not at all - never earlier - so a window that is already
running cannot be shortened by asking for the same removal again under a
shortened delay.

Due removals are applied by `core.models.apply_due_instance_admin_removals()`,
which the five-minute `degraded_guild_sweep` calls (outside that task's
gateway-heartbeat gate, which has nothing to do with removals) and which the
six-hourly membership sweep also calls as a backstop. It used to be the
six-hourly sweep alone, which made the plan's hour an effective one-to-seven
hours; it is now the hour plus at most five minutes. Notification of the removed party
and the remaining admins is **not** implemented: phase 1 has no Discord DM path
and no email path, so the window and the cancel exist and the notice does not.

## The native loop

The host this is written for is Ubuntu 26.04, which is also the production
host's OS; under Windows it is the same distribution in WSL2 (handoff-local.md
section 3 has the Windows side). Two things on it differ from what the stack
runs, and each is pinned back by hand below.

**PostgreSQL 16 does not come from Ubuntu.** 26.04 packages PostgreSQL 18 and
not 16, while the stack runs `postgis/postgis:16-3.4` and `scripts/devdb.sh`
starts cluster 16. The PostgreSQL project's own repository (PGDG) carries 16:

```sh
sudo apt-get update && sudo apt-get install -y postgresql-common ca-certificates curl
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    luajit lua5.4 python3-venv
```

GeoDjango also needs GEOS, GDAL and PROJ; the PostGIS package pulls all three
in. PGDG's PostGIS for 16 is the current 3.x (3.6 at the time of writing), not
the image's 3.4, so the native loop runs two PostGIS minors ahead of the stack.
`ca-certificates` is on the first line because the PGDG script fetches over
HTTPS: without it (a minimal image lacks it) the script prints a certificate
error, still reports success, and the next line cannot find the packages.
`curl` is for uv's installer below.

**Python 3.11 does not come from Ubuntu either.** 26.04 ships 3.14; the api
image runs 3.11 (`PYTHON_VERSION` in `docker/api.Dockerfile`). `uv` installs
the interpreter and builds the venv; it is not an Ubuntu package, so it comes
from its own installer:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"   # the installer does not change the running shell's PATH
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install -r docker/requirements.txt -r requirements-dev.txt
```

Both requirement files, always. `requirements-dev.txt` is loose and
`docker/requirements.txt` is the exact pin the images install; from the loose
file alone, on 3.14, pip picked Django 6.1 (it resolves 6.1 on 3.12 to 3.14 and
5.2.17 on 3.11), and the admin's guild scoping answered a guild admin's write
to another guild's row with a 302 rather than a 403 or 404 - a test failure
caused by a Django the stack does not run.
In that case `tests/test_native_environment.py` also fails, naming each pin the
interpreter does not have; it does not run first, so read its failure before
the others. CI installs the same two files.

Then the database and the suite, from the checkout:

```sh
sudo sh scripts/devdb.sh
PGDATABASE=routemaker_dev .venv/bin/python -m pytest tests/ -q -p no:randomly
```

`devdb.sh` starts cluster 16 if it is down, and creates the `routemaker` role,
the `routemaker` database and the PostGIS extension if any is missing; under
systemd (a desktop, or WSL with systemd enabled) the cluster is already up at
boot and the script only does the second half. It runs as root because it
switches to the `postgres` account. The suite creates and drops schemas, so give
each concurrent run its own `PGDATABASE` (below, "Running the suite twice at
once").

`/tmp` on 26.04 is a tmpfs, sized from RAM and shared by every process on the
host, so a test that measures free space under `tmp_path` sees a few gigabytes
rather than a disk, and how full they are depends on whatever else is running.
The rebuild tests therefore neutralise both halves of the disk gate: what it
reserves is scaled to their toy extract, and its fullness fraction is set to
100 percent, the way `tests/test_operations.py` already did. The gate's own
refusals are tested with a stand-in `disk_usage`. A `/tmp` that genuinely runs
out still fails the suite, and can abort it outright: a pyosmium writer that
hits ENOSPC can raise from its destructor, which ends the process. When `/tmp`
is short, point `TMPDIR` at a real disk: pytest's `tmp_path` and the tests that
call `tempfile` directly both follow it, where `--basetemp` moves only the first.

## The front end

`frontend/` is the public map (docs/DEPLOYMENT.md, "The public front end").
Node is not needed on the host; the official image runs everything, as you, in
the checkout:

```sh
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm ci
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm test
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm run build
```

- `npm test` is `node --test` over `src/**/*.test.{mjs,ts}`: the pure logic
  (error mapping, request pacing, the long-ride rule, stress bar maths, the
  plan in the link) and the stress palette's contrast against the base map's
  own colours, which reads `@protomaps/basemaps` from `node_modules` - so
  `npm ci` first. The TypeScript runs through Node's own type stripping, on by
  default from Node 22.18; `tests/test_frontend.py` runs the same files inside
  pytest, skips on a machine without Node (WSL here) and fails in CI if the
  Node there is older or missing.
- The junction markers (OWNER-DECISIONS 172) are `lib/intersectionMarkers.ts`
  (what is listed, worded and drawn, tested without a DOM), `IntersectionList.tsx`
  (the route summary's list) and `MapView.tsx` (a DOM marker for each, a card on
  click, the list's click opening the same card); the slider's words, its note at
  the top end and the detour tiers are `lib/dials.ts`, `lib/dialsPanel.ts` and
  `lib/summary.ts`. A look at them without the live stack: build the front end,
  serve it from a Caddy (the repository's Caddyfile, `CADDY_SITE_ADDRESS=:80`) on a
  private network beside an api container started from the api image with
  `PYTHONPATH` at the checkout's `src` (`python -m django runserver`), label every
  container of the check `com.docker.compose.project=isect`, and remove them after.
- `frontend/.npmrc` turns off npm's update notifier, which otherwise asks the
  registry for npm's latest version on every run in a fresh container.
- `npm run build` typechecks (`tsc --noEmit`) and then builds `dist/`, which
  is not committed; `npm run typecheck` is the first half alone.
- `npm run dev` serves the UI with hot reload and proxies `/api`, `/tiles` and
  `/basemap` to a stack, rewriting `Origin` and `Referer` to that stack's own
  because the base map refuses any other origin. `DEV_STACK` names the stack;
  inside a container on the compose network that is the edge's name, e.g.
  `docker run --rm -it -u "$(id -u):$(id -g)" -e HOME=/tmp -e DEV_STACK=http://<caddy container> --network routemaker_default -p 127.0.0.1:5173:5173 -v "$PWD/frontend:/app" -w /app node:22 npx vite --host 0.0.0.0`.
  The dev server is for looking at the UI; proofs go through a Caddy serving
  the build, as docs/DEPLOYMENT.md describes, because only that exercises the
  edge's headers.

## What migrations do and do not create

`Segment` is `managed = False` on purpose, so `migrate` does not create it. The
weekly rebuild writes segment data into a staging schema and renames it into
place, so its DDL comes from the pipeline; a migration that owned the table
would fight the swap. Anything anchored to a segment — comments, issues,
closures, cue overrides, reviewer penalties — refers to it by plain columns
rather than a foreign key, because a cross-schema constraint would make the
rename impossible.

Test and CI databases therefore take segment DDL from the pipeline, not from
`migrate`.

## When the database stops

In an ephemeral container the cluster does not survive an idle period: the
process is killed uncleanly rather than shut down, so the next run finds a stale
pid file. A test run that fails with "connection refused" rather than with
something about the code usually means this. One command fixes it:

```sh
scripts/devdb.sh
```

It is idempotent, creates the role, database and PostGIS extension if they are
absent, and waits for the socket before returning.


## The public API

`POST /api/route` is Django Ninja (`core/api.py`); the presets it offers are
`core/presets.py`, the router calls and the stress join `core/routing.py`, and
the limits `core/ratelimit.py`. The schema is at `/api/openapi.json` on any
running api. A request, against the native loop's `runserver` or the stack:

```sh
curl -s -X POST http://localhost:8000/api/route -H 'Content-Type: application/json' \
    -d '{"points": [[-77.0434, 38.9097], [-77.0091, 38.8899]], "preset": "default"}'
```

It needs the four routers (`VALHALLA_UPSTREAMS`) and a populated live segment
schema; without the routers the answer is a 502, which is the API working.
`tests/test_route_api.py` replaces the router at `core.routing._transport`,
the one function that touches the network, so the suite needs neither.

Two settings worth knowing. `WEB_CONCURRENCY` - gunicorn's worker count - also
sizes `ROUTING_CONCURRENCY`, the routes the api may run at once (the count less
two, less the two geocoding slots, at least one); `runserver` is one process,
and the default of 7 gives it 3. And the per-client limit keys on the last `X-Forwarded-For` entry, so a
local client that sets that header chooses its own bucket - harmless here,
because on the stack only Caddy reaches the api and Caddy overwrites it.

**What a client should do.** Keep one route in flight: send the next plan only
when the last has answered, and on a drag replace the pending points rather
than queue another request. Do not retry on a timer. A 429 or 503 carries
`Retry-After`; wait that long once, then send the current points. The per-client
slot is one route on the default pool, so a second concurrent request from the
same browser is refused rather than served.

**Long rides.** Past 150 km of straight line a signed-out request gets 409 with
`"code": "confirm_long"` and `span_km`, and nothing is routed; resend the same
body with `"confirm_long": true` once the visitor agrees. A signed-in session
never sees the 409. Past 200 km the answer is 400 however it is asked. A
route whose traces ran out of time comes back with that part of `stress_m` as
`"unknown"`; treat it like any other unknown stretch.

**The sliders, the ride time and Cargo Bike** (PUBLIC-DIALS, the owner's
requests of 2026-09-27; PLAN.md, "Owner amendments"). All optional and additive; a body without them is planned as
before, at the preset's own starting positions:

```sh
curl -s -X POST http://localhost:8000/api/route -H 'Content-Type: application/json' \
    -d '{"points": [[-77.0434, 38.9097], [-77.0091, 38.8899]], "preset": "cargo",
         "carrying": "people", "stress": 90, "hills": -40, "when": "weekend"}'
```

- `stress`, integer 0-100, rescaled on 2026-10-01 (OWNER-DECISIONS 163 and 164;
  "Intersection costs, the calm search and the detour warning", below): 0 to 70
  is the old 0 to 90 and 70 to 80 the old 90 to 100, `use_roads` 1.0 falling to
  0.10 at 70 (Default) and 0 at 80; above 80 `use_roads` stays 0 and a search
  over the router's routes prices LTS 3, 4 and Avoid at a rate rising
  exponentially to ten metres of detour per metre at 100, with no cap and a
  warning (`detour`). 0 is traffic
  tolerant (the planner warns at 10 or below: the owner, 2026-09-28; a true
  fastest option is a later custom-costing phase), 80 keeps to low-stress ways
  unless avoiding them takes much longer, and past it the route goes out of its
  way for them. The positions in the measurements below are on the scale before
  the rescale; the old position `q` is now `q * 7 / 9` up to 90.
  The graph carries the stress tiers (LTS 3-4 ways as `bicycle=use_sidepath`,
  `lua/routemaker_remap.lua`), and Valhalla weighs that `3 * (1 - use_roads)`,
  so one graph serves every position. LTS 4 and up cost more again ("Graded
  stress", below).
- `hills`, integer -100-100, detent at 0: below it `use_hills = 1 + hills/100`
  (0 is `use_hills` 1.0, no grade penalty, the fastest time); above it a climb
  search among the router's `alternates` (3), choosing the one that climbs most
  within `1 + 0.5 * hills/100` of the direct route's length. Two-point plans
  only, and not past 50 km of straight line (`routing.SEEK_MAX_SPAN_M`: a cold
  65 km search with alternates took 51 s on the live router); `hills_seek.limited`
  says when it was not done.
  Mass Ride refuses `hills > 0` (400).
- `when`: `weekend`, `weekday_rush` (Mon-Fri 07:00-10:00 and 16:00-19:00,
  America/New_York; federal holidays count as weekend) or `weekday_offpeak`;
  absent, the setting of the moment. It sets Valhalla's `date_time` (the next
  Saturday 09:00, Tuesday 08:00 or Tuesday 12:00), which is what the
  conditional restrictions Valhalla reads are evaluated against, and it decides
  whether a road closed to cars at set times counts as a path in `facility_m`
  and as tier 1 in `stress_m`. The closure is read from
  `motor_vehicle:conditional` / `motorcar:conditional` (`routemaker.ridetime`):
  day ranges, week spans that wrap (`Fr 19:00-Mo 06:00`), `PH`, and times with
  no days, which name every day (Clark Place NW's `no @ (06:00-10:15,14:45-19:15)`
  is car-free at weekday rush; supported since the round-1 mutation review).
  A condition it cannot read - a month range, `sunset` - closes nothing.
- `carrying`: `cargo` or `people`, Cargo Bike only (400 elsewhere); it sets the
  stress slider's start (90, Default's, or 100).
- `assist`: boolean, Cargo Bike only (400 elsewhere): electric assist. The ride
  routes on the e-bike graph (e-bike legality) at 18 km/h rather than 14; the
  hills slider keeps Cargo Bike's start, since a heavy bike's motor rarely
  cancels a climb (the owner, 2026-09-27).
- Mass Ride refuses `stress > 0` (400): the owner's "Lock at 0".
- `intersections`, `calm_search` and `detour` (FOLLOWUP-INTERSECTIONS, additive):
  the route's stressful junctions with their reasons, what the search over the
  router's routes did, and how much longer the route is than the direct one;
  the contract is in "Intersection costs, the calm search and the detour
  warning", below.
- `stress_m` has a key `"5"`, "legal but avoid" (additive; the keys still sum to
  the distance): an expressway posted 50 mph or more, or a way the owner
  curated (`fixtures/overrides/2026-09-27-owner-stress.json`, loaded as that
  directory's README says). In the graph it is the LTS 3-4 stress penalty
  plus Valhalla's alley use (`service=alley`, written by
  `routemaker_remap.remap_way`); every preset sends `alley_penalty` =
  `presets.AVOID_ENTRY_PENALTY_S` (1800 s of cost, no time) for entering one,
  which reaches Mass Ride at `use_roads` 1.0 too. Only tier-5 ways pay it (the
  owner's "Only tier-5 roads", 2026-09-27): OSM's own alleys become plain
  service roads in the graph (Valhalla's service penalty, 15 s, where an alley
  had 5 s), and destination-only and private ways keep Valhalla's own
  `destination_only_penalty` (600 s, not sent). The access of a tier-5 way is
  untouched, so it stays routable when it is the only way.
  Measured on the DC box graph (PUBLIC-DIALS round 3, Valhalla `/locate`
  against the graph of 7a04862): all 9,322 destination-only or
  private-for-cars road ways located keep the base graph's
  `destination_only` flag and bicycle access, and 49 of them, OSM's own
  alleys, are service roads; all 1,273 tier-5 ways located are alleys, not
  destination-only, open to bicycles. With every other Anacostia crossing
  excluded, Mass Ride still routes over the tier-5 Douglass roadway.
- A curated tier is a stress adjustment (`routemaker.stress.StressAdjustment`,
  the format in `fixtures/overrides/README.md`): `segment.stress_adjustment_id`
  names it, and only a public adjustment whose words the owner approved also
  fills `stress_computed_tier`, `stress_adjustment_direction` (`up`, `down`,
  `same`), `stress_adjustment_category`, `stress_adjustment_note` and
  `stress_adjustment_display` (`writers._adjustment_columns`, and a table
  constraint that refuses the rest without an id). The answer's
  `stress_adjustments` lists, in route order, each adjustment the traced route
  rides over: `adjustment_id`, `tier`, `adjusted`, `length_m`, and for a
  public, approved one `direction`, `category`, `public_note` and `display`
  (the owner: "Only provide the warnings if the route goes over the road").
  Empty until the live table has the columns. The tiles do not read them.
- `stress_spans` (OWNER-DECISIONS item 81: "Could we also get a color on the
  route for what LTS it is?"): the route's sections, in route order,
  `[{from_m, to_m, tier, facility}]` in whole metres along the traced length
  from 0, each starting where the one before ends. `tier` is 1-5 or null
  (unknown), `facility` the class or null. They come from the same per-piece
  join as `stress_m` and `facility_m` (`routing.classify`; a road closed to cars
  at the ride's time is tier 1 and a path, and on the no-trail variant a lane is
  "none"), with adjacent equal sections merged and a section under 10 m
  (`routing.MIN_SPAN_M`) folded into its neighbour, so a long ride stays a
  short list; the totals are summed from the pieces and stay exact. A leg that
  could not be traced is one null section of its length, and a plan whose
  joins ran past the budget is one null section over the whole route. The map
  scales the sections to the line it draws (`frontend/src/lib/routeColours.ts`)
  and colours them with the stress map's own tokens (`stressStyle.js`).
- The graph a ride routes on (`variant` in the answer): a weekend ride on a
  preset whose graph is the standard one routes on the weekend graph
  (`Variant.WEEKEND`), where roads closed to cars at the weekend are off-road
  paths; if that router does not answer, the standard graph answers instead
  and `variant` says so. E-bike, Cargo with assist and Mass Ride keep their own
  graphs at the weekend.

**The stress and hills sliders, measured** (PUBLIC-DIALS, 2026-09-27: a box
graph, -77.22,38.78,-76.90,39.02, rebuilt from the real extract by the real
pipeline stages before and after the graph change). Share of the route on LTS
3-4 and moving time; "today" is the old graph at the old Default (use_roads
and use_hills 0.5), which reproduced the live Dupont Circle to Capitol answer
(33% LTS1, 48% LTS3, 19% LTS4):

| Trip | today | stress 0 | stress 25 | stress 75 | stress 90 (Default) | stress 100 |
|---|---|---|---|---|---|---|
| Dupont Circle - Capitol | 67%, 21.6 min | 90%, 19.6 | 52%, 21.8 | 17%, 25.9 | 6%, 26.0 | 6%, 26.0 |
| Bethesda - Georgetown | 98%, 29.3 | 98%, 29.3 | 3%, 42.0 | 3%, 42.0 | 3%, 42.0 (92% path) | 3%, 42.0 |
| Silver Spring - Union Station | 10%, 48.6 | 92%, 39.7 | 10%, 48.6 | 10%, 49.2 | 7%, 50.3 | 6%, 50.4 |
| Courthouse - Farragut | 51%, 20.8 | 77%, 19.3 | 11%, 23.7 | 13%, 24.7 | 13%, 24.7 | 13%, 24.7 |
| Logan Circle - Eastern Market | 81%, 18.5 | 90%, 18.1 | 20%, 21.9 | 18%, 22.0 | 9%, 29.4 | 9%, 29.4 |
| Falls Church - DC | 9%, 48.9 | 92%, 41.6 | 1%, 50.2 | 1%, 50.2 | 1%, 50.2 | 1%, 50.2 |

Stress 0 is within 3% of the time of Valhalla's `shortest` route on every
trip, so the direct end is the fastest legal route. (Positions in this table
and the paragraph below are on the scale before the 2026-10-01 rescale: the
old 90 is 70 now.) Default starts at 90, the
owner's answer of 2026-09-27 to "75 or 90?": against 75 it takes Dupont
Circle - Capitol from 17% to 6% on LTS 3-4 for 0.1 min, and Logan Circle -
Eastern Market from 18% to 9% for 7.4 min; the other trips do not move. The hills slider below
its detent moves routes only where the terrain offers a choice (Rosslyn -
Ballston: 105 m of climb at 0, 65 m at -100); above it the climb search found
a hillier alternative on 6 of 14 trips (Bethesda - Georgetown +97 m for
+0.2 km; Takoma - Navy Yard +24 m for +1.8 km), each search under 5 s.

The weekend graph, on the same box (Default, the same trip at the weekend and
on a weekday): Little Falls Parkway 2.84 km at the weekend on the closed
parkway against 3.09 km around it on a weekday; lower Sligo Creek Parkway
0.63 km against 1.07 km; Beach Drive NW at Carter Barron the same line both
ways, 76% against 59% traffic-free. Mass Ride from Anacostia to Nationals Park
took the Frederick Douglass bridge roadway before its tier 5 and takes the
11th Street local span after (3.00 km against 3.05 km); with every other
crossing excluded it still routes over Douglass, and every ordinary preset
crosses on the Riverwalk paths.

The answer adds `facility_m` (`path`, `protected`, `lane`, `none`,
`unknown`, metres summing to the traced length, from `segment.facility` and
`segment.car_free_when`), `dials` (the positions actually planned with) and
`hills_seek` (null unless the hills slider was past its detent). Until the
live segment table has been rebuilt with the facility columns, `facility_m`
is all `unknown` and nothing else changes. On the no-trail graph (Mass Ride)
protected and painted lanes count as `none`: the field rides the roadway (the
owner: "Even protected bike lanes aren't used."); a road closed to cars is
still `path`.

**Sustained grades** (the owner, 2026-09-28: "I'd probably have an increasing
penalty for steeper hills instead" of a hard grade cap; "In many cases it's not
just stepness but steepness and length. 10% can be done for 100m of riding,
people would just sprint before it. If continued over kilometers, that becomes
a hike-a-bike"; and "I'd say a descent over about 2-3% might actually want to
be penalized. There's a point where it's a fun downhill and a point where
you're riding the breaks.").

Valhalla's own grade penalty is already progressive per metre climbed. Its
edge cost is `time * (1 + grade_penalty + ...)`, with `grade_penalty =
(1 - use_hills) * kAvoidHillsStrength[grade]` and a slower bicycle speed
uphill (`kGradeBasedSpeedFactor`); the extra cost per metre climbed over flat
riding, on a quiet street, in metres of flat riding:

| Hills slider | 3% | 5% | 6.5% | 8% | 10% | 13% | 15% |
|---|---|---|---|---|---|---|---|
| 0 (use_hills 1.0) | 12 | 13 | 17 | 20 | 20 | 23 | 31 |
| -60 (0.4) | 18 | 26 | 45 | 61 | 74 | 138 | 191 |
| -100 (0.0) | 22 | 34 | 63 | 88 | 109 | 215 | 297 |

So at -100 a 10% pitch costs 3.2 times a 5% one per metre climbed. What it
cannot do is tell a kick from a long climb: each edge is priced alone, from
its own grade. The grade is Valhalla's, computed from the DEM when the graph is
built (mjolnir/elevationbuilder.cc); no tag feeds it, and no other edge cost
scales with `use_hills`, so a graph tag cannot carry a hills-slider-scaled,
length-aware penalty in the pinned Valhalla. The avoid half therefore weighs
the router's alternatives (`core.routing.choose_gentlest`), as the seek half
does: the router's elevation along each (every 30 m, in the direction ridden)
is read as sustained climbs and descents (`routemaker.climbs`: a run survives a
3 m dip and a 150 m flat), each priced in seconds by

    cost = 1.7 * w(grade - threshold) * past * (1 + past / 1000)

with `past` the metres beyond the first 150 (the kick, free whatever its
grade), `w(x) = x * (1 + x / 0.03)` and a climb's threshold 3%; and the
route with the least `time + (-hills / 100) * cost` is kept. One kilometre at
8% costs 356 s at -100, about what walking it adds. A descent is priced the
same way from the ride type's brake grade (approved by the owner,
2026-09-28: "Approve the table"):

| Ride type | Descents cost past | Why |
|---|---|---|
| Cargo | 3% | the owner's "about 2-3%", braking a loaded bike |
| Mass Ride | 4% | PLAN's low grade tolerance; a field cannot brake as one |
| Group Ride | 5% | a group brakes earlier to stay together |
| Default, Trailmaxxing, Gravel, E-bike | 6% | most riders brake in earnest past 6% |
| Mountain Goat, Fast | never | riders who choose these want the descent |

The avoid half never answers with a route busier than the same trip at the
middle of the slider (the owner, 2026-09-28: "Traffic wins (Recommended)"):
the same request is made again at the middle - one /route without
alternatives, at most 18 s - both routes are traced, and if the hill-avoiding
one's exposure (LTS 3 + 2 x LTS 4 + 3 x tier 5 metres) is worse, the middle's
route is the answer (`hills_avoid.kept_middle`); a middle call or trace that
fails keeps the hill-avoiding route. The check leaves the answer's own traces
8 s of the budget (`MIDDLE_TRACE_RESERVE_S`): the middle call gets at most what
is left less that (and 15 s on the weekend graph), and is not made when that is
under 4 s, so a slow first route no longer leaves the breakdown "unknown". The
route answered is traced once; the check's trace is reused. On the correctness
reviewer's grid (3060
plans on the r6 box graph) the avoid-half plans busier than the middle went
from 89 to 0, the middle's route was kept 93 times, and an avoid-half plan's
time went from a median of 0.12 s (p95 0.53 s) to 0.25 s (p95 0.87 s).

Nothing changes at the middle of the slider or above it, and nothing is
rebuilt: the graph is the same. The limits are the seek half's - a start and
an end only, up to 50 km apart, three alternatives - and every ride below the
middle now asks for them (Cargo starts at -60), which roughly doubles the
router's work for such a ride.

The data (region extract and 1-arc-second DEM, named roads and trails chained
by name, both directions, `routemaker.climbs.runs`): 75,436 climbs past 150 m,
of which 79 are 8% or steeper for a kilometre or more, all in the Catoctins,
the Blue Ridge and around Sugarloaf (Coxey Brown Road, 2.9 km at 10.2%, 4,451
s; Middlepoint Road, 2.3 km at 9.9%; Harp Hill Road, 1.9 km at 9.0%; Park
Mills Road by Sugarloaf, 660 m at 9.0%). The costliest in the District and
Arlington are 1-2 km at 5-7% (Massachusetts Avenue NW, 1.9 km at 5.5%, 360
s; Arizona Avenue NW, Fulton Street NW, Morris Road SE) or short and steep
(Calvert Street NW, 420 m at 10.1%); around Great Falls the steepest roads
are 400-700 m at 7-11%. The DC box has no climb of 8% for a kilometre.

Measured on the box graph through the API's own code: of 16 ridge-crossing
trips, the avoid half changed the route on a few - Georgetown to Glover Park
at -60 takes a 3.72 km route with 86 s of sustained-climb cost against the
router's 103 s; down Massachusetts Avenue NW, Cargo at -60 takes a route 99 m
shorter with 239 s of descent cost against 297 s, while Fast keeps the
direct descent. On most city trips the router offers no gentler alternative,
and the kept route is its own. A per-edge sustained-grade cost - the same
model priced into every edge from the pipeline's elevation - would need a fork
of the costing (PLAN's layer 3); the owner chose "Ship this, fork later
(Recommended)".

**Calibration of the tiers** (OWNER-DECISIONS 83-143; `routemaker.stress`
unless named; PLAN.md quotes the owner's words):

- *Lane count in a city.* Inside the urban-area layer
  (`reference/urban-areas.json`) a one-way street with up to two through lanes
  is read on Furth's single-lane row, speed and volume deciding ("Multi-lane in
  a city isn t nearly that problematic"; "1 Way is typically lower stress at
  similar characteristics"). A two-way multi-lane street, a one-way of three
  lanes or more (`wide one-way floor`, item 143) and a carriageway of a divided
  road are LTS 3 at least (`two-way floor`), and LTS 4 from 30 mph over 8,000
  vehicles a day (`two-way busy`, Furth v2.2's threshold). A quiet one (1,500 a
  day or fewer) keeps its low-volume relief down to the floor, so a 35 mph
  four-lane street at a low count is LTS 3 (item 140, owner-approved, as v2.2
  rates it). Outside urban areas Furth's multilane rule stands. Lanes are
  counted per direction (`tags.lanes_per_direction`).
- *Divided roads* (`routemaker.divided`, item 132). OSM maps a road with a
  median as two one-way ways; a one-way of a divided class (trunk to
  unclassified), named, with a same-named way running the other direction
  alongside it - 13-150 ft (4-45 m) to one side, at two or more points 65 ft
  (20 m) apart - is scored as the two-way road it is. Same-named ways that close
  into a ring under 0.6 mi (1 km) round are circles or loops (Ward, Tenley,
  Blair and Americana Circles) and are left out. 46,343 ways on the region; 133
  MiB and 19 s on this host.
- *A decent painted lane.* At 40 mph a decent lane is LTS 3, a tier below
  mixed traffic (item 84), and not from three through lanes a direction, where
  Montgomery's Appendix D keeps LTS 4. Decent: buffered, or not tagged narrower
  than 5 ft; an untagged width counts.
- *Missing speed limits* take the state's default (items 108, 112): the
  District 20 mph on every class, 15 in alleys; Maryland and Virginia urban
  areas 25 residential, 30 tertiary and unclassified, 35 secondary and primary;
  elsewhere the old class tables. A `maxspeed:type` or `source:maxspeed` naming a
  state (`US-DC:urban`) says the same. The state is the one each way's middle
  vertex lies in, from the rebuild's own extract (`pipeline.states`, item 137;
  a vertex on a shared line goes to Maryland or Virginia, the higher default).
- *Arterials* (item 141): a trunk, primary or secondary road or its link is
  LTS 3 at least without a painted, buffered or protected lane, a paved shoulder
  the bike-lane table credited (item 145: "Yes, count it"), or a facility mapped as its own way beside it
  (`facility.separate_pairs`) - everywhere (`arterial floor`). And v2.2's middle
  band at 20 mph and below: 1,500-8,000 vehicles a day is LTS 2 (`mid volume`);
  it is not redundant after the floor, since it moves the non-arterials.
- *Curated speed limits* (`routemaker.speed_corrections`, `fixtures/speed/`,
  item 131): the Montgomery County parkways with no posted speed are read at
  25 mph; a posted speed wins.
- *Alleys* keep their tier and pay the LTS 3 stress penalty in routing (item
  110, `lua/routemaker_remap.lua`), on top of the tier-5 alley charge.
- *Singletrack* (`routemaker.singletrack`, item 111): a trail rated 1 or more on
  `mtb:scale` or `mtb:scale:imba`, unless paved, is closed to bicycles on every
  graph (`rm:no_bicycle=singletrack`). The C&O towpath stays a path either side
  of lock 21.
- *The CBD rule* (`routemaker.cbd`, item 104): a sidewalk inside DDOT's Central
  Business District and outside the federal areas and the Architect of the
  Capitol's polygon is closed to bicycles (`rm:no_bicycle=cbd_sidewalk`).
- *Avoid gravel* (items 91, 92): the box raises `avoid_bad_surfaces` to 0.9 and
  rides the route as a Road bicycle at the preset's own speed, so every surface
  worse than compacted is priced steeply on every preset; a ride that starts or
  ends on gravel is still planned.

Measured over the region's source extract (2026-09-30, the current head's
rules; 98,411 road miles, proposed, construction, platform and corridor ways
left out; states from the merged extract's boundaries): LTS 1 goes from 47.6%
to 48.1% of the miles against 20d975d, LTS 4 from 17.8% to 17.0%; in the
District LTS 1 from 44.9% to 71.3%, LTS 3 from 10.6% to 12.2% and LTS 4 from
12.8% to 6.3%. Against the 0889eee rules the arterial floor moves 286 mi region-wide (the
District 70 mi, 32 mi of it from LTS 1) and the middle band 73 mi (the District
50 mi). 261 mi of the coverage
lie in West Virginia and Pennsylvania, whose boundaries do not close in the
merged extract; they keep the class tables.

**Deviations from the literature review**
(`reports/LTS-literature-review.md`), kept here because each is a decision,
not an oversight:

1. A one-way street with up to two lanes stays on the single-lane row; the
   review reads two lanes a direction on the multilane rows (items 106, 109).
2. The District's default is a flat 20 mph on every class; the review suggests
   20/25/25 by class. The arterial floor (item 141) covers the arterials that a
   flat 20 would have put at LTS 1.
3. Lanes on a two-way road are halved with floor, not ceil, and
   `lanes:both_ways` is not subtracted.
4. v2.2's bike-lane table is not built; a decent lane at 40 mph is one tier
   below mixed traffic, and an untagged lane width counts as decent.
5. Alleys keep their tier and are priced like LTS 3 in routing; the review
   suggests LTS 2 and a penalty ("Stronger", item 110).
6. A curated 25 mph on the named parkways replaces Montgomery's parkway rule
   (item 131).
7. A quiet multi-lane street at 35 mph keeps its low-volume relief down to
   LTS 3; the review's summary table says LTS 4 at 35 mph and above, while v2.2
   itself agrees with the branch (item 140).
8. Road class is an input: arterials are LTS 3 at least without a facility
   (item 141). Furth's tables read speed, lanes and volume, not class.
9. A one-way of three lanes or more takes the two-way floor, after SFMTA's
   comfort index rather than Furth (item 143).
10. A carriageway of a divided road is scored as two-way, lanes per direction
    from its own `lanes` (item 132).

**Graded stress** (the owner, 2026-09-28: "Yes, grade them (Recommended)" and
"I'd probably want LTS 4 to be twice the stress level of LTS 3 at least.").
A way's *stress level* at a slider position is the cost its tier adds per
metre over the same edge with no tier, as a multiple of the edge's time cost:
Valhalla 3.5.1's bicycle edge cost is `time * factor`, with `factor = 1 +
grade + accommodation * roadway_stress` (sif/bicyclecost.cc), so the stress
level is `factor(tier) - factor(no tier)` for the same edge, grade and speed.
LTS 3 is `bicycle=use_sidepath`, which adds `3 * (1 - use_roads)` to the
accommodation factor. LTS 4 and up add the graph's top practical speed (140,
`kMaxOSMSpeed`) and lane count (15 each way, `kMaxLaneCount`), which raise the
roadway stress through its speed penalty and lane term; the bicycle's time
comes from its own speed, so no duration changes, and the speed limit and
access stay OSM's. Not on the no-trail graph: Mass Ride is locked at 0.

The stress levels, LTS 3 / LTS 4 (and the ratio), modelled from the costing
code for representative roadways at each slider position:

| Roadway | 0 | 25 | 50 | 75 | 90 | 100 |
|---|---|---|---|---|---|---|
| secondary, 1 lane each way, 30 mph | 0 / 1.14 | 0.92 / 4.64 (5.0x) | 1.98 / 10.21 (5.2x) | 3.26 / 20.22 (6.2x) | 4.13 / 28.38 (6.9x) | 4.75 / 34.82 (7.3x) |
| primary, 2 lanes each way, 35 mph | 0 / 1.05 | 1.14 / 4.62 (4.1x) | 2.63 / 10.42 (4.0x) | 4.70 / 21.06 (4.5x) | 6.23 / 29.80 (4.8x) | 7.38 / 36.74 (5.0x) |
| primary, 2 lanes each way, 40 mph, painted lane | 0 / 0.82 | 1.26 / 3.97 (3.1x) | 3.00 / 9.10 (3.0x) | 5.51 / 18.42 (3.3x) | 7.39 / 26.08 (3.5x) | 8.82 / 32.14 (3.6x) |
| trunk, 3 lanes each way, 45 mph | 0 / 0.91 | 1.55 / 4.63 (3.0x) | 3.85 / 10.88 (2.8x) | 7.58 / 22.74 (3.0x) | 10.54 / 32.62 (3.1x) | 12.84 / 40.52 (3.2x) |
| primary, 2 lanes each way, 55 mph | 0 / 0.82 | 1.46 / 4.19 (2.9x) | 3.59 / 9.78 (2.7x) | 6.76 / 20.15 (3.0x) | 9.20 / 28.70 (3.1x) | 11.07 / 35.51 (3.2x) |

Over every combination of class, 1-4 lanes, no, shared or painted lane and a
prior truck route, the smallest ratio at slider positions 5 to 100 is at
least 2.0 on roads posted up to 50 mph, 1.99 at 55 mph and 1.75 at 65 mph;
closing that gap needs a costing fork (PLAN's layer 3), since the graph's
speed and lane count are at their maximum. At 0 LTS 3 adds nothing and LTS 4
about 0.8-1.1, so the most direct route leans off LTS 4 too. Tier 5 is LTS 4
plus the alley charge on entry.

Measured on the DC box graph (PUBLIC-DIALS, 2026-09-28, head fc9bab7):

- Every tier-4 edge located (27,141 of 36,121 ways, 5,148 km open to
  bicycles) carries the marks but 37; with each edge's own class, lanes,
  speed and cycle lane from the ungraded graph, 99.8% of that length is at
  2x or more at every slider position from 5 to 100. 9.9 km falls short
  (1.78x at worst, a bicycle-legal motorway-class way at 105 km/h).
- L Street to Massachusetts Avenue, the review's probe: LTS 4 was 393 m at
  0, 1,675 m at 25 and 482 m at 100 before; it is 393, 393, 300, 77, 77 and
  77 m at 0, 25, 50, 75, 90 and 100 now, trading LTS 4 for LTS 3 as the
  slider rises. Over the 21 box trips LTS 4 never rises by more than 34 m
  from one position to the next (Chevy Chase to Peirce Mill at 50, where the
  route drops 3.1 km of LTS 3; Logan Circle to Eastern Market, 11 m); before,
  five trips rose, by up to 1.3 km.
- The cost at 0: on 10 of the 21 trips the direct end is now 3-19% slower
  than the fastest route (Bethesda to Georgetown 34.9 against 29.3 minutes),
  where before only one was; it leans off LTS 4 at 0 as the owner's "at
  every slider position" asks, and no longer reads as "the fastest legal
  route" there.

**Legs.** Besides the shared contract's fields, a 200 carries `leg_ends`: for
each leg (one fewer than the points) the index in `geometry.coordinates` of its
last vertex, so leg k runs from `leg_ends[k - 1]` (0 for the first) to
`leg_ends[k]`. The planner uses it to put a via dragged off the line into the
leg that was grabbed. It is additive; a client that predates it ignores it.

**The stress tiles.** `GET /tiles/stress/{z}/{x}/{y}.pbf` is a plain Django
view (`core/stress_tiles.py`), not Ninja: a Mapbox Vector Tile drawn by
PostGIS's `ST_AsMVT` from the live segment table, one layer `stress` with
`tier`, `trail`, `unpaved` and `facility` on each feature. It needs only a
populated live schema, no router:

```sh
curl -s -o /tmp/t.pbf -w '%{http_code} %{size_download}\n' http://localhost:8000/tiles/stress/14/4686/6267.pbf
```

A tile is served from the `stress_tile_cache` table once drawn
(`core/tile_cache.py`); `python manage.py predraw_stress_tiles` fills z10-14 for
the live table, and a local `runserver` with an empty cache draws on request.
What each zoom draws, the limits, the cache, the draw slots and timeout and the
overview index are in docs/OPERATIONS.md, "The stress tiles". `tests/mvt.py` decodes a tile for
the tests (`tests/test_stress_tiles.py`) and for looking at one by hand.

**The covered area.** `GET /api/coverage` (Ninja, in `core/api.py`) is the
area routes may be planned in, as a GeoJSON polygon feature - the
`settings.COVERAGE_BBOX` the route validator enforces, which the map greys
out the rest of. `tests/test_coverage_api.py` holds every edge of it to the
validator.

### Place search and place names: `GET /api/geocode`, `GET /api/reverse`

Both are signed out (PLAN.md's owner amendments of 2026-09-27), in
`core/api.py` and `core/geocode.py`, with the limits in `core/ratelimit.py`.
Search needs Photon (`PHOTON_URL`); names need the standard router
(`VALHALLA_UPSTREAMS["standard"]`) and use Photon only for a nearby place.

```sh
curl -s 'http://localhost:8000/api/geocode?q=1100+Wilson+Blvd&lat=38.89&lon=-77.07&limit=6'
curl -s 'http://localhost:8000/api/reverse?lat=38.90133&lon=-77.260598'
```

| | `GET /api/geocode` | `GET /api/reverse` |
| --- | --- | --- |
| Parameters | `q` (2-200 characters after white space is collapsed), optional `lat` and `lon` together (a bias, inside `COVERAGE_BBOX`), `limit` 1-10 (default 6), `lang` (`en` only, the imported language) | `lat`, `lon` (inside `COVERAGE_BBOX`), `lang` (`en`) |
| What reaches Photon | the query with US street abbreviations spelled out (`Blvd`, `St`, `Ave`, `Rd`, `Dr`, `Pkwy`, `Hwy`, `Ct`, `Ln`, `Pl`, `Sq`, `Ter`, `N`/`S`/`E`/`W`, `NE`/`NW`/`SE`/`SW`; `geocode.expand_abbreviations` has the rules), the bias, a count a few above `limit`, `lang`, and `bbox` = `COVERAGE_BBOX`; nothing else the request carries | `lat`, `lon`, `lang`, `limit=1`, `radius=0.25` km |
| 200 | `{"results": [...], "attribution": [...]}`, at most `limit` results, each inside the box, rows with the same name and OSM key within 300 m folded into one | the same shape, zero or one result |

Each result is `{name, label, lon, lat, kind, osm_type, osm_id, osm_key,
osm_value}`. `label` is the name with up to two of neighbourhood, town, county
and state. The four `osm_*` fields may be null; a client shows what the place
is from `osm_key`/`osm_value` (the front end's `placeType`) and can match a
station to its own records by `osm_type`/`osm_id`. For search, `kind` is
Photon's layer (`house`, `street`, `city`, `district`, `other`, ...). For a
name, `kind` is `trail` or `street` when the name is the road or trail the
point snaps to on the standard router's graph (the nearest named edge within
25 m; a named trail within 5 m of the nearest named edge wins, and a route
number such as "US 29" gives way to the street's name), with
`osm_type`/`osm_id` that way; or `near`, worded "near X", in two cases: the
point is on an unnamed trail and the nearest name is more than 5 m further
off - a street, or another, named trail (X is that edge's name, with its
`osm_type` "W" and `osm_id`); or no
named edge is close enough and X is a place Photon knows, never with a house
number. Ferry edges never name a point. If the
router does not answer, the name is the `near` one; if Photon does not, the
label has no neighbourhood.

Refusals, all `{"error": "..."}`: 400 for a parameter above; 403 when the
browser says `Sec-Fetch-Site: cross-site` or `same-site` (refused before it is
counted: any page can make a visitor's browser send a GET); 429 with
`Retry-After` for a spent per-client budget or a geocoding request already in
flight from the client past a second's wait; 503 with `Retry-After` when the
deployment's geocoding slots are still busy after it, or at once when another
request is already waiting; 502 when Photon (search) or both Photon and the router (names) do not
answer in time; 500 for anything else. `tests/test_geocode_api.py` replaces
Photon at `core.geocode._get` and the router at `core.geocode._locate`.

**What a client should do.** Keep one geocoding request in flight for the
page, search and names together - the per-client slot is shared, so a second
concurrent request waits (up to 1 s) and is then refused - and send search
first. The api waits up to a second for one of its two geocoding slots before
answering 503, and names may take only one of the two, so another visitor's
plan being named does not make search busy. A failed name (not an empty one)
is worth asking again later - the front end waits 30 s - rather than showing
coordinates for the rest of the visit. Debounce the search box
(the front end waits 250 ms) and answer only the latest query; ask a name for a
point once, after it stops moving, and cache it by a rounded coordinate. On a
429, 503 or 502 try once more after the `Retry-After` (at most a couple of
seconds), then show the coordinates or "not available". Never put a name in the
link: the fragment is points and ride type, and names are asked again when a
link is opened.

## Intersection costs, the calm search and the detour warning

FOLLOWUP-INTERSECTIONS (2026-10-01; OWNER-DECISIONS 133-136, 138, 163-169, 171,
172; the literature review is `reports/LTS-literature-review-2.md`, "Crossing
penalties by control type and right of way", "Left turns, multi-lane merges
capped by box turns, and slip lanes" and "The stress slider's top end"). Three
things, built on one mechanism: the traffic slider has a top end, a junction
costs what it costs a rider, and a route shows its stressful junctions.

### What Valhalla already does at a junction (measured, read-only, live router)

Valhalla 3.5.1's bicycle costing prices a node through its stop impact and turn
type, a few seconds. Measured on the live standard router (2026-10-01):
`/trace_attributes` over routes along Wisconsin Avenue, Pennsylvania Avenue SE,
K Street, Rhode Island Avenue, Georgia Avenue and Rockville Pike and across
Capitol Hill, Petworth and Takoma, `node.elapsed_time` less each edge's own
length over speed, with `/locate` giving each node's signal flag. Seconds of
transition time per node:

| Movement and place | Nodes | Median | p10 - p90 | Max |
|---|---|---|---|---|
| Straight on, residential cross streets, no signal | 760 | 0.5 | 0.0 - 2.3 | 5.3 |
| Straight on, signalised | 67 | 0.8 | 0.0 - 3.0 | 4.5 |
| Straight across a primary, secondary or tertiary road, from a minor street, no signal | 28 | 3.7 | 3.0 - 4.5 | 5.3 |
| The same, signalised | 15 | 3.7 | 3.0 - 4.5 | 4.5 |
| Right turn, no signal | 33 | 3.0 | 1.2 - 4.1 | 6.0 |
| Left turn, no signal | 33 | 0.9 | 0.6 - 2.3 | 3.8 |

So the built-in intersection cost is a few seconds, the same whether or not
there is a signal (the crossing of a busy road is 3.7 s either way), scaled by
the road class difference and nothing else (not the crossed road's stress,
speed, lanes or volume), and it prices a right turn above a left, the opposite
of the owner's item 166. Against it the literature review's costs are 30 to 100
seconds of riding. The tiles do carry stop, yield and signal flags
(`/locate`'s `edge.stop_sign`, `yield_sign`, `traffic_signal` and the node's own
`traffic_signal`, matched to a traced edge by `edge.id`); `/trace_attributes`
does not return them and `/expansion` is not enabled. The router's cost for a
metre of quiet residential street, from the same traces, is 2.2 times its time
(median; 1.8 to 2.9 at `use_roads` 0 to 1).

### Why the mechanism is on the route, not in the graph

The options were derived node tags in the tag transform plus costing
parameters, or approach-edge penalties. Neither can price a movement:

- Valhalla's per-node knobs are `gate_cost` and `gate_penalty` (gate nodes) and
  the country crossing costs (border control nodes), each a flat charge for
  passing the node in any direction, and both already used (narrow gaps; state
  lines, sent as zero). A charge on every busy-road junction would be paid by
  the rider riding along the busy road as much as by the one crossing it, which
  is item 169's opposite.
- The transform sees one way or one node, never the roads that meet at a node,
  so a tag it derives cannot say "a left across four lanes" or "the stopped
  side". A pipeline stage could, but it would be a graph rebuild to try, and it
  would still hand the router only a per-edge number, and an edge's direction
  does not say whether a rider is turning left or right onto it.
- Edge costs scale with an edge's length, so a penalty on the approach edge
  would charge a long approach more than a short one for the same crossing,
  unless the way were split at every junction (the rebuild adds border nodes
  that way; doing it at every busy junction is the most invasive option).

So `routemaker.intersections` reads the traced route. For each node the route
passes (`routemaker.trace_junctions`, from `/trace_attributes` with
`edge.id`, `edge.begin_heading`, `edge.end_heading`, `edge.use`,
`edge.road_class` and `node.intersecting_edge.*`):

1. the movement, from the headings: left, straight or right (35 degrees is
   straight);
2. the roads that meet there, from the live segment table (`core.junctions`,
   one PostGIS query for the whole route): the way's LTS and, from the first
   rebuild after this, its posted or assumed speed, through lanes a direction
   and one-way (new `road_speed_mph`, `road_lanes`, `road_oneway` columns,
   written from the classifier; until then the reasons name the tier alone), and
   its count where there is one. Only roads the router also has an edge for at
   that node count as crossed, so a sidepath that runs three metres from a
   carriageway is not "crossing" it at every node;
3. who has the right of way, from `/locate` at the busy junctions only
   (batches of 50): a signal, a stop or yield on the rider's approach, a stop on
   the cross road, or neither. A route through neighbourhood streets asks the
   router nothing;
4. the model's cost and severity.

Grade-separated crossings need no case: a bridge or underpass shares no node
with the road it passes, so there is no junction for the model to price.

### The model, and the proposals for the owner

Feet of equivalent quiet-street riding, in `routemaker/intersections.py`, every
number a named constant. They are PROPOSALS taken from the literature review's
table, within its ranges, for the owner to move:

| Situation | Constant | Proposed | Review range and basis |
|---|---|---|---|
| Straight across an LTS 3 road, from the stopped side | `STOPPED_CROSSING_FT[3]` | 1,200 ft | 800-1,600 ft (Eugene 818 ft; Broach 10-20k ADT 6-10% a mile) |
| Straight across an LTS 4 or Avoid road, stopped side | `STOPPED_CROSSING_FT[4]`, `[5]` | 3,000 ft | 2,500-3,500 ft (Broach 20k+ ADT, 1,700-3,260 ft) |
| Scaled by the crossed road's speed | `SPEED_FACTORS` | 0.8 at 25 mph, 1.0 at 35, 1.3 past 45 | Oregon's tables by speed |
| Scaled by its width | `LANE_FACTORS` | 1.0, 1.1 (two lanes a direction), 1.25 wider | a longer crossing |
| Scaled by its volume, where there is a count | `VOLUME_FACTORS` | 0.85 under 5,000 to 1.2 over 20,000 | Broach ADT bands |
| Rural: 45 mph and over, stopped side | `RURAL_SPEED_MPH`, `RURAL_FACTOR` | x1.25 | "rural drivers do not expect bicycles"; Oregon R2-R4 |
| At a traffic signal | `SIGNALISED_CROSSING_FT` | 150 ft (LTS 3), 300 ft (LTS 4, 5) | 100-200 ft, mostly delay (Broach signal 2.1-3.6% a mile) |
| All-way stop | `ALL_WAY_STOP_FT` | 75 ft | 50-100 ft (Broach stop 0.5-0.9%; Arlington -1) |
| On the free-flowing side, cross traffic controlled (item 169) | `PRIORITY_SIDE_FT` | 25 ft | 0-50 ft |
| A mapped crossing way with no signal flag | `MARKED_CROSSING_FACTOR` | x0.5 | judgement: signalised trail crossings do not reach the signal flag |
| Left onto a busy road (item 166) | `MOVEMENT_FACTOR_ONTO["left"]` | x1.5 of the crossing | Copenhagen 154 ft left against 62 ft right; the review: lefts 2-3 times rights |
| Right onto a busy road (item 166) | `MOVEMENT_FACTOR_ONTO["right"]` | x0.1 | "close to 0" |
| Left off an LTS 3 road, across its oncoming lanes | `LEFT_ACROSS_ONCOMING_FT[3]` | 600 ft | Oregon's vehicular left, LTS 3 |
| Left off an LTS 4 road | `LEFT_ACROSS_ONCOMING_FT[4]` | 1,500 ft | Oregon, LTS 4 (capped below) |
| ... where the road is one-way ("unless it's a 1-way", item 133) | | 0 | no oncoming traffic |
| ... at a signal | `SIGNALISED_LEFT_FACTOR` | x0.4 | its own phase |
| Merging across lanes to reach a left (item 167) | `MERGE_FT_PER_LANE`, `BOX_TURN_CAP_FT` | 250 ft a lane, capped at 500 ft | the review's two-stage box turn, 200-500 ft |
| A right turn off a busy road | `RIGHT_FROM_BUSY_FT` | 15 ft | |
| A slip lane (item 169) | `SLIP_LANE_FT`, `SIGNALISED_SLIP_FACTOR` | 800 ft, x0.5 at a signal | "at least an LTS 3 unsignalised crossing, about 800 ft" |
| LTS 1-2 meeting LTS 1-2, with a stop sign (item 171) | `NEIGHBOURHOOD_STOP_FT` | 10 ft, never flagged | the owner's account that DC lets bikes roll through when safe; not legal advice |
| Cap | `MAX_CROSSING_FT` | 4,500 ft | |
| Junctions within 45 m along the route | `MERGE_WITHIN_M`, `MERGED_SHARE` | one junction: the costliest and half of each other | a divided road's two carriageways, a median refuge |

Severity, `ORANGE_MIN_FT` 600 and `RED_MIN_FT` 2,000: orange is "higher stress"
and red "very high" (item 172). An unsignalised crossing of an LTS 3 road
(about 1,200 ft) is orange; of an LTS 4 road (3,000 ft) red; a left onto or
across an LTS 3 road orange, red when the road is fast; any signalised
crossing, the priority side and a neighbourhood stop sign are neither. On a
Mass Ride (`assess(..., group=True)`) the colour is the crossed road's tier
instead (item 138): orange for LTS 3, red for LTS 4 or Avoid, a left across a
one-way road none.

### The calm search, and the slider's rescale

Valhalla's `use_roads` runs 0 to 1, and at 0 its price on an LTS 3 way is at the
ceiling `docs/DEVELOPMENT.md`, "Graded stress" gives (about 5 to 13 times the
way's time). The old slider reached `use_roads` 0 at 90, so the last ten points
changed almost nothing (the baseline below: Bethesda to the Capitol and Falls
Church to Union Station plan the same route at 90 and at 100). The rescale
(`core.presets.use_roads_for`, mirrored in `frontend/src/lib/dials.ts`):

| Position | `use_roads` | Old position | Calm rate |
|---|---|---|---|
| 0 | 1.000 | 0 | 0 |
| 35 | 0.550 | 45 | 0 |
| 50 | 0.357 | 64 | 0 |
| 70 (Default) | 0.100 | 90 | 0 |
| 80 (the old top; Trailmaxxing, Cargo carrying people) | 0.000 | 100 | 0 |
| 85 | 0.000 | | 0.585 |
| 90 | 0.000 | | 1.824 |
| 95 | 0.000 | | 4.447 |
| 100 | 0.000 | | 10.0 |

Every route the old slider could plan is one position's of the new. Above 80 the
router's price is as high as it goes, and `core.refine` takes over: it asks the
router for the best route, reads it (the same trace and stress join as the
answer, plus the junctions), excludes the LTS 4 and Avoid stretches with
`exclude_locations` (one point per edge, up to 60 a round, at most 150 in all, the
router's limit being 200), asks again, then excludes every LTS 3 stretch of the
new route as well, and so on, each round's route calmer and longer than the last.
The score of a candidate, in the router's cost seconds:

    router cost + QUIET_COST x (calm rate x (LTS 3 m + 2 x LTS 4 m + 3 x Avoid m)
                                + intersection weight x (events' cost in m)
                                + climb weight x climb in m)

`QUIET_COST` is 2.2 times the time of a metre at the request's speed. The calm
rate is `calm_rate_for(stress)`: 0 to 80, then `CALM_RATE_MAX` (10, a proposal) x
(e^(3t) - 1) / (e^3 - 1) with t the fraction of the way from 80 to 100: "a
steep (exponential) curve above Default". The intersection weight runs from 0.25
at the traffic tolerant end to 1 at Default and up, so turn and intersection
costs stay active at every position; the climb weight is the hills slider's avoid
half (`-hills / 100` x 12 m of riding a metre of climb), so a relaxed ride is not
a zig-zag over a hill. Turn costs and hill costs are costing options and are
sent at every position.

There is no cap on the detour. The search keeps the best-scoring candidate, and
never one that is busier than the router's own route ("Traffic wins", OWNER-DECISIONS
61, said of hill avoidance and carried here): a candidate with more than 2 per
cent and 50 m more LTS 3, 4 and Avoid exposure (`EXPOSURE_TOLERANCE`,
`EXPOSURE_SLACK_M`) is not taken however many crossings it avoids (measured on
the live router, before the guard: Rockville to Silver Spring at the old top of the
slider traded 1.6 mi more LTS 3-4 for fewer crossings). It stops after two rounds that do not improve it, when no route is left (every way
out excluded: asked again once with only the LTS 4 stretches), when a round
cannot be started with five seconds left, and never excludes within 500 m of the
route's ends or of a via point (a trailhead's only way out is often the one busy
road). `calm_search` in the answer says what it did; `limited` is `time`,
`no_route`, `untraceable` or, where it did not run, `span` (past 18.6 mi
[30 km] apart), `long_ride`, `points` (a start only), `seeking` (the hills
slider's climb search uses the alternatives) or `mass_ride`.

Crossing avoidance is the same search with the approaches to the worst junctions
(cost from 600 ft, three a round) as the exclusions, one round, at every
position but Mass Ride's: the new route is kept if its score, router cost plus
the junction events, is lower.

**Time, alternates and limits** (live router, 2026-10-01): a calm round is a
`/route` (0.5 to 1.5 s), a `/trace_attributes` (0.1 to 0.3 s), the stress and road
joins (0.1 to 0.5 s) and up to four `/locate` calls (0.3 to 0.6 s each), 1 to 3 s a
round. On a quiet host a Default plan took 0.2 to 3 s (1 to 3 s before) and a plan
above 80 1 to 8 s over the 16 trips above; the same plans with other jobs loading
the host took 4 to 17 s, and the first plan after a process starts a few seconds
more. All inside the 40 s budget (`routing.PLAN_BUDGET_S`; the search's own
is `REFINE_BUDGET_S`, 14 s, and it keeps `REFINE_TRACE_RESERVE_S` for the answer).
The router's limits are not in the way: `max_exclude_locations` is 200,
`max_alternates` 3 (the search does not use alternates; Valhalla's alternates
are near-optimal in its own cost, which is not where a calmer route is) and
`max_distance` 500 km. Where long calm detours are NOT found:

- starts and ends more than 18.6 mi (30 km) apart, on a long ride, and rides
  with more than a start and an end where the hills slider is seeking (the
  search says so, `limited`);
- a start or end whose only way out is a busy road (the first 500 m are never
  excluded), so the stretch at each end stays: the Bethesda to Capitol ride
  keeps its first LTS 4 stretch at every position;
- places with no calm connection at all: every exclusion leaves no route, and
  the search ends (Columbia to Baltimore keeps its LTS 3 at 100);
- where the router's best route is already the calmest it can find, which is not
  a failure (Old Town to Mount Vernon, Reston to Leesburg).

**Measured before and after** (live router and segment table, 2026-10-01, a
quiet host, `when=weekend`, Default's other settings; each cell is the route's
length and the miles of it on LTS 3, 4 and Avoid; "before" is the deployed
code at the old positions 90 and 100, "after" this branch at the same routes'
new positions 70 and 80 and above them):

| Trip (straight line) | Before, old 90 | Before, old 100 | After, 70 | After, 80 | After, 90 | After, 100 |
|---|---|---|---|---|---|---|
| Rockville - Silver Spring (9.2 mi) | 11.0, 5.2 | 12.5, 3.1 | 11.0, 5.2 | 12.5, 3.1 | 13.7, 1.7 | 14.1, 1.9 |
| Bethesda - Capitol (8.0 mi) | 12.0, 1.3 | 12.0, 1.1 | 12.0, 1.3 | 12.0, 1.1 | 13.3, 1.7 | 13.3, 1.7 |
| Falls Church - Union Station (8.9 mi) | 11.5, 1.5 | 11.5, 1.5 | 11.5, 1.5 | 12.7, 0.9 | 12.7, 0.9 | 12.7, 0.9 |
| Vienna - Georgetown (10.9 mi) | 12.9, 0.5 | 12.9, 0.5 | 13.3, 0.3 | 13.3, 0.3 | 13.6, 0.2 | 13.6, 0.2 |
| Laurel - College Park (9.5 mi) | 13.4, 6.0 | 13.7, 5.9 | 13.4, 6.0 | 13.7, 5.9 | 16.6, 5.3 | 16.6, 5.3 |
| Old Town - Mount Vernon (7.1 mi) | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 |
| Reston - Leesburg (15.5 mi) | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 |
| Columbia - Baltimore (14.5 mi) | 20.2, 7.7 | 20.3, 7.6 | 20.2, 7.7 | 20.3, 7.6 | 20.3, 7.6 | 20.3, 7.6 |
| Silver Spring - College Park (4.8 mi) | | | | 6.3, 2.3 | 7.1, 0.6 | 7.1, 0.6 |
| Courthouse - Mount Vernon (12.5 mi) | | | | 19.3, 0.3 | 20.0, 0.1 | 20.0, 0.1 |
| Bowie - Annapolis (15.6 mi) | | | | 21.7, 13.1 | 31.4, 10.5 | 31.4, 10.5 |
| Silver Spring - Laurel (12.0 mi) | | | | 16.9, 8.5 | 17.4, 8.3 | 17.4, 8.3 |

What it shows. Positions 70 and 80 plan the old 90 and 100's routes, to the
mile (Falls Church - Union Station at 80 is the one place crossing avoidance found
a calmer route, 1.2 mi longer with 0.6 mi less LTS 3-4). Above 80 the slider now
does what the old top could not: Rockville - Silver Spring goes from 5.2 mi on
LTS 3-4 at Default to 1.7 mi at 90 for 2.7 mi more riding, Silver Spring - College
Park from 2.3 to 0.6 mi, and Bowie - Annapolis takes 31.4 mi (1.72 times the direct route's
18.3 mi, so the planner warns) where position 80's route is 21.7, to cut its LTS 3-4
from 13.1 to 10.5 mi. Where it does not: 90 and 100 plan the same route on most
trips, because the search's candidates are nested and the detour per metre of
busy road a calm candidate costs is almost always under the rate at 90 (1.8); only
the rare candidate dearer than that (Rockville - Silver Spring) needs the top. And
on trips whose busy stretches have no calmer way round within the router's reach
(Columbia - Baltimore, where every exclusion leaves no route; Laurel - College
Park, where excluding its LTS 3 edges sends the router onto LTS 4 roads, which
the guard against a busier route refuses) the route stays; Alexandria - Fort
Washington and Frederick - Urbana did not move above 80 either. Time, a quiet host, `core.routing.plan` in a proof container
against the live routers: 0.2 to 3 s at Default and 1 to 8 s above 80
(the same container under load from other jobs: up to 17 s at Default).


### The detour warning

`routemaker.detour` (item 164: "just warn people"): the route's length against
the most direct legal route (the router at stress 0 and the hills detent, asked
once, only when the route is longer than the larger of 1.25 times or 0.33 mi
over the straight line, which the direct route cannot beat). Silent within the
larger of 1.25 times or +0.33 mi; `note` up to 1.5 times; `warning` above;
`strong` above 2 times (the review's "let it run long, warn at 1.5x and 2x").
The answer's `detour` has `basis`, `reference_m`, `ratio`, `extra_m`, `level` and
`avoided_m` (metres of LTS 3 and worse the direct route has and this one does
not, where there was time to trace it). Where the direct route could not be had
in time, and on Mass Ride, it compares with the straight line and only the old
rule says anything (at least twice as long and 3 km more, a `warning`). The
planner words it with miles first: "This calm route is 2.6x the direct distance
(+18.0 mi, 29.0 km)", with what it buys at a note and "Move the Traffic slider
down" at a warning.

### The contract

`POST /api/route` answers three more fields (all additive; `core.api.RouteOut`):

- `intersections`: a list, in route order, of `{m, lon, lat, severity
  ("orange" or "red"), reason, crossed_tier, movement, control, kind, cost_ft}`,
  null where the junctions could not be read in time (the route is answered
  all the same). Neighbourhood stop signs and anything below 600 ft are not
  listed. `reason` is US units first: "Left turn across a 4-lane 35 mph (56
  km/h) road, no signal".
- `calm_search`: null where no search was asked for, else the object above.
- `detour`: null within the allowance, else the block above.

The planner draws the markers (`frontend/src/lib/intersectionMarkers.ts`, the
`IntersectionList` and `MapView`), a click on one or on its row in the route
summary shows the reason, and dragging the route away re-plans it as any drag
does. The slider's words and its note at the top end are
`frontend/src/lib/dials.ts` and `dialsPanel.ts`.

### Known gaps, and what would close them

- A trail crossing a road at a mapped crossing with `crossing=traffic_signals`
  (a signal or a HAWK) does not reach the router's signal flag: Valhalla's
  transform reads `highway=traffic_signals` alone. Such a crossing reads as
  "no signal" and is counted at `MARKED_CROSSING_FACTOR`. Deriving the signal in
  `lua/routemaker_remap.lua` (`forward_signal` and `backward_signal` on the node)
  is the fix and needs a rebuild to verify, so it is a recorded follow-up.
- Median refuges, raised crossings, bike signals and queue boxes are not read.
- A residential street that is LTS 3 on its own speed or volume is not looked
  for at junctions (only tertiary and up are); its stretch still colours the
  route.
- Valhalla's `use_sidepath` price on LTS 3-4 ways applies by tier and not by
  junction density; the calm search is the only thing above it.
- The live segment table has no speed, lanes or one-way until the first rebuild
  after this change; reasons say "road (LTS 4)" until then. `core.junctions.
  has_trait_columns` checks, as `core.routing` does for the facility columns.

## The worker

Procrastinate runs through its Django integration, so its job tables are
ordinary migrations and the worker is a management command:

```sh
./manage.py migrate                      # includes the procrastinate_* tables
./manage.py procrastinate worker         # every queue; compose splits them
```

Compose runs two workers from the same task module: `worker` on the
`maintenance` queue (the backup and the membership sweep, in the API image) and
`rebuild` on the `rebuild` queue (the weekly rebuild, in the pipeline image that
carries the Valhalla and GDAL binaries, with the five data directories it
writes bound under `/data`). The queue split is what puts the eight-hour build in the container with
the binaries and the 8 GB limit rather than in the API's.

A worker started any other way does not work. `procrastinate --app=... worker`
never sets Django up: it dies on the missing schema, and with the schema applied
by hand every task raises `AppRegistryNotReady`. The suite starts a worker cold
in a subprocess and runs a job through it for exactly this reason.

## The source extract

The rebuild makes its own. `FETCH_EXTRACT` downloads Geofabrik's three state
extracts — District of Columbia, Maryland, Virginia, about **1–2 GB together at
today's sizes**, and that figure moves with the map — merges them, and clips the
merge to the coverage region, leaving two files under `<DATA_ROOT>/extracts/`:

- `merged.osm.pbf`, the three states before the clip. This is what
  `valhalla_build_admins` is given (PLAN:13): the clip cuts boundary relations
  at the coverage edge, so admin polygons built from the clipped file stop where
  the box does.
- `source.osm.pbf`, the clip, which every other stage reads.

```sh
curl -fsSL --retry 3 -o district-of-columbia-latest.osm.pbf.part <url>
osmium merge --overwrite -f pbf dc.osm.pbf md.osm.pbf va.osm.pbf \
    -o merged.osm.pbf.part
osmium extract --overwrite -f pbf -s smart -S types=any \
    --bbox -78.0,38.2,-76.02,39.72 -o source.osm.pbf.part merged.osm.pbf
```

`-s smart -S types=any` is PLAN:13's, and the `-S` half is the one that is easy
to lose: without it the strategy keeps multipolygon relations complete and cuts
every other type, which is exactly the administrative boundaries.

Every command writes a `.part` and moves it into place on success, so a killed
download is never mistaken for a small region — and `-f pbf` is what that
costs. osmium takes the output format from the output file's suffix, and
`.osm.pbf.part` has the wrong one: without the flag it exits during argument
setup with "unknown format", so the whole staging scheme depends on naming the
format explicitly. `tests/test_source.py` holds every one of these arguments
against `pipeline.source.merge_command` and `clip_command`, and
`tests/test_deploy_docs.py` holds the lines restated here against the same two
functions, because a runbook that prints a command osmium refuses is worse than
one that prints none.

It is not downloaded every run. The extract is rebuilt only when either file is
missing or older than `SOURCE_EXTRACT_MAX_AGE` (six days, just under the weekly
cadence), so a rebuild re-run in the same week reuses it. Force a fresh pull by
deleting either file or setting `SOURCE_EXTRACT_FORCE_REFRESH=1`;
`SOURCE_EXTRACT_URLS` points the download at a mirror. Operations covers the
same rules from the deployment's side, including why the disk gate runs before
the download.

Neither `curl` nor `osmium` is on PATH in this development container and there
is no route to Geofabrik, so this stage has never been executed here:
`tests/test_source.py` holds the command lines argument by argument and
`tests/test_pipeline_end_to_end.py` drives the stage through the rebuild with
both binaries stood in for. Developing against a real extract means either
running the rebuild on the deployment host or putting a small hand-made
`merged.osm.pbf`/`source.osm.pbf` pair in `<DATA_ROOT>/extracts/`, which the
freshness rule will then reuse.

## Reference data

The rebuild refuses to run without three files under `<DATA_ROOT>/reference/`,
because each stood in for real data in an early version and each produced a
plausible, wrong map when empty. `scripts/install_reference_data.py` installs
them:

```sh
export DATA_ROOT=/srv/routemaker/data   # a checkout's own path here; see below
python scripts/install_reference_data.py --data-root "$DATA_ROOT" \
    --extract "$DATA_ROOT/extracts/source.osm.pbf" \
    --urban-areas "$DATA_ROOT/reference/inputs/tl_2024_us_uac20.geojson" \
    --volume "$DATA_ROOT/reference/inputs/vdot-aadt-2024.geojson" \
        --volume-source vdot --volume-year 2024 \
    --volume "$DATA_ROOT/reference/inputs/ddot-aadt-2024.geojson" \
        --volume-source ddot --volume-year 2024
```

Two agencies rather than one, because a single one is the case the conflation
step has nothing to arbitrate — `--volume` and its two companions repeat and
are matched up in order. And every input path is absolute: on the deployment
this runs inside the `rebuild` container, whose working directory is `/app`, so
a bare file name resolves somewhere the file is not. Put the GeoJSON files
under `$DATA_ROOT/reference/inputs/`, which that container binds; nothing
outside the five directories it binds is visible to it at all.

`export DATA_ROOT=...` by hand, and never `set -a; . ./.env; set +a`. That file
is compose's input: sourcing it puts every secret in it through a shell, where
`$$` is the pid rather than a literal `$` and a backtick in a value runs a
command, and an exported value then takes precedence over the file when compose
reads it. docs/DEPLOYMENT.md, "`.env` is compose's input, not the shell's", has
the failure this produced.

- `crossings.json` is `fixtures/crossings/potomac-anacostia.json`, copied. Its
  content is community knowledge maintained under the fixture's own README;
  the rebuild logs every row it cannot match against the extract.
- `urban-areas.json` is the list of OSM way ids with **at least half their
  length** inside a Census urban area (`MIN_URBAN_FRACTION = 0.5` in the
  installer). The input is the Census TIGER/Line urban-areas layer
  (`tl_<year>_us_uac20`), converted to GeoJSON with `ogr2ogr -f GeoJSON
  -t_srs EPSG:4326`. A majority of length rather than either extreme, and the
  two errors it sits between are both real: bare intersection graded a Loudoun
  through road urban end to end because a hundred metres of it clipped
  Leesburg's polygon, which is the *lower*-stress reading of an ambiguous input
  on every mile of that road, and containment would grade a District street
  rural because its last block leaves the boundary. The switch is binary — it
  chooses the default speed table, 30 mph urban against 50 rural — so it should
  describe the way rather than its ends.
- `volume.json` is every agency count line with a bidirectional AADT, in the
  shape `conflation.AgencyFeature` loads. The Virginia layer is VDOT's traffic
  volume export from the Virginia Roads portal (`--volume-source vdot`, AADT
  property `AADT`); the District's is DDOT's AADT layer (`--volume-source
  ddot`) and arrives the same way. Directional counts are summed before they
  reach here, which is why the property name is an argument rather than
  guessed.

  **Phase 1 installs VDOT and DDOT, and deliberately not Maryland.** MDOT SHA's
  layer is conditionally licensed, and while the pipeline can say which agency
  touched a way it cannot yet withhold those ways from the published
  derivative — identifiable, not excludable — so installing it today would mean
  publishing something that source influenced. PLAN.md:31-34's waiver mechanism
  is what closes that; handoff.md section 7 carries the row.

  One `--volume-source` flag sets two things, through `SOURCE_TIERS`. `source`
  is the **precedence tier** — `locality`, `state`, `osm` — and it is the only
  vocabulary `conflation.conflate` ranks on. `agency` is the **publisher** —
  `ddot`, `vdot`, `mdot-sha` — and it is the one that travels into the segment
  table's `volume_source` column. The distinction is load-bearing because VDOT
  and MDOT SHA both rank at `state`: a tier in that column could not tell the
  two apart, which is precisely the question a licence asks. The flag is
  casefolded and `mdsha` is accepted for `mdot-sha` (`AGENCY_ALIASES`), and the
  agency is recorded under its one canonical name however it was typed.

  The three columns that carry a count's provenance on the segment table, none
  of them with a Django migration because `create_segment_schema` creates the
  whole schema on every rebuild and the swap promotes it by rename:

  | column | type | meaning |
  |---|---|---|
  | `volume_source` | text | the publishing agency, e.g. `ddot`, `vdot`, `mdot-sha`; null where no count reached the way |
  | `volume_aadt` | integer | the bidirectional count itself, as normalised at install time |
  | `volume_year` | smallint | the count's vintage, nullable: a count nobody can date is a different claim from a current one |

  All three are set whenever a count was in hand, whether or not the volume
  modifier moved the tier, and a stress override keeps them: the question the
  derivative asks is which segments a source touched, not which ones it changed.
  `core.models.Segment` does not declare the last two yet, so they are read by
  SQL and not through the ORM.

Run with only `--data-root`, the script installs the crossings and exits
non-zero naming whichever of the other two is still missing.

On a deployment, `$DATA_ROOT/extracts/source.osm.pbf` does not exist until a
rebuild has produced it: `FETCH_EXTRACT` is the stage that downloads, merges and
clips it, and `LOAD_REFERENCE_DATA` is the one after it. So the first rebuild on
a fresh host is run knowing it will stop at stage two, and this script is run
against the extract that run left behind. docs/OPERATIONS.md, "First rebuild on
a fresh host", has the whole sequence; the script runs in the `rebuild`
container, which is the one that binds `reference` and `extracts`.

## Tiles and the swap

Each variant's tiles live under `<DATA_ROOT>/tiles/<variant>/`: a dated build
directory per rebuild (`20260917T080000Z/`, holding `tiles/`, `tiles.tar` and
the build config), and a `current` symlink the serving container mounts. The
checked-in configs name `/data/tiles/<variant>/current/...`, which resolves to
the same host file inside the rebuild container (`${DATA_ROOT}/tiles` at
`/data/tiles`) and
the serving one (that directory at the same path). The rebuild builds through
a derived config with `current` replaced by the dated directory, promotes by
replacing the symlink, keeps `previous` for rollback, and repoints the
`valhalla_upstream` table before renaming the schema.

`valhalla_service` does not reload tiles, so after a promotion the serving
containers are restarted to load the new extract (`docker compose restart
valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`); starting them against the
new build before stopping the old ones is the blue/green arrangement the plan
describes and phase 1 does not implement. `pipeline.promotion.rollback` undoes
a completed swap: schema, tiles and settings table together.

## Container notes

This page was first written in a cloud container whose egress proxy blocked
image pulls, so the Compose stack could not be brought up there. On a
workstation with Docker (Docker Desktop's WSL integration, handoff-local.md
section 3) it can; the native loop above is still the faster one to develop
against, and the stack is where a change to an image, `compose.yaml` or the
pipeline is run (`scripts/acceptance.py --only A1 A2` is the short gate).

`docs/DEPLOYMENT.md` is what the images are: what `docker compose build` builds,
what each image installs and why, the `collectstatic` deploy step, and the list
of things that still stop a `docker compose up`.

## Lua

The tag transform runs under LuaJIT, because Valhalla 3.5.1's build requires it
(`pkg_check_modules(LuaJIT REQUIRED IMPORTED_TARGET luajit)`) and its own
`graph.lua` calls `bit.bor`, which stock Lua 5.2 and later do not provide. Code
under `lua/` therefore has to stay within Lua 5.1 syntax; `//`, the bitwise
operators and `goto` parse under a developer's `lua5.4` and fail inside the
container, where the failure shows up as Valhalla silently falling back to its
compiled-in transform rather than as a crash.

```sh
apt-get install -y luajit lua5.4
```

`lua/vendor/graph_upstream.lua` is Valhalla's own transform at the pinned
version, checked in so the entry-point contract can be tested against the real
file. Refresh it with `scripts/vendor_valhalla_lua.sh`; do not edit it.

Setting `CI=1` turns the suite's missing-interpreter skips into failures.

## Running the suite twice at once

**A private `PGDATABASE` is enough on its own.** Each Postgres database is its
own namespace, so two runs against two different databases cannot drop each
other's schemas no matter what either one names `live` and `staging` — the
whole failure mode below only exists when two runs share one database.

```sh
PGDATABASE=routemaker_b .venv/bin/python -m pytest
```

`ROUTEMAKER_LIVE_SCHEMA` and `ROUTEMAKER_STAGING_SCHEMA` exist for the
narrower case that actually needs them: two runs sharing one database — a
shared CI Postgres instance, say — where the `live`, `staging` and `live_old`
schema names themselves would otherwise collide and each run would drop the
other's tables mid-test, producing failures that read as code defects rather
than as contention. `tests/test_schema_swap.py` and the rest of the suite take
their schema names from the `segment_schemas` fixture and from
`settings.SEGMENT_SCHEMA_LIVE` / `SEGMENT_SCHEMA_STAGING` rather than writing
`"live"` / `"staging"` as literals, so setting these alongside a private
`PGDATABASE` is safe:

```sh
PGDATABASE=routemaker_shared \
ROUTEMAKER_LIVE_SCHEMA=live_b \
ROUTEMAKER_STAGING_SCHEMA=staging_b \
  .venv/bin/python -m pytest
```

The suite is green both with these two variables unset and with them set to
non-default names; both invocations are exercised before either is relied on.

The production side has no such literals either: the rebuild's staging schema, the
writers' live guard and the swap all read the settings, and
`tests/test_pipeline_end_to_end.py` runs a whole rebuild under renamed schemas to hold
them to it.

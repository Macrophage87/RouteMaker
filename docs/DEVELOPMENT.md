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

Nothing on this page needs the compose stack: the native loop under "Database"
below is what to develop against. If you are standing up a real host, the order
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

## Database

PostgreSQL 16 with PostGIS 3.4, GEOS, GDAL and PROJ. GeoDjango needs all four.

```sh
apt-get install -y postgresql-16-postgis-3 postgresql-16-postgis-3-scripts
pg_ctlcluster 16 main start
su postgres -c "psql -c \"CREATE ROLE routemaker LOGIN PASSWORD 'routemaker' SUPERUSER;\""
su postgres -c "createdb -O routemaker routemaker"
psql -h 127.0.0.1 -U routemaker -d routemaker -c "CREATE EXTENSION postgis;"
./manage.py migrate
```

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
writes bound under `/data`). The queue split is what puts the six-hour build in the container with
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
    --bbox -78.0,38.2,-76.3,39.5 -o source.osm.pbf.part merged.osm.pbf
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
  property `AADT`); Maryland's and the District's arrive the same way with
  their own source names. Directional counts are summed before they reach
  here, which is why the property name is an argument rather than guessed.

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
valhalla-standard valhalla-no-trail valhalla-ebike`); starting them against the
new build before stopping the old ones is the blue/green arrangement the plan
describes and phase 1 does not implement. `pipeline.promotion.rollback` undoes
a completed swap: schema, tiles and settings table together.

## Container notes

Docker's daemon runs in this development container, but image layer pulls are
blocked by the egress proxy, so the Compose stack cannot be brought up here. It
is written to be validated on the deployment host. The native database above is
the loop to develop against in the meantime.

`docs/DEPLOYMENT.md` is what the images are: what `docker compose build` builds,
what each image installs and why, the `collectstatic` deploy step, and the list
of things that still stop a `docker compose up`. No image in this repository has
been built in any environment yet, which that document says plainly.

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

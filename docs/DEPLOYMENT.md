# Deployment: building the stack's images

`compose.yaml` names four images of this project's own. Until this document's
commit, nothing in the repository built any of them: there was no Dockerfile
anywhere and no `build:` stanza, so `docker compose up` on a host with a working
daemon stopped at the first pull of an image that exists in no registry. Five
review rounds read the code and none asked whether the stack could be built.

Two of the four are built now. Two are not, because they have no source.

| Image | Built by | State |
| --- | --- | --- |
| `ghcr.io/macrophage87/routemaker-api:${TAG}` (services `api`, `worker`, `migrate`) | `docker/api.Dockerfile` | Written, never built |
| `ghcr.io/macrophage87/routemaker-pipeline:${TAG}` (service `rebuild`) | `docker/pipeline.Dockerfile` | Written, never built |
| `ghcr.io/macrophage87/routemaker-renderer:${TAG}` | — | No source in the repository |
| `ghcr.io/macrophage87/routemaker-bot:${TAG}` | — | No source in the repository |

### Why every image name carries a registry

The four used to be `routemaker/api:${TAG}` and so on. An unqualified image
reference is a Docker Hub one, so that name is `docker.io/routemaker/api:dev` —
a namespace nobody here controls, and one that exists on Hub today with zero
repositories in it. Nothing stops the next person who registers it from pushing
a `routemaker/api:dev`, and the first host that does not already hold a locally
built image with that tag — after a `docker system prune`, or on a `TAG` it has
never built — would pull it and start it with `PGPASSWORD`,
`KEY_ENCRYPTION_KEY`, `DJANGO_SECRET_KEY` and `DISCORD_CLIENT_SECRET` in its
environment.

Two changes, and they are one decision:

- the four are `ghcr.io/macrophage87/routemaker-<name>`, the GitHub Container
  Registry namespace of this repository's own owner, so the name resolves to a
  place this project controls rather than to a Hub default;
- the four services that declare a `build:` also declare `pull_policy: never`,
  so compose never pulls them. Compose's default for a service with both
  `image:` and `build:` is `missing`, which pulls first. (`build`, which this
  file used to say, is not a fallback: measured on Compose v5.3.1 it rebuilds
  the working tree on every `up` even when the tag is already in the store.
  `compose.yaml`'s `api` service has the measured table for all five values.)

The three third-party images are written out the same way —
`docker.io/library/caddy:2.8-alpine`, `docker.io/postgis/postgis:16-3.4`,
`docker.io/rtuszik/photon-docker:2.4.0`. Nothing about where they come from
changes; what changes is that the registry is stated rather than defaulted.
`tests/test_compose_render.py` asserts that no `image:` in the rendered stack is
an unqualified reference.

**A `TAG` rollback runs what the local store holds, and nothing else.** Roll
back with

```sh
docker image ls ghcr.io/macrophage87/routemaker-api   # is the tag still here?
TAG=v3 docker compose up -d --no-build                # or set TAG=v3 in .env
```

which recreates `api`, `worker`, `migrate` and `rebuild` on
`ghcr.io/macrophage87/routemaker-api:v3` (and the pipeline image's `v3`) as the
store holds it: `pull_policy: never` builds nothing and pulls nothing for a tag
that is present. `--no-build` is for the other case. A plain `up -d` on a host
that no longer holds the tag does not pull it — it *builds* it, from the working
tree, which is the current code and not v3, and tags the result v3. With
`--no-build` the same command refuses with `No such image` instead. Nothing in
this repository pushes images anywhere, so the rollback path is the local store,
and `docker image prune -a` on this host is what takes it away; an image pushed
to that ghcr namespace some day would come back with an explicit `docker pull`,
never from compose.

A deploy is the other way round: `docker compose build`, then `up -d`. `up`
under `never` does not rebuild a tag that is already in the store, so a source
change reaches the containers only through `build` (or `up -d --build`).

## Not built here — read this first

**No image in this repository has ever been built.** The development environment
has no running Docker daemon and its egress proxy blocks image registries, so
nothing below has been executed. What has been done instead is written down
exactly, in `tests/test_images.py`: every `COPY` source is checked against the
repository, the `build:` contexts and dockerfile paths are checked to resolve,
the pipeline image's `FROM` is held to the Valhalla tag the serving containers
run (read out of `compose.yaml`, not restated), no Dockerfile may declare a
secret variable, and the `WORKDIR`/`COPY` layout is checked to put `manage.py`
where compose's `["./manage.py", ...]` commands look for it. Each of those tests
was confirmed to fail when the thing it checks was broken.

Package names were checked as far as a blocked environment allows. The pipeline
image's are Ubuntu 24.04 (noble) names and each was confirmed present in
`packages.ubuntu.com`, which is reachable; the api image's are Debian bookworm
names taken from knowledge, because `packages.debian.org` and the Debian archive
indices are both blocked here. Every pinned Python version in `docker/*.txt` was
confirmed present on PyPI, and each has a manylinux wheel for the interpreter
its image runs. **Nothing here is a claim that either image builds.** The first
`docker compose build` on a host with a daemon is the first real test.

## Build

```sh
cp .env.example .env               # then fill it in; see docs/DEVELOPMENT.md
sudo sh scripts/prepare_data_root.sh --env-file ./.env   # BEFORE the first up
docker compose build               # builds api and pipeline
docker compose up -d               # bot and renderer are skipped: they have no image
```

`docker compose up -d` starts everything except `bot`, `renderer` and `photon`,
which sit behind the `unbuilt` profile. `bot` and `renderer` are there because
neither has a source in this repository and so neither has an image in any
registry: without the profile this command was a pull of
`ghcr.io/macrophage87/routemaker-bot:${TAG}` that could not succeed, on a stack where every other
service was ready to start. `photon` is there because the pinned image's first
act on a fresh host is to download a 61 GB planet index onto the root volume —
see "Photon" below, which has the arithmetic and the two lines that make
enabling the profile safe. `docker compose --profile unbuilt up -d` is how all
three come back; until then their absence is what handoff.md section 7 says it
is — no membership sweep from a gateway connection, no thumbnails, no geocoder.

`TAG` is the image tag, read from `.env` (`TAG=dev` in `.env.example`). It names
the built image, not a registry: `build:` sits beside `image:` in every service
that builds, so `docker compose build` tags the result
`ghcr.io/macrophage87/routemaker-api:${TAG}` and
`ghcr.io/macrophage87/routemaker-pipeline:${TAG}` locally and the `worker`,
`migrate` and
`rebuild` services find it there. Bump it per release so a rollback is a `TAG`
change and `docker compose up -d --no-build` rather than a rebuild (see "A `TAG`
rollback runs what the local store holds" above) — and `up -d`
specifically, because the tag is baked into each container at creation:
`docker compose restart` restarts the containers that exist, on the image they
were created from, and so rolls nothing back. `up -d` re-reads `.env`, sees the
service's image has changed and recreates it, leaving everything else alone.

**Do not move `TAG` while a rebuild is running.** `up -d` recreates every
service whose image changed, `rebuild` among them, and recreating it stops the
running container: the worker takes a SIGTERM, Procrastinate waits for the job
rather than abandoning it (its `shutdown_graceful_timeout` is unset, so the
wait is unbounded), and the `stop_grace_period: 60s` on that service expires
into a SIGKILL. What is left is a `weekly_rebuild` row still `doing` with no
worker behind it — nothing retries it, the next Tuesday's tick refuses on it,
and the staleness alert is eight days out. No grace period covers a six-hour
build, so the rule is the schedule: release outside Tuesday 08:00 UTC and the
hours after it, check `docker compose ps rebuild` first, and if it has already
happened, `docker compose exec -T worker ./manage.py unwedge_job <job_id>`
moves the row back to `todo` (docs/OPERATIONS.md, "Wedged jobs").

`worker` declares the same `stop_grace_period: 60s` and wedges the same way on
a task of its own — a nightly dump or a sweep — with the same repair. And both
grace periods are why a `down` or an `up -d` taken while something is running
**takes about a minute to return**: that is the SIGTERM, the full wait, and
then the kill, not a command that has hung. The two services are stopped in the
same pass, so it is a minute and not two.

**Moving `TAG` back does not undo a migration.** Migrations are applied by the
`migrate` one-shot at every `up`, and nothing runs them backwards: `TAG` set to
the previous release and `docker compose up -d` puts the old code in front of
the new schema. That is
survivable only because every migration in this repository is required to be
backwards-compatible with the release before it (PLAN.md:65) — additive
columns, nullable or defaulted, no rename and no drop in the same release that
stops writing a column. The rule is stated and not enforced: nothing in the
suite reads a migration and refuses a `DROP COLUMN`, so it holds exactly as far
as whoever writes the migration honours it, and a release that breaks it cannot
be put back by moving the tag at all. handoff.md section 7 carries that as an
open row. Going back a release is also a deploy like any other: re-run
`collectstatic` after it, exactly as after a build, or Caddy keeps serving the
assets the newer release collected.

The `api` image builds three services. They differ only in the command compose
gives them: `api` takes the image's default (`gunicorn`), `worker` and `migrate`
override it with `./manage.py`.

## Secrets, and what rotating one costs

The four random values in `.env` — `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY`,
`PGPASSWORD` and `BOT_INTERNAL_SECRET` — are not interchangeable in how they
can be changed after the first `up`. Each of the three below is a procedure
rather than an edit.

**`PGPASSWORD`: change it inside the database first, then in `.env`.** The
postgis image only reads `POSTGRES_PASSWORD` when it initialises an empty
PGDATA. On every later start the directory is already there, the variable is
ignored, and the role keeps the password it was created with — so editing
`.env` alone leaves the file and the database disagreeing. The failure is worse
than a plain outage because the health gate does not see it: `pg_isready`
answers PQPING_OK for a server that is accepting connections, and it reports
the same for a connection the server would reject on the password. The gate
therefore goes green, `migrate` fails authentication, and `api`, `worker` and
`rebuild` — all held on `service_completed_successfully` — never start at all.
The stack comes up as Caddy and three routers, exactly the shape a wrong
`PGHOST` used to produce.

**That shape has two causes and this is only one of them.** The other needs
nobody to have rotated anything: a password that reaches compose through a
shell. `set -a; . ./.env; set +a` before a `docker compose` command — which is
what every snippet in this document used to open with — makes `$$` in a
password the shell's own process id rather than compose's literal-`$` escape,
so `hunter$$2` is `hunter47112` from the shell that ran the first `up` and
`hunter81330` from the next one, and an exported value beats the env file when
compose reads it. PGDATA keeps the first, the second fails authentication, and
what an operator sees is identical to the paragraph above: `pg_isready` green,
`migrate` refused, three services that never start. If you are reading this
because that happened, check whether the shell you ran `up` in had sourced
`.env` before you go looking for a rotation — see "`.env` is compose's input,
not the shell's" below, and use `docker compose config` to see the value
compose is actually about to send (it prints a literal `$` doubled, so decode
`$$` back to `$`).

The order that works:

```sh
docker compose exec -T postgis \
  psql -U routemaker -d routemaker \
  -c "ALTER ROLE routemaker WITH PASSWORD 'the-new-value';"  # 1. the database
# 2. then PGPASSWORD=the-new-value in .env
docker compose up -d                                         # 3. recreate
```

`routemaker` is `PGUSER`/`PGDATABASE` from `.env`, which ship as that and are
also the compose defaults; substitute your own if you changed them. Written out
rather than `"$PGUSER"`, because this document no longer sources `.env` into a
shell and an unset `$PGUSER` here is `psql -U ""`.

Step 1 runs under the *old* password, which the running container still holds
in its own environment, so it has to happen before step 2. `up -d` and not
`restart`: compose reads `.env` when it creates a container, so a restarted
container keeps the environment it was created with and the new value never
reaches it.

Write the value the way `.env.example` says to: if it contains a `$`, wrap the
whole value in single quotes (`PGPASSWORD='pa$w0rd'`), because compose's dotenv
reader strips the quotes and expands nothing between them. Written bare, `$w0rd`
is a variable name that expands to nothing and the role ends up with `pa` —
which is now the password in PGDATA, since `POSTGRES_PASSWORD` is only read
when the directory is initialised. And do **not** source `.env` into a shell on
the way: the shell has its own rules for `$`, `$$` and backticks, and an
exported value wins over the file.

**`DJANGO_SECRET_KEY`: rotating it signs every user out.** Sessions are
database-backed and their payload is signed with this key; `settings.py` sets
no `SECRET_KEY_FALLBACKS`, so every existing session fails to decode and is
discarded on the next request. Nothing is corrupted and nothing needs
repairing — every signed-in user is simply anonymous and signs in through
Discord again. Do it deliberately, at a quiet hour, and expect the support
question rather than being surprised by it.

**`KEY_ENCRYPTION_KEY`: not rotatable in phase 1.** It keys the ban
tombstones, the stored tombstone is the HMAC and nothing else, and there is no
second key path. See docs/DEVELOPMENT.md, "`KEY_ENCRYPTION_KEY` — required, no
default", for what a rotation would silently do.

**`DISCORD_CLIENT_SECRET`: rotate it at Discord first, then here, then
`up -d`.** It is not one of the four generated values — it is issued by the
Discord application and rotated in the developer portal, which invalidates the
old one immediately. Nothing is stored under it: `api` uses it once per sign-in
to exchange an authorization code for a token, reads the identify scope and
throws the token away, so a rotation costs nothing already signed in and there
is no re-encryption anywhere. The only window is between Discord issuing the
new secret and the container holding it, during which every `/auth/callback`
fails the code exchange and the user gets a sign-in refusal; it is seconds if
the `.env` edit is ready before the rotation.

`docker compose up -d`, **not** `docker compose restart`. Compose reads `.env`
when it *creates* a container; `restart` restarts the process the container
already has, with the environment it was created with, so the old secret stays
in place and the sign-in path stays broken with nothing in any log to say the
file was changed. That is the same distinction as `TAG` above and as
`BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` in docs/DEVELOPMENT.md, and it catches
people every time. `docker compose up -d api` is enough — it is the only
service that reads this.

**`BOT_INTERNAL_SECRET`** is shared between `api` and `bot`, and `bot` has no
image in phase 1, so there is nothing on the other end of it to disagree with
yet. When there is, both services read it from `.env` and both need recreating
in the same `up -d`.

## Log rotation

Every service in `compose.yaml` merges the `x-logging` anchor: the `json-file`
driver with `max-size: 10m` and `max-file: 5`. Docker's default for that driver
is no rotation at all, and the file it writes lives under
`/var/lib/docker/containers` on the **root** volume — the small one, the one
nothing in this stack binds and the one whose filling stops the daemon rather
than one container. The stack has no quiet logger: gunicorn runs with
`--access-logfile -`, so each request is a line; three `valhalla_service`
containers log per request; the weekly rebuild prints its way through six
hours. The ceiling is 50 MB per container and roughly 600 MB for the stack,
which is a figure chosen to fit beside the OS and the images rather than to
keep a month of history. What is kept deliberately is on the data volume: the
`ScheduledRun` rows behind the operations page, and the nightly dump.

Setting it per service rather than in `/etc/docker/daemon.json` is deliberate:
this repository configures the stack and not the host, and a daemon default is
a file that a rebuilt host does not have.

## What each image installs, and why

### `docker/api.Dockerfile` — api, worker, migrate

Python 3.11 on Debian bookworm, two stages: a `wheels` stage with a C toolchain
that builds every wheel, and a runtime stage that installs them from a local
directory and never sees a compiler.

- **`gdal-bin`** — GeoDjango needs GDAL, GEOS and PROJ as shared libraries.
  `settings.py` sets neither `GDAL_LIBRARY_PATH` nor `GEOS_LIBRARY_PATH`, so
  GeoDjango resolves both through `ctypes.util.find_library`, which reads
  ldconfig's cache. `gdal-bin` is named rather than `libgdal32` because the
  library package carries an ABI number that changes with the base image;
  `gdal-bin` pulls whichever libgdal the suite ships, and libgeos_c and libproj
  with it. A `RUN` in the image asserts that `find_library` resolves `gdal` and
  `geos_c` at build time, so a wrong package name fails the build rather than
  the first request.
- **`postgresql-client-16`**, from the PostgreSQL project's apt repository —
  `pg_dump` and `pg_restore` for the nightly backup
  (`config/procrastinate.py`, which dumps with `pg_dump -Fc` and reads the
  archive's table of contents back with `pg_restore --list`). Major 16 to match
  `postgis/postgis:16-3.4`: `pg_dump` refuses an archive from a server newer
  than itself, and a mismatch would be discovered at 07:00 UTC by the one job
  whose whole purpose is to be trusted. The image asserts both binaries' major
  version at build time.
- **`libpq5`** — for those two binaries. Django does not need it; the
  `psycopg2-binary` wheel carries its own libpq.
- **`gunicorn`**, plus the runtime Python set in `docker/requirements.txt`.

Runs as uid 10001, non-root.

### `docker/pipeline.Dockerfile` — rebuild

`FROM ghcr.io/valhalla/valhalla:3.5.1`, the same image and tag the three serving
containers run. The rebuild needs `valhalla_build_admins`,
`valhalla_build_timezones`, `valhalla_build_tiles`, `valhalla_build_extract`
(`pipeline/tiles.py`) and `valhalla_service` (the one-shot `trace_attributes`
readback that validates a build), so it is built from that image rather than
compiling Valhalla again — and building tiles with a different Valhalla than the
one that reads them is a tile-schema mismatch that surfaces as a routing failure
after promotion, not as a build failure. `tests/test_images.py` reads the tag out
of `compose.yaml` and holds the `FROM` to it.

The upstream image's runner stage is `FROM ubuntu:24.04`
(github.com/valhalla/valhalla, Dockerfile at tag 3.5.1), so these are noble
package names:

- **`python3-venv`, `python3-pip`** — the upstream runner carries
  `python3-minimal` and no pip, and Ubuntu 24.04 marks its system interpreter
  externally managed (PEP 668), so the project installs into `/opt/venv`, which
  goes first on `PATH` so `manage.py`'s `#!/usr/bin/env python3` resolves to it.
- **`gdal-bin`** — `gdalwarp`, which `pipeline/elevation.py` shells out to for
  every one-degree HGT tile in the coverage box. The upstream runner has
  `libgdal34`, the shared library, and none of the binaries.
- **`osmium-tool`** — the `osmium` command line, for the source-extract stage
  (`osmium merge`, `osmium extract -s smart -S types=any`). This is a different
  thing from the `osmium` **Python** module in `docker/requirements.txt`, which
  is pyosmium and is what `pipeline/extract.py` imports. Both are needed.
- **`sqlite3`** — the CLI, to query `tz_world` in the built timezone database.
- **`curl`, `unzip`, `spatialite-bin`** — `valhalla_build_timezones` is a shell
  script that curls the timezone-boundary-builder release, unzips it, and loads
  the shapefile with `spatialite_tool` and `spatialite`; it checks for
  `spatialite` and `unzip` by name and exits if either is missing. The upstream
  runner already installs all three, and they are named here anyway: an
  inherited package is a dependency nobody declared, and an upstream base change
  would remove it silently.
- **`libpq5`, `ca-certificates`** — the database driver's non-binary path, and
  the https fetch of HGT tiles.

**LuaJIT is not installed and does not need to be.** Valhalla links the Lua tag
transform against `libluajit-5.1-2`, which the upstream image's *runner* stage
installs (its own `apt install` line in the 3.5.1 Dockerfile), and calls it in
process. The standalone `luajit` interpreter appears only in upstream's
`scripts/install-linux-deps.sh`, which runs in the **builder** stage, so the CLI
is absent from the runner — which matters for running `tests/lua/` on a
developer machine and not for this image.

A `RUN` asserts every binary the rebuild shells out to is on `PATH` at build
time. The quiet failure that guards against is a stage that runs, finds no
binary, and is reported as a rebuild failure six hours in.

Runs as uid 10001, non-root.

### The two images with no source

`ghcr.io/macrophage87/routemaker-renderer:${TAG}` is PLAN.md:63's thumbnail
renderer, "a small Node
sidecar using `@maplibre/maplibre-gl-native`". There is no Node service source
in the repository: `frontend/` holds one stress-style module and its test, and
`scripts/` holds five Python scripts and a shell script.
`ghcr.io/macrophage87/routemaker-bot:${TAG}` is handoff.md section 7's first row — no bot source, no gateway handler, no
ingest route.

Neither has a Dockerfile and neither has a `build:`, because writing one would
mean inventing the service. `tests/test_images.py` records both in an explicit
allow-list and asserts that they still have no source; the moment either one
lands, that test fails, the row leaves the list, and the test above it demands a
`build:`.

## `${DATA_ROOT}` and the order it has to be prepared in

Both images run as uid 10001. `${DATA_ROOT}` is a host bind mount, and the
processes write into it: the nightly dump into `${DATA_ROOT}/backups`, the
rebuild into the five directories it binds under `/data` (tiles, extracts,
reference, its own work directory, and the elevation cache — the timezone
database `valhalla_build_timezones` writes goes into the work directory beside
them).

### `.env` is compose's input, not the shell's

**Nothing in this document sources `.env`, and nothing you run before
`docker compose` should either.** It used to open with
`set -a; . ./.env; set +a`, on the reasoning that `$DATA_ROOT` had to come from
somewhere, and the cost of that was every *other* value in the file going
through a shell on its way to compose:

- `$$` is a literal-`$` escape to compose's parser and the shell's own process
  id to `sh`, so `PGPASSWORD=hunter$$2` becomes `hunter47112` in one shell and
  `hunter81330` in the next;
- backticks and `$(...)` in a value are commands the shell runs;
- and an exported variable **wins over the env file**, so whatever the shell
  made of the value is what compose uses.

The way that lands is an outage that does not look like one. The first
`up` initialises PGDATA with whatever this shell produced; the next `up -d`,
from a different shell, sends a different string; `pg_isready` reports
PQPING_OK either way, `migrate` fails authentication, and `api`, `worker` and
`rebuild` — all held on `service_completed_successfully` — never start. That is
the same stack-comes-up-as-Caddy-and-three-routers shape described under
`PGPASSWORD` above, and it happens without anybody having rotated anything.

So the two places that genuinely needed `$DATA_ROOT` each get it another way:

- `scripts/prepare_data_root.sh` takes `--env-file ./.env` and reads the one
  `DATA_ROOT=` line out of it with `sed`. It does not evaluate the file, so a
  password containing `$` or a backtick is a string it never touches.
- `collectstatic` runs under `docker compose run`, which gives the container
  the `api` service's own environment and mounts — no `-v` built out of a shell
  variable at all.

For the handful of host-side snippets that still want the path (creating
`reference/inputs`, copying GeoJSON in), export **that one variable** by hand:

```sh
export DATA_ROOT=/srv/routemaker/data   # the same value as DATA_ROOT in .env
```

It is a path rather than a secret, and typing it is what keeps the rest of the
file out of the shell. Do not skip it and do not guess.
`sudo chown -R 10001:10001 "$DATA_ROOT"` with `DATA_ROOT` unset is
`chown -R 10001:10001 ""`, and with a stray trailing slash or an empty value in
a shell that word-splits it, the argument that reaches `chown` can be `/`.
Recursively chowning the root filesystem ends the host.
`scripts/prepare_data_root.sh` refuses to run without `DATA_ROOT` resolving to
an absolute path for exactly this reason; the manual form has no such guard.

### The directories have to exist, as 10001, before the first `up`

```sh
sudo sh scripts/prepare_data_root.sh --env-file ./.env
```

`--env-file` rather than `sudo -E` with a sourced `.env`, for the reason above:
the script wants one path out of that file and has no business receiving the
deployment's secrets to get it. `DATA_ROOT` already exported also works, and
`--env-file` wins if both are given.

The `chown -R` this replaced was correct and useless, because of when it ran. A
bind mount whose source does not exist on the host is not an error: **the Docker
daemon creates it, as a directory, owned by root**, because the daemon is root.
So on a fresh host the sequence was

1. `install -d` and `chown -R` over a `${DATA_ROOT}` that is empty — there is
   nothing in it to chown yet;
2. `docker compose up -d`, at which point the daemon manufactures
   `${DATA_ROOT}/backups`, `${DATA_ROOT}/static`, `${DATA_ROOT}/elevation`,
   `${DATA_ROOT}/photon`, `${DATA_ROOT}/caddy` and
   `${DATA_ROOT}/tiles/{standard,no-trail,ebike}/current` as `root:root`;
3. every container that runs as 10001 finds a directory it cannot write.

The script creates all of them first. `tests/test_deploy_docs.py` reads the
`${DATA_ROOT}` bind mappings out of `compose.yaml` and fails if the script's
list stops covering them, so a mount added to the stack cannot be forgotten
here.

**It creates every one of them and chowns only the seven this project's own
images write** — `static`, `backups`, `elevation`, `tiles`, `extracts`,
`reference` and `rebuild`. Three are left as they are, and that is the point
rather than an omission:

- `postgres/` is PGDATA. The postgis image's entrypoint chowns it to its own
  uid on every start, so a chown here is undone at best.
- `caddy/` holds the ACME account key and the deployment's TLS private key.
  Caddy runs as root and obtains them itself.
- `photon/` belongs to an image that is not ours and to a service parked behind
  the `unbuilt` profile.

The script used to end in `chown -R 10001:10001 "$DATA_ROOT"`, which swept all
three into the uid that every container of ours runs as — including, until this
wave, a `rebuild` service that bound the whole volume and could therefore read
the private key and the database's files. Both halves of that are now narrowed:
the mount is five directories and the chown is seven.

`docker compose down -v` destroys nothing durable here. Every stateful path in
`compose.yaml` is a host bind mount under `${DATA_ROOT}` and there are no named
volumes at all, so `-v` has nothing of this deployment's to remove — the
database, the certificates, the tiles and the dumps are files on the data
volume and outlive any `down`. What removes them is `rm`.

**If you have already run `up` without doing this**, the remedy is the obvious
one and it is worth knowing it is that simple: stop the stack, run the same
script again now that the directories exist, and start it again. It is
idempotent, and it is the remedy rather than
`sudo chown -R 10001:10001 "$DATA_ROOT"`, which is what this section used to
give: `${DATA_ROOT}` also holds `caddy/` — the ACME account key and the
deployment's TLS private key — along with `postgres/` and the nightly dumps in
`backups/`, and a recursive chown of the root hands all three to the uid every
one of this project's containers runs as. The script chowns the seven
directories those containers write and leaves `postgres/`, `caddy/` and
`photon/` alone. What makes this worth a section is not the difficulty of the fix
but how the failure presents — a permission error from a Valhalla binary six
hours into a rebuild, or a nightly dump that fails on a file it cannot create,
neither of which reads as an ownership problem to whoever is paged for it.

## Moving `${DATA_ROOT}` to a bigger disk

The volume is sized for a second full tile set beside the current one, and the
gate that enforces it (`REBUILD_MIN_FREE_BYTES`, 20 GiB by default) refuses a
rebuild rather than filling the disk. Growing a gp3 volume in place is an online
resize and is the first answer. Moving to a different disk is the second, and it
has one rule:

**Stop the stack first. PGDATA is live.** `${DATA_ROOT}/postgres` is the
database's own data directory, bound straight into the postgis container, and
copying it out from under a running server produces a copy that is neither a
backup nor a filesystem-consistent snapshot — PostgreSQL is writing into it
while `cp` reads it.

```sh
export DATA_ROOT=/srv/routemaker/data          # the current one
docker compose down                            # everything, including postgis
sudo cp -a "$DATA_ROOT/." /mnt/bigger/routemaker/data/
# then DATA_ROOT=/mnt/bigger/routemaker/data in .env
sudo sh scripts/prepare_data_root.sh --env-file ./.env
docker compose up -d
```

`cp -a` and not `cp -r`: ownership and modes are the point. Everything under
there is owned either by uid 10001 (the seven directories this project's images
write) or by the postgis image's own uid (`postgres/`), and `${DATA_ROOT}/caddy`
holds a private key whose mode matters. Re-running the prepare script afterwards
is belt and braces — it creates anything the copy missed and re-asserts the
ownership of the seven, and it touches `postgres/`, `caddy/` and `photon/`
never.

Nothing else has to change. Every path in `compose.yaml` is `${DATA_ROOT}/...`,
every path *inside* a container is `/data/...` and unaffected, and the tile
symlinks under `tiles/<variant>/current` are relative to their own directory, so
they survive the move. `docker compose up -d` recreates every container whose
bind sources changed, which is all of them; `restart` would not, for the usual
reason.

Verify before deleting the old copy: `docker compose ps` all up,
`docker compose exec -T worker ./manage.py check_operations` naming the new path
in its free-space line, and — if tiles were already built — a route. Then `rm`
the old tree.

## Bumping the `postgis` image

`docker.io/postgis/postgis:16-3.4` is a floating patch tag: it is PostgreSQL 16
and PostGIS 3.4, and the image behind it moves as both are patched. A
`docker compose pull postgis && docker compose up -d postgis` therefore picks up
patch releases of each, and that is the ordinary case — it is a restart of the
database and nothing more.

**A PostGIS patch or minor bump wants one statement afterwards.** The extension
in the database keeps the version it was created or last updated with, and the
new image's shared library and its SQL definitions are ahead of it. That
mismatch is not loud; it shows up as functions behaving as the old version did.

```sh
docker compose exec -T postgis \
  psql -U routemaker -d routemaker -c "ALTER EXTENSION postgis UPDATE;"
docker compose exec -T postgis \
  psql -U routemaker -d routemaker -c "SELECT postgis_full_version();"
```

**A PostgreSQL major bump — 16 to 17 — is a dump and restore, not a pull.**
PGDATA's on-disk format is major-version-specific: a 17 server started against a
16 data directory refuses with "database files are incompatible with server" and
the container crash-loops. There is no in-place path in this stack (`pg_upgrade`
is not in the image, and would want both binaries side by side), so it is:

1. take a dump **with the old image still running**, through the ordinary
   nightly path or by hand;
2. `docker compose down`, move `${DATA_ROOT}/postgres` aside — do not delete it
   until the new one is serving;
3. change the tag in `compose.yaml`, `docker compose up -d postgis`, let it
   initdb a fresh PGDATA;
4. restore into it, exactly as "Restoring one" in docs/OPERATIONS.md has it —
   into the empty database, before `migrate` runs;
5. `docker compose up -d`, then `collectstatic`.

**The dump has to come from the old server, and the `pg_dump` has to be at
least as new as it.** `pg_dump` refuses an archive it does not understand and
`pg_restore` refuses one from a *newer* major than its own. The nightly dump is
taken inside `worker`, whose image pins `postgresql-client-16` to match the
server major — so bumping the server major means bumping that pin in
`docker/api.Dockerfile` in the same change, and taking the dump before the
client is bumped or with a client of the new major against the old server
(which is allowed; the other direction is not).

Neither of these has been executed here: there is no daemon in this environment
and no server has ever run from this file. The refusals quoted are PostgreSQL's
documented behaviour, not a transcript.

## Changing posture on a running stack: `:80` to a hostname

The five values that make a deployment plain-HTTP-local or named-and-HTTPS are
one decision (see "Why the example is a hostname and not `:80`"), and changing
them on a stack that is already up is a sequence rather than an edit.

**DNS first.** A hostname commits Caddy to obtaining a certificate for it from
Let's Encrypt the moment the config loads, and that validation is an inbound
request to this host on port 80. So the name has to resolve here, and 80 and 443
have to be reachable from outside, **before** the stack comes up with the new
address. Out of order, Caddy retries with a backoff and the site serves nothing
usable in the meantime — and repeated failures against the same name burn Let's
Encrypt rate limits, which are per name and per week.

Then all five lines in `.env`, together:

```sh
CADDY_SITE_ADDRESS=routes.example.org
DJANGO_ALLOWED_HOSTS=routes.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://routes.example.org
DISCORD_REDIRECT_URI=https://routes.example.org/auth/callback
# and DJANGO_DEBUG deleted or emptied
```

`DJANGO_DEBUG` is the one that is easy to leave behind, and it is the one that
matters most: the local block sets it because `settings.py` derives
`SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` from `not DEBUG` and a
plain-HTTP browser discards a Secure cookie. Left set under a hostname, the
deployment serves tracebacks with its settings in them to the internet and
issues cookies that are not Secure over a connection that is.

**Register the new redirect URI on the Discord application** before anyone
tries to sign in. It has to match character for character; Discord refuses an
authorize request whose `redirect_uri` is not on the list, and the failure is on
Discord's page rather than in any log here. Leave `http://localhost/auth/callback`
registered alongside it if the same application also serves a local stack.

Then:

```sh
docker compose up -d
```

**`up -d`, not `restart`.** Compose reads `.env` when it creates a container, so
`restart` gives every service the environment it already had: Caddy would keep
serving `:80` and the api would keep the old `ALLOWED_HOSTS`. `up -d` sees the
changed values, recreates `caddy` and `api`, and leaves the rest alone.

Changing `CADDY_SITE_ADDRESS` alone is the failure worth naming, because it
half-works: Caddy gets its certificate and serves the name, and then **every
request is a DisallowedHost 400** because `DJANGO_ALLOWED_HOSTS` still says
`localhost`. The site is up, the padlock is there, and nothing renders. The same
edit without `DJANGO_CSRF_TRUSTED_ORIGINS` gets through to the pages and refuses
every POST.

Going the other way — a named stack back to `:80` — is the same five lines in
reverse plus `DJANGO_DEBUG=1`, and it is for a laptop. Never on a host reachable
from outside.

## Adding a second instance admin

There is no "add" button on the user page, and that is deliberate rather than
missing: accounts are created by signing in, never by an admin typing an id.

1. **They sign in first.** Send them to `<your host>/auth/login` and have them
   complete the Discord round-trip once. They will get the admin's ordinary 404
   if they go looking for it — that is what an account with no standing gets —
   but the sign-in creates the `core.User` row, which is the thing that has to
   exist.
2. **Then an existing instance admin promotes them**, at
   `<DJANGO_ADMIN_PATH>core/user/` — `/internal-8f3a/core/user/` with the
   default path. Find the row by Discord id (the list searches on it), open it,
   tick **is instance admin**, save. Every other field on that page is
   read-only, there is no add and no delete, and the save is audited.
3. They sign out and in again, or simply reload: standing is resolved per
   request, so the next request after the save already has it.

The list is only readable by an instance admin in the first place, so step 2 is
something only an existing one can do — which is the whole reason
`BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` exists for the first one
(docs/DEVELOPMENT.md).

Removing one is the same page, unticked, and it is **not** immediate for anyone
but yourself: removing another instance admin schedules it
`INSTANCE_ADMIN_REMOVAL_DELAY_SECONDS` ahead (an hour by default) and any
instance admin can cancel it at
`<DJANGO_ADMIN_PATH>core/pendinginstanceadminremoval/` in the meantime.
Removing yourself takes effect at once. The application refuses to remove the
last one by any path it controls.

## Host requirements

PLAN:293's initial host: **8 vCPU, 32 GB RAM**, with storage split — a small
root volume for the operating system, the Docker images and the checked-out
code, and a **separate 200 GB gp3 data volume**, growable, mounted at
`${DATA_ROOT}`. Every bind in `compose.yaml` is under that mount, which is the
property that makes the root volume disposable and the data volume the only
thing that needs a snapshot.

Both figures are load-bearing rather than aspirational, and each has something
in the repository that assumes it:

- **32 GB.** `scripts/check_compose_limits.py` carries `HOST_RAM_GB = 32` and
  fails if the sum of the compose memory limits, including the duplicate
  Valhalla containers resident during a swap, exceeds it. It runs in the suite
  (`tests/test_compose.py`). A smaller host does not produce a warning: it
  produces an OOM kill of whichever container the kernel picks, during a
  rebuild, which is when the stack is at its peak.
- **8 vCPU.** The CPU limits are written against it — the rebuild takes 4, half
  the machine, so that a six-hour build does not saturate every core and destroy
  the preview latency target. On a 4-vCPU host those limits over-subscribe the
  machine rather than bounding anything.
- **200 GB.** `REBUILD_MIN_FREE_BYTES` defaults to **21474836480 — 20 GiB** —
  and is the rebuild's hard gate: a rebuild refuses to start unless that much is
  free on the data volume, because the volume has to hold two full tile sets at
  swap time plus the extracts and the build scratch. The gate is a refusal, not
  a warning, so an undersized volume is a deployment that never rebuilds. Growing
  a gp3 volume is an online resize and is the first response to the gate firing.

## Photon

`photon` is pinned to `docker.io/rtuszik/photon-docker:2.4.0` — the newest release
tag on
Docker Hub when this was written (pushed 2026-08-17; `latest`, `2` and `2.4` all
resolved to the same digest, which is how the tag was chosen). It was on
`latest`, which is not a pin: PLAN:293 says all images pinned, and a
`docker compose pull` would otherwise bring in whatever that repository's
maintainer had pushed since, with no change in this repository to point at.

**It is behind the `unbuilt` profile, so a default `up` does not start it**, and
the reason is not that it is idle. It is what the pinned image does on a fresh
host, read out of that tag's own source (github.com/rtuszik/photon-docker at
2.4.0):

- `src/utils/config.py:23` defaults `INITIAL_DOWNLOAD` to `True`, and `REGION`
  is unset in this stack, so the entrypoint's first act is to fetch the
  **whole-planet index** — about 61 GB compressed, and around 104 GB free
  needed to unpack it.
- `src/utils/config.py:36` puts that index at `/photon/data`. This stack mounted
  `${DATA_ROOT}/photon` at `/photon/photon_data`, which is the 1.x path, so the
  mount was **inert**: the download would have landed on the container's
  writable layer, on the *root* volume, which the host requirements above size
  small on purpose and which carries the OS, the images and the checkout.
- Short of that space the entrypoint exits 75, and `restart: unless-stopped`
  turns that into a crash loop starting with the operator's first `up` on every
  new deployment.

So the profile is the fix for the first `up`, and two corrections beside it are
what make enabling the profile safe rather than a 61 GB surprise: the mount
target is now `/photon/data`, so an index lands on the data volume where it was
always meant to, and `INITIAL_DOWNLOAD: "False"` means nothing is fetched until
somebody populates the index deliberately.

**Nothing in phase 1 calls Photon, and its index is empty.** PLAN:60 populates
it "from GraphHopper's per-country Photon dump filtered to the coverage bounding
box or from a one-off Nominatim import of the clipped extract, documented as the
heavier option" — neither is built here, there is no script for either, and
nothing in the repository writes into `${DATA_ROOT}/photon`. There is also no
API route to it: the geocoding proxy PLAN:65 describes — Photon behind session
authentication and a per-user rate limit — is not built either. handoff.md
section 7 carries the row. `docker compose --profile unbuilt up -d` starts it
the day there is an index to serve, alongside the bot and the renderer, which
sit behind the same profile for the simpler reason that they have no image at
all.

`scripts/check_compose_limits.py` still counts its 3 GB, and that is deliberate:
the script reads `compose.yaml` rather than a rendered configuration, and it
answers "does this stack fit in 32 GB", not "does today's `up` fit". A profile
is a service that is one flag away from being resident — `renderer` and `bot`
are counted on the same reasoning — so charging all three keeps the sizing
answer true for the day somebody enables them, at the cost of 4.5 GB of
pessimism in a total that has room for it (27.0 GB resident, 25.0 GB at the
blue/green swap peak, against the 32 GB the script fails at).

## What the deployment serves

`/` is a 404, and that is not a fault: `config/urls.py` routes three auth paths
and the admin, and nothing else. Phase 1 has no frontend to serve there
(`frontend/` is one module and its test), so there is no landing page and the
stack is not broken for lacking one.

- **`/auth/login`** is the sign-in entry, and the only one. It starts the
  Discord authorize round-trip; `/auth/callback` finishes it and must match the
  redirect URI registered on the Discord application exactly.
- **`<DJANGO_ADMIN_PATH>`**, `internal-8f3a/` by default, is the admin — and
  with it the operations page at `<DJANGO_ADMIN_PATH>core/scheduledrun/`. It is
  the only usable surface a first deployment has. The non-obvious path is
  obscurity rather than a control: the disabled login form, the derived staff
  resolution and the per-object checks are what protect it.
- **`/static/*`** is served by Caddy from the collected assets, and by nothing
  else.

So a first deployment that reaches `/`, gets a 404 and concludes the stack is
down has concluded wrongly. `/auth/login` is the check.

## Static assets — a deploy step, and it works now

PLAN.md:64: the React frontend is built to static assets, "and Django's admin and
Ninja assets are collected into the same named volume, which Caddy serves; both
are rebuilt on deploy and after a restore." Caddy mounts `${DATA_ROOT}/static` at
`/srv/static:ro`.

There is no build-time `collectstatic` in `docker/api.Dockerfile`, for a reason
that is not going away: `settings.py` raises `ImproperlyConfigured` without
`KEY_ENCRYPTION_KEY`, so any build-time management command would need the
deployment's real secret as a build input, and a secret in a build argument is a
secret in the image's metadata. `collectstatic` is a deploy step, run after every
`docker compose build` and after a restore:

```sh
docker compose run --rm api ./manage.py collectstatic --noinput
```

That is the whole command, and the reason it has no flags is that `compose.yaml`
carries what it needs: the `api` service declares `DATA_ROOT: /data` and binds
`${DATA_ROOT}/static` at `/data/static`, so `settings.STATIC_ROOT` inside the
container is `/data/static` and that is the host directory Caddy serves from.
`docker compose run` gives the one-off container the service's own environment
and mounts, and compose fills `${DATA_ROOT}` in from `.env` itself.

It used to carry `-e DATA_ROOT=/data` and a `-v` mount of
`"$DATA_ROOT/static"`, preceded by a line that sourced `.env` into the shell to
fill that variable in. Both halves were a way to get this wrong. Sourcing the
file hands every value in it to the shell on the way to compose, which is the
thing this document no longer does anywhere (see "`.env` is compose's input,
not the shell's" above). And skipping the sourcing left `$DATA_ROOT` empty, so
the `-v` argument became `/static:/data/static` — a directory at the **host's**
root — and the command reported the files it copied while Caddy went on serving
nothing.

`settings.STATIC_ROOT` is now `DATA_ROOT / "static"` — the same host directory
Caddy mounts at `/srv/static`, so the assets land where the edge serves them from
and nowhere else. Until it was set the command above could not run at all:
`collectstatic` refuses without a `STATIC_ROOT` and it is not overridable from
the command line, so the admin rendered unstyled.

The two flags are both load-bearing, and the earlier version of this command had
neither right. `-v` alone mounted the host directory at `/srv/static`, which is
**Caddy's** path and not this container's: the api service then mounted no part
of the data volume and set no `DATA_ROOT`, so inside the image
`settings.DATA_ROOT` fell back to `BASE_DIR / "data"` and `STATIC_ROOT` with it — `/app/data/static`, on the
container's writable layer, discarded when `run --rm` exits. The service's own
`DATA_ROOT: /data` and its `${DATA_ROOT}/static:/data/static` bind are what make
the two agree by construction now, which matters because the failure was silent:
the command reported the files it copied and the volume stayed empty.

### What the api mounts, and why it is still not where data commands run

The api binds two directories and writes one of them:

| Path | Mode | Who reads it |
| --- | --- | --- |
| `${DATA_ROOT}/static` → `/data/static` | read-write | `collectstatic`, as the deploy step above. Caddy mounts the same directory `:ro` and serves it. |
| `${DATA_ROOT}/tiles` → `/data/tiles` | **read-only** | the operations page's free-space line, which is a `statvfs` on `settings.TILES_DIR`. |

The tiles bind is read-only and it is there for one reader. The operations page
is rendered by the `api` service, and its free-space block measures
`settings.TILES_DIR` — so without the mount it measured `/app/data/tiles`, a
path nothing creates, `statvfs` walked up to `/`, and the page reported the
**container's own writable layer** as the room the next rebuild has. A positive
statement about a filesystem the process could not see. Read-only because a
`statvfs` is the whole of what it does with it; the promotion symlinks under
that directory belong to `rebuild`.

Neither of those makes the api the place to run a data command, and that has
not changed. It holds none of the other four directories the rebuild writes —
`elevation`, `extracts`, `reference`, `rebuild` — and it has no Valhalla or
GDAL binaries at all. Every management command that reads or writes the data
volume therefore runs in `rebuild`, which binds all five under `/data`, or in
`worker`, which binds `${DATA_ROOT}/backups` there and `${DATA_ROOT}/tiles`
read-only beside it:

| Command | Container | Because |
| --- | --- | --- |
| `rollback_rebuild` | `rebuild` | Rewrites the promotion symlinks under `/data/tiles`, which only `rebuild` binds read-write. `api` and `worker` bind the same directory read-only, and there the command refuses on a write probe of every variant's directory — dry run included — naming the directory and the container to use, before anything is renamed or moved. |
| `run_rebuild_now` | `rebuild` | Queues the job for the service that owns the data mounts. It only writes a row, so any Django container could defer it, but the run it starts belongs there. |
| `install_reference_data.py` | `rebuild` | Writes `<DATA_ROOT>/reference/`, and reads the extract under `<DATA_ROOT>/extracts/`. |
| `check_operations` | `worker` | Three of its four checks read the database only; the fourth is a `statvfs` on `TILES_DIR`, which `worker` now binds read-only — in a container that does not mount it, the check reports `not measured` and exits 1 rather than measuring the container's own layer. `worker` rather than `rebuild` because this runs every ten minutes: in `rebuild` each tick spawned a ~95 MiB process **inside the rebuild's 8 GB cgroup**, six times an hour, including during the six-hour build that limit is sized for, and `rebuild` is also the container an `up -d` recreates — while `worker` is up whenever the stack is. The cron entry in docs/OPERATIONS.md has to `cd` into the directory holding `compose.yaml` first — cron runs from the owner's home directory, where `docker compose` finds no project and exits 1 every tick. |
| `unwedge_job` | `worker` | Reads and updates the job table only, so any Django container works; `worker` is the one that is up whenever the stack is, including while `rebuild` is the container being restarted. |

The frontend half of that sentence has no source either: `frontend/` is a single
module and its test, with no React application, no bundler and no build script,
so there is nothing to build into the volume yet. Only the admin's and Ninja's
assets reach the volume today.

## The admin map widget

The jurisdiction pages in the admin edit a polygon by drawing on a map, which is
PLAN.md:52's reason for choosing Django. GeoDjango's default widget builds that
map out of two things this deployment will not have: OpenLayers loaded from
`cdn.jsdelivr.net` — a third party's script running in an instance admin's
authenticated session — and tiles from the public OpenStreetMap servers, which
PLAN.md:15 rules out in as many words.

So OpenLayers is vendored. `src/core/static/core/ol/` holds the build the
installed Django's widget expects, with the release URL and the sha256 of each
file in the `SOURCE` file beside them; it reaches the browser through the same
`collectstatic` step as the rest of the admin's assets, from the same
`/srv/static` Caddy already serves. Nothing else is needed at deploy time, and
the admin makes no request off this deployment's origin.

The basemap under the polygon is a separate question, and in phase 1 the answer
is that there is not one. The PMTiles extract and the renderer are unbuilt, so
the widget draws the geometry over a plain background and requests no tiles at
all. That is the shipped configuration rather than a broken one: the draw,
modify and delete controls are OpenLayers' own and an instance admin can edit a
boundary without any imagery under it.

A deployment that does have tiles — its own renderer once there is one, or a
server the operator has chosen and is entitled to use — sets
`ADMIN_BASEMAP_TILE_URL` to a standard XYZ template, for example
`https://tiles.example.org/basemap/{z}/{x}/{y}.png`, and the widget draws one
XYZ layer from it. The variable is optional, has no default, is read by the
`api` service alone, and is commented out in `.env.example`. `compose.yaml` does
not pass it through to `api` yet — `tests/test_compose.py` records that in its
allow-list — so a deployment that needs it adds that line at the same time.

## The edge: `Caddyfile` and `CADDY_SITE_ADDRESS`

`compose.yaml` bind-mounts `./Caddyfile` at `/etc/caddy/Caddyfile:ro`. The file
did not exist, and Docker creates a *directory* at a missing bind-mount source,
so this was not a startup error — Caddy came up against a directory where it
expected a config and served nothing. It exists now, and `tests/test_deploy_surface.py`
holds every value in it that is also written somewhere else.

Caddy is the only service that publishes a port (PLAN.md:65) and **the only thing
that terminates TLS**. Nothing downstream speaks TLS: gunicorn listens on plain
HTTP inside the compose network, so Django would see every request as insecure —
which fails the CSRF origin check on https form posts and builds `http://`
redirects — if the proxy did not say otherwise. The reverse proxy therefore sets
`X-Forwarded-Proto`, which is the header `settings.SECURE_PROXY_SSL_HEADER`
(`HTTP_X_FORWARDED_PROTO`) reads. The `header_up X-Forwarded-Proto {scheme}`
line in the Caddyfile is documentary rather than load-bearing: Caddy's
`reverse_proxy` sets `X-Forwarded-Proto`, `X-Forwarded-For` and
`X-Forwarded-Host` by default and the explicit line sets it to the same value.
It stays because the setting it satisfies is in a different file and one of
this pair going missing would be a silent `request.is_secure()` of false, and
`tests/test_deploy_surface.py` derives the header name from
`SECURE_PROXY_SSL_HEADER` and checks the proxy sets it. That setting is safe only while nothing but
Caddy can reach the API, which is exactly what the no-published-ports rule
enforces.

It sets one header on everything it serves:
`Strict-Transport-Security: max-age=31536000`. Under the hostname posture Caddy
already redirects `http` to `https`, and HSTS is what removes the plaintext
round trip that redirect *is* — for a browser that has been here before and
whose user types the bare name or follows an old `http://` link. It is at the
site level, so it covers the static responses as much as the proxied ones, and
it is harmless under the `:80` posture: RFC 6797 section 8.1 requires a browser
to ignore this header on a response that did not arrive over a secure
transport, so a local plain-HTTP stack neither pins anything nor breaks.

Deliberately without `includeSubDomains` and without `preload`. The first makes
every sibling name under the same domain HTTPS-only for a year; the second is a
submission to a list browsers ship and which is slow to leave. Neither is a
commitment this repository can make on behalf of whoever runs it — add them in
your own deployment if the domain is yours alone.

**This one was executed.** Caddy 2.8.4 — the minor the `caddy:2.8-alpine` image
tracks — was run against this file on both postures: `caddy validate` accepts
it, and a live server started from it returned
`Strict-Transport-Security: max-age=31536000` on a static file and on a proxied
path (a 502, with the api absent, which is the point: the header is the site's
and not the upstream's). Everything else below is still read as text.

The file routes two things and no more:

- `handle_path /static/*` → `file_server` rooted at `/srv/static`, matching
  `STATIC_URL = "static/"` and the mount above. `handle_path` rather than
  `handle` because the matched prefix has to be stripped before the file server
  sees the path. It does not shadow the admin, which mounts under
  `DJANGO_ADMIN_PATH` (`internal-8f3a/` by default).
- everything else → `reverse_proxy api:8000`, the port
  `docker/api-entrypoint.sh` binds gunicorn to.

Photon, Valhalla and the renderer have no route here on purpose. PLAN.md:65: they
are "reachable only through the API", which proxies geocoding behind session
authentication and a per-user rate limit Photon has no notion of a user to
enforce for itself. A `reverse_proxy` to any of them would put an unauthenticated
geocoder, router or renderer on the public internet, and the suite fails if one
appears.

### `CADDY_SITE_ADDRESS`

The site address is the one variable the caddy service takes, read by the
Caddyfile through Caddy's own `{$VAR}` substitution (evaluated when the config
loads, not by compose), so one file serves both the deployment and a local stack.
Its compose-side default is `:80`; **`.env.example` ships `routes.example.org`**,
and that is a deliberate change of posture rather than a placeholder left in by
accident.

```sh
CADDY_SITE_ADDRESS=routes.example.org   # a hostname: automatic TLS from Let's Encrypt
CADDY_SITE_ADDRESS=:80                  # local: plain HTTP, no certificate at all
```

A hostname commits Caddy to obtaining a certificate for it, so the name has to
resolve to the host and ports 80 and 443 have to be reachable from outside before
the stack comes up. `compose.yaml` still defaults to `:80` for that reason: a
hostname guessed *there* would be a certificate request for somebody else's name
on every host that ran this stack, whereas a hostname in `.env.example` is a
value the operator is already replacing with their own.

### Why the example is a hostname and not `:80`

**The `:80` example that shipped before this one could not hold a session.**
`settings.py` derives `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` from
`not DEBUG`, so with `DJANGO_DEBUG` unset — which is what the example had — every
cookie the site issues is marked `Secure`, and a browser talking plain HTTP to a
`:80` stack silently discards both. The Discord round-trip completes, the
callback sets a session cookie, the browser drops it, and the next request is
anonymous. Nothing logs an error, because nothing went wrong on the server.

Two more values disagreed with it: `DISCORD_REDIRECT_URI` named
`http://localhost:8000`, a port no service in the stack publishes — Caddy
publishes 80 and 443 and is the only service with a `ports:` entry — and
`DJANGO_CSRF_TRUSTED_ORIGINS` was `https://localhost` against an `http` origin,
which refuses every POST the site makes.

So the four values are one decision, and the example now makes it once: a
hostname deployment over HTTPS, with `CADDY_SITE_ADDRESS`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS` and `DISCORD_REDIRECT_URI` all naming
`routes.example.org`, which the operator replaces with their own name in four
places. A plain-HTTP local stack is a clearly separated commented block at the
end of the file: `:80`, `DJANGO_DEBUG=1`, `http://` origins and
`http://localhost/auth/callback` — five lines, taken together or not at all.

`tests/test_compose_render.py` holds the shipped file to it: the redirect URI's
host has to be in `DJANGO_ALLOWED_HOSTS`, its scheme-and-host in
`DJANGO_CSRF_TRUSTED_ORIGINS`, and its port one the rendered stack actually
publishes — and a `:80` site address without `DJANGO_DEBUG=1` is refused
outright, because the example has to work as shipped rather than work once its
reader has noticed a warning.

**Caddy has never run in this environment.** There is no Caddy binary here and no
Docker daemon, so the Caddyfile has not been parsed by Caddy, let alone served a
request. The tests read it as text.

## Known blockers on `docker compose up`

Building the images is necessary and not sufficient. Three things in the
repository stopped or silently misconfigured the stack; all three are fixed on
this tree, and each is pinned by a test that fails if it comes back.

1. ~~**`config.wsgi` does not exist.**~~ **Fixed.** `settings.py` declares
   `WSGI_APPLICATION = "config.wsgi.application"` and there was no `wsgi.py`
   under `src/config/`, so the api container exited at start with
   `ModuleNotFoundError: No module named 'config.wsgi'` while every other
   service came up — `worker`, `migrate` and `rebuild` run `./manage.py` and
   never load it. The module is the standard four lines. The api service's
   default command is `gunicorn config.wsgi:application`, held to the settings
   value by `tests/test_images.py` rather than written twice, and
   `tests/test_deploy_surface.py` imports that same dotted path and checks what
   it resolves to is callable.
2. ~~**`./Caddyfile` does not exist.**~~ **Fixed**, and described under "The
   edge" above. Docker creates a *directory* at a missing bind-mount source, so
   the absence was never a startup error: Caddy ran against a directory and
   served nothing.
3. ~~**The `worker` service has no `DATA_ROOT`.**~~ **Fixed.** Its environment
   block set `DJANGO_SETTINGS_MODULE`, `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY`
   and `PGPASSWORD` but not `DATA_ROOT`, so `settings.DATA_ROOT` fell back to
   `BASE_DIR / "data"` — `/app/data` in the image — and `BACKUP_DIR` with it:
   the nightly dump landed on the container's own writable layer and was lost
   on the next `docker compose up` while the mounted `${DATA_ROOT}/backups`
   stayed empty. `worker` now sets `DATA_ROOT: /data` like `rebuild`, and
   `tests/test_compose.py` asserts every name `settings.py` reads is delivered
   to the service that reads it.

Four more were found in the sixth review round, all in the same place — the
stack as an operator would actually start it, rather than the stack as written
— and all fixed here. What they had in common is that every one of them
rendered: the YAML was right and the deployment was not.

4. ~~**`.env.example` set `PGHOST=127.0.0.1`.**~~ **Fixed.** An environment file
   wins over `${PGHOST:-postgis}`, so rendered from the shipped example all four
   Django services were pointed at the loopback address of their own container.
   `migrate` could not connect, and `api`, `worker` and `rebuild` all wait on
   migrate having completed, so the stack came up as Caddy and three routers
   serving nothing. The line is commented out; the compose default is the
   service name. `tests/test_compose_render.py` renders `docker compose config`
   against a copy of `.env.example` and asserts the rendered value, which is the
   level the YAML-only test could not see.
5. ~~**`bot` and `renderer` had no image and no profile.**~~ **Fixed.** Neither
   has a source, neither has a `build:`, and
   `ghcr.io/macrophage87/routemaker-bot:${TAG}` is in no registry, so the documented `docker compose up -d` stopped at a pull that
   cannot succeed. Both are behind `profiles: ["unbuilt"]` now and the default
   `up` skips them.
6. ~~**`${DATA_ROOT}`'s writable subdirectories were root-owned.**~~ **Fixed**,
   and described above: the documented `chown -R` ran before the first `up`, and
   Docker creates a missing bind source as a root-owned directory, so the chown
   covered none of the directories the problem is about.
   `scripts/prepare_data_root.sh` creates them all first.
7. ~~**Nobody could sign in on the shipped `.env.example`.**~~ **Fixed**, and
   described under "Why the example is a hostname and not `:80`": Secure cookies
   over plain HTTP, a redirect URI on a port nothing publishes, and an https
   trusted origin against an http site.
8. ~~**`migrate` raced the database.**~~ **Fixed.** It depended on `postgis`
   with the implied `service_started`, which is a container that exists — and on
   a fresh volume that is initdb and the PostGIS extension scripts still
   running with the port closed. `postgis` now declares a `pg_isready`
   healthcheck against the same role and database the application uses, and
   `migrate` waits on `service_healthy`. The other three keep waiting on migrate
   having completed, which is strictly later.

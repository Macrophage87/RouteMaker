# Deployment: building the stack's images

`compose.yaml` names four images under `routemaker/`. Until this document's
commit, nothing in the repository built any of them: there was no Dockerfile
anywhere and no `build:` stanza, so `docker compose up` on a host with a working
daemon stopped at the first pull of an image that exists in no registry. Five
review rounds read the code and none asked whether the stack could be built.

Two of the four are built now. Two are not, because they have no source.

| Image | Built by | State |
| --- | --- | --- |
| `routemaker/api:${TAG}` (services `api`, `worker`, `migrate`) | `docker/api.Dockerfile` | Written, never built |
| `routemaker/pipeline:${TAG}` (service `rebuild`) | `docker/pipeline.Dockerfile` | Written, never built |
| `routemaker/renderer:${TAG}` | — | No source in the repository |
| `routemaker/bot:${TAG}` | — | No source in the repository |

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
set -a; . ./.env; set +a           # DATA_ROOT, for the step below and nothing else
sudo -E sh scripts/prepare_data_root.sh   # BEFORE the first up; see below for why
docker compose build               # builds api and pipeline
docker compose up -d               # bot and renderer are skipped: they have no image
```

`docker compose up -d` starts everything except `bot`, `renderer` and `photon`,
which sit behind the `unbuilt` profile. `bot` and `renderer` are there because
neither has a source in this repository and so neither has an image in any
registry: without the profile this command was a pull of
`routemaker/bot:${TAG}` that could not succeed, on a stack where every other
service was ready to start. `photon` is there because the pinned image's first
act on a fresh host is to download a 61 GB planet index onto the root volume —
see "Photon" below, which has the arithmetic and the two lines that make
enabling the profile safe. `docker compose --profile unbuilt up -d` is how all
three come back; until then their absence is what handoff.md section 7 says it
is — no membership sweep from a gateway connection, no thumbnails, no geocoder.

`TAG` is the image tag, read from `.env` (`TAG=dev` in `.env.example`). It names
the built image, not a registry: `build:` sits beside `image:` in every service
that builds, so `docker compose build` tags the result `routemaker/api:${TAG}`
and `routemaker/pipeline:${TAG}` locally and the `worker`, `migrate` and
`rebuild` services find it there. Bump it per release so a rollback is a `TAG`
change and `docker compose up -d` rather than a rebuild — and `up -d`
specifically, because the tag is baked into each container at creation:
`docker compose restart` restarts the containers that exist, on the image they
were created from, and so rolls nothing back. `up -d` re-reads `.env`, sees the
service's image has changed and recreates it, leaving everything else alone.

The `api` image builds three services. They differ only in the command compose
gives them: `api` takes the image's default (`gunicorn`), `worker` and `migrate`
override it with `./manage.py`.

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

`routemaker/renderer:${TAG}` is PLAN.md:63's thumbnail renderer, "a small Node
sidecar using `@maplibre/maplibre-gl-native`". There is no Node service source
in the repository: `frontend/` holds one stress-style module and its test, and
`scripts/` holds five Python scripts and a shell script. `routemaker/bot:${TAG}`
is handoff.md section 7's first row — no bot source, no gateway handler, no
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

**Every shell snippet in this document that uses `$DATA_ROOT` needs the
deployment's environment loaded first.** It is not exported by anything; it
lives in `.env`, which is compose's input and not the shell's:

```sh
set -a; . ./.env; set +a          # or: export DATA_ROOT=/srv/routemaker/data
```

Do not skip it and do not guess. `sudo chown -R 10001:10001 "$DATA_ROOT"` with
`DATA_ROOT` unset is `chown -R 10001:10001 ""`, and with a stray trailing slash
or an empty value in a shell that word-splits it, the argument that reaches
`chown` can be `/`. Recursively chowning the root filesystem ends the host.
`scripts/prepare_data_root.sh` refuses to run without `DATA_ROOT` set to an
absolute path for exactly this reason; the manual form has no such guard.

### The directories have to exist, as 10001, before the first `up`

```sh
set -a; . ./.env; set +a
sudo -E sh scripts/prepare_data_root.sh
```

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

`photon` is pinned to `rtuszik/photon-docker:2.4.0` — the newest release tag on
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
set -a; . ./.env; set +a        # $DATA_ROOT is in .env, not in your shell
docker compose run --rm \
  -e DATA_ROOT=/data \
  -v "$DATA_ROOT/static:/data/static" \
  api ./manage.py collectstatic --noinput
```

Without the first line `$DATA_ROOT` expands to nothing and the `-v` argument
becomes `/static:/data/static`, which mounts a directory at the *host's* root
rather than the data volume: the command succeeds, reports the files it copied,
and Caddy still serves nothing.

`settings.STATIC_ROOT` is now `DATA_ROOT / "static"` — the same host directory
Caddy mounts at `/srv/static`, so the assets land where the edge serves them from
and nowhere else. Until it was set the command above could not run at all:
`collectstatic` refuses without a `STATIC_ROOT` and it is not overridable from
the command line, so the admin rendered unstyled.

The two flags are both load-bearing, and the earlier version of this command had
neither right. `-v` alone mounted the host directory at `/srv/static`, which is
**Caddy's** path and not this container's: **the api service mounts no part of
the data volume and sets no `DATA_ROOT`**, so inside the image
`settings.DATA_ROOT` falls back to `BASE_DIR / "data"` and `STATIC_ROOT` with it — `/app/data/static`, on the
container's writable layer, discarded when `run --rm` exits. `-e DATA_ROOT=/data`
puts it at `/data/static`, which is what the bind mount covers, and matches the
`rebuild` service's own `DATA_ROOT: /data`. Drop the `-e` and the mount has to
move to `/app/data/static` instead; what must not happen is the two disagreeing,
because that failure is silent — the command reports the files it copied and the
volume stays empty.

### The api is not the container to run data commands in

That the api mounts no data is not a blocker and is not being fixed: the api
serves requests and writes nothing durable, so a `DATA_ROOT` on it would name a
path that does not exist inside it. It is a rule about where a command runs, and
it is the reason `collectstatic` above is a `run --rm` with an explicit mount
rather than an `exec` into the running api.

Every management command that reads or writes the data volume therefore runs in
`rebuild`, which binds `tiles`, `elevation`, `extracts`, `reference` and
`rebuild` under `/data`, or in `worker`, which binds `${DATA_ROOT}/backups`
there:

| Command | Container | Because |
| --- | --- | --- |
| `rollback_rebuild` | `rebuild` | Reads and rewrites the promotion symlinks under `<DATA_ROOT>/tiles`. In `api` those resolve to `/app/data/tiles`, which is empty, and the command refuses on every variant with "no previous tiles" — a refusal that reads like a deployment that has never rebuilt. |
| `run_rebuild_now` | `rebuild` | Queues the job for the service that owns the data mounts. It only writes a row, so any Django container could defer it, but the run it starts belongs there. |
| `install_reference_data.py` | `rebuild` | Writes `<DATA_ROOT>/reference/`, and reads the extract under `<DATA_ROOT>/extracts/`. |
| `check_operations` | `api` | Reads the database only. This one is right where it is, and the cron entry in docs/OPERATIONS.md stays as written. |

The frontend half of that sentence has no source either: `frontend/` is a single
module and its test, with no React application, no bundler and no build script,
so there is nothing to build into the volume yet. Only the admin's and Ninja's
assets reach the volume today.

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
   has a source, neither has a `build:`, and `routemaker/bot:${TAG}` is in no
   registry, so the documented `docker compose up -d` stopped at a pull that
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

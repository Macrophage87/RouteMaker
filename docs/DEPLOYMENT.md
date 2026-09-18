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
cp .env.example .env          # then fill it in; see docs/DEVELOPMENT.md
docker compose build          # builds api and pipeline
docker compose up -d
```

`TAG` is the image tag, read from `.env` (`TAG=dev` in `.env.example`). It names
the built image, not a registry: `build:` sits beside `image:` in every service
that builds, so `docker compose build` tags the result `routemaker/api:${TAG}`
and `routemaker/pipeline:${TAG}` locally and the `worker`, `migrate` and
`rebuild` services find it there. Bump it per release so a rollback is a `TAG`
change and a restart rather than a rebuild.

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

## `${DATA_ROOT}` must be owned by uid 10001

Both images run as uid 10001. `${DATA_ROOT}` is a host bind mount, and the
processes write into it: the nightly dump into `${DATA_ROOT}/backups`, the
rebuild into the whole of `/data` (tiles, extracts, the elevation cache, the
timezone database `valhalla_build_timezones` writes beside them).

```sh
sudo install -d -o 10001 -g 10001 "$DATA_ROOT"
sudo chown -R 10001:10001 "$DATA_ROOT"
```

A missed `chown` is a permission error from a binary six hours into a rebuild,
which is not obviously an ownership problem to whoever reads it.

## Static assets — a deploy step, and it does not work yet

PLAN.md:64: the React frontend is built to static assets, "and Django's admin and
Ninja assets are collected into the same named volume, which Caddy serves; both
are rebuilt on deploy and after a restore." Caddy mounts `${DATA_ROOT}/static` at
`/srv/static:ro`.

There is no build-time `collectstatic` in `docker/api.Dockerfile`, for a reason
that is not going away: `settings.py` raises `ImproperlyConfigured` without
`KEY_ENCRYPTION_KEY`, so any build-time management command would need the
deployment's real secret as a build input, and a secret in a build argument is a
secret in the image's metadata. `collectstatic` is a deploy step:

```sh
docker compose run --rm \
  -v "$DATA_ROOT/static:/srv/static" \
  api ./manage.py collectstatic --noinput
```

**This does not work today, and the blocker is in `src/`, not here.**
`settings.py` defines `STATIC_URL` and no `STATIC_ROOT`, and `collectstatic`
refuses to run without one — it is not overridable from the command line. Until
`STATIC_ROOT` is set (to `/srv/static`, or to a path the command above mounts),
the admin's CSS and JS never reach the volume Caddy serves and the admin renders
unstyled. Setting it is a one-line change to `src/config/settings.py`.

The frontend half of that sentence has no source either: `frontend/` is a single
module and its test, with no React application, no bundler and no build script,
so there is nothing to build into the volume yet.

## Known blockers on `docker compose up`

Building the images is necessary and not sufficient. Three things in the
repository will still stop or silently misconfigure the stack, all of them
outside this document's files:

1. **`config.wsgi` does not exist.** `settings.py` declares
   `WSGI_APPLICATION = "config.wsgi.application"` and there is no `wsgi.py`
   under `src/config/`. The api service's default command is
   `gunicorn config.wsgi:application` — held to the settings value by
   `tests/test_images.py` rather than written twice — so the api container will
   exit at start with `ModuleNotFoundError: No module named 'config.wsgi'`
   until that module is added. Nothing else in the stack depends on it:
   `worker`, `migrate` and `rebuild` run `./manage.py` and start fine.
2. **`./Caddyfile` does not exist.** `compose.yaml` mounts
   `./Caddyfile:/etc/caddy/Caddyfile:ro`, and Docker creates a *directory* at a
   bind-mount source that is missing, so Caddy starts against a directory where
   it expects a config file.
3. **The `worker` service has no `DATA_ROOT`.** Its environment block sets
   `DJANGO_SETTINGS_MODULE`, `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY` and
   `PGPASSWORD` but not `DATA_ROOT`, so `settings.DATA_ROOT` falls back to
   `BASE_DIR / "data"` — `/app/data` in the image — and `BACKUP_DIR` with it.
   The service mounts `${DATA_ROOT}/backups` at `/data/backups`, which nothing
   then writes to: the nightly dump lands on the container's own writable layer
   and is lost on the next `docker compose up`. `rebuild` sets `DATA_ROOT: /data`
   and is correct.

# The rebuild service (compose.yaml: routemaker/pipeline:${TAG}).
#
# The weekly rebuild's executor: a Procrastinate worker on the `rebuild` queue
# alone, in the one image that carries the Valhalla binaries. It needs
# valhalla_build_admins, valhalla_build_timezones, valhalla_build_tiles,
# valhalla_build_extract (pipeline/tiles.py, `tile_build_commands`) and
# valhalla_service (pipeline/tiles.py, `trace_attributes` - the one-shot
# readback that validates a build), so it is built FROM the same image the
# serving containers run rather than compiling Valhalla again. Named by
# function rather than by line number: the two line ranges that used to be
# here pointed at neither by the time anybody read them.
#
# The tag is the serving tag on purpose. A rebuild that writes tiles with a
# different Valhalla than the one that reads them is a tile-schema mismatch that
# surfaces as a routing failure after promotion, not as a build failure;
# tests/test_images.py reads the tag out of compose.yaml and holds this FROM to
# it rather than letting the two drift.
#
# Base distro: the upstream image's runner stage is `FROM ubuntu:24.04`
# (github.com/valhalla/valhalla, Dockerfile at tag 3.5.1), so these are noble
# package names, not Debian ones. Each was checked against packages.ubuntu.com,
# which is reachable from the environment this was written in.
#
# NOT BUILT. See docs/DEPLOYMENT.md.

ARG VALHALLA_IMAGE=ghcr.io/valhalla/valhalla:3.5.1


# --- wheels -------------------------------------------------------------------
# Same base as the runtime stage so the wheels are built against the same
# interpreter (Ubuntu 24.04 ships Python 3.12, which satisfies
# pyproject.toml's `requires-python = ">=3.11"`). The C toolchain stays here.
FROM ${VALHALLA_IMAGE} AS wheels

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        python3-pip \
        python3-venv; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY docker/requirements.txt docker/requirements-pipeline.txt ./
# A virtualenv rather than the system interpreter: Ubuntu 24.04 marks its
# python3 externally managed (PEP 668) and pip refuses to write into it.
RUN set -eux; \
    python3 -m venv /opt/venv; \
    /opt/venv/bin/pip install --upgrade pip wheel; \
    /opt/venv/bin/pip wheel --wheel-dir /wheels -r requirements-pipeline.txt


# --- runtime ------------------------------------------------------------------
FROM ${VALHALLA_IMAGE} AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# What each of these is for, and why it is named even when the base already has
# it - an inherited package is a dependency nobody declared, and the upstream
# runner stage's apt line is not this project's contract:
#
#   python3-venv, python3-pip  the project runs under ./manage.py, so this image
#                              needs an interpreter it is allowed to install
#                              into. The upstream runner carries python3-minimal
#                              and no pip.
#   gdal-bin                   gdalwarp, which pipeline/elevation.py:104 shells
#                              out to for every one-degree HGT tile in the
#                              coverage box. The upstream runner has libgdal34,
#                              the shared library, and none of the binaries.
#   osmium-tool                the `osmium` command line, for the source-extract
#                              stage (PLAN.md:13): `osmium merge` and
#                              `osmium extract -s smart -S types=any`. This is
#                              the CLI and is a different thing from the
#                              `osmium` Python module in requirements.txt, which
#                              is pyosmium and is what pipeline/extract.py
#                              imports. Both are needed.
#   sqlite3                    the CLI, to query tz_world in the timezone
#                              database the build produces.
#   spatialite-bin, unzip,     valhalla_build_timezones is a shell script: it
#   curl                       curls the timezone-boundary-builder release,
#                              unzips it, and loads the shapefile with
#                              spatialite_tool and spatialite. It checks for
#                              spatialite and unzip by name and exits if either
#                              is missing - and NOT for spatialite_tool, which
#                              it calls one line later (3.5.1
#                              scripts/valhalla_build_timezones: the `which`
#                              guards, then `spatialite_tool -i -shp ...`), so a
#                              missing spatialite_tool is a timezone build that
#                              gets past its own checks and fails on the import.
#                              Both binaries are in the one package: noble's
#                              spatialite-bin ships /usr/bin/spatialite and
#                              /usr/bin/spatialite_tool
#                              (packages.ubuntu.com/noble/amd64/spatialite-bin/filelist).
#   libpq5                     psycopg2-binary carries its own libpq, but the
#                              psycopg 3 that procrastinate pulls in does not
#                              unless its binary wheel is used.
#   ca-certificates            pipeline/elevation.py fetches HGT tiles over
#                              https through urllib.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gdal-bin \
        libpq5 \
        osmium-tool \
        python3-pip \
        python3-venv \
        spatialite-bin \
        sqlite3 \
        unzip; \
    rm -rf /var/lib/apt/lists/*

# Every binary the rebuild shells out to, asserted at build time. The quiet
# failure this guards is a stage that runs, finds no binary, and is reported as
# a rebuild failure six hours in.
#
# LuaJIT is not on this list and does not need to be: Valhalla links the Lua
# tag transform against libluajit-5.1-2, which the upstream runner stage
# installs (its apt line, verified in the 3.5.1 Dockerfile), and calls it in
# process. The standalone `luajit` interpreter is in upstream's
# scripts/install-linux-deps.sh, which runs in the builder stage only, so the
# CLI is absent from the runner - which matters for tests/lua/ on a developer
# machine and not for this image.
RUN set -eux; \
    for b in valhalla_build_admins valhalla_build_timezones valhalla_build_tiles \
             valhalla_build_extract valhalla_service gdalwarp osmium sqlite3 \
             spatialite spatialite_tool unzip curl; do \
        command -v "$b" >/dev/null || { echo "missing binary: $b" >&2; exit 1; }; \
    done

COPY --from=wheels /wheels /wheels
COPY docker/requirements.txt docker/requirements-pipeline.txt /tmp/
RUN set -eux; \
    python3 -m venv /opt/venv; \
    /opt/venv/bin/pip install --no-index --find-links=/wheels -r /tmp/requirements-pipeline.txt; \
    rm -rf /wheels /tmp/requirements.txt /tmp/requirements-pipeline.txt
# Ahead of /usr/bin, so manage.py's `#!/usr/bin/env python3` shebang resolves to
# the virtualenv and not to the system interpreter, which has none of this
# installed.
ENV PATH=/opt/venv/bin:$PATH

# The same fixed uid as the api image. This service mounts the whole data volume
# at /data and writes tiles, extracts and the elevation cache into it, so
# ${DATA_ROOT} on the host has to be owned by this number - the one deployment
# step that is easy to miss and impossible to misdiagnose from the error.
RUN set -eux; \
    groupadd --system --gid 10001 routemaker; \
    useradd --system --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin routemaker

WORKDIR /app

# manage.py first, because compose runs ["./manage.py", "procrastinate",
# "worker", "--queues=rebuild", ...] relative to this WORKDIR.
COPY --chown=root:root manage.py ./manage.py
COPY --chown=root:root src ./src
# settings.VALHALLA_CONFIG_DIR is BASE_DIR/"valhalla", and pipeline/run.py takes
# its config_dir from that setting, so the checked-in serving configs have to be
# in the image at /app/valhalla - the compose bind mount at /conf is what the
# *serving* containers read, and the generated build configs name /conf/lua for
# mjolnir.graph_lua_name. Both copies are the same files.
COPY --chown=root:root valhalla ./valhalla
COPY --chown=root:root lua ./lua
# scripts/install_reference_data.py installs the three files under
# <DATA_ROOT>/reference/ the rebuild refuses to start without, and this is the
# image with the data volume mounted, so it is run here.
COPY --chown=root:root scripts ./scripts
COPY --chown=root:root fixtures ./fixtures

ENV PYTHONPATH=/app/src

USER 10001:10001

# No CMD. compose.yaml gives this service its command
# (["./manage.py", "procrastinate", "worker", "--queues=rebuild",
# "--concurrency=1"]), and the upstream image declares no ENTRYPOINT, so a CMD
# here would only be a second place for that command to disagree with itself.
# No secrets are baked in: KEY_ENCRYPTION_KEY, DJANGO_SECRET_KEY and PGPASSWORD
# arrive from the environment at runtime.

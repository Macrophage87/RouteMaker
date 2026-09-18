# The api, worker and migrate services (compose.yaml: routemaker/api:${TAG}).
#
# Python 3.11 because pyproject.toml says `requires-python = ">=3.11"` and the
# repository's .venv runs 3.11.15 - that is the interpreter the suite is green
# on, so it is the interpreter the image runs.
#
# Debian because GeoDjango needs GDAL, GEOS and PROJ as shared libraries and
# Debian carries all three, and because pg_dump 16 has to come from the
# PostgreSQL project's apt repository to match postgis/postgis:16-3.4.
#
# NOT BUILT. No Docker daemon runs in the environment this was written in and
# registries are blocked, so this file has been parsed, its COPY sources checked
# against the repository and its package names checked as far as a blocked apt
# index allows - and never built. See docs/DEPLOYMENT.md.

ARG PYTHON_VERSION=3.11
ARG DEBIAN_SUITE=bookworm
# Major 16, to match the server in compose.yaml (postgis/postgis:16-3.4).
# pg_dump refuses an archive from a server newer than itself, and the nightly
# backup's `pg_restore --list` readback would be the thing that discovered a
# mismatch, at 07:00 UTC, in the one job whose whole purpose is to be trusted.
ARG PG_MAJOR=16


# --- wheels -------------------------------------------------------------------
# Everything that might compile happens here and nothing from this stage but the
# wheel directory reaches the runtime image, so a C toolchain is never shipped.
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_SUITE} AS wheels

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY docker/requirements.txt docker/requirements-api.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements-api.txt


# --- runtime ------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_SUITE} AS runtime

ARG DEBIAN_SUITE
ARG PG_MAJOR

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# gdal-bin rather than a version-numbered libgdal: the package name carries the
# ABI number (libgdal32 on bookworm, libgdal34 on noble) and would have to be
# revised with the base image, while gdal-bin is stable and pulls whichever
# libgdal the suite ships - along with libgeos_c and libproj, which GeoDjango
# needs and nothing else here would drag in. settings.py sets neither
# GDAL_LIBRARY_PATH nor GEOS_LIBRARY_PATH, so GeoDjango resolves both through
# ctypes.util.find_library, which reads ldconfig's cache; the RUN below asserts
# that resolution at build time rather than leaving it to the first request.
#
# libpq5 is for pg_dump and pg_restore. Django does not need it: the
# psycopg2-binary wheel carries its own libpq.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${DEBIAN_SUITE}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "postgresql-client-${PG_MAJOR}" \
        gdal-bin \
        libpq5; \
    apt-get purge -y --auto-remove gnupg; \
    rm -rf /var/lib/apt/lists/*

# Two build-time assertions, because the failures they catch are otherwise
# discovered by a request. A missing libgdal or libgeos_c is an ImportError from
# django.contrib.gis at the first import; a pg_dump of the wrong major is a
# nightly backup that fails against the 16 server months later.
RUN set -eux; \
    python -c "import ctypes.util as u, sys; m = [n for n in ('gdal', 'geos_c') if not u.find_library(n)]; sys.exit('GeoDjango cannot resolve: ' + ', '.join(m) if m else 0)"; \
    pg_dump --version | grep -Eq "[[:space:]]${PG_MAJOR}\."; \
    pg_restore --version | grep -Eq "[[:space:]]${PG_MAJOR}\."

COPY --from=wheels /wheels /wheels
COPY docker/requirements.txt docker/requirements-api.txt /tmp/
RUN set -eux; \
    pip install --no-index --find-links=/wheels -r /tmp/requirements-api.txt; \
    rm -rf /wheels /tmp/requirements.txt /tmp/requirements-api.txt

# A fixed uid, not a name: ${DATA_ROOT}/backups is a host bind mount and the
# nightly dump writes into it, so the host directory has to be owned by this
# number. docs/DEPLOYMENT.md says so in the one place an operator will look.
RUN set -eux; \
    groupadd --system --gid 10001 routemaker; \
    useradd --system --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin routemaker

# /app, because compose runs ["./manage.py", ...] for the worker and migrate
# services: the command is relative to WORKDIR, and manage.py has to be there
# and executable for execve to find it.
WORKDIR /app

# The source stays laid out as it is in the repository and goes on PYTHONPATH
# rather than into site-packages. That is deliberate and it is not a shortcut:
# settings.py computes `BASE_DIR = Path(__file__).resolve().parents[2]`, so a
# `config` package installed at .../site-packages/config/settings.py would put
# BASE_DIR at .../python3.11, and DATA_ROOT's default and VALHALLA_CONFIG_DIR
# would both resolve under the interpreter's library directory. The layout is
# part of the settings contract.
COPY --chown=root:root manage.py ./manage.py
COPY --chown=root:root src ./src
ENV PYTHONPATH=/app/src

# Read-only to the process that runs it: nothing in the application writes to
# its own source tree, and the one directory it does write (the backups bind
# mount) is owned by this uid on the host.
USER 10001:10001

# gunicorn's default bind. Caddy is the only service that publishes a port; this
# is reachable on the compose network alone.
EXPOSE 8000

# No secrets are baked in. KEY_ENCRYPTION_KEY, DJANGO_SECRET_KEY,
# DISCORD_CLIENT_SECRET and PGPASSWORD arrive from the environment at runtime,
# scoped per service by compose.yaml - which is also why there is no build-time
# `manage.py collectstatic` here: settings.py raises ImproperlyConfigured
# without KEY_ENCRYPTION_KEY, so any build-time management command would need
# the secret in the build. collectstatic is a deploy step; docs/DEPLOYMENT.md
# has the command. (It used to say here that the step could not run at all
# because settings.py defined no STATIC_ROOT. It does now - `DATA_ROOT /
# "static"`, the directory Caddy mounts - so that sentence was describing a
# fixed defect as a current one.)
COPY --chown=root:root docker/api-entrypoint.sh /usr/local/bin/routemaker-api
CMD ["routemaker-api"]

#!/bin/sh
# Bring the development database up, idempotently.
#
# In an ephemeral container the cluster does not survive an idle period: the
# process is killed uncleanly rather than shut down, so the next run finds a
# stale pid file and refuses to start until it is cleared. `pg_ctlcluster`
# handles that itself, which is why this is safe to run whenever a test run
# fails with "connection refused" rather than something about the code.
set -eu

pg_isready >/dev/null 2>&1 && { echo "database already up"; exit 0; }

pg_ctlcluster 16 main start
until pg_isready >/dev/null 2>&1; do sleep 1; done

su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='routemaker'\"" \
  | grep -q 1 || su postgres -c \
  "psql -c \"CREATE ROLE routemaker LOGIN PASSWORD 'routemaker' SUPERUSER\""

su postgres -c "psql -tAlc \"SELECT 1 FROM pg_database WHERE datname='routemaker'\"" \
  | grep -q 1 || su postgres -c "createdb -O routemaker routemaker"

PGPASSWORD=routemaker psql -h 127.0.0.1 -U routemaker -d routemaker \
  -qc "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null

echo "database up"

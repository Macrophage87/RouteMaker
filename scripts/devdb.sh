#!/bin/sh
# Bring the development database up, idempotently.
#
# In an ephemeral container the cluster does not survive an idle period: the
# process is killed uncleanly rather than shut down, so the next run finds a
# stale pid file and refuses to start until it is cleared. `pg_ctlcluster`
# handles that itself, which is why this is safe to run whenever a test run
# fails with "connection refused" rather than something about the code.
set -eu

# Only the cluster start is conditional. Everything below is idempotent and runs
# every time: a running server is not the same thing as a provisioned one, and a
# container that has the cluster up but the role, database or extension missing
# is exactly the state this script exists to repair.
if pg_isready >/dev/null 2>&1; then
  echo "cluster already running"
else
  pg_ctlcluster 16 main start
  until pg_isready >/dev/null 2>&1; do sleep 1; done
fi

su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='routemaker'\"" \
  | grep -q 1 || su postgres -c \
  "psql -c \"CREATE ROLE routemaker LOGIN PASSWORD 'routemaker' SUPERUSER\""

su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='routemaker'\"" \
  | grep -q 1 || su postgres -c "createdb -O routemaker routemaker"

PGPASSWORD=routemaker psql -h 127.0.0.1 -U routemaker -d routemaker \
  -qc "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null

# On the role as well as per connection, so psql and any tooling that bypasses
# Django resolve the same way. public first: an unqualified CREATE TABLE lands in
# the first existing schema on the path, and the live schema is renamed away by
# every weekly swap.
su postgres -c "psql -qc \"ALTER ROLE routemaker IN DATABASE routemaker \
  SET search_path = public, live\"" >/dev/null

# A test database left behind by an interrupted run makes the next run fail in
# ways that look like code failures.
su postgres -c "dropdb --if-exists test_routemaker" >/dev/null 2>&1 || true

echo "database up"

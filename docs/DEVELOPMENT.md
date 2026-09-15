# Development environment

The plan's deployment target is one Docker Compose stack on one AWS host. For
development the same components run natively, which is faster to iterate against
and, for the database layer, tests the real thing rather than a stand-in.

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

## Container notes

Docker's daemon runs in this development container, but image layer pulls are
blocked by the egress proxy, so the Compose stack cannot be brought up here. It
is written to be validated on the deployment host. The native database above is
the loop to develop against in the meantime.

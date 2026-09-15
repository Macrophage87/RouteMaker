"""The worker app and its periodic tasks.

Procrastinate runs jobs in PostgreSQL rather than in a broker, which is why
there is no Redis in the stack: one durable store, one backup, one restore.

Every periodic task here writes a success row that an alert reads, rather than
relying on the absence of an error. A job that never ran produces no error at
all, and the failure modes that matter most here - a rebuild that stopped
running, a backup that stopped being taken - are exactly that shape.
"""

from __future__ import annotations

import os
from pathlib import Path

from procrastinate import App, PsycopgConnector

app = App(
    connector=PsycopgConnector(
        kwargs={
            "host": os.environ.get("PGHOST", "127.0.0.1"),
            "dbname": os.environ.get("PGDATABASE", "routemaker"),
            "user": os.environ.get("PGUSER", "routemaker"),
            "password": os.environ.get("PGPASSWORD", "routemaker"),
        }
    )
)

# Cron schedules. The rebuild runs in a low-traffic window because it takes half
# the host's cores and widens the latency alerts while it does.
WEEKLY_REBUILD_CRON = "0 8 * * 2"  # Tuesday 08:00 UTC, early morning local
NIGHTLY_BACKUP_CRON = "0 7 * * *"
MEMBERSHIP_SWEEP_CRON = "0 */6 * * *"

# How long each may run before it is considered stuck. The rebuild's ceiling is
# longer than its expected duration but shorter than the eight days after which
# the "no rebuild completed" alert fires, so a hung rebuild is caught by its own
# timeout rather than by the weekly alarm.
REBUILD_TIMEOUT_S = 6 * 60 * 60
SWEEP_TIMEOUT_S = 30 * 60


# The tasks themselves. Until these existed, this module defined an App, four
# constants and nothing else, while compose ran a worker against it: the weekly
# rebuild, the nightly backup and the six-hourly sweep were never scheduled and
# the cron strings above were decoration. The tests asserted the strings, so
# nothing noticed.
#
# Each takes the `timestamp` argument Procrastinate passes to a periodic task,
# and each opens a run row so that "this stopped happening" is something an alert
# can see.


@app.periodic(cron=WEEKLY_REBUILD_CRON)
@app.task(name="weekly_rebuild", queue="rebuild", queueing_lock="weekly_rebuild")
def weekly_rebuild(timestamp: int) -> None:
    """Build into staging, validate, swap.

    Queued under a lock because two concurrent rebuilds would write the same
    staging schema and the same tile directory. It gets its own queue so the
    six-hour build does not sit in front of the sweep.
    """
    from django.conf import settings

    from core.runs import record
    from pipeline.rebuild import run_rebuild
    from pipeline.run import RebuildContext, build_handlers

    with record("weekly_rebuild"):
        context = RebuildContext(
            source_pbf=settings.REBUILD_SOURCE_PBF,
            work_dir=settings.REBUILD_WORK_DIR,
            reference_dir=settings.REBUILD_REFERENCE_DIR,
        )
        run_rebuild(build_handlers(context))


@app.periodic(cron=NIGHTLY_BACKUP_CRON)
@app.task(name="nightly_backup", queue="maintenance", queueing_lock="nightly_backup")
def nightly_backup(timestamp: int) -> None:
    """Dump the database, excluding the membership cache.

    The cache is excluded rather than dumped and protected. Who organizes with
    whom is the sensitive part of this deployment, and the cache is rebuildable
    from the bot's backfill, so the copy that sits on disk for months is the one
    worth not having.
    """
    from core.runs import record

    with record("nightly_backup") as run:
        run.detail = str(perform_backup())
        run.save(update_fields=["detail"])


@app.periodic(cron=MEMBERSHIP_SWEEP_CRON)
@app.task(name="membership_sweep", queue="maintenance", queueing_lock="membership_sweep")
def membership_sweep(timestamp: int) -> None:
    """The backstop for what the gateway missed, and the privacy purge.

    Revocation lands in seconds through the gateway; this catches a disconnect.
    It also drops rows for people who have never signed in, so the cache does not
    quietly accumulate a roster of a guild's membership.
    """
    from core.membership import sweep_memberships
    from core.runs import record

    with record("membership_sweep") as run:
        purged, departed = sweep_memberships()
        run.detail = f"purged {purged} never-signed-in rows, dropped {departed} departed rows"
        run.save(update_fields=["detail"])


def perform_backup(now=None) -> Path:
    """pg_dump to the data volume. Separated so the task body stays readable."""
    import subprocess

    from django.conf import settings
    from django.utils import timezone

    now = now or timezone.now()
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = settings.BACKUP_DIR / f"routemaker-{now:%Y%m%dT%H%M%SZ}.dump"
    database = settings.DATABASES["default"]
    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            f"--host={database['HOST']}",
            f"--port={database['PORT']}",
            f"--username={database['USER']}",
            # Excluded, not merely unprotected. See the task docstring.
            "--exclude-table-data=*.cached_membership",
            f"--file={destination}",
            database["NAME"],
        ],
        check=True,
        env={**os.environ, "PGPASSWORD": database["PASSWORD"]},
    )
    return destination

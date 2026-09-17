"""The worker app and its periodic tasks.

Procrastinate runs jobs in PostgreSQL rather than in a broker, which is why
there is no Redis in the stack: one durable store, one backup, one restore.

The app is Procrastinate's Django integration rather than a bare App with its
own connector. Three things follow from that, and the first version had none
of them: the worker's schema arrives through `migrate` like every other table
(the bare App had no schema step anywhere, and `procrastinate schema --apply`
cannot upgrade one that exists); the worker process is `manage.py procrastinate
worker`, which sets Django up before a task runs (the bare CLI never did, so
every task raised AppRegistryNotReady); and the job tables are readable through
the ORM, which is what the plan's failed-jobs admin page needs. Tasks register
on the integration's app through PROCRASTINATE_IMPORT_PATHS naming this module.

Every periodic task here writes a success row that an alert reads, rather than
relying on the absence of an error. A job that never ran produces no error at
all, and the failure modes that matter most here - a rebuild that stopped
running, a backup that stopped being taken - are exactly that shape.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from procrastinate import RetryStrategy
from procrastinate.contrib.django import app

# Cron schedules. The rebuild runs in a low-traffic window because it takes half
# the host's cores and widens the latency alerts while it does.
WEEKLY_REBUILD_CRON = "0 8 * * 2"  # Tuesday 08:00 UTC, early morning local
NIGHTLY_BACKUP_CRON = "0 7 * * *"
MEMBERSHIP_SWEEP_CRON = "0 */6 * * *"

# How long each may run before it is considered stuck. The rebuild's ceiling is
# longer than its expected duration but shorter than the eight days after which
# the "no rebuild completed" alert fires, so a hung rebuild is caught by its own
# timeout rather than by the weekly alarm. Enforced: the rebuild hands its
# deadline to every binary it runs and checks it between stages; the sweep runs
# under core.runs.run_with_deadline.
REBUILD_TIMEOUT_S = 6 * 60 * 60
SWEEP_TIMEOUT_S = 30 * 60

# The plan's job rule: retried with exponential backoff, up to five times.
# Procrastinate counts an attempt when a run finishes or is scheduled for
# retry, after the retry decision, so the first failure is judged at
# attempts=0 and the sixth at attempts=5, where max_attempts stops it: one run
# and five retries. The wait before retry n is exponential_wait ** n seconds -
# 6 s, 36 s, 3.6 min, 22 min, 2.2 h - so a transient failure (a database
# restart, a download that dropped) is retried within seconds and a persistent
# one is out of retries within three hours, when the alert can name it.
RETRY = RetryStrategy(max_attempts=5, exponential_wait=6)

# Tables whose data is excluded from the nightly dump. The membership cache
# because who organizes with whom is the sensitive part of this deployment and
# it is rebuildable from the bot's backfill; the session table because a dump
# that sits on disk for months must not carry live sessions.
BACKUP_EXCLUDED_TABLES = ("cached_membership", "app_session")


class RebuildAbandoned(RuntimeError):
    """A rebuild failed for a reason a retry cannot fix, and is not retried.

    Validation, missing reference data, the disk gate and a stage with no
    handler are all the same on the fifth attempt as on the first; retrying
    them is thirty hours of CPU for the same alert. Only a failure whose cause
    is not one of these - a database hiccup, a download that dropped - goes
    back to Procrastinate as a plain RebuildFailed and is retried.
    """


@app.periodic(cron=WEEKLY_REBUILD_CRON)
@app.task(
    name="weekly_rebuild",
    queue="rebuild",
    queueing_lock="weekly_rebuild",
    retry=RetryStrategy(
        max_attempts=RETRY.max_attempts,
        exponential_wait=RETRY.exponential_wait,
        retry_exceptions=[],  # filled below, once the exception class is importable
    ),
)
def weekly_rebuild(timestamp: int) -> None:
    """Build into staging and a dated tile directory, validate, swap, reconcile.

    Queued under a lock because two concurrent rebuilds would write the same
    staging schema and the same tile directory. It gets its own queue so the
    six-hour build does not sit in front of the sweep - and so that the
    container with the Valhalla binaries and the data mounts is the one that
    runs it: compose's `rebuild` service is a worker on this queue alone.
    """
    from django.conf import settings

    from core.runs import record
    from pipeline.rebuild import RebuildFailed, RebuildTimedOut, run_rebuild
    from pipeline.run import RebuildContext, build_handlers

    with record("weekly_rebuild") as run:
        context = RebuildContext(
            source_pbf=settings.REBUILD_SOURCE_PBF,
            work_dir=settings.REBUILD_WORK_DIR,
            reference_dir=settings.REBUILD_REFERENCE_DIR,
            deadline=time.monotonic() + REBUILD_TIMEOUT_S,
        )
        try:
            report = run_rebuild(build_handlers(context), deadline=context.deadline)
        except RebuildFailed as error:
            if isinstance(error.cause, terminal_causes()):
                raise RebuildAbandoned(str(error)) from error
            raise
        except RebuildTimedOut as error:
            raise RebuildAbandoned(str(error)) from error
        run.detail = f"build {context.build_id}: {len(report.completed)} stages completed"
        run.save(update_fields=["detail"])


def terminal_causes() -> tuple[type[Exception], ...]:
    """Failures a retry cannot fix. Imported lazily: this module is imported
    at Django app-ready time and the pipeline imports the ORM."""
    from pipeline.elevation import ElevationTileInvalid
    from pipeline.rebuild import StageNotImplemented
    from pipeline.run import ReferenceDataMissing, ValidationFailed
    from pipeline.tiles import DiskGateRefused, TilePathsNotPerVariant

    return (
        ValidationFailed,
        ReferenceDataMissing,
        DiskGateRefused,
        StageNotImplemented,
        ElevationTileInvalid,
        TilePathsNotPerVariant,
    )


def _retry_only_rebuild_failures() -> None:
    from pipeline.rebuild import RebuildFailed

    weekly_rebuild.retry_strategy.retry_exceptions = [RebuildFailed]


_retry_only_rebuild_failures()


@app.periodic(cron=NIGHTLY_BACKUP_CRON)
@app.task(name="nightly_backup", queue="maintenance", queueing_lock="nightly_backup", retry=RETRY)
def nightly_backup(timestamp: int) -> None:
    """Dump the database, excluding the membership cache and the sessions.

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
@app.task(
    name="membership_sweep", queue="maintenance", queueing_lock="membership_sweep", retry=RETRY
)
def membership_sweep(timestamp: int) -> None:
    """The backstop for what the gateway missed, and the privacy purge.

    Revocation lands in seconds through the gateway; this catches a disconnect.
    It also drops rows for people who have never signed in, so the cache does not
    quietly accumulate a roster of a guild's membership.
    """
    from core.membership import sweep_memberships
    from core.runs import record, run_with_deadline

    with record("membership_sweep") as run:
        purged, departed = run_with_deadline(sweep_memberships, SWEEP_TIMEOUT_S, "membership_sweep")
        run.detail = f"purged {purged} never-signed-in rows, dropped {departed} departed rows"
        run.save(update_fields=["detail"])


class BackupVerificationFailed(RuntimeError):
    """The dump on disk is not the dump the task promised."""


def perform_backup(now=None, read_listing: Callable[[Path, dict], str] | None = None) -> Path:
    """pg_dump to the data volume, then read the archive's table of contents
    back to prove it is what was asked for. Separated so the task body stays
    readable. `read_listing` is pg_restore --list, injectable so a test can
    hand this function a listing that leaks and watch it refuse."""
    import subprocess

    from django.conf import settings
    from django.utils import timezone

    read_listing = read_listing or _pg_restore_list
    now = now or timezone.now()
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = settings.BACKUP_DIR / f"routemaker-{now:%Y%m%dT%H%M%SZ}.dump"
    database = settings.DATABASES["default"]
    env = {**os.environ, "PGPASSWORD": database["PASSWORD"]}
    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            f"--host={database['HOST']}",
            f"--port={database['PORT']}",
            f"--username={database['USER']}",
            # Excluded, not merely unprotected. See the task docstring.
            *(f"--exclude-table-data=*.{table}" for table in BACKUP_EXCLUDED_TABLES),
            f"--file={destination}",
            database["NAME"],
        ],
        check=True,
        env=env,
    )
    verify_dump_listing(read_listing(destination, env))
    return destination


def _pg_restore_list(archive: Path, env: dict) -> str:
    import subprocess

    return subprocess.run(
        ["pg_restore", "--list", str(archive)], check=True, capture_output=True, text=True, env=env
    ).stdout


# One entry of a custom-format archive's table of contents, as pg_restore
# --list prints it: "1234; 0 5678 TABLE DATA public app_user routemaker".
_TOC_ENTRY = re.compile(r"^\d+;\s+\d+\s+\d+\s+TABLE DATA\s+(\S+)\s+(\S+)", re.MULTILINE)


def verify_dump_listing(listing: str) -> list[str]:
    """The tables whose data the archive carries, or a failure naming why not.

    An archive with no data entries at all is a dump of nothing - a wrong
    database name produces exactly that, and pg_dump exits zero. An archive
    carrying data for an excluded table is the leak the exclusion exists for.
    """
    tables = [f"{schema}.{table}" for schema, table in _TOC_ENTRY.findall(listing)]
    if not tables:
        raise BackupVerificationFailed("the archive carries no table data at all")
    leaked = [t for t in tables if t.rsplit(".", 1)[1] in BACKUP_EXCLUDED_TABLES]
    if leaked:
        raise BackupVerificationFailed(f"the archive carries data it must exclude: {leaked}")
    return tables

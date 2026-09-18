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
# The degraded-guild mark is bounded by GATEWAY_ALERT_AFTER, five minutes, so it
# runs on that cadence rather than with the six-hourly sweep. A guild marked an
# hour late carries an hour of stale grants that the plan's one number - 72 hours
# from the alert - does not allow for.
DEGRADED_GUILD_SWEEP_CRON = "*/5 * * * *"

# How long each may run before it is considered stuck. The rebuild's ceiling is
# longer than its expected duration but shorter than the eight days after which
# the "no rebuild completed" alert fires, so a hung rebuild is caught by its own
# timeout rather than by the weekly alarm. Enforced: the rebuild hands its
# deadline to every binary it runs and checks it between stages; the sweep runs
# under core.runs.run_with_deadline.
REBUILD_TIMEOUT_S = 6 * 60 * 60
SWEEP_TIMEOUT_S = 30 * 60
# The backup's ceiling, and it is the maintenance queue's bound rather than the
# backup's own convenience. `pg_dump` had no timeout at all, and the maintenance
# worker is one slot (`--concurrency` defaults to 1), so a dump blocked on a
# lock or a stalled write held that slot for as long as the process lived -
# forever, in the case the timeout exists for - while every five-minute
# degraded-guild tick under it was dropped, because Procrastinate skips a
# periodic job whose previous one is still queued or locked.
#
# Thirty minutes rather than a number derived from the dump: it is the bound the
# membership sweep already puts on the same slot, so the queue's worst case is
# unchanged by the backup existing, and a `pg_dump -Fc` of this database is
# minutes, so half an hour is a wedged process rather than a slow night. What
# this does not do on its own is restore the five-minute bound: a tick that
# falls inside a legitimate 20-minute dump is still dropped. Only a second slot
# does that, and the slot count lives in compose - see docs/OPERATIONS.md.
BACKUP_TIMEOUT_S = 30 * 60

# The worker's own heartbeat, as a periodic task that writes a run row. The plan
# alerts on "worker heartbeat silent for 10 minutes", and the cheapest honest
# form of that here is the same shape as every other alert in this file: a row
# whose absence `core.runs.stale_tasks` reports. Five minutes so that ten is two
# missed ticks rather than one.
WORKER_HEARTBEAT_CRON = "*/5 * * * *"

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

# How many dumps stay on the data volume. They are local-only for now - the
# plan's S3 upload with SSE-KMS and 30-day remote retention is not built - and
# they land on the volume the rebuild's disk gate measures, so an unbounded
# series of them would eventually refuse every rebuild with "grow the volume" as
# the only remedy. Seven: a week of nightly dumps, so corruption noticed over a
# weekend still has a local copy to restore from, at a bounded cost in gigabytes
# rather than a year's worth.
BACKUP_KEEP = 7


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
    from pipeline import retention
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
        # After the promotion, not before it: what is removed is decided by
        # where `current` and `previous` point, and until the swap has moved
        # them the build being retired still looks like the one being served.
        # Nothing pruned these, so a deployment kept one dated tile set per week
        # forever on the volume whose disk gate refuses a rebuild that cannot
        # fit two - the gate would eventually decline every rebuild with "grow
        # the volume" as the only remedy left.
        pruned = retention.prune_tile_builds(settings.TILES_DIR)
        run.detail = (
            f"build {context.build_id}: {len(report.completed)} stages completed, "
            f"pruned {sum(len(builds) for builds in pruned.values())} old build directories"
        )
        run.save(update_fields=["detail"])


def terminal_causes() -> tuple[type[Exception], ...]:
    """Failures a retry cannot fix. Imported lazily: this module is imported
    at Django app-ready time and the pipeline imports the ORM.

    The two timeouts are here for a harder reason than the others. A rebuild
    killed by its own deadline - `RebuildTimedOut` from the stage boundary
    check, `subprocess.TimeoutExpired` from a binary handed the remaining
    budget - is not going to finish inside six hours on the next attempt
    either; the budget is the same and the work is the same. Left retryable it
    was retried five times, and a retry re-runs the whole rebuild including
    SWAP, whose `DROP SCHEMA live_old` destroys the very schema a rollback
    would put back. The first timed-out rebuild would have spent thirty hours
    of CPU dismantling its own rollback target one attempt at a time.

    `RebuildTimedOut` raised *between* stages is caught by name in the task
    body; this entry is for the same class arriving as a `RebuildFailed.cause`,
    which is what happens when a handler's own `_run_command` finds no budget
    left.
    """
    import subprocess

    from pipeline.elevation import ElevationTileInvalid
    from pipeline.rebuild import RebuildTimedOut, StageNotImplemented
    from pipeline.run import ReferenceDataMissing, ValidationFailed
    from pipeline.tiles import DiskGateRefused, TilePathsNotPerVariant

    return (
        ValidationFailed,
        ReferenceDataMissing,
        DiskGateRefused,
        StageNotImplemented,
        ElevationTileInvalid,
        TilePathsNotPerVariant,
        RebuildTimedOut,
        subprocess.TimeoutExpired,
    )


def _retry_only_rebuild_failures() -> None:
    from pipeline.rebuild import RebuildFailed

    weekly_rebuild.retry_strategy.retry_exceptions = [RebuildFailed]


_retry_only_rebuild_failures()


class BackupTimedOut(RuntimeError):
    """The dump ran past its budget and was killed. Not retried."""


class RetryUnlessTimedOut(RetryStrategy):
    """`RETRY`, except for a job that ran out of its own time budget.

    A dump killed at thirty minutes is not a transient failure: the budget is
    the same on the next attempt and so is the lock or the stalled write that
    consumed it. Retried, it would hold the single-slot maintenance queue for
    thirty minutes five more times - two and a half hours of exactly the
    starvation the timeout was added to end. The nightly schedule is the retry,
    and the 26-hour alert window is what notices if that one fails too.
    """

    def get_retry_decision(self, *, exception, job):  # type: ignore[override]
        if isinstance(exception, BackupTimedOut):
            return None
        return super().get_retry_decision(exception=exception, job=job)


@app.periodic(cron=NIGHTLY_BACKUP_CRON)
@app.task(
    name="nightly_backup",
    queue="maintenance",
    queueing_lock="nightly_backup",
    retry=RetryUnlessTimedOut(
        max_attempts=RETRY.max_attempts, exponential_wait=RETRY.exponential_wait
    ),
)
def nightly_backup(timestamp: int) -> None:
    """Dump the database, excluding the membership cache and the sessions, then
    prune what the dump and the run history leave behind.

    The cache is excluded rather than dumped and protected. Who organizes with
    whom is the sensitive part of this deployment, and the cache is rebuildable
    from the bot's backfill, so the copy that sits on disk for months is the one
    worth not having.

    The pruning rides here rather than on a schedule of its own for the same
    reason the session sweep rides with the membership sweep: it is the same
    shape of work, it is cheap, and a second schedule is a second thing to
    notice had stopped. It runs after the dump has been written and verified, so
    a night on which the backup fails keeps every old dump it has.
    """
    from django.conf import settings

    from core.runs import prune_job_rows, prune_run_rows, record
    from pipeline import retention

    with record("nightly_backup") as run:
        destination = perform_backup()
        pruned_dumps = retention.prune_backups(settings.BACKUP_DIR, keep=BACKUP_KEEP)
        run.detail = (
            f"{destination}; pruned {len(pruned_dumps)} old dumps, "
            f"{prune_run_rows()} run rows, {prune_job_rows()} finished job rows"
        )
        run.save(update_fields=["detail"])


@app.periodic(cron=MEMBERSHIP_SWEEP_CRON)
@app.task(
    name="membership_sweep", queue="maintenance", queueing_lock="membership_sweep", retry=RETRY
)
def membership_sweep(timestamp: int) -> None:
    """The backstop for what the gateway missed, and the privacy purge.

    Revocation lands in seconds through the gateway; this catches a disconnect.
    It also drops rows for people who have never signed in, so the cache does not
    quietly accumulate a roster of a guild's membership, and rows for accounts
    that have been deleted or ban-tombstoned, which go on sight.

    The session sweep runs here too, for the same reason the membership purge
    does: both hold rows naming who was signed in, or who organizes with whom,
    for people who may have asked to be forgotten.
    """
    from core.membership import sweep_memberships
    from core.models import apply_due_instance_admin_removals
    from core.revocation import sweep_sessions
    from core.runs import record, run_with_deadline

    def sweep() -> tuple[int, int, int, int]:
        # The session sweep rides here rather than on a cron of its own: it is
        # the same shape of work (rows nothing will ever accept again, for
        # people who may have asked to be forgotten), it is cheap, and a second
        # schedule would be a second thing to notice had stopped. Inside the
        # same deadline, so the budget covers the task rather than half of it.
        # Due instance-admin removals ride here too, as a backstop rather than
        # as the applier. The applier is the five-minute degraded sweep: at this
        # task's `0 */6 * * *` the plan's one-hour delay was really one to seven
        # hours, depending on where in the cycle the removal was requested. It is
        # kept here as well because it is one indexed query on a table that is
        # almost always empty, and because this is the sweep whose absence the
        # operations alerts already notice - so if the five-minute task stops,
        # removals are late rather than never. On a healthy deployment this
        # reports zero, which is the honest number.
        purged, departed = sweep_memberships()
        return purged, departed, sweep_sessions(), apply_due_instance_admin_removals()

    with record("membership_sweep") as run:
        purged, departed, sessions, removals = run_with_deadline(
            sweep, SWEEP_TIMEOUT_S, "membership_sweep"
        )
        # "never-signed-in" was the whole of the purge once and is not any more:
        # the count now also carries rows dropped for deleted and tombstoned
        # accounts, which go on sight rather than after thirty days.
        run.detail = (
            f"purged {purged} forgotten and never-signed-in rows, "
            f"dropped {departed} departed rows and {sessions} session rows, "
            f"applied {removals} due instance-admin removals"
        )
        run.save(update_fields=["detail"])


@app.periodic(cron=DEGRADED_GUILD_SWEEP_CRON)
@app.task(
    name="degraded_guild_sweep",
    queue="maintenance",
    queueing_lock="degraded_guild_sweep",
)
def degraded_guild_sweep(timestamp: int) -> None:
    """Mark guilds degraded while the gateway is silent, and restore them after.

    Gated on the gateway having ever reported, and the gate is not a nicety.
    `mark_degraded_guilds` reads the deployment-wide gateway clock from a
    `ScheduledRun(task="gateway_heartbeat")` row and fails *closed* when there
    is none: it marks every active guild degraded, and standing lapses 72 hours
    later. That is the correct reading for a bot that has gone quiet, and it is
    catastrophic here, because on this deployment nothing writes that heartbeat
    at all - the bot is phase-1 work that has not been built (see the handoff's
    "no bot" item). Ungated, the first tick after deploy would revoke the whole
    deployment's standing on a schedule, for an outage that has not happened.

    So the transition arms itself: until one heartbeat row exists this logs that
    it is waiting for the gateway and touches nothing. The moment the bot writes
    its first heartbeat the task is live, with no deploy step to remember.

    Not retried. It is idempotent and runs every five minutes, so the next tick
    is the retry - and a retry schedule would hold the queueing lock through
    several ticks, which is the opposite of what a five-minute bound wants.

    It also applies due instance-admin removals, and that half runs whatever the
    gateway gate says.

    PLAN.md:212 makes the removal of a peer take effect "after a delay,
    configurable and defaulting to an hour". The only thing that applied one was
    the membership sweep on `0 */6 * * *`, so an hour's delay was in fact between
    one and seven hours depending on where in the six-hour cycle the removal was
    requested - a removed admin kept every power for most of a working day. This
    is the five-minute task, so the delay becomes the plan's hour plus at most
    five minutes.

    Outside the gate deliberately. The gate exists because `mark_degraded_guilds`
    fails closed on a deployment whose bot has never reported and would revoke
    every guild's standing for an outage that has not happened. Applying a
    removal whose clock has already run out depends on no gateway, no bot and no
    heartbeat; holding it behind that gate would mean that on this deployment -
    where nothing writes a heartbeat at all, because the bot is unbuilt - the
    five-minute path applied nothing and the effective delay was still six hours.
    """
    import logging

    from core.models import apply_due_instance_admin_removals
    from core.revocation import gateway_has_ever_reported, mark_degraded_guilds
    from core.runs import record

    with record("degraded_guild_sweep") as run:
        if not gateway_has_ever_reported():
            logging.getLogger(__name__).info(
                "no gateway heartbeat has ever been recorded, so the degraded mark is "
                "held: this would otherwise degrade every guild on a deployment whose "
                "bot has not been built yet"
            )
            detail = "waiting for the gateway: no heartbeat has ever been recorded"
        else:
            marked, restored = mark_degraded_guilds()
            detail = f"marked {marked} guilds degraded, restored {restored} to active"
        removals = apply_due_instance_admin_removals()
        run.detail = f"{detail}; applied {removals} due instance-admin removals"
        run.save(update_fields=["detail"])


@app.periodic(cron=WORKER_HEARTBEAT_CRON)
@app.task(name="worker_heartbeat", queue="maintenance", queueing_lock="worker_heartbeat")
def worker_heartbeat(timestamp: int) -> None:
    """Write a row saying the worker is still running jobs.

    The plan's health check for the worker, and the one alert on the list that
    fires when the component that writes every *other* alert row has died: a
    stalled worker stops writing the backup row and the sweep rows too, but
    their windows are 26 and 12 hours, so without this the deployment would take
    half a day to notice. This is the cheapest honest form - the row is written
    by the same machinery as every other periodic task, so "the worker is dead"
    becomes a stale row like everything else rather than a second mechanism.

    Honest about what it measures: it reports that the worker dequeued and
    finished a job, not that its process is alive. On a one-slot maintenance
    worker a job holding the slot past the window shows up here as a gap, which
    is a true statement about a worker that is running nothing else - and the
    reason every task on this queue has a bounded timeout.

    Not retried, for the same reason the degraded-guild sweep is not: the next
    tick is the retry, and a retry schedule would hold the queueing lock across
    several ticks of the bound it exists to keep.
    """
    from core.runs import record

    with record("worker_heartbeat") as run:
        run.detail = f"worker alive, pid {os.getpid()}"
        run.save(update_fields=["detail"])


class BackupVerificationFailed(RuntimeError):
    """The dump on disk is not the dump the task promised."""


def perform_backup(
    now=None,
    read_listing: Callable[[Path, dict, float], str] | None = None,
    timeout_s: float | None = None,
) -> Path:
    """pg_dump to the data volume, then read the archive's table of contents
    back to prove it is what was asked for. Separated so the task body stays
    readable. `read_listing` is pg_restore --list, injectable so a test can
    hand this function a listing that leaks and watch it refuse.

    Both binaries run under one budget, the same way the rebuild runs its own:
    a monotonic deadline taken once, and whatever is left of it handed to each
    subprocess as its timeout. One budget rather than one each, because what is
    bounded is the maintenance slot the whole task holds, not either process.
    """
    import subprocess

    from django.conf import settings
    from django.utils import timezone

    read_listing = read_listing or _pg_restore_list
    now = now or timezone.now()
    deadline = time.monotonic() + (BACKUP_TIMEOUT_S if timeout_s is None else timeout_s)
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = settings.BACKUP_DIR / f"routemaker-{now:%Y%m%dT%H%M%SZ}.dump"
    database = settings.DATABASES["default"]
    env = {**os.environ, "PGPASSWORD": database["PASSWORD"]}
    try:
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
            timeout=_remaining(deadline, "pg_dump"),
        )
        listing = read_listing(destination, env, _remaining(deadline, "pg_restore --list"))
    except subprocess.TimeoutExpired as expired:
        # The child is already killed by subprocess.run; what is left is the
        # half-written archive, which must not be mistaken for last night's.
        destination.unlink(missing_ok=True)
        raise BackupTimedOut(
            f"the backup exceeded its {BACKUP_TIMEOUT_S:.0f}s budget and was killed "
            f"while running {expired.cmd[0]}"
        ) from expired
    verify_dump_listing(listing)
    return destination


def _remaining(deadline: float, what: str) -> float:
    """What is left of the budget, or a refusal to start something that cannot
    finish inside it."""
    import subprocess

    left = deadline - time.monotonic()
    if left <= 0:
        raise subprocess.TimeoutExpired(cmd=[what], timeout=0)
    return left


def _pg_restore_list(archive: Path, env: dict, timeout: float | None = None) -> str:
    import subprocess

    return subprocess.run(
        ["pg_restore", "--list", str(archive)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
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

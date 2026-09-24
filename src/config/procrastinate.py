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
from procrastinate.exceptions import JobAborted

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


# What a finished swap leaves the operator to do, in one place because it is
# said twice - once in the success detail and once in the message a failure
# after the swap is abandoned with - and the two must not drift. The abandoned
# message used to say "the new build is being served", which is the one thing
# that is not true until somebody restarts the routers: the schema swap is
# instant, the tile directories are not, so an operator reading that alert
# concluded there was nothing to do and left three routers serving last week's
# graph against this week's segment rows.
ROUTER_RESTART_NOTICE = (
    "The routers serve the previous build until they are restarted: "
    "`docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike`."
)


class RebuildAlreadyRunning(JobAborted):
    """Another `weekly_rebuild` job is already `doing`, so this one will not start.

    Not retried: the reason this job cannot run is that another one is running,
    and by the time a retry came round the thing to do would be to look at that
    one rather than to start a third. `RebuildAbandoned` carries the same
    meaning for every other terminal cause; this is a class of its own so that
    the message reads as what it is - and so that the job lands in a status
    that reads as what it is.

    That is what `JobAborted` buys, and it is not cosmetic. A task body that
    raises anything else is finished `failed` by the worker
    (`procrastinate.worker.Worker._process_job`), and `failed` is what both
    alert surfaces count: a Tuesday tick that correctly declined to start a
    second rebuild left a failed job on the operations page and a non-zero
    `check_operations` for the thirty days `prune_job_rows` keeps it, with
    nothing an operator could do to clear it and nothing wrong. `JobAborted`
    finishes the job `aborted` instead - a terminal status, pruned on the same
    schedule, counted by neither alert - and the worker deliberately computes no
    retry decision for it, so "not retried" is the class's own doing rather than
    a line in the retry strategy.
    """


@app.periodic(cron=WEEKLY_REBUILD_CRON)
@app.task(
    name="weekly_rebuild",
    queue="rebuild",
    queueing_lock="weekly_rebuild",
    pass_context=True,
    retry=RetryStrategy(
        max_attempts=RETRY.max_attempts,
        exponential_wait=RETRY.exponential_wait,
        retry_exceptions=[],  # filled below, once the exception class is importable
    ),
)
def weekly_rebuild(context=None, *, timestamp: int) -> None:
    """Build into staging and a dated tile directory, validate, swap, reconcile.

    Queued under a lock because two concurrent rebuilds would write the same
    staging schema and the same tile directory. It gets its own queue so the
    six-hour build does not sit in front of the sweep - and so that the
    container with the Valhalla binaries and the data mounts is the one that
    runs it: compose's `rebuild` service is a worker on this queue alone.

    The lock is not the whole of that guarantee and was read as if it were.
    Procrastinate's queueing-lock index is partial on `WHERE status = 'todo'`,
    so it deduplicates *queued* rebuilds and permits the tick to queue one
    behind a rebuild that is `doing`. What has been serialising those in
    practice is `--concurrency=1` on the rebuild service: the second job waits
    because there is one slot, not because anything refused it. So the pre-flight
    below refuses to *start* while another `weekly_rebuild` is `doing`, which is
    the guarantee the docstring claimed - it holds for a second rebuild worker,
    for a slot count somebody raises, and for the hand-fired job that
    `run_rebuild_now` queues, where the tick is the second caller rather than
    the first.

    `context` is Procrastinate's job context, which is how this job knows its
    own id and does not refuse itself. It defaults to None so the task body
    stays callable directly, which is how the suite runs it.

    Retention brackets the run rather than following it: once before the disk
    gate, which is terminal and would otherwise refuse every week on a volume
    the prune could have made room on, and once in a `finally`, so the
    directory a failed rebuild wrote does not sit on the volume until the
    second following success.
    """
    from django.conf import settings

    from core.runs import jobs_in_flight, record
    from pipeline import retention
    from pipeline.rebuild import RebuildFailed, RebuildTimedOut, run_rebuild
    from pipeline.run import RebuildContext, build_handlers

    # Before the run row is opened, so a duplicate that never starts does not
    # write a failure row for a rebuild that is running perfectly well.
    job_id = getattr(getattr(context, "job", None), "id", None)
    running = jobs_in_flight("weekly_rebuild", statuses=("doing",), exclude_id=job_id)
    if running:
        other = running[0]
        raise RebuildAlreadyRunning(
            f"refusing to start: job {other.id} is already running a weekly_rebuild on the "
            f"{other.queue_name} queue, and two at once write the same staging schema and "
            "the same tile directory. Watch that one, or look at the operations page."
        )

    with record("weekly_rebuild") as run:
        context = RebuildContext(
            source_pbf=settings.REBUILD_SOURCE_PBF,
            work_dir=settings.REBUILD_WORK_DIR,
            reference_dir=settings.REBUILD_REFERENCE_DIR,
            deadline=time.monotonic() + REBUILD_TIMEOUT_S,
        )
        # Before the disk gate, which is the first thing the first stage runs.
        # Pruning only after a successful run put the whole of retention
        # downstream of a gate that is terminal: once the volume was too full
        # for a second tile set the gate refused every week, and the one
        # mechanism that could have freed the space never ran again, however
        # many prunable builds were sitting on the volume. It is safe here by
        # construction - `prune_builds` never removes what `current` or
        # `previous` points at, which is the served graph and the rollback
        # target, and this rebuild has written nothing yet.
        reclaimed = _prune_tile_builds(
            context.tiles_dir, retention.KEEP_BUILDS, "before the disk gate"
        )
        try:
            try:
                report = run_rebuild(build_handlers(context), deadline=context.deadline)
            except RebuildTimedOut as timed_out:
                # The between-stages door, reshaped into the one the stages
                # themselves come through. Both are "this rebuild stopped at
                # stage X", and the classification below turns on nothing but
                # the stage - so a budget that lapsed at the SWAP -> RECONCILE
                # boundary used to be abandoned with "the time budget ran out"
                # and no mention that the schema had already been renamed, while
                # the identical failure from inside the reconcile handler got the
                # swap-completed message and the router-restart notice. One
                # classification, both doors.
                if timed_out.stage is None:
                    raise
                raise RebuildFailed(timed_out.stage, timed_out) from timed_out
        except RebuildFailed as error:
            if error.stage in stages_after_swap():
                # The swap completed, so `live_old` is now the schema a
                # rollback would put back - and a retry re-runs SWAP, whose
                # `DROP SCHEMA live_old CASCADE` destroys it. The reconcile is
                # a report rather than a promotion, so the deployment is
                # serving the new build correctly and what is missing is the
                # drift row; that is worth an alert and a hand-run, not five
                # more swaps.
                raise RebuildAbandoned(
                    f"{error}. The swap completed, so this rebuild is not retried: a retry "
                    f"would re-run the swap and drop the {settings.SEGMENT_SCHEMA_RETIRED} "
                    f"schema a rollback needs. {ROUTER_RESTART_NOTICE} Re-run the "
                    "reconciliation by hand, or let next week's rebuild write the next "
                    "drift report."
                ) from error
            if isinstance(error.cause, terminal_causes()):
                raise RebuildAbandoned(str(error)) from error
            raise
        except RebuildTimedOut as error:
            # Only a timeout that names no stage reaches this, which `run_rebuild`
            # does not raise today. Kept so that the class is terminal however it
            # arrives rather than retried by default.
            #
            # It is therefore unreachable defensive code, deliberately, and it is
            # written down here because the suite cannot say so: no test can
            # construct the call that lands in this arm, so deleting the arm
            # breaks nothing and a mutation that removes it cannot be killed.
            # The line it costs is the price of `RebuildTimedOut` staying
            # terminal if `run_rebuild` ever raises one without a stage.
            raise RebuildAbandoned(str(error)) from error
        finally:
            # On every path, not only the successful one. A rebuild that died
            # after BUILD_TILES left a third tile set on the volume that
            # nothing removed until the *second* following success, because
            # the prune ran after `run_rebuild` returned and a failure never
            # returns. What survives here is what the promotion symlinks name -
            # the served graph and the rollback target - plus this run's own
            # build, which is `current` if it swapped and something to look at
            # if it did not. Everything else goes now rather than a week from
            # now, so a second failed week does not leave a fourth tile set.
            reclaimed += _prune_tile_builds(
                context.tiles_dir, 0, "after the run", protect=[context.build_id]
            )
        # The override report rides on the row an operator reads first. It was
        # computed every week and read by nothing, so whether a reviewed
        # correction was in force - or had matched no way in this week's
        # extract - was findable only in the log.
        overridden = (
            f" {context.override_report.summary()}." if context.override_report is not None else ""
        )
        run.detail = (
            f"build {context.build_id}: {len(report.completed)} stages completed, "
            f"pruned {reclaimed} old build directories.{overridden} {ROUTER_RESTART_NOTICE}"
        )
        run.save(update_fields=["detail"])


def _prune_tile_builds(tiles_dir, keep: int, what: str, protect=()) -> int:
    """`retention.prune_tile_builds`, counted, and never the reason a rebuild fails.

    It runs in a `finally` that is on the path of every failure the rebuild can
    have, so an error raised here would replace the error being reported - the
    rebuild's own, which is the one the alert and the run row need to name. A
    prune that cannot run is logged and left to the next attempt; the disk gate
    is what notices if it never runs at all.
    """
    import logging

    from pipeline import retention

    try:
        pruned = retention.prune_tile_builds(tiles_dir, keep=keep, protect=protect)
    except Exception:  # noqa: BLE001 - cleanup must not replace the failure it follows
        logging.getLogger(__name__).exception("could not prune old build directories %s", what)
        return 0
    return sum(len(builds) for builds in pruned.values())


def stages_after_swap() -> frozenset:
    """Stages that run once the schema rename has been made.

    A failure in one of them is terminal however ordinary its cause. The
    retry strategy retries a plain `RebuildFailed`, and a retried rebuild
    runs the whole thing again including SWAP - whose `DROP SCHEMA live_old
    CASCADE` destroys the schema a rollback would put back. So the first
    `RECONCILE` failure, a reconciliation that hit a database hiccup, would
    have dismantled the rollback target on its way to reporting the same
    error five more times.

    Derived from the stage order rather than written out, so a stage added
    after the swap is terminal on the day it is added. Imported lazily for the
    same reason `terminal_causes` is: this module is imported at Django
    app-ready time and the pipeline imports the ORM.
    """
    from pipeline.rebuild import Stage, stages_before

    return frozenset(Stage) - set(stages_before(Stage.SWAP)) - {Stage.SWAP}


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

    Both doors arrive here as a `RebuildFailed.cause` now: the one a handler's
    own `_run_command` comes through when it finds no budget left, and the
    between-stages check, which carries the stage it was about to start and is
    wrapped into the same `RebuildFailed` by the task body. That is what makes
    the stage-after-swap branch cover a timeout as well, so a budget that lapses
    at the SWAP -> RECONCILE boundary is abandoned with the router-restart
    notice rather than with "the time budget ran out" and nothing else.

    `SwapUndoIncomplete` is here for a third reason again, and it is about what
    a retry would be running *on*. A swap that failed and undid itself is
    retryable and should be - the deployment is back on the build it was
    serving. A swap whose undo did not finish leaves one variant on this week's
    tiles and two on last week's, or settings rows naming a build no tile
    directory describes, and the stage is SWAP rather than after it, so nothing
    else in this function's sight made it terminal: the ordinary shape of that
    failure, a symlink write refused by a read-only volume, was retried five
    times over a deployment no component had a consistent picture of. The undo
    reporting a failure is the signal, not the cause of the original error.
    """
    import subprocess

    from pipeline.elevation import ElevationTileInvalid
    from pipeline.promotion import SwapUndoIncomplete
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
        SwapUndoIncomplete,
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
    notice had stopped.

    It runs in a `finally`, which is the difference between "rides here" and
    "rides on the dump succeeding". Every prune was downstream of `pg_dump`, so
    a dump that failed - a lock, a full volume, the thirty-minute timeout -
    stopped the run-row and job-row pruning as well, and those two are what
    keep `procrastinate_jobs` and `scheduled_run` from growing without bound.
    The one failure mode that fills a volume therefore also switched off the
    mechanism that reclaims space on it, and it stayed off for as many nights
    as the dump kept failing. Only the *dump* retention is still conditional,
    and only in the direction that is safe: `prune_backups` runs on the failure
    path too, but with nothing new written it has one fewer dump to count, so a
    failed night keeps the oldest dump it would otherwise have dropped.
    """
    from django.conf import settings

    from core.runs import prune_job_rows, prune_run_rows, record
    from pipeline import retention

    with record("nightly_backup") as run:
        try:
            destination = perform_backup()
        finally:
            # Counted into locals rather than into the f-string below, because
            # the f-string is on the success path and these have to run on
            # both. `record` re-raises whatever `perform_backup` raised, so a
            # failed night still fails - it just fails having pruned.
            pruned_dumps = retention.prune_backups(settings.BACKUP_DIR, keep=BACKUP_KEEP)
            pruned_runs = prune_run_rows()
            pruned_jobs = prune_job_rows()
        run.detail = (
            f"{destination}; pruned {len(pruned_dumps)} old dumps, "
            f"{pruned_runs} run rows, {pruned_jobs} finished job rows"
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

    The dump is written to `<name>.dump.part` and renamed to `<name>.dump` only
    after the verification has passed, and the part file is removed on every
    failure path. A dump under the ordinary name is therefore a dump that was
    written whole and read back, which is the only promise a restore procedure
    can act on.
    """
    import subprocess

    from django.conf import settings
    from django.utils import timezone

    read_listing = read_listing or _pg_restore_list
    now = now or timezone.now()
    deadline = time.monotonic() + (BACKUP_TIMEOUT_S if timeout_s is None else timeout_s)
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = settings.BACKUP_DIR / f"routemaker-{now:%Y%m%dT%H%M%SZ}.dump"
    # Written under a name no restore would ever pick and renamed only once the
    # listing has been read back and accepted. Only the timeout used to clean up
    # after itself, so a `pg_dump` that exited non-zero - a wrong database name,
    # a permission error, a full volume - and a dump the verification rejected
    # both left `routemaker-<instant>.dump` on the volume: the newest by name,
    # which is precisely the one an operator restoring "last night's" reaches
    # for, and in the verification case possibly carrying the membership-cache
    # rows the exclusion exists to keep off the disk. `prune_backups` matches
    # the final name only, so a part file is never mistaken for a kept dump
    # either.
    part = destination.with_name(destination.name + ".part")
    database = settings.DATABASES["default"]
    env = {**os.environ, "PGPASSWORD": database["PASSWORD"]}
    try:
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
                    f"--file={part}",
                    database["NAME"],
                ],
                check=True,
                env=env,
                timeout=_remaining(deadline, "pg_dump"),
            )
            listing = read_listing(part, env, _remaining(deadline, "pg_restore --list"))
        except subprocess.TimeoutExpired as expired:
            # The child is already killed by subprocess.run; what is left is the
            # half-written archive, which the cleanup below removes.
            raise BackupTimedOut(
                f"the backup exceeded its {BACKUP_TIMEOUT_S:.0f}s budget and was killed "
                f"while running {expired.cmd[0]}"
            ) from expired
        verify_dump_listing(listing)
        # The rename is the last thing that happens, so the ordinary name exists
        # only for an archive that was written whole and verified.
        part.replace(destination)
    except BaseException:
        # Every failure path, including the ones nothing here anticipates: what
        # must not survive is a partial or rejected archive under a name the
        # restore procedure trusts.
        part.unlink(missing_ok=True)
        raise
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

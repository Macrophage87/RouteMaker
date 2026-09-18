"""Recording that a scheduled task ran.

Every periodic task writes a row here, success or failure, because the failures
that matter most produce nothing to read. A rebuild that stopped being scheduled
and a backup that stopped being taken both emit no error at all, so an alert
built on the absence of an error stays silent through precisely the two outages
it exists for. What is watched is the absence of a recent success.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import TypeVar

from django.utils import timezone

from .models import ScheduledRun

logger = logging.getLogger(__name__)

# How long each task may go without a success before it is considered broken.
# The rebuild's window is eight days rather than seven, so one missed run is not
# an alert; two are. The backup's is 26 hours for the same reason at a day's
# cadence.
#
# The two five-minute tasks are windowed at six missed ticks rather than at one.
# A single dropped tick is ordinary: Procrastinate skips a periodic job whose
# previous one is still queued or locked, so any job ahead of it on the
# maintenance queue - a backup, a sweep - drops the tick that falls under it,
# and a worker restart drops one too. Six consecutive misses is not a skipped
# tick, it is a worker that stopped, and thirty minutes is well inside the
# windows either task feeds: the degraded mark's own deadline is anchored to the
# gateway heartbeat row rather than to the time of the mark, so a mark made half
# an hour late still lapses standing at the same instant, and the plan's
# ten-minute heartbeat alert fires first and names the worker directly.
#
# The heartbeat's window is the plan's own number - "worker heartbeat silent for
# 10 minutes" - which is two missed ticks of its five-minute schedule. It is
# deliberately the tightest window here: it is the one alert that fires when the
# worker itself has died, and every other row on this list stops being written
# at the same moment without any of their windows having passed.
STALE_AFTER = {
    "weekly_rebuild": 8 * 24 * 60 * 60,
    "nightly_backup": 26 * 60 * 60,
    "membership_sweep": 12 * 60 * 60,
    "degraded_guild_sweep": 30 * 60,
    "worker_heartbeat": 10 * 60,
}

# How long a run row is kept. The five-minute tasks alone write about 105,000
# rows a year into a table nothing ever pruned, and the rows are read by exactly
# one question - "has this task succeeded lately" - which needs the newest row
# and no other. Thirty days is what the plan retains request logs for, and it is
# long enough that the morning after a bad week still has the history in it.
RUN_ROW_RETENTION_S = 30 * 24 * 60 * 60

# Finished Procrastinate jobs and their events, same reasoning and same number.
# Only terminal jobs are pruned: a row still `todo` or `doing` is live state the
# worker owns, whatever its age.
JOB_ROW_RETENTION_S = RUN_ROW_RETENTION_S
TERMINAL_JOB_STATUSES = ("succeeded", "failed", "cancelled", "aborted")


@contextmanager
def record(task: str) -> Iterator[ScheduledRun]:
    """Open a run row, close it on the way out, and let the error through.

    The failure is re-raised rather than swallowed: Procrastinate's own retry and
    dead-job handling are what should see it. This row is for the alert that
    notices nothing has succeeded lately, which is a different question from
    whether this attempt failed.
    """
    run = ScheduledRun.objects.create(task=task, started_at=timezone.now())
    try:
        yield run
    except Exception as error:
        run.finished_at = timezone.now()
        run.succeeded = False
        run.detail = f"{type(error).__name__}: {error}"[:4000]
        run.save(update_fields=["finished_at", "succeeded", "detail"])
        logger.exception("scheduled task %s failed", task)
        raise
    run.finished_at = timezone.now()
    run.succeeded = True
    run.save(update_fields=["finished_at", "succeeded", "detail"])


def last_success(task: str):
    """The most recent successful run of a task, or None."""
    return ScheduledRun.objects.filter(task=task, succeeded=True).order_by("-started_at").first()


def first_run_at():
    """When this deployment first recorded a scheduled run, or None.

    The oldest `ScheduledRun` row of any task and any outcome. It is half of
    `deployment_epoch`, and the half that only exists once something has run.
    """
    row = ScheduledRun.objects.order_by("started_at").first()
    return None if row is None else row.started_at


def migrations_applied_at():
    """When this deployment last applied a migration, or None.

    `MAX(django_migrations.applied)`, which is written by `migrate` and by
    nothing else. Every deployment procedure in docs/DEPLOYMENT.md runs
    `migrate` before it starts a worker, so this row exists on a stack where no
    job has ever been dequeued - which is the case the run-row epoch could not
    see. Nothing in this project prunes `django_migrations`, so unlike the run
    rows it does not move once written.

    Read with SQL rather than through `MigrationRecorder`, which would build a
    model and a table check on a path that runs on every alert tick.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(applied) FROM django_migrations")
        row = cursor.fetchone()
    return None if row is None else row[0]


def deployment_epoch():
    """The moment every never-succeeded task's window is measured from.

    The earlier of the deployment's first run row and its last migration, and
    None only when there is neither - which on a database Django can read
    cannot happen, because `migrate` is what created the table this query runs
    against.

    Two reasons it is not `first_run_at` alone, and both are outages the old
    predicate reported as "ok":

    - **A worker that never dequeued anything writes no run row at all.** A
      `--queues` typo, a crash loop, a maintenance container that never came
      up: jobs pile up `todo`, no row is ever written, `first_run_at` is None,
      and with no epoch nothing is ever stale. `check_operations` printed "ok"
      for ever on a deployment whose scheduler had never run once - the exact
      deployment the ten-minute heartbeat alert exists for. The migration row
      exists from the first `migrate`, so the heartbeat's window starts when the
      deployment does rather than when its first job finishes.
    - **The run-row epoch drifts.** `prune_run_rows` keeps the newest row per
      task and drops the rest past `RUN_ROW_RETENTION_S`, so on a deployment
      older than that retention `first_run_at` is not "when this stack started
      running", it is "thirty days ago", and it walks forward every night. The
      migration timestamp is written once and pruned by nothing, so taking the
      earlier of the two pins the epoch to it on any deployment older than the
      retention and the alert's own reference stops moving.

    A fresh deployment still does not page in its first minute: `migrate` ran a
    moment ago, no run row is older, so the epoch is a moment ago and every
    window is still open. What it does not do is give a task *newly added* to
    `STALE_AFTER` a grace period of its own on an old deployment - it is named
    on the first tick until it succeeds once, which is one alert that clears
    itself rather than a silence.
    """
    candidates = [moment for moment in (first_run_at(), migrations_applied_at()) if moment]
    return min(candidates) if candidates else None


def stale_tasks(now=None) -> list[str]:
    """Tasks with no success inside their window. What the alert reads."""
    return [entry["task"] for entry in stale_task_details(now)]


def stale_task_details(now=None) -> list[dict]:
    """The same answer with its evidence attached, for the surfaces that show it.

    One predicate, used by both, because two copies of "is this task stale"
    drift: an operations page that disagrees with the alert about which task is
    broken is worse than not having the page.

    Two cases, and the second is the one that used to be wrong:

    - A task that has succeeded is stale once that success is older than its
      window. Unchanged, and it is the whole of the steady-state rule.
    - A task that has never succeeded is stale once its window has elapsed
      *since this deployment's epoch* - not immediately. "Never" and "not yet"
      are the same absence of a row and they are not the same condition: every
      window on this list is measured from a moment, and on a minute-old
      deployment no moment has passed. The old predicate called all five stale
      from the first `up`, so `check_operations` - the documented cron entry -
      exited 1 on a deployment where nothing at all was wrong, and a monitor
      that pages on the first morning of every install is a monitor that gets
      muted.

    The epoch is `deployment_epoch`, and it used to be the first run row alone.
    That reads None on a deployment whose worker never dequeued a single job -
    a `--queues` typo, a crash loop - so nothing was ever stale and this
    function returned an empty list for ever on exactly the outage the
    ten-minute heartbeat window exists to name. See `deployment_epoch` for what
    replaced it and why it does not drift.

    What this does not do is excuse a task that is never registered at all. The
    windows keep running from the epoch, so a task missing from the worker's
    schedule is stale as soon as its own window has passed - eight days for the
    rebuild, ten minutes for the heartbeat - which is the same lateness any
    other silent failure gets.
    """
    now = now or timezone.now()
    started = deployment_epoch()
    stale = []
    for task, window in STALE_AFTER.items():
        run = last_success(task)
        if run is not None:
            age = (now - run.started_at).total_seconds()
            if age < window:
                continue
        else:
            age = None
            if started is None or (now - started).total_seconds() < window:
                continue
        stale.append(
            {
                "task": task,
                "window_s": window,
                "last_success_at": None if run is None else run.started_at,
                "age_s": age,
            }
        )
    return stale


T = TypeVar("T")


class TaskTimedOut(RuntimeError):
    """A scheduled task ran past its budget and was abandoned."""


# How long the caller waits, after cancelling the abandoned thread's query, for
# that thread to unwind and close its own connection properly. Past it the
# caller closes the socket itself. Short because it is only ever paid on the
# timeout path, and long enough for a cancelled statement to raise and a
# `finally` to run.
ABANDON_GRACE_S = 0.5


def run_with_deadline(function: Callable[[], T], timeout_s: float, name: str = "task") -> T:
    """Run a task body with a hard time budget.

    The body runs in its own thread with its own database connection, and the
    caller waits at most `timeout_s`. Past that the caller raises and the job
    fails - which is what lets Procrastinate retry it and the alert see it -
    while the abandoned body is left to finish or die with the process. This is
    the enforcement for the sweep, which is pure Python and SQL and cannot be
    given a subprocess timeout the way the rebuild's binaries can.

    "Left to finish" used to include the connection it had opened. Django's
    connections are per-thread, so the `finally` below runs on the thread that
    owns the connection and is the only place that can close it politely - and
    it does not run at all while the body is still going. A sweep abandoned at
    its deadline therefore sat on a backend for as long as it kept running,
    every five minutes, with up to six copies resident; the suite proved it by
    failing to drop its own test database afterwards.

    So the deadline now reaches into the abandoned thread. `cancel()` is
    PQcancel, which is the one libpq entry point documented as safe to call from
    another thread, and it unblocks a statement in flight so the body raises and
    closes its own connection on the way out. A body blocked in Python rather
    than in the database has nothing to cancel, so after a short grace the caller
    closes the socket itself: an abandoned thread that is going to be killed by
    the process is not a reason to hold a backend open until then.
    """
    from django.db import connections

    outcome: dict[str, object] = {}
    opened: dict[str, object] = {}

    def body() -> None:
        # Bound on this thread, where `connections["default"]` is this thread's
        # own wrapper, so the caller can reach the right one.
        opened["connection"] = connections["default"]
        try:
            outcome["result"] = function()
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller's thread
            outcome["error"] = error
        finally:
            connections["default"].close()

    thread = threading.Thread(target=body, name=f"{name}-deadline", daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        _release_abandoned_connection(opened.get("connection"), thread, name)
        raise TaskTimedOut(f"{name} exceeded its {timeout_s:.0f}s budget and was abandoned")
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["result"]  # type: ignore[return-value]


def _release_abandoned_connection(wrapper, thread: threading.Thread, name: str) -> None:
    """Give an abandoned thread's database connection back to the server.

    The close at the end is the one thing here that can take the process with
    it. `close()` is PQfinish, and psycopg 3.3.5 calls it without holding the
    connection's lock, so closing while the abandoned thread is still inside
    libpq - between `PQsendQuery` and `PQgetResult`, which is where a thread
    blocked on a statement sits - frees a `PGconn` another thread is reading:
    a segfault of the whole worker, to reclaim one backend. The grace above is
    half a second, and half a second is a guess about how long a cancelled
    statement takes to raise, not a guarantee.

    So the close is gated on the connection being idle. `transaction_status`
    is read from `PGconn` itself rather than from any bookkeeping of ours, and
    ACTIVE means exactly "a command is in progress on this connection". A
    connection still ACTIVE after the grace is left to the thread's own
    `finally`, which is the only place that can close it safely, and the leak
    is logged by name so an operator reading about a wedged sweep is told the
    backend is still there.
    """
    raw = getattr(wrapper, "connection", None)
    if raw is None or getattr(raw, "closed", False):
        return
    try:
        raw.cancel()
    except Exception:  # noqa: BLE001 - nothing here may replace the timeout
        logger.exception("could not cancel the abandoned %s query", name)
    thread.join(ABANDON_GRACE_S)
    if getattr(raw, "closed", False):
        return
    if _is_busy(raw):
        logger.warning(
            "leaving the abandoned %s connection open: it is still executing a command, "
            "and closing it under the thread that owns it can take the worker down. "
            "One backend stays held until that thread unwinds or the process ends",
            name,
        )
        return
    try:
        raw.close()
    except Exception:  # noqa: BLE001 - same
        logger.exception("could not close the abandoned %s connection", name)


def _is_busy(raw) -> bool:
    """Whether libpq is in the middle of a command on this connection.

    Unreadable counts as busy. Anything that is not a psycopg connection with a
    live `PGconn` behind it is not something to call PQfinish on from another
    thread on a guess: a leaked backend is recoverable and a segfaulted worker
    is not.
    """
    from psycopg import pq

    try:
        return raw.pgconn.transaction_status == pq.TransactionStatus.ACTIVE
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("could not read the abandoned connection's transaction status")
        return True


def prune_run_rows(now=None) -> int:
    """Drop run rows past their retention, keeping what the alert reads.

    The newest row per task survives whatever its age, and so does the newest
    *successful* row per task, because those two are the whole of what
    `stale_tasks` looks at. Pruning them would turn a task that has not run for
    a year into a task with no history, which reads the same as a task that has
    never been registered - and a retention policy that erases the alert's own
    reference is worse than no retention at all.
    """
    now = now or timezone.now()
    keep = set(
        ScheduledRun.objects.order_by("task", "-started_at")
        .distinct("task")
        .values_list("id", flat=True)
    )
    keep |= set(
        ScheduledRun.objects.filter(succeeded=True)
        .order_by("task", "-started_at")
        .distinct("task")
        .values_list("id", flat=True)
    )
    cutoff = now - timedelta(seconds=RUN_ROW_RETENTION_S)
    deleted, _ = ScheduledRun.objects.filter(started_at__lt=cutoff).exclude(id__in=keep).delete()
    return deleted


def prune_job_rows(now=None) -> int:
    """Drop finished Procrastinate jobs past their retention, events with them.

    Age is the time of a job's last event rather than `scheduled_at`, which is
    null for anything deferred immediately - the same reading Procrastinate's
    own `delete_old_jobs` takes. Events go by the foreign key's ON DELETE
    CASCADE. A job still referenced by a periodic-defer row is left alone: that
    reference is how the scheduler knows it has already fired this tick, and
    deleting it violates the constraint rather than tidying anything.
    """
    from django.db import connection

    now = now or timezone.now()
    cutoff = now - timedelta(seconds=JOB_ROW_RETENTION_S)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM procrastinate_jobs
            WHERE id IN (
                SELECT aged.id FROM (
                    SELECT DISTINCT ON (job.id) job.id, job.status, event.at AS latest_at
                      FROM procrastinate_jobs job
                      JOIN procrastinate_events event ON job.id = event.job_id
                     ORDER BY job.id, event.at DESC
                ) AS aged
                WHERE aged.status = ANY(%s::procrastinate_job_status[])
                  AND aged.latest_at < %s
            )
            AND id NOT IN (
                SELECT job_id FROM procrastinate_periodic_defers WHERE job_id IS NOT NULL
            )
            """,
            [list(TERMINAL_JOB_STATUSES), cutoff],
        )
        return cursor.rowcount


# Statuses a job holds while Procrastinate still has work to do with it. The
# queueing lock is not this set: Procrastinate's partial unique index is
# `WHERE status = 'todo'` (procrastinate/sql/schema.sql), so it deduplicates
# *queued* jobs and has no opinion at all about one that is running. Everything
# that wants "is this task in flight" has to ask for both.
IN_FLIGHT_JOB_STATUSES = ("todo", "doing")


def jobs_in_flight(
    task_name: str,
    statuses: tuple[str, ...] = IN_FLIGHT_JOB_STATUSES,
    exclude_id: int | None = None,
) -> list:
    """Jobs of one task that Procrastinate has not finished with, oldest first.

    The one reader of this that matters is the pre-flight in `run_rebuild_now`.
    The command relied on the queueing lock alone and documented it as covering
    "queued or running", which is half true and dangerous in the half that is
    not: with a rebuild `doing`, the index is empty, the second deferral
    succeeds, and when the running job hits a transient failure
    `procrastinate_retry_job` sets it back to `todo` - straight onto the row the
    second deferral put there. The retry becomes a unique violation inside the
    job-finishing path, so a rebuild that should have been retried is a worker
    error instead.

    `exclude_id` is for a caller that is itself one of the jobs being counted.
    """
    from procrastinate.contrib.django.models import ProcrastinateJob

    jobs = ProcrastinateJob.objects.filter(task_name=task_name, status__in=list(statuses))
    if exclude_id is not None:
        jobs = jobs.exclude(id=exclude_id)
    return list(jobs.order_by("id"))


# How long a job may sit in `doing` before it is wedged rather than slow, per
# task, in one place. Every number here is the budget the task enforces on
# itself, so a job that has outlived it is a job whose enforcement did not
# happen - a worker killed mid-run, an abandoned thread, a container OOMed -
# rather than a long one.
#
# The two five-minute tasks enforce no budget of their own; they get the
# maintenance queue's bound, which is what every other task on that queue is
# held to and is 360 times their cadence. Anything not named gets it too.
DEFAULT_JOB_BUDGET_S = 30 * 60


def job_budgets() -> dict[str, float]:
    """The budget table, read from the constants the tasks themselves use.

    Imported lazily and not at module scope: `config.procrastinate` is imported
    at Django app-ready time and imports this module back, inside its task
    bodies.
    """
    from config.procrastinate import BACKUP_TIMEOUT_S, REBUILD_TIMEOUT_S, SWEEP_TIMEOUT_S

    return {
        "weekly_rebuild": REBUILD_TIMEOUT_S,
        "nightly_backup": BACKUP_TIMEOUT_S,
        "membership_sweep": SWEEP_TIMEOUT_S,
        "degraded_guild_sweep": DEFAULT_JOB_BUDGET_S,
        "worker_heartbeat": DEFAULT_JOB_BUDGET_S,
    }


# What an operator does about a wedged job, named here rather than in each
# surface's own string: the page, the command and the runbook must all send the
# operator to the same place, and the whole point of the row is that there is
# something to do about it.
WEDGED_JOB_REMEDY = (
    "if its worker is gone, `manage.py unwedge_job <id>` puts the job back on the queue"
)


def wedged_jobs(now=None) -> list[dict]:
    """Jobs still `doing` long past the budget of the task they are running.

    The gap this closes is the one a killed rebuild fell into. Both surfaces
    read `status="failed"`, and a worker that dies mid-job never writes that
    status: the row stays `doing` forever, because the process that would have
    finished it is gone. So a rebuild killed at hour three was on no alert at
    all until `weekly_rebuild` went stale - eight days later - and in the
    meantime the operations page said nothing was wrong while the job holding
    the rebuild queue's only slot was never going to move.

    Age is measured from the job's last event, which for a `doing` job is the
    `started` event Procrastinate writes when it picks the job up. There is no
    `started_at` column to read; `scheduled_at` is the fallback and is null for
    anything deferred immediately, and a job with neither is left alone rather
    than reported on a timestamp that was guessed.
    """
    from django.db.models import Max
    from procrastinate.contrib.django.models import ProcrastinateJob

    now = now or timezone.now()
    budgets = job_budgets()
    wedged = []
    running = (
        ProcrastinateJob.objects.filter(status="doing")
        .annotate(last_event_at=Max("procrastinateevent__at"))
        .order_by("id")
    )
    for job in running:
        started = job.last_event_at or job.scheduled_at
        if started is None:
            continue
        budget = budgets.get(job.task_name, DEFAULT_JOB_BUDGET_S)
        age = (now - started).total_seconds()
        if age >= budget:
            wedged.append(
                {
                    "id": job.id,
                    "task": job.task_name,
                    "queue": job.queue_name,
                    "budget_s": budget,
                    "age_s": age,
                    "started_at": started,
                    # Carried on the row rather than composed by each surface,
                    # so the page and the command cannot end up naming
                    # different remedies - and so that a report of a wedged job
                    # is never just a statement that something is broken.
                    "remedy": WEDGED_JOB_REMEDY,
                }
            )
    return wedged


def failed_job_count() -> int:
    """How many jobs are in a failed state, not how many are being shown.

    `failed_jobs` truncates, and a surface that reports the length of a
    truncated list reports its own limit: with 25 shown of 400 failed jobs the
    alert said "25 failed job(s)" every time, which reads as a number that has
    stopped moving.
    """
    from procrastinate.contrib.django.models import ProcrastinateJob

    return ProcrastinateJob.objects.filter(status="failed").count()


def failed_jobs(limit: int = 50):
    """Recent Procrastinate jobs in a failed state, newest first.

    The plan's "failed jobs appear on an admin page and alert after the final
    retry": a job that has exhausted its retries is left `failed` by the worker,
    and until something displays that, the only record of a job that died five
    times is a log line nobody is reading.

    Annotated with the time of its last event, because a job row carries no
    timestamp of its own other than `scheduled_at`, which is null for anything
    deferred immediately - so "when did this fail" is otherwise unanswerable
    from the row an operator is looking at.
    """
    from django.db.models import Max
    from procrastinate.contrib.django.models import ProcrastinateJob

    return list(
        ProcrastinateJob.objects.filter(status="failed")
        .annotate(last_event_at=Max("procrastinateevent__at"))
        .order_by("-id")[:limit]
    )


def disk_headroom(disk_usage=None) -> dict | None:
    """The tiles volume, when it is close enough to the rebuild's own gate to say so.

    The fourth thing the alerts watch, and the one that used to be reported by
    nothing until it was already a refusal. `pipeline.tiles.check_disk_gate` is
    a hard gate: a rebuild that cannot fit a second full tile set beside the
    served one, without taking the volume past `DISK_GATE_FRACTION`, does not
    start at all - and the only remedy it offers is "grow the volume, which is
    an online resize". An operator who learns that from a failed Tuesday
    rebuild learns it a week late, on a volume that also carries `PGDATA` and
    the nightly dumps.

    So this measures the same two things the gate does, minus the part that
    cannot be known cheaply. The gate reserves `max(current tile set + four
    times the source extract, REBUILD_MIN_FREE_BYTES)`; walking the tile tree
    on every alert tick is not something to do from a health probe, so what is
    checked here is the floor alone:

    - free space below `REBUILD_MIN_FREE_BYTES`, and
    - the volume already past `DISK_GATE_FRACTION` full once that floor is
      added to what is used.

    Both are weaker than the gate by construction - the gate's reservation is
    never smaller than the floor - so this is the alert that fires *before* the
    refusal rather than with it. Returning None means there is nothing to say.

    The path is `settings.TILES_DIR`, and it is measured at its nearest
    existing ancestor: `check_disk_gate` creates the directory before it calls
    `disk_usage`, so the filesystem it measures is the one the ancestor is on,
    and a probe that raised `FileNotFoundError` on a host whose first rebuild
    has not run would be an alert that fails on a new deployment. The path
    actually measured is reported, because `check_operations` is documented as
    a cron entry in `api` - a container that mounts no part of the data volume
    - and a free-space line that does not say which filesystem it read is a
    line that can be quietly about the wrong one.
    """
    import shutil

    from django.conf import settings

    disk_usage = disk_usage or shutil.disk_usage
    measured = _nearest_existing(settings.TILES_DIR)
    usage = disk_usage(str(measured))
    minimum_free = settings.REBUILD_MIN_FREE_BYTES
    fraction = settings.DISK_GATE_FRACTION
    fraction_after = (usage.used + minimum_free) / usage.total if usage.total else 1.0
    if usage.free >= minimum_free and fraction_after <= fraction:
        return None
    return {
        "path": str(measured),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "minimum_free_bytes": minimum_free,
        "fraction": fraction,
        "fraction_after": fraction_after,
        # Percentages as well as ratios, because the template renders these and
        # Django's `floatformat` cannot turn 0.8 into 80 without arithmetic in
        # the page. One conversion, in the one place that knows what the
        # numbers mean.
        "fraction_pct": fraction * 100,
        "fraction_after_pct": fraction_after * 100,
    }


def _nearest_existing(path):
    """`path` if it exists, else the closest parent that does.

    Never raises and never returns something outside the path's own chain: the
    root always exists, so the walk terminates.
    """
    from pathlib import Path

    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate

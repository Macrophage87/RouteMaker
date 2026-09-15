"""Recording that a scheduled task ran.

Every periodic task writes a row here, success or failure, because the failures
that matter most produce nothing to read. A rebuild that stopped being scheduled
and a backup that stopped being taken both emit no error at all, so an alert
built on the absence of an error stays silent through precisely the two outages
it exists for. What is watched is the absence of a recent success.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from django.utils import timezone

from .models import ScheduledRun

logger = logging.getLogger(__name__)

# How long each task may go without a success before it is considered broken.
# The rebuild's window is eight days rather than seven, so one missed run is not
# an alert; two are. The backup's is 26 hours for the same reason at a day's
# cadence.
STALE_AFTER = {
    "weekly_rebuild": 8 * 24 * 60 * 60,
    "nightly_backup": 26 * 60 * 60,
    "membership_sweep": 12 * 60 * 60,
}


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


def stale_tasks(now=None) -> list[str]:
    """Tasks with no success inside their window. What the alert reads."""
    now = now or timezone.now()
    stale = []
    for task, window in STALE_AFTER.items():
        run = last_success(task)
        if run is None or (now - run.started_at).total_seconds() >= window:
            stale.append(task)
    return stale

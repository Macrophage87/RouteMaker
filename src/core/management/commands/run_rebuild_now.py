"""`manage.py run_rebuild_now` - queue the weekly rebuild once, by hand.

docs/OPERATIONS.md has referred to "a hand-fired rebuild" since wave 3 - in the
build-id collision note, in the freshness rule's list of reasons a rebuild
re-runs inside the same week, and in the RECONCILE failure's "worth a hand-run"
- and there was no way to fire one. The rebuild is a Procrastinate periodic
task on its own queue, so the only route to it was `python -c` with Django set
up by hand, inside the right container, remembering that the task takes a
`timestamp` argument. On a fresh host that is also the *first* rebuild, which
is not an edge case at all: nothing else creates the tiles the routers serve.

This defers the job and returns. It does not run the rebuild: the job is picked
up by the `rebuild` service, which is the container with the Valhalla binaries,
the data mounts and the six-hour budget, and it is picked up within seconds if
that service is up. Watch it with `docker compose logs -f rebuild`.

Single-flight is two checks, because one of them covers less than it was once
said to. `weekly_rebuild` carries `queueing_lock="weekly_rebuild"`, and that
lock is a partial unique index whose predicate is `WHERE status = 'todo'`
(procrastinate/sql/schema.sql): it deduplicates jobs that are *queued* and has
no opinion whatever about one that is *running*. This file, its `--help` and
docs/OPERATIONS.md all claimed it covered "queued or running", and the gap is
not cosmetic. Deferring a second rebuild while the first is `doing` succeeded,
and then the first hit a transient failure: `procrastinate_retry_job` puts a
retried job back to `todo`, straight into the index next to the row this
command had just inserted, and the retry died of a unique violation inside the
job-finishing path. A rebuild that should have been retried became a worker
error, and the operator had two rebuilds queued behind it.

So the pre-flight below reads the job table for a `weekly_rebuild` in either
state and refuses by job id and status, and the `AlreadyEnqueued` handler stays
for the race the pre-flight cannot close - two operators, or an operator and
the Tuesday tick, between the read and the insert. That one the index does
settle, correctly.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from procrastinate.exceptions import AlreadyEnqueued

from config.procrastinate import WEEKLY_REBUILD_CRON

RESTART_HINT = (
    "When it finishes, restart the routers so they load the promoted build - "
    "`valhalla_service` reads its tiles once at start and does not reload them: "
    "docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike"
)

IN_FLIGHT_REFUSAL = (
    "Watch the one in flight with `docker compose logs -f rebuild`, or look at the "
    "operations page. Two rebuilds at once would write the same staging schema and "
    "the same tile directory."
)


class Command(BaseCommand):
    help = (
        "Queue one weekly_rebuild job now, on the rebuild queue, in addition to "
        f"the schedule ({WEEKLY_REBUILD_CRON}). Refuses while one is queued or running: "
        "the task's queueing lock covers a queued job, and this command's own pre-flight "
        "covers a running one."
    )

    def handle(self, *args, **options) -> None:
        # Imported here rather than at module scope: importing the app module
        # registers the tasks, and a management command that did that at import
        # time would do it during `manage.py help` as well.
        from config.procrastinate import app
        from core.audit import record
        from core.models import AuditLogEntry
        from core.runs import jobs_in_flight

        rebuild = app.tasks["weekly_rebuild"]

        # Before the defer, and naming what it found. The queueing lock cannot
        # do this half: its index is `WHERE status = 'todo'`, so a rebuild that
        # is `doing` is invisible to it, and the job this command would queue
        # collides with that one the moment it is retried.
        in_flight = jobs_in_flight("weekly_rebuild")
        if in_flight:
            job = in_flight[0]
            raise CommandError(
                f"a rebuild is already in flight - job {job.id} is {job.status} on the "
                f"{job.queue_name} queue - so this one was not queued. {IN_FLIGHT_REFUSAL}"
            )

        try:
            # The periodic task's own signature. Procrastinate passes the tick's
            # unix time to a scheduled run; a hand-fired one passes now, so the
            # argument means the same thing in both cases and the job row reads
            # as what it is rather than as `timestamp=0`.
            job_id = rebuild.defer(timestamp=int(time.time()))
        except AlreadyEnqueued as already:
            # The race the pre-flight above cannot close: another operator, or
            # the Tuesday tick, deferring between the read and the insert. The
            # index settles that one correctly, and it is reported rather than
            # swallowed - an operator who fires a second rebuild because the
            # first seems slow must not be told it worked.
            raise CommandError(
                f"a rebuild was queued while this one was being deferred, so it was not "
                f"queued: {already}. {IN_FLIGHT_REFUSAL}"
            ) from already

        # The audit log's account of who started a rebuild. There is no request
        # and no session behind this - it is a shell in a container - so the
        # actor is None, which is the honest value and is what the log's own
        # "worker or host operator" row means. Nothing under src/pipeline or in
        # these commands wrote an audit row before, so the one action that
        # starts six hours of work over the served graph left no record at all.
        record(
            None,
            "run_rebuild_now",
            "procrastinatejob",
            job_id,
            AuditLogEntry.Outcome.ALLOWED,
            detail=f"hand-fired weekly_rebuild queued as job {job_id} on the {rebuild.queue} queue",
        )

        self.stdout.write(
            f"queued weekly_rebuild as job {job_id} on the {rebuild.queue} queue. "
            "The rebuild service runs it; this command does not."
        )
        self.stdout.write(RESTART_HINT)

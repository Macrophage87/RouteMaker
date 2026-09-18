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

Single-flight is not re-implemented here. `weekly_rebuild` carries
`queueing_lock="weekly_rebuild"`, which is a partial unique index in the
database over jobs that are not finished, so a second deferral while one is
queued or running is refused by PostgreSQL and arrives here as
`AlreadyEnqueued`. That is reported as a refusal with a non-zero exit rather
than swallowed: an operator who fires a second rebuild because the first seems
slow must not be told it worked, and two concurrent rebuilds would write the
same staging schema and the same tile directory.
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


class Command(BaseCommand):
    help = (
        "Queue one weekly_rebuild job now, on the rebuild queue, in addition to "
        f"the schedule ({WEEKLY_REBUILD_CRON}). Refuses while one is already queued."
    )

    def handle(self, *args, **options) -> None:
        # Imported here rather than at module scope: importing the app module
        # registers the tasks, and a management command that did that at import
        # time would do it during `manage.py help` as well.
        from config.procrastinate import app

        rebuild = app.tasks["weekly_rebuild"]
        try:
            # The periodic task's own signature. Procrastinate passes the tick's
            # unix time to a scheduled run; a hand-fired one passes now, so the
            # argument means the same thing in both cases and the job row reads
            # as what it is rather than as `timestamp=0`.
            job_id = rebuild.defer(timestamp=int(time.time()))
        except AlreadyEnqueued as already:
            raise CommandError(
                "a rebuild is already queued or running, so this one was not queued: "
                f"{already}. Watch the one in flight with `docker compose logs -f rebuild`, "
                "or look at the operations page. Two rebuilds at once would write the same "
                "staging schema and the same tile directory."
            ) from already

        self.stdout.write(
            f"queued weekly_rebuild as job {job_id} on the {rebuild.queue} queue. "
            "The rebuild service runs it; this command does not."
        )
        self.stdout.write(RESTART_HINT)

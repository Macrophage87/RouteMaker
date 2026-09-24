"""`manage.py unwedge_job <id>` - put back a job whose worker died holding it.

The hole this fills is the one a `docker compose up -d` opens. The rebuild
service has no `stop_grace_period` long enough for a six-hour build, so a
`down`, an `up -d` that recreates the container, a host reboot or an OOM kill
takes the worker out with SIGKILL in the middle of a run. Procrastinate marks a
job `doing` when it is picked up and writes its terminal status from the worker
process; kill that process and nothing ever writes one. The row stays `doing`
for ever.

Nothing in Procrastinate 3.9.0 repairs that by itself. `prune_stalled_workers`
deletes stalled *worker* rows - it is what the next worker runs at startup, and
`procrastinate_jobs.worker_id` is `ON DELETE SET NULL`, so the job is
disowned rather than requeued. `get_stalled_jobs` reports such jobs and has no
caller anywhere in the library. Meanwhile both of this project's single-flight
checks read exactly that row: `run_rebuild_now` refuses "a rebuild is already
in flight", and `weekly_rebuild` refuses to start every Tuesday. A deployment
whose rebuild was killed once therefore never rebuilds again, and the only
documented way out was `procrastinate shell` and `retry <id>`, which is written
down nowhere an operator would find at three in the morning.

So: one command, one job id. It refuses unless the job is `doing` and its worker
is provably gone, and otherwise does what a retry does - `procrastinate_retry_job`,
the same function the retry strategy calls, which puts the row back to `todo` for
the next worker to pick up.

"Provably gone" is the workers table, which is the only evidence there is.
A running worker updates `procrastinate_workers.last_heartbeat` every
`update_heartbeat_interval` seconds (10 by default) from its own asyncio task,
and a sync task body runs in a thread, so a worker six hours into a rebuild is
still beating. A job whose worker row is missing - because another worker
pruned it, or because it was never registered - has no worker. A job whose
worker last beat longer ago than `STALLED_WORKER_TIMEOUT_S` is the definition
Procrastinate's own `prune_stalled_workers` uses. Anything else is a live
worker and this command refuses: requeueing a job that is genuinely running is
how two rebuilds end up writing the same staging schema.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Procrastinate's own number. The default lives on the keyword argument
# `procrastinate.worker.Worker.__init__(stalled_worker_timeout=...)` - there is
# no module constant to import - and it is 30 seconds against an
# `update_heartbeat_interval` of 10, so a worker three missed beats behind is
# what the library itself deletes as stalled. Taking a different number here
# would mean this command and the worker disagreed about which workers exist,
# and the suite reads the signature and asserts this equals it rather than
# asserting the literal against itself.
STALLED_WORKER_TIMEOUT_S = 30.0

# What the operator does next, which is not the same sentence for every job.
# It used to be: every unwedged job, on every queue, was told to watch the
# rebuild service and to queue a fresh run with `manage.py run_rebuild_now` -
# advice that on a `nightly_backup` names a service that does not run it and a
# command that does not queue it. The requeued row is picked up by whichever
# worker serves its queue, and only the rebuild has a hand-fire command at all.
REBUILD_NEXT_STEPS = (
    "The rebuild service picks a `todo` weekly_rebuild up within seconds while it is "
    "running (`docker compose logs -f rebuild`). If it is not running, start it, or "
    "queue a fresh one with `manage.py run_rebuild_now` once this row has cleared."
)
MAINTENANCE_NEXT_STEPS = (
    "The worker service picks a `todo` job off the {queue} queue within seconds while it "
    "is running (`docker compose logs -f worker`). If it is not running, start it. There "
    "is nothing to queue by hand: {task} is periodic, so if this row is not worth running "
    "again you can leave it and the next tick will write its own job."
)
# And for a job the retry did not put back. `procrastinate_retry_job_v2`
# finishes a `doing` job with an abort requested on it instead of requeueing it,
# so the row is terminal: no worker will pick it up, and telling the operator to
# watch for one sends them to wait on nothing. What is left to do is start a new
# run, if one is still wanted, and with this row finished nothing is in flight
# to refuse it.
FINISHED_PREAMBLE = (
    "An abort had been requested on it, so Procrastinate finished it as {landed} "
    "instead of requeueing it, and no worker will pick it up."
)
REBUILD_FINISHED_NEXT_STEPS = (
    " If a rebuild is still wanted, queue a fresh one with `manage.py run_rebuild_now`; "
    "nothing is in flight to refuse it now."
)
MAINTENANCE_FINISHED_NEXT_STEPS = (
    " There is nothing to queue by hand: {task} is periodic, and the next tick writes its own job."
)


def next_steps(task_name: str, queue_name: str, landed: str = "todo") -> str:
    """The sentence that fits the job that was just put back, or was not.

    Keyed on the task rather than on the queue because what differs is the
    hand-fire command, and `run_rebuild_now` is the only one there is; and on
    where the row landed, because a job that is `todo` again is waited for and
    one that was finished instead is replaced.
    """
    if landed != "todo":
        tail = (
            REBUILD_FINISHED_NEXT_STEPS
            if task_name == "weekly_rebuild"
            else MAINTENANCE_FINISHED_NEXT_STEPS.format(task=task_name)
        )
        return FINISHED_PREAMBLE.format(landed=landed) + tail
    if task_name == "weekly_rebuild":
        return REBUILD_NEXT_STEPS
    return MAINTENANCE_NEXT_STEPS.format(task=task_name, queue=queue_name)


class Command(BaseCommand):
    help = (
        "Put a job whose worker died back on its queue. Refuses unless the job is "
        "`doing` and its worker's heartbeat has stopped."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "job_id",
            type=int,
            help=(
                "The Procrastinate job id, as the operations page and "
                "`manage.py check_operations` print it on the wedged-job line."
            ),
        )

    def handle(self, *args, **options) -> None:
        # Imported in the handler rather than at module scope: these reach the
        # ORM and the app's task registry, and a management command that did
        # that at import time would do it during `manage.py help` too.
        from procrastinate.contrib.django.models import ProcrastinateJob

        from config.procrastinate import app
        from core.audit import record
        from core.models import AuditLogEntry

        job_id = options["job_id"]
        try:
            job = ProcrastinateJob.objects.get(id=job_id)
        except ProcrastinateJob.DoesNotExist as missing:
            raise CommandError(
                f"there is no job {job_id}. The operations page and `check_operations` "
                "print the id of every wedged job."
            ) from missing

        if job.status != "doing":
            raise CommandError(
                f"job {job_id} is {job.status}, not doing, so there is nothing wedged to "
                "put back. A `todo` job is already queued; a terminal one is finished, and "
                "a fresh run is `manage.py run_rebuild_now` rather than this."
            )

        alive = self._live_worker(job)
        if alive is not None:
            raise CommandError(
                f"job {job_id} is still being run by worker {alive.id}, which last reported "
                f"{alive.last_heartbeat}, inside the {STALLED_WORKER_TIMEOUT_S:.0f}s Procrastinate "
                "itself treats as alive. Requeueing it would put a second copy of a running "
                "job on the queue. Watch it instead, or stop the worker first."
            )

        # The other collision, and it is the one `run_rebuild_now` was written
        # about: Procrastinate's queueing-lock index is partial on
        # `WHERE status = 'todo'`, so moving this row back to `todo` while
        # another job holds the same lock there is a unique violation inside
        # the retry function rather than anything this command could report.
        if job.queueing_lock:
            queued = ProcrastinateJob.objects.filter(
                queueing_lock=job.queueing_lock, status="todo"
            ).exclude(id=job_id)
            other = queued.order_by("id").first()
            if other is not None:
                raise CommandError(
                    f"job {other.id} is already queued under the same queueing lock "
                    f"({job.queueing_lock}), and Procrastinate allows only one `todo` job per "
                    f"lock, so job {job_id} cannot go back on the queue while it is there. "
                    "That queued job is the next run; this row is the dead one. Let the "
                    "queued job run, or cancel it first."
                )

        app.job_manager.retry_job_by_id(job_id=job_id, retry_at=timezone.now())
        # Read back rather than assumed. `procrastinate_retry_job_v2` finishes a
        # `doing` job as `failed` instead of requeueing it when an abort has been
        # requested on it, which is the right answer - somebody asked for this
        # job to stop - and the wrong thing to print "queued again" about.
        landed = ProcrastinateJob.objects.get(id=job_id).status

        # The same shape of row `run_rebuild_now` and `rollback_rebuild` write,
        # and for the same reason: this is an operator reaching into the job
        # table from a shell in a container, so there is no request, no session
        # and honestly no actor - a null actor is what this log means by the
        # worker or the host operator.
        record(
            None,
            "unwedge_job",
            "procrastinatejob",
            job_id,
            AuditLogEntry.Outcome.ALLOWED,
            detail=(
                f"job {job_id} ({job.task_name} on the {job.queue_name} queue) was doing with "
                f"no live worker and is now {landed}"
            ),
        )

        what = "is queued again" if landed == "todo" else f"is now {landed}"
        self.stdout.write(f"job {job_id} ({job.task_name} on the {job.queue_name} queue) {what}.")
        self.stdout.write(next_steps(job.task_name, job.queue_name, landed))

    def _live_worker(self, job):
        """The job's worker if it is still beating, else None.

        None covers three cases that are the same thing to an operator: the job
        never had a worker id, the worker row has been deleted (which is what
        `prune_stalled_workers` does at the next worker's startup, leaving this
        job's `worker_id` NULL through the foreign key's ON DELETE SET NULL),
        and the worker row is still there but has stopped reporting.
        """
        worker = job.worker
        if worker is None:
            return None
        if worker.last_heartbeat is None:
            return None
        silent_for = (timezone.now() - worker.last_heartbeat).total_seconds()
        return None if silent_for > STALLED_WORKER_TIMEOUT_S else worker

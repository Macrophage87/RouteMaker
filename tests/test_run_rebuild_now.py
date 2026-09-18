"""`manage.py run_rebuild_now` - the hand-fired rebuild the runbook referred to.

docs/OPERATIONS.md named a hand-fired rebuild in three places before there was
any way to fire one, and the first rebuild on a fresh host is that same command:
nothing else creates the tiles the routers serve, and the weekly cron is up to
seven days away.

The job, not the rebuild. This command defers and returns; the `rebuild`
service is what runs the work, because that is the container with the Valhalla
binaries, the data mounts and the six-hour budget. So what is asserted here is
the row it writes - the queue, the task, the lock, the status - rather than
anything about a build, which tests/test_worker_schedule.py already runs against
the real handler set.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from procrastinate.contrib.django import app


@pytest.fixture(autouse=True)
def no_jobs_left_over(django_db_setup, django_db_blocker):
    """Empty the job table around each test in this file.

    Procrastinate's Django models are unmanaged, and `flush` - which is what
    pytest-django runs between `transaction=True` tests - only truncates the
    tables Django manages. So a deferred job survives into the next test, and
    the first thing every test here does is defer the one job the queueing lock
    allows: without this, test two fails on test one's row and the failure looks
    exactly like the behaviour test two is asserting.
    """
    from django.db import connection

    def empty() -> None:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE procrastinate_jobs RESTART IDENTITY CASCADE")

    with django_db_blocker.unblock():
        empty()
    yield
    with django_db_blocker.unblock():
        empty()


def queued_rebuilds():
    from procrastinate.contrib.django.models import ProcrastinateJob

    return ProcrastinateJob.objects.filter(task_name="weekly_rebuild")


@pytest.mark.django_db(transaction=True)
def test_the_command_queues_one_job_on_the_rebuild_queue() -> None:
    """On the rebuild queue specifically. The maintenance worker runs in the api
    image, which carries neither the Valhalla binaries nor any data mount, so a
    rebuild queued there would be picked up by a container that cannot run it -
    and would fail at the first binary rather than at anything informative."""
    call_command("run_rebuild_now")

    jobs = list(queued_rebuilds())
    assert len(jobs) == 1, f"expected exactly one queued rebuild, got {jobs}"
    job = jobs[0]
    assert job.queue_name == "rebuild"
    assert job.status == "todo"
    assert job.queueing_lock == "weekly_rebuild"
    assert set(job.args) == {"timestamp"}, (
        f"the periodic task takes a timestamp and the job carries {job.args}; a job "
        "deferred with the wrong arguments fails on the worker, not here"
    )
    assert job.args["timestamp"] > 0, (
        "a hand-fired run passes the time it was fired, so the row reads as what it is"
    )


def set_status(job_id: int, status: str) -> None:
    """Move a job to a status by hand, as the worker's own SQL would.

    The Django models Procrastinate exposes are read-only on purpose - the
    worker owns those rows - so a test that wants a job in `doing` writes the
    status the same way the worker does.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = %s::procrastinate_job_status WHERE id = %s",
            [status, job_id],
        )


@pytest.mark.django_db(transaction=True)
def test_a_second_call_while_one_is_queued_is_refused() -> None:
    """Two concurrent rebuilds would write the same staging schema and the same
    dated tile directory.

    Reported rather than swallowed, and with a non-zero exit: an operator who
    fires a second rebuild because the first seems slow must not be told it
    worked.
    """
    call_command("run_rebuild_now")

    with pytest.raises(CommandError) as refused:
        call_command("run_rebuild_now")

    assert "already in flight" in str(refused.value)
    assert "todo" in str(refused.value), "the refusal names the status it found"
    assert queued_rebuilds().count() == 1, "the refused call queued a second job anyway"


@pytest.mark.django_db(transaction=True)
def test_a_call_while_one_is_running_is_refused_too() -> None:
    """The case the queueing lock does not cover, and the one an operator is
    most likely to be in when they reach for this command.

    Procrastinate's queueing-lock index is partial on `WHERE status = 'todo'`
    (procrastinate/sql/schema.sql), so a rebuild that is `doing` is not in it
    and a second deferral is accepted. This command's docstring, its `--help`
    and docs/OPERATIONS.md all said the lock covered "queued or running"; it
    does not, and what it costs is in the retry test below.
    """
    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(job_id, "doing")

    with pytest.raises(CommandError) as refused:
        call_command("run_rebuild_now")

    message = str(refused.value)
    assert f"job {job_id}" in message, f"the refusal names the job in flight: {message}"
    assert "doing" in message, f"and the status it is in: {message}"
    assert queued_rebuilds().count() == 1, "the refused call queued a second job anyway"


@pytest.mark.django_db(transaction=True)
def test_the_running_rebuild_can_still_be_retried_afterwards() -> None:
    """What the missing pre-flight actually broke, which is not the second job.

    `procrastinate_retry_job` sets a retried job back to `todo`. With a second
    rebuild sitting in `todo` under the same queueing lock - which is exactly
    what this command used to queue while the first was running - that UPDATE
    collides on the partial unique index, so a transient `RebuildFailed` in the
    running rebuild becomes a unique violation inside the job-finishing path
    rather than the retry the strategy asked for.

    Asserted as the retry succeeding with one job in the table, after the
    refusal has kept it at one.
    """
    from django.db import connection

    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(job_id, "doing")
    with pytest.raises(CommandError):
        call_command("run_rebuild_now")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT procrastinate_retry_job_v2(%s, %s, NULL, NULL, NULL)",
            [job_id, timezone.now()],
        )

    job = queued_rebuilds().get()
    assert job.id == job_id, "the retried job is the one that was running"
    assert job.status == "todo", "and it is queued again rather than lost"
    assert job.attempts == 1


@pytest.mark.django_db(transaction=True)
def test_the_lock_still_settles_the_race_the_pre_flight_cannot() -> None:
    """The pre-flight reads and then inserts, so two callers can both read an
    empty table. That gap is the queueing lock's, and it is still handled:
    `AlreadyEnqueued` is reported as a refusal with a non-zero exit rather than
    swallowed or allowed to surface as a traceback."""
    from procrastinate.exceptions import AlreadyEnqueued

    from core.management.commands import run_rebuild_now as command_module

    def deferred_by_somebody_else(**kwargs):
        raise AlreadyEnqueued("a job with the same queueing lock is already queued")

    task = app.tasks["weekly_rebuild"]
    original = task.defer
    task.defer = deferred_by_somebody_else
    try:
        with pytest.raises(CommandError) as refused:
            call_command("run_rebuild_now")
    finally:
        task.defer = original

    assert "queued while this one was being deferred" in str(refused.value)
    assert command_module.IN_FLIGHT_REFUSAL in str(refused.value)
    assert queued_rebuilds().count() == 0


@pytest.mark.django_db(transaction=True)
def test_queueing_one_is_audited() -> None:
    """Six hours of work over the served graph, started from a shell. Nothing
    under src/pipeline or in these commands wrote an audit row before this, so
    the one action that starts a rebuild by hand left no record of having
    happened - and the actor is None because there honestly is none: no request,
    no session, a container the host operator is exec'd into."""
    from core.models import AuditLogEntry

    call_command("run_rebuild_now")

    entry = AuditLogEntry.objects.get(action="run_rebuild_now")
    assert entry.actor is None and entry.actor_user_id is None
    assert entry.model == "procrastinatejob"
    assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
    assert entry.object_id == str(queued_rebuilds().get().id)
    assert "weekly_rebuild" in entry.detail


@pytest.mark.django_db(transaction=True)
def test_a_refused_call_writes_no_audit_row() -> None:
    """The log records what happened, and nothing happened."""
    from core.models import AuditLogEntry

    call_command("run_rebuild_now")
    with pytest.raises(CommandError):
        call_command("run_rebuild_now")

    assert AuditLogEntry.objects.filter(action="run_rebuild_now").count() == 1


# --- `rollback_rebuild`, the other command an operator runs from a shell -------------
#
# It lives here rather than beside the rollback's own end-to-end test because
# what is asserted is the audit row, which is this file's subject: the two
# commands that change the served deployment from a container, and the record
# they leave. The rollback itself is stubbed - tests/test_pipeline_end_to_end.py
# runs the real one against two real builds - so that this stays a test of what
# is written to the log and on which path.


@pytest.mark.django_db(transaction=True)
def test_a_confirmed_rollback_is_audited_and_a_dry_run_is_not(monkeypatch) -> None:
    """`rollback_rebuild --confirm` repoints every ValhallaUpstream row and
    retires the graph being served, and it wrote no audit row at all: the
    settings rows changed and the log had no account of when, or of the fact
    that a human rather than the weekly job had done it.

    The dry run is the other half. It changes nothing, and a log that records
    reads is one nobody reads.
    """
    from django.conf import settings

    from core.models import AuditLogEntry
    from pipeline.variants import Variant

    target = {variant: f"2026091{index}T080000Z" for index, variant in enumerate(Variant)}
    monkeypatch.setattr(
        "core.management.commands.rollback_rebuild.rollback_target", lambda tiles_dir: target
    )
    rolled_back: list = []
    monkeypatch.setattr("core.management.commands.rollback_rebuild.rollback", rolled_back.append)

    call_command("rollback_rebuild")
    assert rolled_back == [], "the dry run does not roll back"
    assert not AuditLogEntry.objects.filter(action="rollback_rebuild").exists()

    call_command("rollback_rebuild", "--confirm")

    assert len(rolled_back) == 1
    entry = AuditLogEntry.objects.get(action="rollback_rebuild")
    assert entry.actor is None and entry.actor_user_id is None
    assert entry.model == "valhallaupstream"
    assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
    for variant in Variant:
        assert f"{variant.value}={target[variant]}" in entry.detail, entry.detail
    assert settings.SEGMENT_SCHEMA_RETIRED in entry.detail


@pytest.mark.django_db(transaction=True)
def test_the_command_tells_the_operator_to_restart_the_routers() -> None:
    """`valhalla_service` opens its tile extract once at start and never reloads
    it, so a rebuild that is not followed by a restart promotes a build the
    running containers cannot see - a deployment whose routes disagree with its
    own segment table, which reads like a conflation bug. The one command that
    starts a rebuild by hand is the right place to say so."""
    from io import StringIO

    out = StringIO()
    call_command("run_rebuild_now", stdout=out)
    printed = out.getvalue()

    assert "docker compose restart" in printed
    for variant in ("valhalla-standard", "valhalla-no-trail", "valhalla-ebike"):
        assert variant in printed, variant


@pytest.mark.django_db(transaction=True)
def test_the_refusal_names_the_oldest_job_in_flight() -> None:
    """`jobs_in_flight` is ordered oldest first and the refusal takes the first
    row, which is the one an operator should go and look at: the rebuild that
    is actually running, not whatever was queued behind it afterwards.

    Reversed, the message would name a job that has not started - and the
    remedy it offers, `docker compose logs -f rebuild`, would show nothing
    about it. Two rows are needed to tell the two orderings apart, and the only
    way to have two is one `doing` and one `todo`: the queueing lock's index is
    partial on `WHERE status = 'todo'`.
    """
    from core.runs import jobs_in_flight

    running = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(running, "doing")
    queued = app.tasks["weekly_rebuild"].defer(timestamp=1)
    assert queued > running

    assert [job.id for job in jobs_in_flight("weekly_rebuild")] == [running, queued]

    with pytest.raises(CommandError) as refused:
        call_command("run_rebuild_now")

    message = str(refused.value)
    assert f"job {running} is doing" in message, (
        f"the refusal names the rebuild that is running, not the one queued behind it: {message}"
    )

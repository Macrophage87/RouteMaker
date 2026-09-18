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


@pytest.mark.django_db(transaction=True)
def test_a_second_call_while_one_is_queued_is_refused() -> None:
    """Two concurrent rebuilds would write the same staging schema and the same
    dated tile directory. The refusal is the task's `queueing_lock`, which is a
    unique index in the database rather than a check in this command - so it
    holds against a job the weekly schedule deferred, against one another
    operator fired, and against a second worker.

    Reported rather than swallowed, and with a non-zero exit: an operator who
    fires a second rebuild because the first seems slow must not be told it
    worked.
    """
    call_command("run_rebuild_now")

    with pytest.raises(CommandError) as refused:
        call_command("run_rebuild_now")

    assert "already queued" in str(refused.value)
    assert queued_rebuilds().count() == 1, "the refused call queued a second job anyway"


@pytest.mark.django_db(transaction=True)
def test_the_refusal_is_the_lock_and_not_a_count_of_rows() -> None:
    """The guard has to be the same one that protects the weekly schedule.

    A command that counted `todo` jobs itself would have two defects this does
    not: a race between the count and the insert, and no opinion at all about a
    rebuild that is already *running* - which is the case an operator is most
    likely to be in when they reach for this.
    """
    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)

    with pytest.raises(CommandError, match="already queued or running"):
        call_command("run_rebuild_now")

    assert queued_rebuilds().get().id == job_id


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

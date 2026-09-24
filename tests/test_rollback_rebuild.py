"""`manage.py rollback_rebuild` against a rebuild that is still running.

The command had no pre-flight at all, and the one it was missing is the one
`run_rebuild_now` already had. What a rollback does is not confined to the
build it names: `pipeline.promotion.rollback_swap` drops any staging schema
`CASCADE` - its own comment calls it "left behind by a rebuild that did not
swap" - and it repoints every `ValhallaUpstream` row. Run against a rebuild
that is halfway through, it deletes the rows that rebuild is writing into, and
nothing raises at the time: the build fails later as a plain `RebuildFailed`
and is retried five times, each retry writing into a schema this command may
drop again. The narrower interleaving is quieter still - a rollback landing
between `perform_swap`'s repoint and the schema rename leaves the tiles naming
one build and the live schema another, with no error anywhere.

So the refusal is first, before `rollback_target` reads anything, and it
applies to the dry run as well: the dry run's entire output is advice about an
action that must not be taken while this is true.

The rollback itself is stubbed here. tests/test_pipeline_end_to_end.py runs the
real one against two real builds; what is asserted here is which calls reach it.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from config.procrastinate import app


@pytest.fixture(autouse=True)
def no_jobs_left_over(django_db_setup, django_db_blocker):
    """Empty the job table around each test.

    Procrastinate's Django models are unmanaged, so the `flush` pytest-django
    runs between transactional tests does not touch them: a job left `doing` by
    another file is still there for the first test here, where it would be
    indistinguishable from the refusal this file is about.
    """
    from django.db import connection

    def empty() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE procrastinate_periodic_defers, procrastinate_events, "
                "procrastinate_jobs RESTART IDENTITY CASCADE"
            )

    with django_db_blocker.unblock():
        empty()
    yield
    with django_db_blocker.unblock():
        empty()


@pytest.fixture
def stubbed_rollback(monkeypatch, tmp_path):
    """`rollback_target` answering with a build per variant, and `rollback`
    recording that it was called. Returns the list of calls.

    `TILES_DIR` is a real, writable directory with one per variant, because
    the command's write probe is real: these tests are about the in-flight
    refusal, and a tiles directory this process cannot write is the other one.
    """
    from django.conf import settings

    from pipeline.variants import Variant

    for variant in Variant:
        (tmp_path / variant.value).mkdir()
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path)

    target = {variant: f"2026091{index}T080000Z" for index, variant in enumerate(Variant)}
    monkeypatch.setattr(
        "core.management.commands.rollback_rebuild.rollback_target", lambda tiles_dir: target
    )
    calls: list = []
    monkeypatch.setattr("core.management.commands.rollback_rebuild.rollback", calls.append)
    return calls


def set_status(job_id: int, status: str) -> None:
    """Move a job to a status the way the worker does. The Django models
    Procrastinate exposes are read-only on purpose - the worker owns the rows."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = %s::procrastinate_job_status WHERE id = %s",
            [status, job_id],
        )


@pytest.mark.django_db(transaction=True)
def test_a_confirmed_rollback_is_refused_while_a_rebuild_is_running(stubbed_rollback) -> None:
    """The case that executes: the staging schema the running rebuild is
    writing into is dropped `CASCADE` under it."""
    from core.models import AuditLogEntry

    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(job_id, "doing")

    with pytest.raises(CommandError) as refused:
        call_command("rollback_rebuild", "--confirm")

    message = str(refused.value)
    assert f"job {job_id}" in message, f"the refusal names the job it found: {message}"
    assert "doing" in message, f"and the status it is in: {message}"
    assert stubbed_rollback == [], "the rollback ran anyway"
    assert not AuditLogEntry.objects.filter(action="rollback_rebuild").exists()


@pytest.mark.django_db(transaction=True)
def test_a_confirmed_rollback_is_refused_while_a_rebuild_is_queued(stubbed_rollback) -> None:
    """A `todo` rebuild is refused too, and it is not a lesser case: the
    rebuild service picks a queued job up within seconds, so a rollback that
    started against a queued rebuild is a rollback racing a rebuild that is
    about to begin."""
    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)

    with pytest.raises(CommandError) as refused:
        call_command("rollback_rebuild", "--confirm")

    assert f"job {job_id}" in str(refused.value)
    assert "todo" in str(refused.value)
    assert stubbed_rollback == []


@pytest.mark.django_db(transaction=True)
def test_the_dry_run_is_refused_too(stubbed_rollback) -> None:
    """Its whole output is "this is the build you would go back to", which is
    advice about an action that is not safe to take while a rebuild is in
    flight. Printing it and then refusing the confirmed call would be telling
    an operator to do the thing at three in the morning and then arguing."""
    from io import StringIO

    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(job_id, "doing")

    out = StringIO()
    with pytest.raises(CommandError):
        call_command("rollback_rebuild", stdout=out)

    assert "would go back to" not in out.getvalue()
    assert stubbed_rollback == []


@pytest.mark.django_db(transaction=True)
def test_a_finished_rebuild_does_not_refuse_anything(stubbed_rollback) -> None:
    """The refusal is about jobs Procrastinate has not finished with. A
    succeeded rebuild is exactly the situation this command exists for - the
    promotion that went wrong is the one that completed."""
    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(job_id, "succeeded")

    call_command("rollback_rebuild", "--confirm")

    assert len(stubbed_rollback) == 1


@pytest.mark.django_db(transaction=True)
def test_the_dry_run_prints_the_restart_hint(stubbed_rollback) -> None:
    """The restart is half the procedure - `valhalla_service` reads its tiles
    once at start - and the dry run is where an operator reads what the
    procedure is. Printing it only on the confirmed path meant the rehearsal
    left out the step that makes the rollback take effect."""
    from io import StringIO

    from core.management.commands.rollback_rebuild import RESTART_HINT

    out = StringIO()
    call_command("rollback_rebuild", stdout=out)
    printed = out.getvalue()

    assert stubbed_rollback == [], "it is still a dry run"
    assert RESTART_HINT in printed
    for variant in ("valhalla-standard", "valhalla-no-trail", "valhalla-ebike"):
        assert variant in printed, variant


@pytest.mark.django_db(transaction=True)
def test_the_refusal_names_the_oldest_rebuild_in_flight(stubbed_rollback) -> None:
    """Two can be in flight at once - Procrastinate's queueing-lock index is
    partial on `WHERE status = 'todo'`, so a running rebuild and a queued one
    coexist - and the one the operator has to deal with is the running one.

    `jobs_in_flight` returns them oldest first. Named from the other end, the
    refusal points at the job that is merely queued while the one actually
    writing into the staging schema goes unmentioned: the operator is told to
    watch `docker compose logs -f rebuild` for a job that is not running, and
    the running one is what the rollback would have been racing.
    """
    running = app.tasks["weekly_rebuild"].defer(timestamp=0)
    set_status(running, "doing")
    queued = app.tasks["weekly_rebuild"].defer(timestamp=1)
    assert queued > running, "ids are handed out in order, so the older job sorts first"

    with pytest.raises(CommandError) as refused:
        call_command("rollback_rebuild", "--confirm")

    message = str(refused.value)
    assert f"job {running} is doing" in message, (
        f"the refusal does not name the running rebuild, which is the one a rollback "
        f"would be racing: {message}"
    )
    assert f"job {queued}" not in message, message
    assert stubbed_rollback == []

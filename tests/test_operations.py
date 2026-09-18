"""The surfaces that make an alert visible, and the pruning that keeps them cheap.

`core.runs.stale_tasks` existed, was correct, and had no caller: nothing read
it, no page displayed it, and no command exited non-zero on it, so every "task X
has not succeeded in Y" alert in the plan was computed by nobody. The failed-job
admin page the plan names in phase 1 did not exist either, and neither did the
worker heartbeat. This file holds the three of them to the level each takes
effect: the page over HTTP with a real session, the command by calling it, and
the pruning against real rows in a real database.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.db import connection
from django.urls import reverse
from django.utils import timezone

db = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def empty_job_tables(transactional_db):
    """Start each test with no Procrastinate rows.

    They are unmanaged models, so Django's own flush between transactional tests
    does not touch them: a job deferred by another test in the same run is still
    sitting there, failed or not, and a test that asserts "nothing is wrong"
    would read another file's leftovers.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE procrastinate_periodic_defers, procrastinate_events, "
            "procrastinate_jobs RESTART IDENTITY CASCADE"
        )
    yield


def sign_in(client, user):
    """A session the epoch middleware will accept, as the Discord callback makes
    one. Without the row, the middleware logs the request straight back out and
    the admin answers 404 for a reason that has nothing to do with permissions.
    """
    from core.models import Session

    client.force_login(user)
    now = timezone.now()
    Session.objects.create(
        session_key=client.session.session_key,
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )
    return client


def operations_url() -> str:
    return reverse("routemaker_admin:core_scheduledrun_changelist")


def make_job(task_name: str, status: str, event_age: timedelta) -> int:
    """One Procrastinate job row with one event, at whatever age is wanted.

    Written with SQL because the Django models the integration exposes are
    deliberately read-only - the CLI and the worker own those tables - and the
    thing under test reads and deletes them through SQL too.
    """
    at = timezone.now() - event_age
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, priority, args, status, attempts, abort_requested)
            VALUES ('maintenance', %s, 0, '{}'::jsonb, %s::procrastinate_job_status, 5, false)
            RETURNING id
            """,
            [task_name, status],
        )
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'failed', %s)",
            [job_id, at],
        )
    return job_id


# --- The admin page ------------------------------------------------------------------


@db
def test_the_operations_page_answers_404_to_anyone_who_is_not_an_admin(client) -> None:
    """The same 404 the rest of the admin gives an unadmitted request: the path
    does not confirm that an admin is here."""
    from core.models import User

    assert client.get(operations_url()).status_code == 404

    member = User.objects.create(discord_user_id=9001)
    sign_in(client, member)
    assert client.get(operations_url()).status_code == 404


@db
def test_the_operations_page_is_instance_admin_only(client) -> None:
    """Guild-admin staff reach the admin, and must not reach this page: it names
    the deployment's internals rather than any one guild's rows, which is the
    same sensitivity the audit log is gated on."""
    from core.admin_operations import ScheduledRunAdmin

    class Request:
        def __init__(self, user):
            self.user = user

    class GuildAdmin:
        is_instance_admin = False
        is_staff = True
        is_active = True
        is_authenticated = True

    page = ScheduledRunAdmin(*_admin_args())
    assert not page.has_view_permission(Request(GuildAdmin()))
    assert not page.has_module_permission(Request(GuildAdmin()))
    assert not page.has_add_permission(Request(GuildAdmin()))
    assert not page.has_change_permission(Request(GuildAdmin()))
    assert not page.has_delete_permission(Request(GuildAdmin()))


def _admin_args():
    from core.admin import site
    from core.models import ScheduledRun

    return ScheduledRun, site


@db
def test_an_instance_admin_sees_the_stale_tasks_and_the_failed_jobs(client) -> None:
    """The whole point of the page, over HTTP, against a real session."""
    from core.models import ScheduledRun, User

    now = timezone.now()
    # Everything but the backup has succeeded recently, so the page has exactly
    # one stale task to name rather than the whole list.
    for task in ("weekly_rebuild", "membership_sweep", "degraded_guild_sweep", "worker_heartbeat"):
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    job_id = make_job("nightly_backup", "failed", timedelta(hours=1))

    admin = User.objects.create(discord_user_id=9002, is_instance_admin=True)
    sign_in(client, admin)
    response = client.get(operations_url())

    assert response.status_code == 200
    body = response.content.decode()
    assert "nightly_backup" in body, "the stale task is named"
    assert (
        "weekly_rebuild" not in body.split("<h2>Failed jobs</h2>")[0].split("<h2>Windows</h2>")[0]
    ), "a task that has succeeded lately is not on the stale list"
    assert f">{job_id}<" in body, "the failed job is named"


@db
def test_a_guild_admin_who_reaches_the_page_is_refused_by_the_page(client) -> None:
    """`has_module_permission` only hides the index entry, and the admin site's
    `admin_view` wrapper only asks `has_permission`, which is staff - so a guild
    admin, who is staff, reaches this view. The changelist replaces Django's own
    and never calls `super()`, so the permission check inside it is the only
    thing standing between them and the deployment's internals.
    """
    from core.auth_backend import attach_standing
    from core.models import CachedMembership, ConfiguredGuild, RoleMapping, User

    guild = ConfiguredGuild.objects.create(guild_id=5000, name="Test Club")
    guild_admin = User.objects.create(discord_user_id=9004)
    RoleMapping.objects.create(
        guild=guild, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN
    )
    CachedMembership.objects.create(
        discord_user_id=guild_admin.discord_user_id,
        guild=guild,
        role_ids=[7],
        last_confirmed=timezone.now(),
    )
    attach_standing(guild_admin)
    assert guild_admin.is_staff, "a guild admin reaches the admin at all, which is the point"

    sign_in(client, guild_admin)
    assert client.get(operations_url()).status_code == 403


@db
def test_the_page_marks_the_stale_task_and_only_the_stale_task(client) -> None:
    """The row, not the word. `nightly_backup` appears elsewhere on the page -
    in the windows table and in any run row - so a test that searches the body
    for the name is satisfied by a page whose stale list is empty."""
    import re

    from core.models import ScheduledRun, User
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        if task != "nightly_backup":
            ScheduledRun.objects.create(
                task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
            )

    admin = User.objects.create(discord_user_id=9005, is_instance_admin=True)
    sign_in(client, admin)
    body = client.get(operations_url()).content.decode()

    rows = re.findall(r'<tr class="stale-task">.*?</tr>', body, re.DOTALL)
    assert len(rows) == 1, f"one row for one stale task, found {len(rows)}"
    assert "nightly_backup" in rows[0]
    assert "never" in rows[0], "a task that has never succeeded says so"
    assert "no-stale-tasks" not in body
    assert not any("weekly_rebuild" in row for row in rows), (
        "a task that has succeeded inside its window has no row"
    )


@db
def test_the_page_says_so_when_nothing_is_wrong(client) -> None:
    from core.models import ScheduledRun, User
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    admin = User.objects.create(discord_user_id=9003, is_instance_admin=True)
    sign_in(client, admin)

    body = client.get(operations_url()).content.decode()
    assert "no-stale-tasks" in body
    assert "no-failed-jobs" in body


@db
def test_the_page_is_under_the_configured_admin_path() -> None:
    """It is reached through the admin site, so the unadvertised path, the
    disabled login form and the 404 for anyone unadmitted all apply to it
    without a second implementation of any of them."""
    assert operations_url() == f"/{settings.ADMIN_PATH}core/scheduledrun/"


# --- The command -----------------------------------------------------------------------


@db
def test_check_operations_exits_non_zero_when_something_is_stale() -> None:
    """For a cron entry or a health probe, which cannot log into an admin."""
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 1
    assert "stale: weekly_rebuild" in out.getvalue()


@db
def test_check_operations_exits_zero_when_nothing_is() -> None:
    from io import StringIO

    from django.core.management import call_command

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 0
    assert "ok: no stale tasks, no failed jobs" in out.getvalue()


@db
def test_check_operations_reports_a_failed_job_even_when_nothing_is_stale() -> None:
    """The plan's other alert: a job that has exhausted its retries. Without
    this, a job that died five times is a log line nobody is reading."""
    from io import StringIO

    from django.core.management import call_command

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    job_id = make_job("weekly_rebuild", "failed", timedelta(minutes=5))

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 1
    assert f"failed job: {job_id} weekly_rebuild" in out.getvalue()


@db
def test_check_operations_counts_every_failed_job_and_lists_the_newest() -> None:
    """The count is the number that is wrong, not the number being shown.

    With a limit of 25 and 400 failed jobs the summary line printed "25 failed
    job(s)" on every run, which reads as a number that has stopped moving
    rather than one that is off the end of the page - and the flag's own help
    said the rest were "still counted".
    """
    from io import StringIO

    from django.core.management import call_command

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    jobs = [make_job("weekly_rebuild", "failed", timedelta(minutes=minute)) for minute in range(4)]

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", "--failed-job-limit", "2", stdout=out)
    printed = out.getvalue()

    assert exit_code.value.code == 1
    assert "0 stale task(s), 4 failed job(s)" in printed
    assert printed.count("failed job: ") == 2, "the listing is the one that is truncated"
    assert "listing the 2 newest of 4 failed jobs" in printed
    assert f"failed job: {max(jobs)}" in printed, "newest first"


@db
def test_check_operations_ignores_a_job_that_merely_finished() -> None:
    from io import StringIO

    from django.core.management import call_command

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    make_job("weekly_rebuild", "succeeded", timedelta(minutes=5))

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 0


# --- Pruning the history ---------------------------------------------------------------


@db
def test_run_rows_past_their_retention_go_but_the_alerts_reference_stays() -> None:
    """About 105,000 rows a year from the five-minute tasks alone, into a table
    nothing ever pruned. What must survive is what `stale_tasks` reads: the
    newest successful row per task, whatever its age, because a task pruned down
    to nothing reads as a task that was never registered."""
    from core.models import ScheduledRun
    from core.runs import RUN_ROW_RETENTION_S, prune_run_rows, stale_tasks

    now = timezone.now()
    ancient = now - timedelta(seconds=RUN_ROW_RETENTION_S * 2)
    keeper = ScheduledRun.objects.create(
        task="weekly_rebuild", started_at=ancient, finished_at=ancient, succeeded=True
    )
    older_success = ScheduledRun.objects.create(
        task="weekly_rebuild",
        started_at=ancient - timedelta(days=7),
        finished_at=ancient,
        succeeded=True,
    )
    ancient_failure = ScheduledRun.objects.create(
        task="nightly_backup", started_at=ancient, finished_at=ancient, succeeded=False
    )
    recent = ScheduledRun.objects.create(
        task="membership_sweep", started_at=now, finished_at=now, succeeded=True
    )

    assert prune_run_rows(now) == 1

    assert ScheduledRun.objects.filter(id=keeper.id).exists(), "the alert's own reference"
    assert not ScheduledRun.objects.filter(id=older_success.id).exists()
    assert ScheduledRun.objects.filter(id=ancient_failure.id).exists(), "newest row for its task"
    assert ScheduledRun.objects.filter(id=recent.id).exists()
    # And the answer the alert gives is unchanged by the pruning.
    assert "weekly_rebuild" in stale_tasks(now)
    assert "membership_sweep" not in stale_tasks(now)


@db
def test_finished_job_rows_past_their_retention_go_and_live_ones_do_not() -> None:
    from core.runs import JOB_ROW_RETENTION_S, prune_job_rows

    old = timedelta(seconds=JOB_ROW_RETENTION_S * 2)
    aged_failure = make_job("weekly_rebuild", "failed", old)
    aged_success = make_job("membership_sweep", "succeeded", old)
    aged_todo = make_job("membership_sweep", "todo", old)
    recent_failure = make_job("nightly_backup", "failed", timedelta(hours=1))

    assert prune_job_rows() == 2

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM procrastinate_jobs ORDER BY id")
        surviving = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT count(*) FROM procrastinate_events WHERE job_id = %s", [aged_failure]
        )
        assert cursor.fetchone()[0] == 0, "events go with the job they belong to"
    assert aged_failure not in surviving
    assert aged_success not in surviving
    assert aged_todo in surviving, "a job the worker has not finished is live state, not history"
    assert recent_failure in surviving


@db
def test_the_newest_successful_row_survives_even_when_a_later_run_failed() -> None:
    """The keep set is two rows per task, not one.

    `stale_tasks` reads the newest *successful* row, and a task whose newest row
    is a failure is exactly the task an operator is about to ask about. Keeping
    only the newest row of any kind would prune the success it is measured
    against, turning "this succeeded three months ago and has failed since" into
    "this has never succeeded".
    """
    from core.models import ScheduledRun
    from core.runs import RUN_ROW_RETENTION_S, prune_run_rows, stale_task_details

    now = timezone.now()
    ancient = now - timedelta(seconds=RUN_ROW_RETENTION_S * 2)
    success = ScheduledRun.objects.create(
        task="nightly_backup", started_at=ancient, finished_at=ancient, succeeded=True
    )
    failure = ScheduledRun.objects.create(
        task="nightly_backup",
        started_at=ancient + timedelta(hours=1),
        finished_at=ancient + timedelta(hours=1),
        succeeded=False,
    )

    assert prune_run_rows(now) == 0

    assert ScheduledRun.objects.filter(id=failure.id).exists(), "the newest row of any kind"
    assert ScheduledRun.objects.filter(id=success.id).exists(), "and the newest successful one"
    backup = [entry for entry in stale_task_details(now) if entry["task"] == "nightly_backup"]
    assert backup and backup[0]["last_success_at"] == success.started_at, (
        "the alert can still say when this last worked"
    )


@db
def test_a_job_still_running_is_not_history_however_old_it_is() -> None:
    """Only terminal statuses are pruned. A job left `doing` by a worker that
    died is live state - the row another worker's `fetch_job` and the admin's
    failed-job page both read - and deleting it makes the work disappear rather
    than the history."""
    from core.runs import JOB_ROW_RETENTION_S, prune_job_rows

    old = timedelta(seconds=JOB_ROW_RETENTION_S * 2)
    doing = make_job("weekly_rebuild", "doing", old)
    aborting = make_job("membership_sweep", "aborting", old)
    finished = make_job("nightly_backup", "succeeded", old)

    assert prune_job_rows() == 1

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM procrastinate_jobs ORDER BY id")
        surviving = [row[0] for row in cursor.fetchall()]
    assert doing in surviving, "a job a worker is holding is not old history"
    assert aborting in surviving, "nor is one that has been asked to stop"
    assert finished not in surviving


@db
def test_a_job_a_periodic_defer_still_points_at_is_left_alone() -> None:
    """That row is how the scheduler knows it has already fired this tick, and
    deleting the job it names violates the constraint rather than tidying
    anything."""
    from core.runs import JOB_ROW_RETENTION_S, prune_job_rows

    job_id = make_job("weekly_rebuild", "succeeded", timedelta(seconds=JOB_ROW_RETENTION_S * 2))
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO procrastinate_periodic_defers
                   (task_name, periodic_id, defer_timestamp, job_id)
               VALUES ('weekly_rebuild', '', 1, %s)""",
            [job_id],
        )

    assert prune_job_rows() == 0
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs WHERE id = %s", [job_id])
        assert cursor.fetchone()[0] == 1

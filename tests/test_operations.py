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

    Afterwards as well as before, and the second half is not symmetry. The
    tests here leave `todo` rebuilds behind on purpose - that is what unwedging
    one produces - and files that run later have their own single-flight
    refusals to assert, which a leftover queued rebuild satisfies for them.
    """

    def empty() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE procrastinate_periodic_defers, procrastinate_events, "
                "procrastinate_jobs RESTART IDENTITY CASCADE"
            )

    empty()
    yield
    empty()


@pytest.fixture(autouse=True)
def ample_free_space(monkeypatch, tmp_path_factory):
    """Take the free-space check out of every test that is not about it.

    `check_operations` and the operations page report a tiles volume that is
    close to the rebuild's disk gate, and the gate's numbers are real ones -
    20 GiB free and 80 percent full. A test asserting "nothing is wrong" would
    otherwise be asserting something about the machine the suite is running on,
    and would start failing on a busy CI box for a reason that has nothing to
    do with the code under test.

    Neutralised rather than mocked out, so the code path still runs: with no
    floor to reserve and a gate at 100 percent there is genuinely nothing to
    report, and a test that wants the alert sets its own numbers.

    `TILES_DIR` is pointed at a directory that exists for the same reason and
    it is not cosmetic. A checkout has no `data/` directory, so in the suite
    `settings.TILES_DIR` is exactly the shape of a container with no data
    volume mounted - which is now its own answer, `DISK_UNMEASURED`, and its
    own alert. Every test here that is not about the mount says so by taking
    this fixture; the ones that are about it point `TILES_DIR` somewhere
    missing themselves.
    """
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 1.0)
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path_factory.mktemp("tiles"))


@pytest.fixture
def real_deployment_epoch():
    """Requested by a test that wants the real `migrations_applied_at`.

    Its presence in a test's fixture list is what switches the autouse patch
    below off, which keeps the opt-out inside this file rather than in a
    project-wide pytest marker.
    """
    return True


@pytest.fixture(autouse=True)
def migrations_applied_now(request, monkeypatch):
    """Pin the deployment epoch's other half to "a moment ago".

    `core.runs.deployment_epoch` is the earlier of the oldest run row and
    `MAX(django_migrations.applied)`, and the second half is a real column in
    the test database whose value is whenever pytest-django built it. Left
    alone, every test here that asserts something about a deployment with no
    run rows would quietly depend on how long this suite has been running -
    ten minutes in, the heartbeat window has passed and a "fresh deployment"
    test fails. The tests that are about the epoch set their own value.
    """
    if "real_deployment_epoch" in request.fixturenames:
        return
    from core import runs

    monkeypatch.setattr(runs, "migrations_applied_at", lambda: timezone.now())


def deployment_up_since(ago: timedelta, now=None):
    """A `ScheduledRun` row old enough that every alert window has passed since.

    A task that has never succeeded is measured from this deployment's *first*
    run row rather than from now (`core.runs.stale_task_details`), so a test
    about a task that is genuinely late needs the deployment to have a history
    at all. Without one it is describing a stack that came up a moment ago,
    where nothing is late yet - which is the case
    `test_a_fresh_deployment_has_nothing_to_alert_about` covers.

    The row is a *failed* `weekly_rebuild`, so it is a first moment and nothing
    else: it makes no task look successful.
    """
    from core.models import ScheduledRun

    now = now or timezone.now()
    started = now - ago
    return ScheduledRun.objects.create(
        task="weekly_rebuild", started_at=started, finished_at=started, succeeded=False
    )


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
    deployment_up_since(timedelta(days=90), now)
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
    deployment_up_since(timedelta(days=90), now)
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

    deployment_up_since(timedelta(days=90))
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
    assert "ok: no stale tasks, no wedged jobs, no failed jobs" in out.getvalue()


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
    assert "0 stale task(s), 0 wedged job(s), 4 failed job(s)" in printed
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


# --- A job nothing finished ------------------------------------------------------------
#
# Both surfaces read `status="failed"` and nothing else. A worker killed
# mid-job - OOM, a `docker compose down` in the middle of a rebuild, a host
# reboot - never writes that status, because the process that would have
# written it is gone: the row stays `doing` for ever. So a rebuild killed at
# hour three was on no surface at all until `weekly_rebuild` went stale eight
# days later, while the job holding the rebuild queue's only slot was never
# going to move, and the operations page said nothing was wrong the whole time.


@db
def test_check_operations_reports_a_job_wedged_past_its_budget() -> None:
    """The rebuild's own six-hour budget is what "too long" means for it, so a
    job that has outlived it is a job whose enforcement did not happen."""
    from io import StringIO

    from django.core.management import call_command

    from config.procrastinate import REBUILD_TIMEOUT_S
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    job_id = make_job("weekly_rebuild", "doing", timedelta(seconds=REBUILD_TIMEOUT_S + 60))

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    printed = out.getvalue()

    assert exit_code.value.code == 1, "nothing else on this deployment is wrong, and it is"
    assert f"wedged job: {job_id} weekly_rebuild" in printed, printed
    assert f"past its {REBUILD_TIMEOUT_S:.0f}s budget" in printed, printed
    assert "1 wedged job(s)" in printed


@db
def test_check_operations_leaves_a_job_inside_its_budget_alone() -> None:
    """The alert is "past its budget", not "running". A six-hour rebuild that
    is three hours in is a rebuild, and an alert that fired on it would fire
    every Tuesday morning."""
    from io import StringIO

    from django.core.management import call_command

    from config.procrastinate import REBUILD_TIMEOUT_S
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    make_job("weekly_rebuild", "doing", timedelta(seconds=REBUILD_TIMEOUT_S - 60))

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)

    assert exit_code.value.code == 0, out.getvalue()
    assert "wedged" not in out.getvalue().replace("no wedged jobs", "")


@db
def test_the_budget_a_job_is_judged_against_is_its_own_tasks() -> None:
    """One table, read from the constants the tasks enforce on themselves. The
    sweep's half hour and the rebuild's six hours are two different numbers, and
    judging the sweep by the rebuild's budget is a sweep that is wedged for five
    and a half hours before anything says so."""
    from io import StringIO

    from django.core.management import call_command

    from config.procrastinate import REBUILD_TIMEOUT_S, SWEEP_TIMEOUT_S
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, job_budgets

    assert job_budgets()["membership_sweep"] == SWEEP_TIMEOUT_S
    assert job_budgets()["weekly_rebuild"] == REBUILD_TIMEOUT_S

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    sweep = make_job("membership_sweep", "doing", timedelta(seconds=SWEEP_TIMEOUT_S + 60))
    # Older than the sweep's budget, younger than the rebuild's, so a single
    # shared number cannot make both of these assertions pass.
    make_job("weekly_rebuild", "doing", timedelta(seconds=SWEEP_TIMEOUT_S + 60))

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    printed = out.getvalue()

    assert exit_code.value.code == 1
    assert f"wedged job: {sweep} membership_sweep" in printed, printed
    assert "1 wedged job(s)" in printed, (
        f"the rebuild is three hours short of its own budget: {printed}"
    )


@db
def test_the_operations_page_shows_a_wedged_job(client) -> None:
    """The same row on the surface an operator who is logged in is looking at.
    Two surfaces, one computation, which is the rule the stale list already
    follows: a page that disagrees with the alert is worse than no page."""
    from config.procrastinate import REBUILD_TIMEOUT_S
    from core.models import User

    job_id = make_job("weekly_rebuild", "doing", timedelta(seconds=REBUILD_TIMEOUT_S + 60))

    admin = User.objects.create(discord_user_id=9010, is_instance_admin=True)
    sign_in(client, admin)
    response = client.get(operations_url())

    assert response.status_code == 200
    body = response.content.decode()
    wedged_section = body.split("<h2>Wedged jobs</h2>")[1].split("<h2>Failed jobs</h2>")[0]
    assert f">{job_id}<" in wedged_section, wedged_section
    assert "weekly_rebuild" in wedged_section
    assert "no-wedged-jobs" not in body


@db
def test_the_operations_page_says_so_when_no_job_is_wedged(client) -> None:
    """The row, not the word: a page whose wedged section is empty must say it
    is empty, or an operator reading it cannot tell the check from a check that
    is not there."""
    from config.procrastinate import REBUILD_TIMEOUT_S
    from core.models import User

    make_job("weekly_rebuild", "doing", timedelta(seconds=REBUILD_TIMEOUT_S - 60))

    admin = User.objects.create(discord_user_id=9011, is_instance_admin=True)
    sign_in(client, admin)
    body = client.get(operations_url()).content.decode()

    assert 'id="no-wedged-jobs"' in body
    assert 'class="wedged-job"' not in body


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


# --- A deployment's first minutes ------------------------------------------------------


@db
def test_a_fresh_deployment_has_nothing_to_alert_about() -> None:
    """The cron entry docs/OPERATIONS.md gives is `check_operations` every ten
    minutes, and on a host that had just run `docker compose up -d` it exited 1
    with all five tasks named. Nothing was wrong: `weekly_rebuild` had not
    missed eight days, it had existed for a minute. "Has never run" and "has not
    run for long enough to matter" were the same missing row.

    The first alert an operator ever sees being a false one, on the morning of
    the install, from the entry they have just added, is how a monitor gets
    muted - which costs the alert that fires six weeks later for a real reason.
    """
    from io import StringIO

    from django.core.management import call_command

    from core.runs import stale_task_details, stale_tasks

    assert stale_tasks() == [], f"a database with no runs at all reports {stale_task_details()}"

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 0, (
        f"check_operations pages on a deployment that has just started: {out.getvalue()}"
    )


@db
def test_a_task_that_has_never_run_is_stale_once_its_window_has_passed() -> None:
    """The other half, and the one the change must not cost: a task that is
    never scheduled at all is still an alert. Its clock starts at the
    deployment's first run row - the only evidence in the database of when this
    stack started running - so the rebuild is named eight days later and the
    heartbeat ten minutes later, which is the same lateness every other silent
    failure here gets.
    """
    from core.runs import STALE_AFTER, stale_task_details, stale_tasks

    now = timezone.now()
    window = STALE_AFTER["weekly_rebuild"]
    first = deployment_up_since(timedelta(seconds=window - 60), now)

    assert "weekly_rebuild" not in stale_tasks(now), (
        "a minute inside the window measured from the deployment's first row"
    )
    assert "nightly_backup" in stale_tasks(now), (
        "the backup's 26-hour window passed days ago on this deployment and it has never succeeded"
    )

    first.started_at = now - timedelta(seconds=window + 60)
    first.save(update_fields=["started_at"])
    stale = {entry["task"]: entry for entry in stale_task_details(now)}
    assert "weekly_rebuild" in stale, "a minute past it, and no success anywhere, is stale"
    assert stale["weekly_rebuild"]["last_success_at"] is None
    assert stale["weekly_rebuild"]["age_s"] is None, (
        "there is no age to report for a task that has never succeeded; the surfaces print "
        "'never' from this"
    )


@db
def test_the_first_row_is_the_deployments_and_not_the_tasks_own() -> None:
    """One clock for every task that has never succeeded, and it is the oldest
    row in the table whatever wrote it. A per-task first row would be no clock
    at all - a task that has never run has no row of its own, which is the
    whole condition being measured.
    """
    from core.models import ScheduledRun
    from core.runs import first_run_at, stale_tasks

    now = timezone.now()
    assert first_run_at() is None

    # One task succeeding is what starts every other task's window.
    started = now - timedelta(hours=27)
    ScheduledRun.objects.create(
        task="worker_heartbeat", started_at=started, finished_at=started, succeeded=True
    )
    assert first_run_at() == started
    stale = stale_tasks(now)
    assert "nightly_backup" in stale, "26 hours have passed since this deployment's first row"
    assert "weekly_rebuild" not in stale, "eight days have not"


# --- A deployment whose worker never dequeued anything ----------------------------------
#
# The case the run-row epoch could not see at all. `first_run_at` is written by
# the first periodic task to *finish*, so a worker that never dequeued a job -
# a `--queues` typo, a crash loop, a maintenance container that never came up -
# leaves the table empty, the epoch None, and nothing stale for ever. The
# deployment that needed the ten-minute heartbeat alert most was the one it
# could not fire on.


@db
def test_a_worker_that_never_dequeued_anything_is_an_alert_once_its_window_passes(
    monkeypatch,
) -> None:
    """Jobs `todo`, no run row anywhere, and `check_operations` said "ok".

    The epoch is now the earlier of the first run row and the deployment's last
    migration, and `migrate` runs before any worker does, so the heartbeat's
    ten-minute window starts when the deployment does rather than when its
    first job finishes. Both sides of that window are asserted, because the
    half that must not regress is the fresh install: an alert that fires in the
    first minute of every deployment is an alert that gets muted.
    """
    from io import StringIO

    from django.core.management import call_command

    from core import runs
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER

    make_job("worker_heartbeat", "todo", timedelta(minutes=30))
    assert not ScheduledRun.objects.exists(), "no task has ever finished on this deployment"

    window = STALE_AFTER["worker_heartbeat"]
    monkeypatch.setattr(
        runs, "migrations_applied_at", lambda: timezone.now() - timedelta(seconds=window - 60)
    )
    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 0, (
        f"a minute inside the heartbeat window is not an alert yet: {out.getvalue()}"
    )

    monkeypatch.setattr(
        runs, "migrations_applied_at", lambda: timezone.now() - timedelta(seconds=window + 60)
    )
    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    assert exit_code.value.code == 1, (
        "a deployment whose worker has never dequeued a job reported ok for ever"
    )
    assert "stale: worker_heartbeat" in out.getvalue()


@db
def test_the_epoch_exists_as_soon_as_migrate_has_run(real_deployment_epoch) -> None:
    """The real column, not a stand-in: `MAX(django_migrations.applied)`.

    Every deployment procedure runs `migrate` before it starts a worker, and
    nothing in this project prunes `django_migrations`, so this is the one
    timestamp that is there on a stack where no job has ever been dequeued.
    The test database was built by running the migrations, so it has one.
    """
    from core.models import ScheduledRun
    from core.runs import deployment_epoch, migrations_applied_at

    applied = migrations_applied_at()
    assert applied is not None, "the test database was built by `migrate` and has the rows"
    assert not ScheduledRun.objects.exists()
    assert deployment_epoch() == applied, "with no run row, the migration is the whole epoch"


@db
def test_the_epoch_is_the_earlier_of_the_two_and_does_not_drift(real_deployment_epoch) -> None:
    """`prune_run_rows` keeps the newest row per task and drops the rest past
    thirty days, so on an old deployment `first_run_at` is not "when this stack
    started running" - it is "thirty days ago", and it walks forward every
    night. The migration timestamp is written once and pruned by nothing, so
    taking the earlier of the two pins the epoch to it and the reference the
    alert measures against stops moving.
    """
    from core.models import ScheduledRun
    from core.runs import deployment_epoch, first_run_at, migrations_applied_at

    applied = migrations_applied_at()
    older = applied - timedelta(days=400)
    ScheduledRun.objects.create(
        task="worker_heartbeat", started_at=older, finished_at=older, succeeded=True
    )
    assert deployment_epoch() == older, "a run row older than the migration is the epoch"

    ScheduledRun.objects.all().delete()
    newer = applied + timedelta(days=400)
    ScheduledRun.objects.create(
        task="worker_heartbeat", started_at=newer, finished_at=newer, succeeded=True
    )
    assert first_run_at() == newer
    assert deployment_epoch() == applied, (
        "the oldest surviving run row has drifted past the migration, so the migration is "
        "the epoch and the windows stop moving with the pruning"
    )


@db
def test_a_success_exactly_its_window_old_is_stale() -> None:
    """The edge itself, which nothing pinned: with `age < window` widened to
    `age <= window` every test still passed, because no test ever wrote a
    success exactly one window old. The window is "no success inside the last
    N seconds", so the instant the window closes is outside it.
    """
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, stale_tasks

    now = timezone.now()
    for task in STALE_AFTER:
        started = now - timedelta(seconds=STALE_AFTER[task])
        ScheduledRun.objects.create(
            task=task, started_at=started, finished_at=started, succeeded=True
        )
    assert sorted(stale_tasks(now)) == sorted(STALE_AFTER), (
        "a success exactly one window old is outside the window, not on its edge"
    )


# --- Free space on the tiles volume ----------------------------------------------------
#
# The disk gate is a hard refusal whose only remedy is growing the volume, and
# nothing reported the volume until that refusal arrived - so the first an
# operator heard of it was a rebuild that did not run, a week after it could
# have been fixed.


def fake_usage(total: int, used: int):
    """A `shutil.disk_usage` stand-in, so the assertion is about the numbers
    rather than about the machine the suite happens to run on."""
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    return lambda path: usage(total, used, total - used)


@db
def test_a_volume_too_full_for_the_next_rebuild_is_an_alert(monkeypatch) -> None:
    """Below the floor the gate reserves, which is `REBUILD_MIN_FREE_BYTES`."""
    from io import StringIO

    from django.core.management import call_command

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, disk_headroom

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)
    short = disk_headroom(disk_usage=fake_usage(200 * 1024**3, 190 * 1024**3))
    assert short["status"] == "short" and short["alert"]
    assert short["free_bytes"] == 10 * 1024**3

    # The command through its own code path, with a floor no filesystem can
    # satisfy rather than a stubbed check: what is asserted is that the fourth
    # check reaches the exit code, not that a stand-in was called.
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 1 << 62)
    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    printed = out.getvalue()
    assert exit_code.value.code == 1, f"nothing else is wrong, so this is the disk: {printed}"
    assert "disk:" in printed
    assert "1 volume(s) short of room for a rebuild" in printed


@db
def test_a_volume_over_the_gate_fraction_is_an_alert_before_the_gate_refuses(
    monkeypatch,
) -> None:
    """Free space alone is not the gate. The gate also refuses a build that
    would take the volume past `DISK_GATE_FRACTION`, and it charges the floor
    at minimum - so a volume with room for the floor in absolute terms, but not
    without crossing 80 percent, is one the next rebuild refuses.
    """
    from core.runs import disk_headroom

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    # 30 GiB free of 100, floor 20: the floor fits, but using it leaves the
    # volume 90 percent full.
    tight = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 70 * 1024**3))
    assert tight["status"] == "short", "free space alone said this volume was fine"
    assert tight["free_bytes"] > tight["minimum_free_bytes"]
    assert tight["fraction_after"] > tight["fraction"]

    roomy = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 40 * 1024**3))
    assert roomy["status"] == "ok", "60 GiB free of 100 and 60 percent full after the floor is fine"
    assert not roomy["alert"]
    # The ok answer carries the evidence too, because the surfaces render it:
    # "there is room" with no path and no figure behind it is the sentence a
    # container that had measured the wrong filesystem printed.
    assert roomy["free_bytes"] == 60 * 1024**3
    assert roomy["path"] == str(settings.TILES_DIR)


@db
def test_the_free_space_line_names_the_path_it_measured(monkeypatch) -> None:
    """The check runs wherever the runbook's cron entry puts it, and only one
    container mounts the data volume. A line that does not say which path it
    read is a line that can be quietly about the wrong one.
    """
    from core.runs import disk_headroom

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 1 << 62)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    reported = disk_headroom()
    assert reported["status"] == "short"
    assert reported["path"] == str(settings.TILES_DIR), (
        "the path reported is the tiles directory itself, which is the filesystem "
        "check_disk_gate measures after it has created it"
    )


@db
def test_a_container_with_no_tiles_volume_says_so_rather_than_reassuring(monkeypatch) -> None:
    """The finding this replaced a reassurance for.

    `settings.TILES_DIR` is `DATA_ROOT / "tiles"` and `DATA_ROOT` falls back to
    a path inside the image, so in a container with no data volume mounted the
    directory is simply not there. The probe used to walk up to the nearest
    existing ancestor - `/` - measure the container's own root filesystem, find
    it roomy, and let both surfaces say "the tiles volume has room for the next
    rebuild": a positive claim about a filesystem neither of them had ever
    seen, on the one check whose whole job is to be read before the rebuild's
    disk gate refuses.

    So a missing `TILES_DIR` is its own answer and its own alert. It is an
    alert rather than a silence because it is the outcome where the check has
    no coverage at all, and a monitor that exits 0 while a quarter of it is
    blind is the silence the check was added to break; it clears for good by
    mounting the volume, so it costs one page rather than a recurring one.
    """
    from io import StringIO
    from pathlib import Path

    from django.core.management import call_command

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, disk_headroom

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    unmounted = Path(settings.TILES_DIR) / "no" / "data" / "volume" / "here"
    monkeypatch.setattr(settings, "TILES_DIR", unmounted)

    reported = disk_headroom()
    assert reported["status"] == "unmeasured"
    assert reported["alert"], "a container that cannot see the volume is not a container with room"
    assert reported["path"] is None
    assert reported["tiles_dir"] == str(unmounted)

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    printed = out.getvalue()
    assert exit_code.value.code == 1, f"a blind check exited 0: {printed}"
    assert "not measured" in printed, printed
    assert str(unmounted) in printed, "the line names the path that is missing"
    assert "is not present in this container" in printed, printed
    assert "1 volume(s) not measured" in printed, printed
    assert "room for a rebuild" not in printed, (
        f"nothing may claim there is room for a rebuild here: {printed}"
    )


@db
def test_the_operations_page_does_not_reassure_about_a_volume_it_cannot_see(
    client, monkeypatch
) -> None:
    """The same, on the page: the block that rendered "The tiles volume has
    room for the next rebuild" over a filesystem the container never mounted.
    """
    from pathlib import Path

    from core.models import User

    unmounted = Path(settings.TILES_DIR) / "no" / "data" / "volume" / "here"
    monkeypatch.setattr(settings, "TILES_DIR", unmounted)
    admin = User.objects.create(discord_user_id=9104, is_instance_admin=True)
    sign_in(client, admin)

    body = client.get(operations_url()).content.decode()
    assert "disk-not-measured" in body
    assert "disk-has-room" not in body, "the page reassured about a volume it cannot see"
    assert str(unmounted) in body, "the page names the path that is missing"
    assert "is not present in this container" in body
    assert "room for the next rebuild" not in body, "the reassurance is still rendered"


@db
def test_the_operations_page_shows_a_volume_with_no_room(client, monkeypatch) -> None:
    from core.models import User

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 1 << 62)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)
    admin = User.objects.create(discord_user_id=9101, is_instance_admin=True)
    sign_in(client, admin)

    body = client.get(operations_url()).content.decode()
    assert "disk-headroom" in body
    assert "disk-has-room" not in body


@db
def test_the_operations_page_says_so_when_there_is_room(client, monkeypatch) -> None:
    """And says it with the path and the free bytes in it.

    The sentence used to be "The tiles volume has room for the next rebuild" -
    no path, no figure - which is a claim that reads the same whether the
    number behind it came from the tiles volume or from the container's root
    filesystem. A reassurance that cannot be checked against anything is what
    let the unmounted container look healthy.
    """
    from core.models import User

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 0)
    admin = User.objects.create(discord_user_id=9102, is_instance_admin=True)
    sign_in(client, admin)

    body = client.get(operations_url()).content.decode()
    assert "disk-has-room" in body
    assert str(settings.TILES_DIR) in body, "the page names the path it measured"
    assert "free of" in body, "and the free space it found there"
    assert "room for the next rebuild" in body, "and still says what that means"


@db
def test_the_ok_line_names_the_path_and_the_free_space(monkeypatch) -> None:
    """`check_operations`' ok line, same reason as the page's.

    "ok: ... room for a rebuild" was printed by a container measuring its own
    root filesystem, and a reassurance with no path and no number in it cannot
    be read against the volume it is supposed to be about.
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

    out = StringIO()
    with pytest.raises(SystemExit) as exit_code:
        call_command("check_operations", stdout=out)
    printed = out.getvalue()
    assert exit_code.value.code == 0, printed
    assert printed.startswith("ok:"), printed
    assert str(settings.TILES_DIR) in printed, f"the ok line names the path it measured: {printed}"
    assert "GiB free for a rebuild" in printed, printed


# --- Putting a wedged job back ----------------------------------------------------------


@db
def test_both_surfaces_name_the_command_that_clears_a_wedged_job(client) -> None:
    """A wedged job was reported and nothing said what to do about it, and
    there was nothing to do: Procrastinate prunes stalled *workers*, not their
    jobs, so a rebuild whose worker was SIGKILLed stayed `doing` for ever and
    both single-flight checks refused every rebuild after it. The remedy is one
    command, and it is named on the row rather than composed by each surface so
    the page and the monitor cannot send an operator to different places.
    """
    from io import StringIO

    from django.core.management import call_command

    from core.models import ScheduledRun, User
    from core.runs import STALE_AFTER, wedged_jobs

    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    make_job("weekly_rebuild", "doing", timedelta(hours=9))

    assert all("unwedge_job" in entry["remedy"] for entry in wedged_jobs())

    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("check_operations", stdout=out)
    assert "unwedge_job" in out.getvalue()

    admin = User.objects.create(discord_user_id=9103, is_instance_admin=True)
    sign_in(client, admin)
    assert "unwedge_job" in client.get(operations_url()).content.decode()


def wedged_rebuild(minutes: int = 600, worker_id=None) -> int:
    """A `weekly_rebuild` job `doing` for longer than its own budget, owned by
    `worker_id` or by nobody."""
    at = timezone.now() - timedelta(minutes=minutes)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, priority, args, status, attempts,
                 abort_requested, queueing_lock, worker_id)
            VALUES ('rebuild', 'weekly_rebuild', 0, '{}'::jsonb, 'doing', 0,
                    false, 'weekly_rebuild', %s)
            RETURNING id
            """,
            [worker_id],
        )
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'started', %s)",
            [job_id, at],
        )
    return job_id


def register_worker(last_heartbeat) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_workers (last_heartbeat) VALUES (%s) RETURNING id",
            [last_heartbeat],
        )
        return cursor.fetchone()[0]


def job_status(job_id: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT status FROM procrastinate_jobs WHERE id = %s", [job_id])
        return cursor.fetchone()[0]


@db
def test_unwedge_job_puts_a_disowned_job_back_on_its_queue() -> None:
    """The whole point. A worker killed with SIGKILL writes no terminal status,
    and the next worker's startup prunes the stalled worker row - which sets
    this job's `worker_id` NULL through the foreign key and leaves the job
    `doing` for ever. `run_rebuild_now` and the in-task check both read that
    row, so the deployment never rebuilds again.
    """
    from io import StringIO

    from django.core.management import call_command

    from core.models import AuditLogEntry

    job_id = wedged_rebuild()

    out = StringIO()
    call_command("unwedge_job", str(job_id), stdout=out)

    assert job_status(job_id) == "todo"
    printed = out.getvalue()
    assert f"job {job_id}" in printed and "queued again" in printed
    assert "rebuild service" in printed, "it says what happens next"
    assert "run_rebuild_now" in printed

    entry = AuditLogEntry.objects.get(action="unwedge_job")
    assert entry.actor is None and entry.actor_user_id is None, (
        "a shell in a container has no actor, the same as run_rebuild_now"
    )
    assert entry.model == "procrastinatejob"
    assert entry.object_id == str(job_id)
    assert entry.outcome == AuditLogEntry.Outcome.ALLOWED


@db
def test_unwedge_job_refuses_while_the_worker_is_still_beating() -> None:
    """The refusal that makes the command safe to hand an operator. A worker
    running a six-hour rebuild updates `procrastinate_workers.last_heartbeat`
    every ten seconds from its own asyncio task - the sync task body runs in a
    thread, so the loop keeps beating - and requeueing a job that is genuinely
    running is how two rebuilds end up writing the same staging schema.
    """
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from core.models import AuditLogEntry

    worker = register_worker(timezone.now())
    job_id = wedged_rebuild(worker_id=worker)

    with pytest.raises(CommandError) as refused:
        call_command("unwedge_job", str(job_id))

    assert f"worker {worker}" in str(refused.value)
    assert job_status(job_id) == "doing", "the refused call requeued it anyway"
    assert not AuditLogEntry.objects.filter(action="unwedge_job").exists()


@db
def test_unwedge_job_accepts_a_worker_that_has_stopped_reporting() -> None:
    """The worker row outliving the process: `prune_stalled_workers` runs at
    the *next* worker's startup, so between the kill and that startup the row
    is still there with a heartbeat that has stopped. Procrastinate's own
    definition of stalled is the number used here.
    """
    from django.core.management import call_command

    from core.management.commands.unwedge_job import STALLED_WORKER_TIMEOUT_S

    silent = timezone.now() - timedelta(seconds=STALLED_WORKER_TIMEOUT_S + 30)
    job_id = wedged_rebuild(worker_id=register_worker(silent))

    call_command("unwedge_job", str(job_id))

    assert job_status(job_id) == "todo"


@db
def test_unwedge_job_refuses_a_job_that_is_not_doing() -> None:
    """`todo` is already queued and a terminal status is finished. Neither is
    wedged, and moving either would be this command inventing work."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    queued = make_job("weekly_rebuild", "todo", timedelta(minutes=1))
    with pytest.raises(CommandError) as refused:
        call_command("unwedge_job", str(queued))
    assert "not doing" in str(refused.value)

    with pytest.raises(CommandError) as missing:
        call_command("unwedge_job", str(queued + 10_000))
    assert "no job" in str(missing.value)


@db
def test_unwedge_job_refuses_when_the_queueing_lock_is_already_taken() -> None:
    """The collision `run_rebuild_now` exists to avoid, from the other side.
    Procrastinate's queueing-lock index is partial on `WHERE status = 'todo'`,
    so moving this row back to `todo` while another job holds the same lock
    there is a unique violation inside the retry function - a traceback out of
    a command an operator is running at three in the morning, rather than a
    sentence telling them the next run is already queued.
    """
    from django.core.management import call_command
    from django.core.management.base import CommandError

    wedged = wedged_rebuild()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, priority, args, status, attempts,
                 abort_requested, queueing_lock)
            VALUES ('rebuild', 'weekly_rebuild', 0, '{}'::jsonb, 'todo', 0, false,
                    'weekly_rebuild')
            RETURNING id
            """
        )
        queued = cursor.fetchone()[0]

    with pytest.raises(CommandError) as refused:
        call_command("unwedge_job", str(wedged))

    assert f"job {queued}" in str(refused.value)
    assert "queueing lock" in str(refused.value)
    assert job_status(wedged) == "doing"


# --- The budget table, read from the constants rather than beside them ------------------


def test_the_sweeps_budget_follows_the_constant_the_task_enforces(monkeypatch) -> None:
    """`SWEEP_TIMEOUT_S` and `DEFAULT_JOB_BUDGET_S` are both thirty minutes
    today, so every assertion comparing the sweep's budget to a number passes
    whichever of the two `job_budgets` reads. That is not a test of the table,
    it is a coincidence: the sweep's half hour is `run_with_deadline`'s own
    argument and the default is the maintenance queue's bound for a task that
    enforces nothing, and the day one of them moves the wedged-job alert would
    silently judge the sweep by the wrong one.

    So the constant is moved and the table is read again.
    """
    from config import procrastinate as worker
    from core.runs import job_budgets

    monkeypatch.setattr(worker, "SWEEP_TIMEOUT_S", 1234)
    assert job_budgets()["membership_sweep"] == 1234, (
        "the sweep's budget is the number the sweep enforces on itself, not the default"
    )


def test_the_default_job_budget_is_the_maintenance_queues_bound() -> None:
    """Half an hour, which is what the backup and the sweep are each held to on
    that one-slot queue - so a task that enforces nothing of its own is judged
    by the same number as everything beside it. An hour would put the two
    five-minute tasks 720 ticks late before anything said so."""
    from config.procrastinate import BACKUP_TIMEOUT_S, SWEEP_TIMEOUT_S
    from core.runs import DEFAULT_JOB_BUDGET_S

    assert DEFAULT_JOB_BUDGET_S == 30 * 60
    assert DEFAULT_JOB_BUDGET_S == BACKUP_TIMEOUT_S == SWEEP_TIMEOUT_S, (
        "it is the queue's bound, and these three being equal is the reason it is that number"
    )


def test_the_stalled_worker_timeout_is_procrastinates_own_number() -> None:
    """Read out of the library rather than asserted against itself.

    `unwedge_job` refuses while a job's worker has beaten inside
    `STALLED_WORKER_TIMEOUT_S`, and the number is only defensible because it is
    the one Procrastinate's own `prune_stalled_workers` uses: a command with a
    shorter window would requeue jobs the library still considers owned, and a
    longer one would refuse to clear a job whose worker row the next worker's
    startup has already deleted. The old test imported the constant and
    compared it with itself, so 30.0 could have become 30000.0 without a single
    failure.

    There is no module-level constant to import in 3.9.0 - the default lives on
    the keyword argument of `procrastinate.worker.Worker.__init__` - so the
    signature is what is read, the same way the dropped-tick doc test reads
    `procrastinate.periodic.MAX_DELAY`.
    """
    import inspect

    from procrastinate.worker import Worker

    from core.management.commands.unwedge_job import STALLED_WORKER_TIMEOUT_S

    parameters = inspect.signature(Worker.__init__).parameters
    assert "stalled_worker_timeout" in parameters, (
        "procrastinate.worker.Worker no longer takes stalled_worker_timeout; unwedge_job's "
        "definition of a dead worker has to be re-derived from whatever replaced it"
    )
    assert STALLED_WORKER_TIMEOUT_S == parameters["stalled_worker_timeout"].default, (
        "unwedge_job and the worker must agree about which workers still exist"
    )


def wedged_backup(minutes: int = 600, worker_id=None) -> int:
    """A `nightly_backup` job `doing` on the maintenance queue for longer than
    its budget, owned by `worker_id` or by nobody.

    No queueing lock: the backup does not take one, which is also why an
    operator unwedging it is not told about a lock collision.
    """
    at = timezone.now() - timedelta(minutes=minutes)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, priority, args, status, attempts,
                 abort_requested, worker_id)
            VALUES ('maintenance', 'nightly_backup', 0, '{}'::jsonb, 'doing', 0, false, %s)
            RETURNING id
            """,
            [worker_id],
        )
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'started', %s)",
            [job_id, at],
        )
    return job_id


@db
def test_unwedging_a_backup_names_the_worker_rather_than_the_rebuild() -> None:
    """What the command told an operator to do next was one fixed paragraph.

    It named the rebuild service, `docker compose logs -f rebuild` and
    `manage.py run_rebuild_now` - for every job on every queue. A SIGKILLed
    `nightly_backup` leaves a `doing` row exactly the way a killed rebuild
    does, and it is the ordinary case on any stack that has ever been
    recreated while the maintenance worker was mid-dump; the operator who
    cleared it was then sent to a service that does not run the task and to a
    command that does not queue it. `run_rebuild_now` would have queued a
    six-hour rebuild instead of the backup they came to fix.
    """
    from io import StringIO

    from django.core.management import call_command

    job_id = wedged_backup()

    out = StringIO()
    call_command("unwedge_job", str(job_id), stdout=out)

    assert job_status(job_id) == "todo"
    printed = out.getvalue()
    assert "queued again" in printed
    assert "worker service" in printed, f"the service that actually runs it: {printed}"
    assert "maintenance queue" in printed, f"and the queue it is on: {printed}"
    assert "nightly_backup is periodic" in printed, printed
    assert "run_rebuild_now" not in printed, (
        f"a backup is not requeued by the rebuild's hand-fire command: {printed}"
    )
    assert "logs -f rebuild" not in printed, (
        f"nor watched in the container that does not run it: {printed}"
    )


@db
def test_unwedging_a_rebuild_still_names_the_rebuild_service() -> None:
    """The other half of the same change: making the paragraph task-aware must
    not cost the rebuild the one hand-fire command there is."""
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("unwedge_job", str(wedged_rebuild()), stdout=out)
    printed = out.getvalue()
    assert "rebuild service" in printed and "run_rebuild_now" in printed, printed
    assert "worker service" not in printed, printed


@db
def test_what_a_failure_could_not_put_back_reaches_the_row_and_the_page(client) -> None:
    """`add_note` is how this project says "and here is what is still broken".

    `pipeline.promotion` attaches what a failed undo could not restore to the
    error it re-raises, because the caller classifies on that error and a
    report about the undo is not what it classifies on. The run row then wrote
    `str(error)`, which does not include notes, so the sentence saying the
    deployment was half-restored lived in the container's log and nowhere
    else: not in the detail column, not on the operations page, not in
    anything read after the fact.

    The note is also two `raise ... from ...` levels below the exception this
    context manager sees by the time a rebuild failure arrives - wrapped into
    `RebuildFailed` and then into `RebuildAbandoned` - so the walk is over the
    cause chain rather than over the error alone.
    """
    from core.models import ScheduledRun, User
    from core.runs import record

    note = "the swap's undo could not restore standard's tile links (read-only file system)"

    with pytest.raises(ValueError):
        with record("weekly_rebuild"):
            try:
                inner = OSError("the data volume is read-only")
                inner.add_note(note)
                raise inner
            except OSError as error:
                try:
                    raise RuntimeError("rebuild failed at stage swap") from error
                except RuntimeError as wrapped:
                    raise ValueError("this rebuild is not retried") from wrapped

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert run.detail.startswith("ValueError: this rebuild is not retried"), run.detail
    assert note in run.detail, f"the note two causes down never reached the row: {run.detail}"

    admin = User.objects.create(discord_user_id=9105, is_instance_admin=True)
    sign_in(client, admin)
    body = client.get(operations_url()).content.decode()
    assert "could not restore standard" in body, "and the page shows the row it is written on"


@db
def test_a_run_rows_detail_is_bounded_and_says_each_thing_once() -> None:
    """Two things the note walk has to keep doing.

    An undo can attach one note per variant plus the settings rows, so the
    detail is not a fixed length any more and the 4000-character slice is what
    keeps it out of the way. And the same sentence can sit at two levels of the
    cause chain - `SwapUndoIncomplete` carries the notes of the error it
    wraps - which is one fact and not two.
    """
    from core.models import ScheduledRun
    from core.runs import record

    note = "could not restore the settings rows"
    with pytest.raises(RuntimeError):
        with record("weekly_rebuild"):
            inner = OSError("the data volume is read-only")
            inner.add_note(note)
            try:
                raise inner
            except OSError as error:
                wrapper = RuntimeError("the swap failed")
                wrapper.add_note(note)
                raise wrapper from error

    detail = ScheduledRun.objects.get(task="weekly_rebuild").detail
    assert detail.count(note) == 1, f"the same note at two levels is one fact: {detail}"

    with pytest.raises(RuntimeError):
        with record("membership_sweep"):
            raise RuntimeError("x" * 9000)

    assert len(ScheduledRun.objects.get(task="membership_sweep").detail) == 4000


@db
def test_the_migration_epoch_is_the_last_migration_and_not_the_first(
    real_deployment_epoch,
) -> None:
    """`MAX(applied)`, because what this dates is *this* deployment.

    `django_migrations` is append-only and nothing in this project prunes it,
    so the first row in it is the day the project's first migration was applied
    to this database and never moves again. Read that way the "deployment
    epoch" is the age of the database rather than the age of the running
    stack - every never-succeeded task's window would be measured from a point
    months in the past, every one of them would be outside its window from the
    first tick, and a deployment that had just been rolled out would page for
    four tasks that had simply not run yet.
    """
    from core.runs import migrations_applied_at

    now = timezone.now()
    oldest = now - timedelta(days=400)
    newest = now + timedelta(days=400)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, %s), (%s, %s, %s)",
            ["tq_probe", "0001_oldest", oldest, "tq_probe", "0002_newest", newest],
        )
    try:
        applied = migrations_applied_at()
        assert applied == newest, (
            "the epoch is not the most recent migration; read as MIN it is the day this "
            f"database was first migrated ({oldest}), which never moves again"
        )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_migrations WHERE app = %s", ["tq_probe"])


@db
def test_free_space_exactly_at_the_floor_is_room(monkeypatch) -> None:
    """The floor is what a rebuild reserves, so a volume carrying exactly that
    much is a volume the reservation fits in. Refused at equality this alert
    fires one byte before the gate it is supposed to precede would, and it
    fires on the volume the plan sizes to that number exactly."""
    from core.runs import disk_headroom

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 1.0)

    at_the_floor = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 80 * 1024**3))
    assert at_the_floor["free_bytes"] == at_the_floor["minimum_free_bytes"]
    assert at_the_floor["status"] == "ok", "exactly the floor is the floor, not below it"
    assert not at_the_floor["alert"]

    one_short = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 80 * 1024**3 + 1))
    assert one_short["status"] == "short", "and a byte below it is short"


@db
def test_a_volume_exactly_at_the_gate_fraction_is_room(monkeypatch) -> None:
    """`check_disk_gate` refuses a build that would take the volume *past*
    `DISK_GATE_FRACTION`. Landing on it is not past it, and an alert that
    disagrees with the gate about its own boundary is an alert an operator
    learns to discount."""
    from core.runs import disk_headroom

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    # 60 used of 100, plus the 20 GiB floor, is exactly 80 percent.
    on_the_line = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 60 * 1024**3))
    assert on_the_line["fraction_after"] == on_the_line["fraction"]
    assert on_the_line["status"] == "ok", "exactly at the gate fraction is not past it"

    over = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 60 * 1024**3 + 1024**3))
    assert over["status"] == "short", "and a gibibyte past it is"


@db
def test_a_volume_below_the_floor_is_short_even_where_the_fraction_is_content(
    monkeypatch,
) -> None:
    """Two halves, and either one on its own is a refusal.

    They are not the same question, because `free` is not `total - used`:
    ext4 reserves blocks for root, and a thin or quota'd volume can report a
    great deal of unused space that this process may not have. Here the
    fraction is comfortable - ten percent used, thirty with the floor charged
    against an eighty percent gate - and the rebuild still cannot reserve what
    it needs, because only a gibibyte of that room is actually available.
    """
    from collections import namedtuple

    from core.runs import disk_headroom

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    reserved = disk_headroom(disk_usage=lambda path: usage(100 * 1024**3, 10 * 1024**3, 1024**3))
    assert reserved["fraction_after"] <= reserved["fraction"], (
        "the fraction half of the check is content here, so only the free-space half "
        "can be what refuses"
    )
    assert reserved["free_bytes"] < reserved["minimum_free_bytes"]
    assert reserved["status"] == "short" and reserved["alert"], (
        "a volume with a gibibyte available and a 20 GiB floor to reserve reported room "
        "for the next rebuild"
    )


@db
def test_the_headroom_is_measured_on_the_tiles_directory_itself(monkeypatch, tmp_path) -> None:
    """Measured there, not only reported as there.

    Every other headroom test hands in a `disk_usage` that answers the same
    numbers whatever path it is asked about, so `disk_usage("/")` in place of
    `disk_usage(tiles_dir)` passed them all while the dict went on naming
    `TILES_DIR` as the path it measured. Here the two filesystems disagree: the
    tiles volume is short and everything else is roomy, and only a measurement
    of the tiles directory can come back short.
    """
    from collections import namedtuple

    from core.runs import disk_headroom

    usage = namedtuple("usage", "total used free")
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    monkeypatch.setattr(settings, "TILES_DIR", tiles_dir)
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    asked: list[str] = []

    def by_path(path):
        asked.append(str(path))
        if str(path) == str(tiles_dir):
            return usage(200 * 1024**3, 195 * 1024**3, 5 * 1024**3)
        return usage(1000 * 1024**3, 10 * 1024**3, 990 * 1024**3)

    measured = disk_headroom(disk_usage=by_path)
    assert asked == [str(tiles_dir)], asked
    assert measured["status"] == "short" and measured["alert"], measured
    assert measured["free_bytes"] == 5 * 1024**3
    assert measured["path"] == str(tiles_dir)


@db
def test_a_volume_that_reports_no_size_at_all_reads_as_full(monkeypatch) -> None:
    """A total of zero is a filesystem that cannot be measured - a stub mount,
    a pseudo-filesystem, a driver that answers with nothing. There is no
    honest fraction to compute, and the two directions are not symmetric: read
    as empty it is a volume nothing will ever report on, and read as full it is
    one alert that names the path and clears as soon as the mount is real."""
    from core.runs import disk_headroom

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    unsized = disk_headroom(disk_usage=fake_usage(0, 0))
    assert unsized["fraction_after"] == 1.0, "an unmeasurable volume is treated as full"
    assert unsized["status"] == "short" and unsized["alert"]


@db
def test_the_percentages_the_page_renders_are_percentages(monkeypatch) -> None:
    """The template renders these straight - `{{ ... |floatformat:0 }}` - because
    `floatformat` cannot turn 0.8 into 80 without arithmetic in the page. A
    ratio left in the percent field reads as "the volume is past 1 % full", on
    the alert whose whole job is to be believed before the gate refuses.

    Both dicts, because the unmeasured answer renders the same field.
    """
    from pathlib import Path

    from core.runs import disk_headroom

    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 20 * 1024**3)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 0.8)

    measured = disk_headroom(disk_usage=fake_usage(100 * 1024**3, 70 * 1024**3))
    assert measured["fraction_pct"] == 80.0, measured
    assert measured["fraction_after_pct"] == pytest.approx(90.0), measured

    monkeypatch.setattr(settings, "TILES_DIR", Path(settings.TILES_DIR) / "not" / "mounted")
    unmeasured = disk_headroom()
    assert unmeasured["status"] == "unmeasured"
    assert unmeasured["fraction_pct"] == 80.0, unmeasured


@db
def test_unwedge_job_reports_the_status_the_retry_actually_left(tmp_path) -> None:
    """Read back, not assumed.

    `procrastinate_retry_job_v2` does not always requeue: a `doing` job with an
    abort requested on it is *finished* as `failed` instead, which is the right
    answer - somebody asked this job to stop - and the wrong thing to print
    "is queued again" about. Told that, an operator watches the rebuild service
    for a job that will never be picked up, and the audit row says a job went
    back on the queue when it did not.
    """
    from io import StringIO

    from django.core.management import call_command

    from core.models import AuditLogEntry

    job_id = wedged_rebuild()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET abort_requested = true WHERE id = %s", [job_id]
        )

    out = StringIO()
    call_command("unwedge_job", str(job_id), stdout=out)

    landed = job_status(job_id)
    assert landed == "failed", (
        "the premise of this test: an abort request turns the retry into a finish, and if "
        "Procrastinate has changed that, what this command prints has to be re-derived"
    )
    printed = out.getvalue()
    assert "is now failed" in printed, printed
    assert "queued again" not in printed, (
        f"the command claimed the job was requeued when the retry failed it: {printed}"
    )
    entry = AuditLogEntry.objects.get(action="unwedge_job")
    assert "is now failed" in entry.detail, entry.detail


def aborted(job_id: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET abort_requested = true WHERE id = %s", [job_id]
        )
    return job_id


@db
@pytest.mark.parametrize("make", [wedged_rebuild, wedged_backup], ids=["rebuild", "backup"])
def test_a_job_the_retry_finished_is_not_followed_by_pickup_advice(make) -> None:
    """The status line was corrected and the paragraph after it was not.

    Having said the job is now `failed`, the command went on to say the service
    picks a `todo` job up within seconds - the advice for a row that went back
    on the queue, printed under one that did not. Whatever it says next, it must
    not send the operator to watch for a pickup that cannot happen, and on both
    queues.
    """
    from io import StringIO

    from django.core.management import call_command

    from core.management.commands.unwedge_job import next_steps

    job_id = aborted(make())
    out = StringIO()
    call_command("unwedge_job", str(job_id), stdout=out)
    assert job_status(job_id) == "failed", "the premise, as above"

    printed = out.getvalue()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT task_name, queue_name FROM procrastinate_jobs WHERE id = %s", [job_id]
        )
        task_name, queue_name = cursor.fetchone()
    assert next_steps(task_name, queue_name, "todo") not in printed, (
        f"a finished job was given the advice for a requeued one: {printed}"
    )
    assert "`todo`" not in printed and "logs -f" not in printed, printed


@db
@pytest.mark.parametrize("make", [wedged_rebuild, wedged_backup], ids=["rebuild", "backup"])
def test_a_job_the_retry_finished_is_told_what_happened_and_what_is_next(make) -> None:
    """What the paragraph after a finished job does say, not only what it
    leaves out: that the job was finished as `failed` and no worker will take
    it, and then the way forward for that task - `run_rebuild_now` for the
    rebuild, and for a periodic task that it is periodic, by name, and the next
    tick replaces it. Read from the paragraph alone, so the status line above
    it cannot answer for it."""
    from io import StringIO

    from django.core.management import call_command

    job_id = aborted(make())
    out = StringIO()
    call_command("unwedge_job", str(job_id), stdout=out)
    with connection.cursor() as cursor:
        cursor.execute("SELECT task_name FROM procrastinate_jobs WHERE id = %s", [job_id])
        (task_name,) = cursor.fetchone()

    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) >= 2, out.getvalue()
    paragraph = lines[-1].lower()
    assert "failed" in paragraph, paragraph
    assert "no worker" in paragraph, paragraph
    if task_name == "weekly_rebuild":
        assert "run_rebuild_now" in paragraph, paragraph
    else:
        assert task_name in paragraph and "periodic" in paragraph, paragraph
        assert "next tick" in paragraph, paragraph
        assert "run_rebuild_now" not in paragraph, paragraph


@db
def test_the_rebuild_a_finished_unwedge_points_to_can_be_queued() -> None:
    """The advice after a finished rebuild names `run_rebuild_now`, and it is
    only advice if the command then works: with the row finished nothing is in
    flight, so the fresh run queues."""
    from io import StringIO

    from django.core.management import call_command

    job_id = aborted(wedged_rebuild())
    out = StringIO()
    call_command("unwedge_job", str(job_id), stdout=out)
    assert "run_rebuild_now" in out.getvalue(), out.getvalue()

    queued = StringIO()
    call_command("run_rebuild_now", stdout=queued)
    assert "queued weekly_rebuild as job" in queued.getvalue(), queued.getvalue()


@db
def test_unwedge_job_is_not_blocked_by_the_lock_its_own_row_holds() -> None:
    """The queueing-lock check is about *another* job.

    It can only ever be about another job, because the row being unwedged is
    `doing` - the command refuses anything else before it gets here - and
    Procrastinate's queueing-lock index is partial on `WHERE status = 'todo'`.
    So the wedged job's own lock is not a collision with itself, and the
    exclusion of its own id is a belt on top of that braces.
    """
    from django.core.management import call_command
    from procrastinate.contrib.django.models import ProcrastinateJob

    job_id = wedged_rebuild()
    assert ProcrastinateJob.objects.get(id=job_id).queueing_lock == "weekly_rebuild"
    assert not ProcrastinateJob.objects.filter(
        queueing_lock="weekly_rebuild", status="todo"
    ).exists(), "nothing else holds the lock, and the wedged row itself is `doing`"

    call_command("unwedge_job", str(job_id))

    assert job_status(job_id) == "todo"

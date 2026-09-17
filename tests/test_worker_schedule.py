"""The periodic tasks the worker actually runs.

Three versions of this file, three ways of not testing the worker. The first
asserted the cron strings and nothing else, while no task was registered. The
second asserted registration, and monkeypatched `run_rebuild` in the one test
meant to prove the rebuild was wired - stubbing out the one function that
would have noticed the handler set could not run. And both called the task
functions from inside pytest, where conftest had already set Django up, so a
worker that died on a missing schema and raised AppRegistryNotReady on every
job passed them all.

So: the rebuild task runs its real handler set with only the binaries stood
in for; a worker is started cold in a subprocess, as compose starts it, and
runs a deferred job; and the timeouts, retries and backup verification are
exercised rather than restated.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from procrastinate.jobs import Job
from rebuild_fixtures import (
    REPO,
    FakeBinaries,
    build_toy_extract,
    fake_fetch,
    state_polygons,
    write_reference_data,
)

from config.procrastinate import (
    DEGRADED_GUILD_SWEEP_CRON,
    MEMBERSHIP_SWEEP_CRON,
    NIGHTLY_BACKUP_CRON,
    REBUILD_TIMEOUT_S,
    SWEEP_TIMEOUT_S,
    WEEKLY_REBUILD_CRON,
    RebuildAbandoned,
    app,
    verify_dump_listing,
)

REBUILD_ALERT_AFTER_S = 8 * 24 * 60 * 60


@pytest.fixture
def states():
    yield from state_polygons()


def registered() -> dict[str, str]:
    """Registered periodic tasks, as {task name: cron}."""
    return {
        name: periodic.cron
        for (name, _periodic_id), periodic in app.periodic_registry.periodic_tasks.items()
    }


def test_each_cron_constant_has_a_task_behind_it() -> None:
    """A schedule nothing is registered against is a comment."""
    assert registered() == {
        "weekly_rebuild": WEEKLY_REBUILD_CRON,
        "nightly_backup": NIGHTLY_BACKUP_CRON,
        "membership_sweep": MEMBERSHIP_SWEEP_CRON,
        "degraded_guild_sweep": DEGRADED_GUILD_SWEEP_CRON,
    }


def test_the_rebuild_cannot_run_twice_at_once() -> None:
    """Two concurrent rebuilds would write the same staging schema and the same
    tile directory."""
    rebuild = app.tasks["weekly_rebuild"]
    assert rebuild.queueing_lock == "weekly_rebuild"
    assert rebuild.queue == "rebuild", "a six-hour build must not sit in front of the sweep"


def test_the_maintenance_tasks_share_a_queue_away_from_the_rebuild() -> None:
    for name in ("nightly_backup", "membership_sweep", "degraded_guild_sweep"):
        assert app.tasks[name].queue == "maintenance"
        assert app.tasks[name].queueing_lock == name


# --- The rebuild task, with its real handlers -----------------------------------------


@pytest.fixture
def rebuild_environment(monkeypatch, tmp_path, segment_schemas):
    """What the weekly task finds on a deployed box, in a temporary directory,
    with only the binaries and the 3DEP download stood in for. The disk gate
    measures the real volume; its floor is lowered so a developer's disk passes."""
    source = tmp_path / "extracts" / "source.osm.pbf"
    source.parent.mkdir()
    build_toy_extract(source)
    write_reference_data(tmp_path, urban=(100, 200, 300, 400, 500))
    monkeypatch.setattr(settings, "REBUILD_SOURCE_PBF", source)
    monkeypatch.setattr(settings, "REBUILD_WORK_DIR", tmp_path / "rebuild")
    monkeypatch.setattr(settings, "REBUILD_REFERENCE_DIR", tmp_path / "reference")
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path / "tiles")
    monkeypatch.setattr(settings, "ELEVATION_DIR", tmp_path / "elevation")
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 0)

    binaries = FakeBinaries()
    monkeypatch.setattr(
        "pipeline.run._run_command", lambda command, deadline=None, clock=None: binaries(command)
    )
    monkeypatch.setattr("pipeline.elevation.fetch_3dep", fake_fetch)
    return tmp_path, binaries


@pytest.mark.django_db(transaction=True)
def test_the_rebuild_task_runs_the_real_handler_set(rebuild_environment, states) -> None:
    """The registered callable, exactly as the worker calls it: no samplers
    injected, no handlers replaced, nothing skipped. Every stage runs, the
    swap promotes, and the run row records it."""
    from core.models import DriftReport, ScheduledRun, ValhallaUpstream

    root, binaries = rebuild_environment
    app.tasks["weekly_rebuild"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert run.succeeded and run.finished_at is not None
    assert "14 stages completed" in run.detail

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {settings.SEGMENT_SCHEMA_LIVE}.segment")
        assert cursor.fetchone()[0] == 5
        cursor.execute(f"SELECT count(*) FROM {settings.SEGMENT_SCHEMA_LIVE}.border_crossing")
        assert cursor.fetchone()[0] == 1
    assert ValhallaUpstream.objects.count() == 3
    assert DriftReport.objects.count() == 1
    build_id = ValhallaUpstream.objects.get(variant="standard").build_id
    assert os.readlink(root / "tiles" / "standard" / "current") == build_id
    assert len(binaries.commands("valhalla_build_tiles")) == 3
    assert len(binaries.commands("valhalla_service")) == 4, "three grade reads and one tag read"
    assert (root / "elevation" / "N38" / "N38W078.hgt").is_file()


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_that_cannot_start_records_the_failure_and_is_not_retried(
    rebuild_environment, monkeypatch
) -> None:
    """The row is for the alert that notices nothing has succeeded lately.
    Whether this attempt failed is Procrastinate's question, so the error goes
    back to it - but as RebuildAbandoned, which the retry strategy does not
    retry, because a missing extract is the same on the fifth attempt."""
    from core.models import ScheduledRun

    root, _binaries = rebuild_environment
    monkeypatch.setattr(settings, "REBUILD_SOURCE_PBF", root / "absent.osm.pbf")

    with pytest.raises(RebuildAbandoned, match="source extract missing"):
        app.tasks["weekly_rebuild"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded
    assert "source extract missing" in run.detail


def job(attempts: int) -> Job:
    return Job(
        queue="rebuild",
        lock=None,
        queueing_lock="weekly_rebuild",
        task_name="weekly_rebuild",
        task_kwargs={},
        attempts=attempts,
    )


def test_jobs_are_retried_with_exponential_backoff_up_to_five_times() -> None:
    """The plan's rule, asserted as the schedule the strategy produces rather
    than as the constants it was built from. Procrastinate increments
    `attempts` after the retry decision (in finish_job and retry_job, never in
    fetch), so the first failure is judged at attempts=0 and the sixth at
    attempts=5: one run, five retries, each wait six times the last."""
    from pipeline.rebuild import RebuildFailed, Stage

    transient = RebuildFailed(Stage.FETCH_EXTRACT, OSError("connection reset"))
    for name in ("weekly_rebuild", "nightly_backup", "membership_sweep"):
        strategy = app.tasks[name].retry_strategy
        assert strategy is not None, f"{name} is never retried"
        waits = []
        for finished_runs in range(0, 8):
            asked_at = timezone.now()
            decision = strategy.get_retry_decision(exception=transient, job=job(finished_runs))
            if decision is None:
                break
            waits.append(round((decision.retry_at - asked_at).total_seconds()))
        assert waits == [6, 36, 216, 1296, 7776], f"{name}: {waits}"
        assert finished_runs == 5, f"{name}: retrying stopped after {finished_runs} runs, not 5"
        assert sum(waits) < 3 * 60 * 60, "every retry lands within the same morning"


def test_a_rebuild_abandoned_for_a_terminal_cause_is_not_retried() -> None:
    """Validation, missing reference data and the disk gate are the same on
    the fifth attempt as on the first; retrying them is thirty hours of CPU for
    the same alert."""
    strategy = app.tasks["weekly_rebuild"].retry_strategy
    abandoned = RebuildAbandoned("rebuild failed at stage validate: ...")
    assert strategy.get_retry_decision(exception=abandoned, job=job(0)) is None


# --- Startability: a cold worker, as compose runs it ----------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_cold_worker_runs_a_deferred_job() -> None:
    """The worker process as compose starts it, in a subprocess with no Django
    set up by anything but the command itself, against this test's database:
    the schema has to be there from migrate, the app has to resolve, the task
    has to be registered, and the job has to reach the ORM without
    AppRegistryNotReady. The membership sweep is the job because it is the
    cheapest one that touches the database and writes a run row."""
    from procrastinate.contrib.django.models import ProcrastinateJob

    from core.models import ScheduledRun

    job_id = app.tasks["membership_sweep"].defer(timestamp=0)

    env = {
        **os.environ,
        "PGDATABASE": connection.settings_dict["NAME"],
        "DJANGO_SETTINGS_MODULE": "config.settings",
    }
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "procrastinate",
            "worker",
            "--one-shot",
            "--queues=maintenance",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]

    assert ProcrastinateJob.objects.get(id=job_id).status == "succeeded", result.stderr[-3000:]
    run = ScheduledRun.objects.get(task="membership_sweep")
    assert run.succeeded
    assert run.detail.startswith("purged ")


# --- Timeouts, enforced ---------------------------------------------------------------


def test_the_time_budgets_are_the_plans() -> None:
    assert REBUILD_TIMEOUT_S == 6 * 60 * 60
    assert SWEEP_TIMEOUT_S == 30 * 60


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_past_its_budget_is_abandoned_at_the_next_stage(
    rebuild_environment, monkeypatch
) -> None:
    from core.models import ScheduledRun

    monkeypatch.setattr("config.procrastinate.REBUILD_TIMEOUT_S", 0)
    with pytest.raises(RebuildAbandoned, match="time budget"):
        app.tasks["weekly_rebuild"].func(timestamp=0)
    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded and "time budget" in run.detail


def test_a_binary_is_killed_when_the_budget_runs_out() -> None:
    """A wedged valhalla_build_tiles is killed by the rebuild's own deadline
    rather than left for the eight-day alarm."""
    from pipeline.run import _run_command

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command(["sleep", "30"], deadline=time.monotonic() + 0.3)
    assert time.monotonic() - started < 5

    from pipeline.rebuild import RebuildTimedOut

    with pytest.raises(RebuildTimedOut):
        _run_command(["sleep", "30"], deadline=time.monotonic() - 1)


@pytest.mark.django_db
def test_a_sweep_past_its_budget_fails_the_job(monkeypatch) -> None:
    from core.models import ScheduledRun
    from core.runs import TaskTimedOut

    def slow_sweep(now=None):
        time.sleep(3)
        return 0, 0

    monkeypatch.setattr("core.membership.sweep_memberships", slow_sweep)
    monkeypatch.setattr("config.procrastinate.SWEEP_TIMEOUT_S", 0.2)

    started = time.monotonic()
    with pytest.raises(TaskTimedOut, match="membership_sweep exceeded"):
        app.tasks["membership_sweep"].func(timestamp=0)
    assert time.monotonic() - started < 2
    assert not ScheduledRun.objects.get(task="membership_sweep").succeeded


# --- The degraded-guild mark, and the sweep it rides beside ---------------------------


@pytest.mark.django_db
class TestTheDegradedGuildSweep:
    """`mark_degraded_guilds` was the transition `should_mark_degraded` and
    `degraded_window` were written for and never had - two correct predicates
    called from nowhere, so `ConfiguredGuild.state` was written by nothing and
    no guild could ever leave `active`.

    Registering it is not enough, because it fails closed on silence. On a
    deployment whose bot has not been built - which is this one - it would mark
    every guild degraded on its first tick and lapse the deployment's standing
    72 hours later, for an outage that never happened. So the gate is part of
    the wiring and is tested with it.
    """

    def guild(self, guild_id: int = 900):
        from core.models import ConfiguredGuild

        return ConfiguredGuild.objects.create(guild_id=guild_id, name="Club")

    def heartbeat(self, age: timedelta):
        from core.models import ScheduledRun
        from core.revocation import GATEWAY_HEARTBEAT_TASK

        now = timezone.now()
        return ScheduledRun.objects.create(
            task=GATEWAY_HEARTBEAT_TASK,
            started_at=now - age,
            finished_at=now - age,
            succeeded=True,
        )

    def run_task(self):
        from core.models import ScheduledRun

        app.tasks["degraded_guild_sweep"].func(timestamp=0)
        return ScheduledRun.objects.filter(task="degraded_guild_sweep").latest("started_at")

    def test_the_schedule_is_inside_the_bound_it_enforces(self) -> None:
        """Derived from the cron rather than restated beside it: the mark is
        bounded by GATEWAY_ALERT_AFTER, and a guild marked an hour late carries
        an hour of stale grants the plan's single 72-hour number does not allow
        for. The six-hourly sweep is not this schedule."""
        from croniter import croniter

        from core.revocation import GATEWAY_ALERT_AFTER

        base = timezone.now()

        def interval(cron: str) -> timedelta:
            iterator = croniter(cron, base)
            first = iterator.get_next(type(base))
            return iterator.get_next(type(base)) - first

        assert interval(DEGRADED_GUILD_SWEEP_CRON) <= GATEWAY_ALERT_AFTER
        assert interval(DEGRADED_GUILD_SWEEP_CRON) < interval(MEMBERSHIP_SWEEP_CRON)

    def test_no_guild_is_touched_until_the_gateway_has_ever_reported(self) -> None:
        """Nothing writes the heartbeat on this deployment, so an ungated task
        would revoke every guild's standing on a five-minute schedule."""
        guild = self.guild()
        run = self.run_task()

        guild.refresh_from_db()
        assert guild.state == "active", "a bot that was never built is not a bot that went silent"
        assert guild.standing_valid_until is None
        assert "waiting for the gateway" in run.detail

    def test_a_gateway_silent_past_the_bound_marks_guilds_degraded(self) -> None:
        """Once the heartbeat exists at all, silence is the outage the window
        is for, and the window runs from the alert rather than from now."""
        from core.revocation import DEGRADED_WINDOW, GATEWAY_ALERT_AFTER

        guild = self.guild()
        beat = self.heartbeat(timedelta(hours=2))
        run = self.run_task()

        guild.refresh_from_db()
        assert guild.state == "degraded"
        expected = beat.started_at + GATEWAY_ALERT_AFTER + DEGRADED_WINDOW
        assert abs(guild.standing_valid_until - expected) < timedelta(seconds=1)
        assert "marked 1 guilds degraded" in run.detail

    def test_a_fresh_heartbeat_marks_nothing(self) -> None:
        guild = self.guild()
        self.heartbeat(timedelta(seconds=30))
        run = self.run_task()

        guild.refresh_from_db()
        assert guild.state == "active"
        assert "marked 0 guilds degraded" in run.detail

    def test_it_is_not_retried_because_the_next_tick_is_the_retry(self) -> None:
        """A retry schedule would hold the queueing lock across several ticks
        of a five-minute bound, which is the opposite of what the bound wants."""
        assert app.tasks["degraded_guild_sweep"].retry_strategy is None


@pytest.mark.django_db(transaction=True)
def test_the_membership_sweep_also_drops_dead_session_rows() -> None:
    """`sweep_sessions` had no caller: rows for banned and deleted accounts,
    and rows whose Django session had already gone, sat in the table naming who
    was signed in and when for someone who asked to be forgotten. The middleware
    only ever reaches a row when a request carries the matching cookie, so an
    orphan is never looked at again and never deleted.

    Also the detail string. "purged N never-signed-in rows" stopped being true
    when the purge started counting rows dropped for deleted and tombstoned
    accounts, which go on sight rather than after thirty days.

    `transaction=True` because both sweeps run inside `run_with_deadline`, on
    their own thread and their own connection, which is where the task's time
    budget is enforced - a rolled-back test transaction is invisible to them.
    """
    from core.models import ScheduledRun, Session, User

    now = timezone.now()
    user = User.objects.create(discord_user_id=77)
    # No Django session row was ever created for this key, so it is orphaned.
    Session.objects.create(
        session_key="orphan",
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )

    app.tasks["membership_sweep"].func(timestamp=0)

    assert not Session.objects.filter(session_key="orphan").exists()
    detail = ScheduledRun.objects.get(task="membership_sweep").detail
    assert "1 session rows" in detail
    assert "never-signed-in rows" not in detail.replace("forgotten and never-signed-in rows", "")
    assert "forgotten and never-signed-in rows" in detail


# --- The backup ------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_backup_excludes_the_sessions_and_the_membership_cache(monkeypatch, tmp_path) -> None:
    """A real pg_dump of this test's database, read back with pg_restore --list
    the way the task reads it. The membership cache is excluded because who
    organizes with whom is the sensitive part; the sessions because a dump that
    sits on disk for months must not carry live ones. The reviewer's own check
    was `pg_restore --list | grep app_session`, and it found the table."""
    from config.procrastinate import perform_backup
    from core.models import ScheduledRun

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    destination = perform_backup()
    assert destination.parent == tmp_path / "backups"
    assert destination.suffix == ".dump"

    listing = subprocess.run(
        ["pg_restore", "--list", str(destination)], capture_output=True, text=True, check=True
    ).stdout
    data_entries = [line for line in listing.splitlines() if "TABLE DATA" in line]
    assert any("app_user" in line for line in data_entries), "the dump carries the users"
    assert not any("app_session" in line for line in data_entries)
    assert not any("cached_membership" in line for line in data_entries)

    app.tasks["nightly_backup"].func(timestamp=0)
    assert ScheduledRun.objects.get(task="nightly_backup").succeeded


@pytest.mark.django_db(transaction=True)
def test_the_task_itself_refuses_a_dump_whose_listing_leaks(monkeypatch, tmp_path) -> None:
    """Verification is production behaviour, not a test-side check: handed a
    table of contents that carries session data, perform_backup raises and
    the run row records a failure rather than a success."""
    from config.procrastinate import BackupVerificationFailed, perform_backup

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    def leaking_listing(archive, env):
        assert archive.exists(), "the dump is written before it is verified"
        return "1; 0 1 TABLE DATA public app_user r\n2; 0 2 TABLE DATA public app_session r\n"

    with pytest.raises(BackupVerificationFailed, match="app_session"):
        perform_backup(read_listing=leaking_listing)


def test_the_verification_refuses_a_dump_that_carries_what_it_must_not() -> None:
    from config.procrastinate import BackupVerificationFailed

    good = (
        "1234; 0 5678 TABLE DATA public app_user routemaker\n"
        "1235; 0 5679 TABLE DATA public jurisdiction routemaker\n"
    )
    assert verify_dump_listing(good) == ["public.app_user", "public.jurisdiction"]
    with pytest.raises(BackupVerificationFailed, match="app_session"):
        verify_dump_listing(good + "1236; 0 5680 TABLE DATA public app_session routemaker\n")
    with pytest.raises(BackupVerificationFailed, match="no table data"):
        verify_dump_listing("1; 0 0 ENCODING - ENCODING\n")


# --- Alerting --------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_alert_reads_the_absence_of_a_recent_success() -> None:
    """A rebuild that stopped being scheduled emits no error at all, so an alert
    built on errors stays silent through exactly the outage it exists for."""
    from core.models import ScheduledRun
    from core.runs import stale_tasks

    now = timezone.now()
    assert set(stale_tasks(now)) == {"weekly_rebuild", "nightly_backup", "membership_sweep"}

    for task in ("weekly_rebuild", "nightly_backup", "membership_sweep"):
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(hours=1), finished_at=now, succeeded=True
        )
    assert stale_tasks(now) == []

    # A failure is not a success, and neither is an old one.
    ScheduledRun.objects.filter(task="weekly_rebuild").update(succeeded=False)
    assert stale_tasks(now) == ["weekly_rebuild"]


def test_rebuild_timeout_is_shorter_than_its_alert_window() -> None:
    """A hung rebuild should be caught by its own timeout, not left for the
    weekly 'nothing completed' alarm to notice eight days later."""
    from core.runs import STALE_AFTER

    assert REBUILD_TIMEOUT_S < STALE_AFTER["weekly_rebuild"]
    assert STALE_AFTER["weekly_rebuild"] == REBUILD_ALERT_AFTER_S


def test_each_alert_window_is_wider_than_its_schedule() -> None:
    """Otherwise the alert fires on its own cadence rather than on a failure.

    Derived from the cron expressions rather than restated, which is what the
    earlier version of this test got wrong: it compared a constant against
    another constant three lines above it in the same file.
    """
    from croniter import croniter

    from core.runs import STALE_AFTER

    crons = {
        "weekly_rebuild": WEEKLY_REBUILD_CRON,
        "nightly_backup": NIGHTLY_BACKUP_CRON,
        "membership_sweep": MEMBERSHIP_SWEEP_CRON,
    }
    base = timezone.now()
    for task, cron in crons.items():
        iterator = croniter(cron, base)
        first = iterator.get_next(type(base))
        second = iterator.get_next(type(base))
        interval = (second - first).total_seconds()
        assert STALE_AFTER[task] > interval, f"{task} alerts on its own schedule"


def test_rebuild_is_scheduled_off_peak() -> None:
    """It takes half the cores and widens the latency alerts while it runs."""
    minute, hour, _dom, _month, _dow = WEEKLY_REBUILD_CRON.split()
    assert minute == "0"
    assert 6 <= int(hour) <= 10, "08:00 UTC is early morning locally"

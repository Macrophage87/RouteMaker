"""The periodic tasks the worker actually runs.

The previous version of this file asserted the cron strings and nothing else.
No task was registered anywhere - `config.procrastinate` defined an App, four
constants and zero `@app.task` - while compose ran a worker against it, so the
weekly rebuild, the nightly backup and the six-hourly sweep were never scheduled
and the strings were decoration. Constants restated as assertions are how that
passed for a scheduling test.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from config.procrastinate import (
    MEMBERSHIP_SWEEP_CRON,
    NIGHTLY_BACKUP_CRON,
    REBUILD_TIMEOUT_S,
    WEEKLY_REBUILD_CRON,
    app,
)

REBUILD_ALERT_AFTER_S = 8 * 24 * 60 * 60


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
    }


def test_the_rebuild_cannot_run_twice_at_once() -> None:
    """Two concurrent rebuilds would write the same staging schema and the same
    tile directory."""
    rebuild = app.tasks["weekly_rebuild"]
    assert rebuild.queueing_lock == "weekly_rebuild"
    assert rebuild.queue == "rebuild", "a six-hour build must not sit in front of the sweep"


def test_the_maintenance_tasks_share_a_queue_away_from_the_rebuild() -> None:
    for name in ("nightly_backup", "membership_sweep"):
        assert app.tasks[name].queue == "maintenance"
        assert app.tasks[name].queueing_lock == name


@pytest.mark.django_db
def test_the_rebuild_task_runs_the_rebuild_and_records_it(monkeypatch, tmp_path) -> None:
    """Registered is not the same as wired. This runs the registered callable and
    asserts it reached run_rebuild with handlers built from the configured
    paths."""
    from core.models import ScheduledRun

    seen = {}

    def fake_run_rebuild(handlers, skip=frozenset()):
        seen["handlers"] = handlers
        return None

    monkeypatch.setattr("pipeline.rebuild.run_rebuild", fake_run_rebuild)
    monkeypatch.setattr("django.conf.settings.REBUILD_SOURCE_PBF", tmp_path / "source.osm.pbf")
    monkeypatch.setattr("django.conf.settings.REBUILD_WORK_DIR", tmp_path / "work")
    monkeypatch.setattr("django.conf.settings.REBUILD_REFERENCE_DIR", tmp_path / "reference")

    app.tasks["weekly_rebuild"].func(timestamp=0)

    assert seen["handlers"], "the task built no handlers"
    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert run.succeeded and run.finished_at is not None


@pytest.mark.django_db
def test_a_failing_task_records_the_failure_and_re_raises(monkeypatch, tmp_path) -> None:
    """The row is for the alert that notices nothing has succeeded lately.
    Whether this attempt failed is Procrastinate's question, so the error goes
    back to it rather than being swallowed here."""
    from core.models import ScheduledRun

    def explode(handlers, skip=frozenset()):
        raise RuntimeError("tile build died")

    monkeypatch.setattr("pipeline.rebuild.run_rebuild", explode)
    monkeypatch.setattr("django.conf.settings.REBUILD_SOURCE_PBF", tmp_path / "source.osm.pbf")
    monkeypatch.setattr("django.conf.settings.REBUILD_WORK_DIR", tmp_path / "work")
    monkeypatch.setattr("django.conf.settings.REBUILD_REFERENCE_DIR", tmp_path / "reference")

    with pytest.raises(RuntimeError, match="tile build died"):
        app.tasks["weekly_rebuild"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded
    assert "tile build died" in run.detail


@pytest.mark.django_db
def test_the_backup_excludes_the_membership_cache(monkeypatch, tmp_path) -> None:
    """Excluded rather than dumped and protected: who organizes with whom is the
    sensitive part, and the cache is rebuildable from the bot's backfill."""
    from config.procrastinate import perform_backup
    from core.models import ScheduledRun

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return None

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("django.conf.settings.BACKUP_DIR", tmp_path / "backups")

    destination = perform_backup()
    assert "--exclude-table-data=*.cached_membership" in captured["argv"]
    assert destination.parent == tmp_path / "backups"
    assert destination.suffix == ".dump"

    app.tasks["nightly_backup"].func(timestamp=0)
    assert ScheduledRun.objects.get(task="nightly_backup").succeeded


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

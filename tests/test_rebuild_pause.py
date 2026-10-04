"""OWNER-DECISIONS 355: the weekly rebuild can be paused with WEEKLY_REBUILD_PAUSED.

Paused, the scheduled run logs and returns before it reads or writes anything; a
rebuild fired by hand (`run_rebuild_now`, which defers with `manual=True`) still runs.
No database: the first thing an unpaused run does is `jobs_in_flight`, which is stood
in for here by a sentinel that proves the run went on.
"""

from __future__ import annotations

import importlib
import inspect
import logging

import pytest

from config import procrastinate as tasks


class WentOn(Exception):
    """Raised by the stand-in for the first thing an unpaused rebuild does."""


@pytest.fixture
def went_on(monkeypatch):
    import core.runs

    def first_step(*args, **kwargs):
        raise WentOn

    monkeypatch.setattr(core.runs, "jobs_in_flight", first_step)
    monkeypatch.setattr(core.runs, "record", first_step)


@pytest.mark.django_db
def test_paused_the_scheduled_run_logs_writes_a_paused_row_and_builds_nothing(
    settings, went_on, caplog
) -> None:
    from core.models import ScheduledRun
    from core.runs import PAUSED_DETAIL

    settings.WEEKLY_REBUILD_PAUSED = True
    with caplog.at_level(logging.WARNING, logger="config.procrastinate"):
        assert tasks.weekly_rebuild(timestamp=0) is None
    assert "weekly rebuild paused (WEEKLY_REBUILD_PAUSED)" in caplog.text
    rows = list(ScheduledRun.objects.filter(task="weekly_rebuild"))
    assert [(r.succeeded, r.detail, r.finished_at is not None) for r in rows] == [
        (False, PAUSED_DETAIL, True)
    ]
    assert "paused" in str(rows[0])


@pytest.mark.django_db
def test_a_paused_rebuild_is_reported_paused_not_stale(settings, monkeypatch) -> None:
    """The release re-check's S-A probe: the last success nine days ago, then a paused
    tick. Not stale (no alert), and listed as paused; stale again eight days after the
    last paused tick."""
    from datetime import timedelta

    from django.utils import timezone
    from test_operations import deployment_up_since

    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, paused_task_details, stale_tasks

    deployment_up_since(timedelta(days=90))
    now = timezone.now()
    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    ScheduledRun.objects.filter(task="weekly_rebuild").update(
        started_at=now - timedelta(days=9, hours=1), finished_at=now - timedelta(days=9)
    )
    assert "weekly_rebuild" in stale_tasks(), "the premise: nine days without a rebuild is stale"
    settings.WEEKLY_REBUILD_PAUSED = True
    tasks.weekly_rebuild(timestamp=0)  # the paused Tuesday tick
    assert "weekly_rebuild" not in stale_tasks()
    assert [p["task"] for p in paused_task_details()] == ["weekly_rebuild"]
    # A pause whose ticks stopped: stale again past the window.
    assert "weekly_rebuild" in stale_tasks(now + timedelta(days=9))
    assert paused_task_details(now + timedelta(days=9)) == []


def test_paused_a_hand_fired_rebuild_still_runs(settings, went_on) -> None:
    settings.WEEKLY_REBUILD_PAUSED = True
    with pytest.raises(WentOn):
        tasks.weekly_rebuild(timestamp=0, manual=True)


def test_not_paused_the_scheduled_run_goes_on(settings, went_on, caplog) -> None:
    settings.WEEKLY_REBUILD_PAUSED = False
    with pytest.raises(WentOn):
        tasks.weekly_rebuild(timestamp=0)
    assert "paused" not in caplog.text


@pytest.mark.parametrize(
    ("value", "paused"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        (" 1 ", True),
        ("", False),
        ("0", False),
        ("false", False),
        ("yes", False),
    ],
)
def test_the_switch_reads_1_or_true(monkeypatch, value, paused) -> None:
    monkeypatch.setenv("WEEKLY_REBUILD_PAUSED", value)
    import config.settings as settings_module

    reloaded = importlib.reload(settings_module)
    try:
        assert reloaded.WEEKLY_REBUILD_PAUSED is paused
    finally:
        monkeypatch.delenv("WEEKLY_REBUILD_PAUSED")
        importlib.reload(settings_module)


def test_run_rebuild_now_defers_a_manual_job_and_the_schedule_is_unchanged() -> None:
    from core.management.commands import run_rebuild_now

    assert "rebuild.defer(timestamp=int(time.time()), manual=True)" in inspect.getsource(
        run_rebuild_now
    )
    assert tasks.WEEKLY_REBUILD_CRON == "0 8 * * 2"

"""Worker schedules and timeouts."""

from __future__ import annotations

from config.procrastinate import (
    MEMBERSHIP_SWEEP_CRON,
    NIGHTLY_BACKUP_CRON,
    REBUILD_TIMEOUT_S,
    WEEKLY_REBUILD_CRON,
)

REBUILD_ALERT_AFTER_S = 8 * 24 * 60 * 60
BACKUP_ALERT_AFTER_S = 26 * 60 * 60


def test_rebuild_timeout_is_shorter_than_its_alert_window() -> None:
    """A hung rebuild should be caught by its own timeout, not left for the
    weekly 'nothing completed' alarm to notice eight days later."""
    assert REBUILD_TIMEOUT_S < REBUILD_ALERT_AFTER_S


def test_backup_runs_more_often_than_its_alert_window() -> None:
    """A 26-hour alert window needs a daily backup; anything sparser alerts on
    its own schedule rather than on a failure."""
    assert NIGHTLY_BACKUP_CRON.startswith("0 7 * * *")
    assert BACKUP_ALERT_AFTER_S > 24 * 60 * 60


def test_membership_sweep_is_the_backstop_not_the_mechanism() -> None:
    """Revocation lands in seconds through the gateway. The sweep exists to catch
    what the gateway missed, so six-hourly is a backstop interval rather than a
    staleness bound."""
    assert MEMBERSHIP_SWEEP_CRON == "0 */6 * * *"


def test_rebuild_is_scheduled_off_peak() -> None:
    """It takes half the cores and widens the latency alerts while it runs."""
    minute, hour, _dom, _month, _dow = WEEKLY_REBUILD_CRON.split()
    assert minute == "0"
    assert 6 <= int(hour) <= 10, "08:00 UTC is early morning locally"

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.revocation import (
    ABSOLUTE_SESSION_LIFETIME,
    DEGRADED_WINDOW,
    GATEWAY_ALERT_AFTER,
    IDLE_SESSION_LIFETIME,
    SessionRecord,
    degraded_window,
    should_mark_degraded,
    tombstone,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def session(**kwargs) -> SessionRecord:
    return SessionRecord(
        key=kwargs.pop("key", "abc"),
        user_id=kwargs.pop("user_id", 1),
        issued_epoch=kwargs.pop("issued_epoch", 1),
        created_at=kwargs.pop("created_at", NOW - timedelta(days=1)),
        last_seen_at=kwargs.pop("last_seen_at", NOW - timedelta(minutes=1)),
    )


class TestSessionEpoch:
    def test_bumping_the_epoch_invalidates_the_session(self) -> None:
        """One write revokes that user's sessions and nobody else's. Django's
        session table has no user column, so without this the only global lever
        is rotating the secret key, which signs everybody out."""
        assert session().is_valid(current_epoch=1, now=NOW)
        assert not session().is_valid(current_epoch=2, now=NOW)

    def test_absolute_lifetime_is_enforced(self) -> None:
        """Django implements idle expiry natively but not an absolute cap."""
        old = session(created_at=NOW - ABSOLUTE_SESSION_LIFETIME - timedelta(hours=1))
        assert not old.is_valid(current_epoch=1, now=NOW)

    def test_idle_lifetime_is_enforced(self) -> None:
        idle = session(last_seen_at=NOW - IDLE_SESSION_LIFETIME - timedelta(hours=1))
        assert not idle.is_valid(current_epoch=1, now=NOW)


class TestTombstone:
    def test_tombstone_is_keyed(self) -> None:
        """A Discord id has an enumerable candidate set, so an unkeyed hash gives
        no privacy against anyone holding a dump."""
        a = tombstone(123456789, key=b"secret-one")
        b = tombstone(123456789, key=b"secret-two")
        assert a != b

    def test_tombstone_is_stable_for_ban_enforcement(self) -> None:
        key = b"secret"
        assert tombstone(123456789, key) == tombstone(123456789, key)

    def test_unkeyed_tombstone_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unkeyed hash is reversible"):
            tombstone(123456789, key=b"")


class TestDegradedWindow:
    def test_window_runs_from_the_alert_not_from_a_grace_period(self) -> None:
        """Stacking two windows would leave the deployment carrying stale grants
        for twice as long as a single lost guild does."""
        assert degraded_window(NOW) == NOW + DEGRADED_WINDOW

    def test_mark_uses_the_same_threshold_as_the_alert(self) -> None:
        assert should_mark_degraded(NOW - GATEWAY_ALERT_AFTER, NOW)
        assert not should_mark_degraded(NOW - GATEWAY_ALERT_AFTER + timedelta(seconds=1), NOW)

    def test_maximum_stale_grant_is_one_window_not_two(self) -> None:
        """72 hours from the alert, everywhere, and that is the only number."""
        from core.standing import MAX_STALE_GRANT

        lapses_at = degraded_window(NOW)
        assert lapses_at - NOW == MAX_STALE_GRANT

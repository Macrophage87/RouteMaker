from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.membership import (
    PURGE_NEVER_SIGNED_IN_AFTER,
    GatewayEvent,
    apply_event,
    should_purge,
    sweep_priority,
)
from core.standing import Membership

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
GUILD = 1000


def row(**kwargs) -> Membership:
    return Membership(
        guild_id=kwargs.pop("guild_id", GUILD),
        role_ids=kwargs.pop("role_ids", frozenset({7})),
        last_confirmed=kwargs.pop("last_confirmed", NOW - timedelta(minutes=5)),
        **kwargs,
    )


def test_role_change_updates_the_cache() -> None:
    event = GatewayEvent("update", GUILD, 1, role_ids=frozenset({8, 9}))
    updated = apply_event(row(), event, NOW)
    assert updated.role_ids == frozenset({8, 9})
    assert updated.last_confirmed == NOW


def test_removal_marks_rather_than_deletes() -> None:
    """Deleting outright makes a removal indistinguishable from a row that was
    never there, and the two carry different windows."""
    removed = apply_event(row(), GatewayEvent("remove", GUILD, 1), NOW)
    assert removed is not None
    assert removed.removed_at == NOW


def test_removal_ends_standing_immediately() -> None:
    """The earlier version asserted the row stayed usable for fifteen minutes,
    which locked in a window long enough to enumerate the club's routes."""
    removed = apply_event(row(), GatewayEvent("remove", GUILD, 1), NOW)
    assert not removed.is_usable(NOW)


def test_removal_does_not_refresh_the_row_age_clock() -> None:
    """Stamping last_confirmed on a removal extended the row's life against the
    staleness backstop - a removal event lengthening the grant it revokes."""
    old = row(last_confirmed=NOW - timedelta(hours=71))
    removed = apply_event(old, GatewayEvent("remove", GUILD, 1), NOW)
    assert removed.last_confirmed == old.last_confirmed


def test_an_unknown_event_kind_is_refused_not_treated_as_an_add() -> None:
    """The failure direction of an unrecognised event must not be granting
    membership, in a module whose rule is that absence is absence of standing."""
    with pytest.raises(ValueError, match="unknown gateway event kind"):
        apply_event(None, GatewayEvent("GUILD_MEMBER_REMOVE", GUILD, 1), NOW)


def test_rejoining_clears_a_prior_removal() -> None:
    removed = apply_event(row(), GatewayEvent("remove", GUILD, 1), NOW)
    rejoined = apply_event(removed, GatewayEvent("add", GUILD, 1, frozenset({7})), NOW)
    assert rejoined.removed_at is None
    assert rejoined.is_usable(NOW)


def test_pending_member_is_recorded_as_pending() -> None:
    """Catches long-standing members who joined before a server's rules gate
    existed, so the denial can say so rather than reading as a broken site."""
    pending = apply_event(None, GatewayEvent("add", GUILD, 1, pending=True), NOW)
    assert pending.pending
    assert not pending.is_usable(NOW)


def test_rows_for_people_who_never_signed_in_are_purged() -> None:
    """Who organizes with whom is the sensitive part, so the cache does not
    accumulate a roster of people who never touched the application."""
    old = row(last_confirmed=NOW - PURGE_NEVER_SIGNED_IN_AFTER - timedelta(days=1))
    assert should_purge(old, has_ever_signed_in=False, now=NOW)
    assert not should_purge(old, has_ever_signed_in=True, now=NOW)


def test_degraded_sweep_prioritises_active_sessions() -> None:
    """The budget runs out, so ordering decides who keeps working; staleness is
    noticed first by the people currently using the site."""
    idle = row(last_confirmed=NOW - timedelta(hours=1))
    active = row(last_confirmed=NOW - timedelta(hours=2))
    ordered = sweep_priority([(idle, False), (active, True)])
    assert ordered[0] is active

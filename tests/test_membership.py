from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

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


# The gateway path end to end: event in, row written, permission resolved. Until
# `record_event` existed, `apply_event` returned a dataclass to a caller that did
# not exist, nothing anywhere wrote a CachedMembership row, and the table
# `attach_standing` reads was filled by nothing - so "a role removed in Discord
# revokes the matching application permission" had no path from one end to the
# other and no way to be tested.


@pytest.fixture
def guild(db):
    from core.models import ConfiguredGuild, RoleMapping

    configured = ConfiguredGuild.objects.create(guild_id=GUILD, name="DCBP")
    RoleMapping.objects.create(
        guild=configured, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN
    )
    RoleMapping.objects.create(
        guild=configured, role_id=8, permission=RoleMapping.Permission.REVIEWER
    )
    return configured


@pytest.fixture
def member(db):
    from core.models import User

    return User.objects.create(discord_user_id=1)


@pytest.mark.django_db
def test_a_gateway_event_becomes_a_cached_row(guild) -> None:
    from core.membership import record_event
    from core.models import CachedMembership

    now = timezone.now()
    record_event(GatewayEvent("add", GUILD, 1, role_ids=frozenset({7})), now)

    row = CachedMembership.objects.get(discord_user_id=1, guild=guild)
    assert row.role_ids == [7]
    assert row.removed_at is None
    assert row.last_confirmed == now


@pytest.mark.django_db
def test_a_role_removed_in_discord_revokes_the_application_permission(guild, member) -> None:
    """The plan's assertion, which nothing could exercise before.

    The role is dropped by an update event carrying the remaining roles, which is
    the shape Discord sends: there is no "role removed" event.
    """
    from core.auth_backend import attach_standing
    from core.membership import record_event

    now = timezone.now()
    record_event(GatewayEvent("add", GUILD, 1, role_ids=frozenset({7})), now)
    attach_standing(member, now)
    assert member._admin_guild_ids == frozenset({GUILD})
    assert member.is_staff

    record_event(GatewayEvent("update", GUILD, 1, role_ids=frozenset()), now)
    attach_standing(member, now)
    assert member._admin_guild_ids == frozenset()
    assert member._member_guild_ids == frozenset({GUILD}), "still a member, just not an admin"


@pytest.mark.django_db
def test_leaving_the_guild_revokes_standing_entirely(guild, member) -> None:
    from core.auth_backend import attach_standing
    from core.membership import record_event
    from core.models import CachedMembership

    now = timezone.now()
    record_event(GatewayEvent("add", GUILD, 1, role_ids=frozenset({8})), now)
    record_event(GatewayEvent("remove", GUILD, 1), now)

    row = CachedMembership.objects.get(discord_user_id=1)
    assert row.removed_at == now, (
        "marked rather than deleted, so the grace runs from a known instant"
    )

    attach_standing(member, now)
    assert member._member_guild_ids == frozenset()
    assert member._reviewer_guild_ids == frozenset()


@pytest.mark.django_db
def test_a_guild_the_deployment_has_not_configured_caches_nothing() -> None:
    """A guild the bot is in but that is not configured is the admission control.
    Caching it would build a roster of a server that has not asked to be here."""
    from core.membership import record_event
    from core.models import CachedMembership

    assert record_event(GatewayEvent("add", 999999, 1, role_ids=frozenset({7}))) is None
    assert not CachedMembership.objects.exists()


@pytest.mark.django_db
def test_a_removal_for_someone_with_no_row_creates_none(guild) -> None:
    """Creating one to mark it removed would turn "never a member" into "was"."""
    from core.membership import record_event
    from core.models import CachedMembership

    assert record_event(GatewayEvent("remove", GUILD, 1)) is None
    assert not CachedMembership.objects.exists()


@pytest.mark.django_db
def test_the_sweep_purges_rows_for_people_who_never_signed_in(guild) -> None:
    from core.membership import sweep_memberships
    from core.models import CachedMembership

    now = timezone.now()
    stale = now - PURGE_NEVER_SIGNED_IN_AFTER - timedelta(days=1)
    CachedMembership.objects.create(discord_user_id=1, guild=guild, last_confirmed=stale)
    CachedMembership.objects.create(discord_user_id=2, guild=guild, last_confirmed=now)

    purged, _departed = sweep_memberships(now)
    assert purged == 1
    assert list(CachedMembership.objects.values_list("discord_user_id", flat=True)) == [2]


@pytest.mark.django_db
def test_the_sweep_keeps_rows_for_people_who_have_signed_in(guild) -> None:
    """The purge is about not holding a roster of people who never touched the
    site. Someone who has signed in is a user of it, however long ago."""
    from core.membership import sweep_memberships
    from core.models import CachedMembership, User

    now = timezone.now()
    User.objects.create(discord_user_id=1, last_login=now - timedelta(days=200))
    CachedMembership.objects.create(
        discord_user_id=1,
        guild=guild,
        last_confirmed=now - PURGE_NEVER_SIGNED_IN_AFTER - timedelta(days=1),
    )

    purged, departed = sweep_memberships(now)
    assert (purged, departed) == (0, 0)
    assert CachedMembership.objects.count() == 1


@pytest.mark.django_db
def test_the_sweep_leaves_a_stale_row_for_a_current_member_alone(guild, member) -> None:
    """Sweeping these reads as tidiness and is a revocation bug.

    The bot confirms a row when an event arrives, and a member whose roles have
    not changed generates no events, so every quiet member's row ages past the
    ceiling within three days. Deleting it leaves nothing for a reconfirmation to
    refresh and drops that member's standing until they happen to change a role.
    Staleness belongs where attach_standing already handles it: the row stays and
    grants nothing until the bot reconfirms it.
    """
    from core.auth_backend import attach_standing
    from core.membership import sweep_memberships
    from core.models import CachedMembership, User
    from core.standing import MAX_ROW_AGE

    now = timezone.now()
    User.objects.filter(pk=member.pk).update(last_login=now)
    stale = now - MAX_ROW_AGE - timedelta(minutes=1)
    CachedMembership.objects.create(
        discord_user_id=1, guild=guild, role_ids=[7], last_confirmed=stale
    )

    assert sweep_memberships(now) == (0, 0)
    assert CachedMembership.objects.count() == 1, "the row a reconfirmation would refresh"

    attach_standing(member, now)
    assert member._member_guild_ids == frozenset(), "and it grants nothing while stale"


@pytest.mark.django_db
def test_the_sweep_drops_departed_rows_once_they_grant_nothing(guild, member) -> None:
    """Marked rather than deleted at the moment of departure, so the grace runs
    from a known instant - but kept indefinitely it is the same roster by another
    name, and past the ceiling a re-add would write a fresh row anyway."""
    from core.membership import sweep_memberships
    from core.models import CachedMembership, User
    from core.standing import MAX_ROW_AGE

    now = timezone.now()
    User.objects.filter(pk=member.pk).update(last_login=now)
    CachedMembership.objects.create(
        discord_user_id=1,
        guild=guild,
        last_confirmed=now - timedelta(minutes=5),
        removed_at=now - MAX_ROW_AGE - timedelta(minutes=1),
    )
    CachedMembership.objects.create(
        discord_user_id=2, guild=guild, last_confirmed=now, removed_at=now
    )

    purged, departed = sweep_memberships(now)
    assert (purged, departed) == (0, 1), "a fresh removal is inside the window"
    assert list(CachedMembership.objects.values_list("discord_user_id", flat=True)) == [2]

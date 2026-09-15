"""The authorization resolver.

The reviewers hit this hardest, so the tests are written around the specific
failures they found rather than around the happy path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.standing import (
    DELIBERATE_REMOVAL_GRACE,
    MAX_ROW_AGE,
    GuildStanding,
    GuildState,
    Level,
    Membership,
    Route,
    Viewer,
    Visibility,
    can_read,
    can_see_marshal_detail,
    resolve,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
GUILD = 1000
OTHER_GUILD = 2000


def active(guild_id=GUILD) -> dict[int, GuildStanding]:
    return {guild_id: GuildStanding(guild_id, GuildState.ACTIVE, NOW - timedelta(days=30))}


def fresh(guild_id=GUILD, **kwargs) -> Membership:
    return Membership(guild_id, frozenset(), NOW - timedelta(minutes=5), **kwargs)


def route(**kwargs) -> Route:
    return Route(
        owner_id=kwargs.pop("owner_id", 1),
        visibility=kwargs.pop("visibility", Visibility.SERVER),
        owning_guild_id=kwargs.pop("owning_guild_id", GUILD),
        **kwargs,
    )


class TestPrecedence:
    def test_ban_overrides_every_per_route_grant(self) -> None:
        """Ban comes first and nothing below it can restore standing - not
        ownership, not collaboration, not guild admin."""
        owner = Viewer(
            user_id=1, is_banned=True, memberships=(fresh(),), admin_guild_ids=frozenset({GUILD})
        )
        assert resolve(owner, route(owner_id=1), active(), NOW) is Level.NONE
        assert not can_read(owner, route(owner_id=1, visibility=Visibility.PUBLIC), active(), NOW)

    def test_deletion_tombstone_overrides_ownership(self) -> None:
        deleted = Viewer(user_id=1, is_deleted=True, memberships=(fresh(),))
        assert resolve(deleted, route(owner_id=1), active(), NOW) is Level.NONE

    def test_instance_admin_outranks_everything_else(self) -> None:
        admin = Viewer(user_id=9, is_instance_admin=True)
        assert resolve(admin, route(visibility=Visibility.PRIVATE), {}, NOW) is Level.INSTANCE_ADMIN


class TestGuildStateAndRowAge:
    def test_absent_row_is_absence_of_standing(self) -> None:
        """Never unknown-therefore-allow."""
        stranger = Viewer(user_id=2)
        assert resolve(stranger, route(), active(), NOW) is Level.NONE

    def test_stale_row_grants_nothing(self) -> None:
        """The backstop for a frozen database: the cache expires on its own even
        when no component is left running to mark it."""
        stale = Membership(GUILD, frozenset(), NOW - MAX_ROW_AGE - timedelta(minutes=1))
        viewer = Viewer(user_id=2, memberships=(stale,))
        assert resolve(viewer, route(), active(), NOW) is Level.NONE

    def test_revoked_guild_grants_nothing_however_fresh_the_row(self) -> None:
        """Row age alone cannot express a revoke-now, which is why guild state
        exists alongside it."""
        guilds = {GUILD: GuildStanding(GUILD, GuildState.REVOKED, NOW)}
        viewer = Viewer(user_id=2, memberships=(fresh(),))
        assert resolve(viewer, route(), guilds, NOW) is Level.NONE

    def test_degraded_guild_grants_inside_its_window_only(self) -> None:
        inside = {
            GUILD: GuildStanding(
                GUILD, GuildState.DEGRADED, NOW - timedelta(hours=1), NOW + timedelta(hours=1)
            )
        }
        expired = {
            GUILD: GuildStanding(
                GUILD, GuildState.DEGRADED, NOW - timedelta(hours=80), NOW - timedelta(hours=8)
            )
        }
        viewer = Viewer(user_id=2, memberships=(fresh(),))
        assert resolve(viewer, route(), inside, NOW) is Level.MEMBER
        assert resolve(viewer, route(), expired, NOW) is Level.NONE

    def test_deliberate_removal_bites_in_minutes(self) -> None:
        """A removal must take effect while rows confirmed ten minutes ago still
        look fresh, which row age alone cannot express."""
        removed = Membership(
            GUILD,
            frozenset(),
            NOW - timedelta(minutes=5),
            removed_at=NOW - DELIBERATE_REMOVAL_GRACE - timedelta(minutes=1),
        )
        viewer = Viewer(user_id=2, memberships=(removed,))
        assert resolve(viewer, route(), active(), NOW) is Level.NONE

    def test_pending_member_has_no_standing(self) -> None:
        viewer = Viewer(user_id=2, memberships=(fresh(pending=True),))
        assert resolve(viewer, route(), active(), NOW) is Level.NONE

    def test_timed_out_member_has_no_standing(self) -> None:
        viewer = Viewer(user_id=2, memberships=(fresh(timed_out_until=NOW + timedelta(hours=1)),))
        assert resolve(viewer, route(), active(), NOW) is Level.NONE


class TestCrossGuild:
    def test_reviewer_in_one_club_is_not_a_reviewer_in_another(self) -> None:
        viewer = Viewer(
            user_id=2,
            memberships=(fresh(OTHER_GUILD),),
            reviewer_guild_ids=frozenset({OTHER_GUILD}),
        )
        guilds = {**active(), **active(OTHER_GUILD)}
        assert resolve(viewer, route(owning_guild_id=GUILD), guilds, NOW) is Level.NONE

    def test_guild_admin_does_not_moderate_another_guilds_routes(self) -> None:
        """Without this split, one guild's admin could moderate every other
        guild's routes."""
        viewer = Viewer(
            user_id=2, memberships=(fresh(OTHER_GUILD),), admin_guild_ids=frozenset({OTHER_GUILD})
        )
        guilds = {**active(), **active(OTHER_GUILD)}
        assert resolve(viewer, route(owning_guild_id=GUILD), guilds, NOW) is Level.NONE

    def test_audience_guild_member_gets_member_standing(self) -> None:
        """A ride co-organized by several clubs is reviewed by all of them."""
        viewer = Viewer(user_id=2, memberships=(fresh(OTHER_GUILD),))
        guilds = {**active(), **active(OTHER_GUILD)}
        r = route(audience_guild_ids=frozenset({OTHER_GUILD}))
        assert resolve(viewer, r, guilds, NOW) is Level.MEMBER


class TestMarshalDetail:
    """The rule the fresh review found inverted: keyed to standing, not tier."""

    def test_suppressed_for_a_token_holder_on_a_public_route(self) -> None:
        """The tier-based version served marshal data here, which is backwards."""
        stranger = Viewer(user_id=2)
        r = route(visibility=Visibility.PUBLIC)
        assert not can_see_marshal_detail(stranger, r, active(), NOW, has_link_token=True)

    def test_suppressed_for_anonymous_on_a_public_route(self) -> None:
        assert not can_see_marshal_detail(
            Viewer(), route(visibility=Visibility.PUBLIC), active(), NOW
        )

    def test_served_to_a_member_on_a_private_route(self) -> None:
        """The tier-based version suppressed it here, which is also backwards."""
        member = Viewer(user_id=2, memberships=(fresh(),))
        r = route(visibility=Visibility.PRIVATE)
        assert can_see_marshal_detail(member, r, active(), NOW)

    def test_served_to_the_owner_of_a_public_route(self) -> None:
        owner = Viewer(user_id=1, memberships=(fresh(),))
        assert can_see_marshal_detail(
            owner, route(owner_id=1, visibility=Visibility.PUBLIC), active(), NOW
        )


class TestGuests:
    def test_guest_may_comment_on_a_public_route(self) -> None:
        guest = Viewer(user_id=3)
        assert resolve(guest, route(visibility=Visibility.PUBLIC), active(), NOW) is Level.GUEST

    def test_guest_writing_can_be_turned_off_per_route(self) -> None:
        guest = Viewer(user_id=3)
        r = route(visibility=Visibility.PUBLIC, guest_comments_enabled=False)
        assert resolve(guest, r, active(), NOW) is Level.NONE

    def test_anonymous_may_read_public_but_holds_no_level(self) -> None:
        anon = Viewer()
        r = route(visibility=Visibility.PUBLIC)
        assert resolve(anon, r, active(), NOW) is Level.NONE
        assert can_read(anon, r, active(), NOW)

    def test_anonymous_cannot_read_a_private_route(self) -> None:
        assert not can_read(Viewer(), route(visibility=Visibility.PRIVATE), active(), NOW)


class TestTiersAreCumulative:
    @pytest.mark.parametrize(
        ("lower", "higher"),
        [
            (Visibility.PRIVATE, Visibility.REVIEWERS),
            (Visibility.REVIEWERS, Visibility.SERVER),
            (Visibility.SERVER, Visibility.LINK),
            (Visibility.LINK, Visibility.PUBLIC),
        ],
    )
    def test_each_tier_admits_everyone_the_one_below_admits(self, lower, higher) -> None:
        member = Viewer(user_id=2, memberships=(fresh(),))
        assert can_read(member, route(visibility=lower), active(), NOW)
        assert can_read(member, route(visibility=higher), active(), NOW)

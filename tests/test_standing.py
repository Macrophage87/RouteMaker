"""The authorization resolver.

The reviewers hit this hardest, so the tests are written around the specific
failures they found rather than around the happy path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.standing import (
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

    def test_removal_ends_standing_immediately(self) -> None:
        """Not after a grace period. The earlier version gave a kicked member a
        fifteen-minute window, which is long enough to script the club's whole
        route index. The grace belongs to the guild, whose ejection of the bot is
        a different event with a different reason behind it."""
        removed = Membership(
            GUILD,
            frozenset(),
            NOW - timedelta(minutes=5),
            removed_at=NOW - timedelta(seconds=1),
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

    def test_served_to_a_collaborator_on_a_private_route(self) -> None:
        """The tier-based version suppressed it here, which is also backwards. A
        named collaborator is a per-route grant, so it holds at every tier - a
        bare club member is not admitted to a private route at all."""
        collaborator = Viewer(user_id=2, memberships=(fresh(),))
        r = route(visibility=Visibility.PRIVATE, collaborator_ids=frozenset({2}))
        assert can_see_marshal_detail(collaborator, r, active(), NOW)

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
    """Cumulative runs upward: a viewer admitted at tier N is admitted at every
    tier above it. It does not mean a club member is admitted everywhere, which
    is what the earlier version of this class asserted - and, because it passed,
    what kept a genuine read bypass in place."""

    @pytest.mark.parametrize(
        ("lower", "higher"),
        [
            (Visibility.SERVER, Visibility.LINK),
            (Visibility.LINK, Visibility.PUBLIC),
        ],
    )
    def test_admission_carries_upward(self, lower, higher) -> None:
        member = Viewer(user_id=2, memberships=(fresh(),))
        assert can_read(member, route(visibility=lower), active(), NOW)
        assert can_read(member, route(visibility=higher), active(), NOW)

    @pytest.mark.parametrize("tier", [Visibility.PRIVATE, Visibility.REVIEWERS])
    def test_club_membership_does_not_admit_below_server(self, tier) -> None:
        """Belonging to a club does not admit you to a route its owner has not
        shared with the club. An unpermitted ride kept private until ride day was
        readable by every one of several thousand Discord members, marshal posts
        included."""
        member = Viewer(user_id=2, memberships=(fresh(),))
        assert resolve(member, route(visibility=tier), active(), NOW) is Level.NONE
        assert not can_read(member, route(visibility=tier), active(), NOW)

    def test_per_route_grants_hold_at_every_tier(self) -> None:
        collaborator = Viewer(user_id=2, memberships=(fresh(),))
        r = route(visibility=Visibility.PRIVATE, collaborator_ids=frozenset({2}))
        assert can_read(collaborator, r, active(), NOW)


class TestLinkTokens:
    def test_a_token_grants_reading_and_never_a_level(self) -> None:
        """Honouring the token as a level let a signed-in stranger reach GUEST on
        a route whose owner had switched guest comments off - and a public
        route's token URL sits alongside its slug URL, so it is no secret."""
        stranger = Viewer(user_id=7)
        r = route(visibility=Visibility.PUBLIC, guest_comments_enabled=False)
        assert resolve(stranger, r, active(), NOW, has_link_token=True) is Level.NONE

    def test_a_token_does_not_confer_commenting_at_the_link_tier(self) -> None:
        stranger = Viewer(user_id=7)
        r = route(visibility=Visibility.LINK)
        assert resolve(stranger, r, active(), NOW, has_link_token=True) is Level.NONE
        assert can_read(stranger, r, active(), NOW, has_link_token=True)

    def test_link_requires_login_closes_the_anonymous_surface(self) -> None:
        """The lockdown a club reaches for when a route has leaked and the ride
        is imminent."""
        r = route(visibility=Visibility.LINK, link_requires_login=True)
        assert not can_read(Viewer(), r, active(), NOW, has_link_token=True)
        assert can_read(Viewer(user_id=7), r, active(), NOW, has_link_token=True)


class TestOrthogonalGrants:
    def test_a_view_only_collaborator_cannot_edit(self) -> None:
        """The edit flag is an audited owner grant, not a consequence of being
        named on the route."""
        from core.standing import can_edit

        viewer = Viewer(user_id=2)
        assert not can_edit(viewer, route(collaborator_ids=frozenset({2})))
        assert can_edit(viewer, route(editor_ids=frozenset({2})))

    def test_a_collaborator_is_not_automatically_a_reviewer(self) -> None:
        """COLLABORATOR sorts above REVIEWER in the lattice, so a level
        comparison would make every collaborator a reviewer and render the
        owner's audited review grant unenforceable."""
        from core.standing import can_review

        viewer = Viewer(user_id=2)
        r = route(collaborator_ids=frozenset({2}))
        assert not can_review(viewer, r, Level.COLLABORATOR)
        assert can_review(viewer, route(reviewer_ids=frozenset({2})), Level.COLLABORATOR)


class TestSanctionedMembers:
    def test_a_timed_out_member_does_not_fall_through_to_guest(self) -> None:
        """A timeout that leaves someone commenting on the club's public routes
        is not a timeout."""
        viewer = Viewer(user_id=2, memberships=(fresh(timed_out_until=NOW + timedelta(hours=1)),))
        assert resolve(viewer, route(visibility=Visibility.PUBLIC), active(), NOW) is Level.NONE

    def test_a_removed_member_does_not_fall_through_to_guest(self) -> None:
        viewer = Viewer(user_id=2, memberships=(fresh(removed_at=NOW),))
        assert resolve(viewer, route(visibility=Visibility.PUBLIC), active(), NOW) is Level.NONE


class TestStaleGrantCeiling:
    def test_a_degraded_window_cannot_exceed_the_stated_maximum(self) -> None:
        """The admin's audited reclassify action writes that column; a bug or a
        hostile admin could otherwise write a window of any length at all."""
        from core.standing import MAX_STALE_GRANT

        overlong = {
            GUILD: GuildStanding(
                GUILD,
                GuildState.DEGRADED,
                NOW - MAX_STALE_GRANT - timedelta(hours=1),
                NOW + timedelta(days=365),
            )
        }
        viewer = Viewer(user_id=2, memberships=(fresh(),))
        assert resolve(viewer, route(), overlong, NOW) is Level.NONE

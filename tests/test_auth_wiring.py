"""The auth layer as Django actually resolves it.

Every assertion here is about live configuration rather than about a docstring.
The phase 1 panel found that the plan's five mechanisms - derived is_staff, an
authentication backend answering from standing, unusable passwords, is_superuser
forced false, and epoch middleware - were described in comments and implemented
nowhere, so these tests read the resolved settings and the real model.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def guild():
    from core.models import ConfiguredGuild

    return ConfiguredGuild.objects.create(guild_id=1000, name="Test Club")


def member_of(guild, user, *, permission=None, **row):
    from core.models import CachedMembership, RoleMapping

    role_id = 55
    if permission:
        RoleMapping.objects.create(guild=guild, role_id=role_id, permission=permission)
    row.setdefault("last_confirmed", timezone.now())
    return CachedMembership.objects.create(
        discord_user_id=user.discord_user_id,
        guild=guild,
        role_ids=[role_id],
        **row,
    )


class TestNoSecondCredential:
    def test_the_user_model_is_not_djangos_default(self) -> None:
        assert settings.AUTH_USER_MODEL == "core.User"

    def test_no_account_can_hold_a_usable_password(self) -> None:
        """Enforced at the model layer rather than at the creation path, so no
        code path anywhere can give an account one - and so it cannot appear in
        the nightly dump."""
        user = User.objects.create(discord_user_id=1)
        user.set_password("hunter2")
        user.save()
        user.refresh_from_db()
        assert not user.has_usable_password()

    def test_is_superuser_cannot_be_set(self) -> None:
        """Superuser short-circuits the per-object checks this design depends on."""
        user = User.objects.create(discord_user_id=2)
        assert user.is_superuser is False
        with pytest.raises(AttributeError):
            user.is_superuser = True

    def test_is_staff_is_not_a_stored_field(self) -> None:
        """A stored grant outlives the standing it came from."""
        assert not any(f.name == "is_staff" for f in User._meta.fields)

    def test_model_backend_is_not_installed(self) -> None:
        """It authenticates a stored password and answers has_perm from
        permission rows; this deployment has neither."""
        assert "django.contrib.auth.backends.ModelBackend" not in settings.AUTHENTICATION_BACKENDS


class TestDerivedStaff:
    def test_a_plain_member_is_not_staff(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=3)
        member_of(guild, user, permission=RoleMapping.Permission.MEMBER)
        attach_standing(user)
        assert not user.is_staff

    def test_a_guild_admin_is_staff(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=4)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        attach_standing(user)
        assert user.is_staff
        assert user._admin_guild_ids == frozenset({1000})

    def test_a_banned_admin_loses_the_admin(self, guild) -> None:
        """One answer serves both, which is the whole reason staff is derived."""
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=5, is_banned=True)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        attach_standing(user)
        assert not user.is_staff

    def test_a_banned_admin_is_not_staff_even_with_standing_on_the_object(self) -> None:
        """`is_staff`'s own ban conjunct, isolated.

        The test above bans and then resolves, and `attach_standing` empties the
        guild sets for a banned account - so the emptied set is what refuses and
        the conjunct inside `is_staff` could be deleted with the suite green.
        Here the standing is on the object and the flag is the only thing left
        to say no, which is the case that matters: a ban has to end the admin
        whatever some earlier resolution left cached on the instance.
        """
        user = User.objects.create(discord_user_id=6, is_banned=True)
        user._admin_guild_ids = frozenset({1000})
        assert not user.is_staff

        user.is_banned = False
        user.is_deleted = True
        assert not user.is_staff

        user.is_deleted = False
        assert user.is_staff, "and the standing is otherwise real"

    def test_a_revoked_guild_takes_its_admins_with_it(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=6)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        guild.state = "revoked"
        # Left over from a spell in degraded state, which is how a real row gets
        # here: revocation does not clear the column. Without the revoked check
        # running first, a guild that was degraded before it was ejected keeps
        # granting standing until that expiry passes.
        guild.standing_valid_until = timezone.now() + timedelta(hours=1)
        guild.save()
        attach_standing(user)
        assert not user.is_staff

    def test_a_stale_membership_row_grants_no_admin(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping
        from core.standing import MAX_ROW_AGE

        user = User.objects.create(discord_user_id=7)
        member_of(
            guild,
            user,
            permission=RoleMapping.Permission.GUILD_ADMIN,
            last_confirmed=timezone.now() - MAX_ROW_AGE - timedelta(hours=1),
        )
        attach_standing(user)
        assert not user.is_staff

    def test_a_removed_member_loses_standing_immediately(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=8)
        member_of(
            guild,
            user,
            permission=RoleMapping.Permission.GUILD_ADMIN,
            removed_at=timezone.now(),
        )
        attach_standing(user)
        assert not user.is_staff


class TestSessionEpoch:
    def test_bumping_the_epoch_invalidates_the_session(self) -> None:
        """Without this the epoch is a column nothing reads, and ban, suspension,
        deletion and sign-out-everywhere all leave the person signed in."""
        from core.auth_backend import session_is_current

        user = User.objects.create(discord_user_id=9)
        now = timezone.now()
        assert session_is_current(user, 1, now - timedelta(days=1), now)
        user.session_epoch = 2
        assert not session_is_current(user, 1, now - timedelta(days=1), now)

    def test_a_banned_user_has_no_current_session_whatever_the_epoch(self) -> None:
        """The epoch is bumped by ban and deletion now, so this is belt to those
        braces - and it is the check that still bites when a flag was set by a
        fixture, a migration or a hand-written UPDATE that bumped nothing."""
        from core.auth_backend import session_is_current

        user = User.objects.create(discord_user_id=10)
        now = timezone.now()
        assert session_is_current(user, user.session_epoch, now, now)

        user.is_banned = True
        assert not session_is_current(user, user.session_epoch, now, now)

    def test_banning_a_user_bumps_the_epoch(self) -> None:
        """It was a column the middleware read and nothing incremented, so ban,
        suspension, deletion and sign-out-everywhere all left the person signed
        in - the exact mechanism `revocation`'s docstring opens by describing."""
        user = User.objects.create(discord_user_id=11)
        before = user.session_epoch
        user.is_banned = True
        user.save(update_fields=["is_banned"])
        user.refresh_from_db()
        assert user.session_epoch == before + 1

    def test_deleting_an_account_bumps_the_epoch(self) -> None:
        user = User.objects.create(discord_user_id=12)
        before = user.session_epoch
        user.is_deleted = True
        user.save()
        user.refresh_from_db()
        assert user.session_epoch == before + 1

    def test_an_ordinary_save_does_not_bump_it(self) -> None:
        """Otherwise every request that touched the row would sign the person
        out, which is a revocation mechanism that revokes everything."""
        user = User.objects.create(discord_user_id=13)
        before = user.session_epoch
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        user.refresh_from_db()
        assert user.session_epoch == before

    def test_the_middleware_is_installed_after_authentication(self) -> None:
        """It needs request.user, so ordering is part of the mechanism."""
        middleware = settings.MIDDLEWARE
        assert "core.middleware.SessionEpochMiddleware" in middleware
        assert middleware.index(
            "django.contrib.auth.middleware.AuthenticationMiddleware"
        ) < middleware.index("core.middleware.SessionEpochMiddleware")


class TestAttachStandingBranches:
    """The resolver Django actually calls.

    Every branch below survived deletion against the whole suite. The
    authorization module that *was* tested, `core.standing`, is reached from no
    production path, so a role-mapping inversion that made every reviewer a guild
    admin - and the ban, timeout and deletion checks - were invisible.
    """

    def test_a_timed_out_member_has_no_standing(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=20)
        now = timezone.now()
        member_of(
            guild,
            user,
            permission=RoleMapping.Permission.GUILD_ADMIN,
            timed_out_until=now + timedelta(hours=1),
        )
        attach_standing(user, now)
        assert user._member_guild_ids == frozenset()
        assert not user.is_staff

    def test_standing_returns_when_the_timeout_expires(self, guild) -> None:
        """Bounded by the clock, not by the column being cleared: Discord does not
        send an event when a timeout lapses."""
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=21)
        now = timezone.now()
        member_of(
            guild,
            user,
            permission=RoleMapping.Permission.GUILD_ADMIN,
            timed_out_until=now - timedelta(minutes=1),
        )
        attach_standing(user, now)
        assert user.is_staff

    def test_a_deleted_user_gets_nothing_from_a_row_that_survived(self, guild) -> None:
        """Renamed. This asserts that `attach_standing` grants a deleted user
        nothing, which is true and is not the plan's test of that name - that one
        is about the row coming back at all, and it lives in test_membership.py
        where the gateway is."""
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=22, is_deleted=True)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        attach_standing(user)
        assert user._member_guild_ids == frozenset()

    def test_a_role_mapped_to_instance_admin_does_not_confer_it(self, guild) -> None:
        """Pinned, and pinned against the reviewer's suggestion rather than with
        it, because the plan decides this and the plan is explicit.

        Round 3 asked for `attach_standing` to interpret INSTANCE_ADMIN. PLAN's
        instance-admin section says the role is "independent of every guild,
        deriving from the instance-admin list alone and never from guild
        membership, role mapping, the bot, or the membership cache, so the people
        who can fix a broken bot can still sign in when every guild is degraded".
        Honouring the mapping would make the deployment's one cross-guild role
        lapse with a club's gateway connection, which is the failure that
        sentence exists to rule out - and which
        `TestInstanceAdminSurvivesADegradedDeployment` asserts does not happen.

        The half of the finding that is real - that a fresh deployment had
        exactly one instance admin forever - is fixed by registering the user
        admin, which is what the plan prescribes: "instance admins are then added
        and removed in the admin, audited".
        """
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=25)
        member_of(guild, user, permission=RoleMapping.Permission.INSTANCE_ADMIN)
        attach_standing(user)

        assert not user.is_instance_admin
        assert not user.is_staff
        assert user._admin_guild_ids == frozenset()
        assert user._reviewer_guild_ids == frozenset()
        assert user._member_guild_ids == frozenset({1000}), "they are still a member"

    def test_a_reviewer_is_a_reviewer_and_not_an_admin(self, guild) -> None:
        """An inverted mapping here makes every reviewer a guild admin, which is
        the difference between seeing a private route and editing the configured
        guild list."""
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=23)
        member_of(guild, user, permission=RoleMapping.Permission.REVIEWER)
        attach_standing(user)
        assert user._reviewer_guild_ids == frozenset({1000})
        assert user._admin_guild_ids == frozenset()
        assert not user.is_staff

    def test_a_pending_member_has_no_standing(self, guild) -> None:
        """Catches long-standing members who joined before a server's rules gate
        existed, so the denial can say so rather than reading as a broken site."""
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=24)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN, pending=True)
        attach_standing(user)
        assert user._member_guild_ids == frozenset()

    def test_an_unconfigured_guild_cannot_be_cached_at_all(self) -> None:
        """A guild the bot is in but that is not configured is inert. That, rather
        than the bot's Public Bot flag, is the admission control.

        Here it is structural: a cached row hangs off a ConfiguredGuild row, so
        there is no shape a membership in an unconfigured guild could take. The
        behavioural half - that the gateway ignores such an event rather than
        creating the guild - is in test_membership.
        """
        from core.models import CachedMembership

        guild_field = CachedMembership._meta.get_field("guild")
        assert guild_field.remote_field.model.__name__ == "ConfiguredGuild"
        assert not guild_field.null, "a row with no configured guild must not exist"

    def test_a_degraded_guild_honours_cached_standing_inside_the_window(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        now = timezone.now()
        user = User.objects.create(discord_user_id=26)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        guild.state = "degraded"
        guild.standing_valid_until = now + timedelta(hours=1)
        guild.save()
        attach_standing(user, now)
        assert user.is_staff

    def test_a_degraded_guild_lapses_to_nothing_after_the_window(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        now = timezone.now()
        user = User.objects.create(discord_user_id=27)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        guild.state = "degraded"
        guild.standing_valid_until = now - timedelta(minutes=1)
        guild.save()
        attach_standing(user, now)
        assert not user.is_staff

    def test_a_degraded_guild_is_clamped_to_the_stated_maximum(self, guild) -> None:
        """A column is not trusted to carry a window of arbitrary length: a value
        far in the future would make one lost guild permanent."""
        from core.auth_backend import attach_standing
        from core.models import RoleMapping
        from core.standing import MAX_STALE_GRANT

        now = timezone.now()
        user = User.objects.create(discord_user_id=28)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        guild.state = "degraded"
        guild.standing_valid_until = now + timedelta(days=3650)
        guild.save()
        ConfiguredGuildRow = type(guild)
        ConfiguredGuildRow.objects.filter(pk=guild.pk).update(
            state_since=now - MAX_STALE_GRANT - timedelta(minutes=1)
        )
        attach_standing(user, now)
        assert not user.is_staff, "the ceiling runs from state_since, not from the column"


class TestHasPerm:
    def test_an_inactive_user_holds_no_permission(self, guild) -> None:
        """is_active is what ban and deletion resolve through, so dropping it from
        the conjunct hands a banned guild admin the admin back."""
        from core.auth_backend import DiscordStandingBackend, attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=30)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        attach_standing(user)
        assert DiscordStandingBackend().has_perm(user, "core.view_configuredguild")

        user.is_banned = True
        attach_standing(user)
        assert not user.is_active
        assert not DiscordStandingBackend().has_perm(user, "core.view_configuredguild")

    def test_a_member_with_no_admin_standing_holds_no_permission(self, guild) -> None:
        """The guard that answers before the allow-list is consulted.

        Deleting `if not _admin_guild_ids: return False` from `has_perm` left
        the suite green, because reaching the admin at all needs `is_staff`,
        which needs the same set - so every test that drives a permission
        through a request has an admin on the other end and the guard is masked.
        Asked directly, an ordinary club member must hold nothing: the
        allow-list is what a guild admin holds, not what anyone holds.

        `has_module_perms`' identical guard is already killed by the module test
        below; this is the other half of the same conjunction.
        """
        from core.auth_backend import DiscordStandingBackend, attach_standing
        from core.models import RoleMapping

        backend = DiscordStandingBackend()
        member = User.objects.create(discord_user_id=34)
        member_of(guild, member, permission=RoleMapping.Permission.MEMBER)
        attach_standing(member)

        assert member.is_active and not member.is_instance_admin
        assert member._member_guild_ids == frozenset({1000}), "a member in good standing"
        assert member._admin_guild_ids == frozenset(), "and no admin anywhere"

        for perm in sorted(DiscordStandingBackend.GUILD_ADMIN_PERMISSIONS):
            assert not backend.has_perm(member, perm), perm
        assert not backend.has_module_perms(member, "core")

    def test_a_signed_in_stranger_holds_nothing_either(self) -> None:
        """No memberships at all, which is what a brand new account is."""
        from core.auth_backend import DiscordStandingBackend, attach_standing

        backend = DiscordStandingBackend()
        stranger = User.objects.create(discord_user_id=35)
        attach_standing(stranger)
        for perm in sorted(DiscordStandingBackend.GUILD_ADMIN_PERMISSIONS):
            assert not backend.has_perm(stranger, perm), perm

    def test_a_banned_instance_admin_holds_nothing(self) -> None:
        """is_active is load-bearing here and nowhere else.

        Everywhere else the empty standing sets would refuse on their own, so
        dropping the conjunct changes nothing and a test built on a banned guild
        admin passes either way. The instance-admin branch returns before it
        consults standing at all, so without is_active a banned instance admin
        keeps every permission on every model.
        """
        from core.auth_backend import DiscordStandingBackend, attach_standing

        user = User.objects.create(discord_user_id=32, is_instance_admin=True)
        attach_standing(user)
        assert DiscordStandingBackend().has_perm(user, "core.change_configuredguild")

        user.is_banned = True
        attach_standing(user)
        assert not DiscordStandingBackend().has_perm(user, "core.change_configuredguild")
        assert not DiscordStandingBackend().has_module_perms(user, "core")

    @pytest.fixture
    def guild_admin(self, guild):
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=31)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        attach_standing(user)
        return user

    def test_the_instance_admin_only_set_is_the_one_the_plan_names(self) -> None:
        """Pinned flat, because the loop below is driven from this set and a loop
        driven from a set cannot notice an entry leaving it. Deleting
        "rolemapping" or "auditlogentry" left 431 tests passing; `cachedmembership`
        - the table that grants any role in any guild - was never in it at all.
        """
        from core.auth_backend import DiscordStandingBackend

        assert DiscordStandingBackend.INSTANCE_ADMIN_ONLY_MODELS == frozenset(
            {
                "configuredguild",
                "jurisdiction",
                "override",
                "bantombstone",
                "user",
                "rolemapping",
                "auditlogentry",
                "cachedmembership",
                "bordercrossing",
                # Deleting the bootstrap claim re-arms the environment path, so
                # it belongs with the tables that grant standing even though
                # nothing registers it in the admin.
                "bootstrapclaim",
            }
        )

    def test_a_guild_admin_cannot_write_any_of_them(self, guild_admin) -> None:
        """The configured guild list is the deployment's admission control:
        adding a row self-onboards a server, and editing guild_id is an unaudited
        remap of the snowflake every standing check matches against."""
        from core.auth_backend import DiscordStandingBackend

        backend = DiscordStandingBackend()
        for model in sorted(DiscordStandingBackend.INSTANCE_ADMIN_ONLY_MODELS):
            for action in ("add", "change", "delete"):
                perm = f"core.{action}_{model}"
                assert not backend.has_perm(guild_admin, perm), perm
        assert backend.has_perm(guild_admin, "core.view_configuredguild")

    def test_permissions_are_an_allow_list_and_not_a_deny_list(self, guild_admin) -> None:
        """The deny-list this replaced answered True for everything nobody had
        thought to name, so a guild admin held `core.approve_override`,
        `auth.add_permission` and `admin.delete_logentry` - and phase 4 brings
        exactly those custom actions."""
        from core.auth_backend import DiscordStandingBackend

        backend = DiscordStandingBackend()
        for perm in (
            "core.approve_override",
            "core.remap_configuredguild",
            "core.change_route",
            "auth.add_permission",
            "auth.change_user",
            "admin.delete_logentry",
            "sessions.delete_session",
            "core.invent_a_permission_in_phase_4",
        ):
            assert not backend.has_perm(guild_admin, perm), perm

    def test_module_permission_is_not_held_for_every_app(self, guild_admin) -> None:
        """It answered True for every app label, `admin` and `auth` included,
        because neither starts with a write prefix."""
        from core.auth_backend import DiscordStandingBackend

        backend = DiscordStandingBackend()
        assert backend.has_module_perms(guild_admin, "core")
        for label in ("admin", "auth", "sessions", "contenttypes", "nonexistent"):
            assert not backend.has_module_perms(guild_admin, label), label

    def test_an_instance_admin_still_holds_everything(self) -> None:
        from core.auth_backend import DiscordStandingBackend, attach_standing

        user = User.objects.create(discord_user_id=33, is_instance_admin=True)
        attach_standing(user)
        backend = DiscordStandingBackend()
        assert backend.has_perm(user, "core.change_configuredguild")
        assert backend.has_module_perms(user, "core")

    def test_the_allow_list_may_not_name_a_write_on_a_standing_table(self) -> None:
        """The two constants are kept from drifting apart by a check that runs at
        import, not by whoever reviews the next diff."""
        from django.core.exceptions import ImproperlyConfigured

        from core.auth_backend import DiscordStandingBackend, check_guild_admin_allow_list

        check_guild_admin_allow_list(
            DiscordStandingBackend.GUILD_ADMIN_PERMISSIONS,
            DiscordStandingBackend.INSTANCE_ADMIN_ONLY_MODELS,
        )
        with pytest.raises(ImproperlyConfigured, match="privilege escalation"):
            check_guild_admin_allow_list(
                frozenset({"core.change_rolemapping"}),
                DiscordStandingBackend.INSTANCE_ADMIN_ONLY_MODELS,
            )


class TestSessionEpochMiddleware:
    """Driven through a real request. The module's own docstring says a value
    nothing reads revokes nothing, and until these existed nothing read it: the
    middleware could be replaced with a pass-through and the suite stayed green.
    """

    def signed_in(self, user, **row):
        from django.contrib.sessions.backends.db import SessionStore

        from core.models import Session

        store = SessionStore()
        store.create()
        now = timezone.now()
        row.setdefault("issued_epoch", user.session_epoch)
        row.setdefault("created_at", now)
        row.setdefault("last_seen_at", now)
        Session.objects.create(session_key=store.session_key, user=user, **row)
        return store

    def request_for(self, user, store):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.session = store
        request.user = user
        return request

    def run_middleware(self, request):
        from core.middleware import SessionEpochMiddleware

        return SessionEpochMiddleware(lambda r: "ok")(request)

    def test_a_live_session_survives_and_its_clock_moves(self) -> None:
        from core.models import Session

        user = User.objects.create(discord_user_id=40)
        store = self.signed_in(user, last_seen_at=timezone.now() - timedelta(hours=2))
        request = self.request_for(user, store)

        before = Session.objects.get(session_key=store.session_key).last_seen_at
        assert self.run_middleware(request) == "ok"
        after = Session.objects.get(session_key=store.session_key).last_seen_at
        assert after > before, "the idle clock never moves, so every session expires"
        assert hasattr(request.user, "_member_guild_ids"), "standing was never attached"

    def test_a_stale_epoch_ends_the_session(self) -> None:
        """Ban, suspension, deletion and sign-out-everywhere all land here."""
        from core.models import Session

        user = User.objects.create(discord_user_id=41)
        store = self.signed_in(user)
        user.session_epoch += 1
        user.save(update_fields=["session_epoch"])

        key = store.session_key  # logout() flushes the store and clears it
        request = self.request_for(user, store)
        self.run_middleware(request)
        assert not Session.objects.filter(session_key=key).exists()
        assert not request.user.is_authenticated

    def test_a_session_past_the_absolute_lifetime_ends(self) -> None:
        """Django implements idle expiry natively but not an absolute cap."""
        from core.models import Session
        from core.revocation import ABSOLUTE_SESSION_LIFETIME

        user = User.objects.create(discord_user_id=42)
        store = self.signed_in(
            user, created_at=timezone.now() - ABSOLUTE_SESSION_LIFETIME - timedelta(minutes=1)
        )
        key = store.session_key
        self.run_middleware(self.request_for(user, store))
        assert not Session.objects.filter(session_key=key).exists()

    def test_an_idle_session_ends(self) -> None:
        from core.models import Session
        from core.revocation import IDLE_SESSION_LIFETIME

        user = User.objects.create(discord_user_id=43)
        store = self.signed_in(
            user, last_seen_at=timezone.now() - IDLE_SESSION_LIFETIME - timedelta(minutes=1)
        )
        key = store.session_key
        self.run_middleware(self.request_for(user, store))
        assert not Session.objects.filter(session_key=key).exists()

    def test_a_session_with_no_row_is_refused(self) -> None:
        """The row is the only thing carrying the epoch, so a session without one
        cannot be checked and is not trusted."""
        from django.contrib.sessions.backends.db import SessionStore

        user = User.objects.create(discord_user_id=44)
        store = SessionStore()
        store.create()
        request = self.request_for(user, store)
        self.run_middleware(request)
        assert not request.user.is_authenticated

    def test_an_anonymous_request_passes_through(self) -> None:
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.backends.db import SessionStore

        store = SessionStore()
        store.create()
        assert self.run_middleware(self.request_for(AnonymousUser(), store)) == "ok"

    def test_a_row_is_never_matched_against_another_persons_epoch(self) -> None:
        """The `user=user` half of the lookup.

        Session keys are unguessable, so this is not a lookup an attacker drives
        - but without the conjunct the middleware answers a question about
        whoever holds the key rather than about whoever is signed in, and it
        would then write another account's clock and attach standing to a
        request that has no row of its own. A row belongs to one person, and
        every revocation in this deployment is per person.
        """
        from core.models import Session

        owner = User.objects.create(discord_user_id=45)
        other = User.objects.create(discord_user_id=46)
        store = self.signed_in(owner, last_seen_at=timezone.now() - timedelta(hours=2))
        # Read before the middleware runs: `logout` flushes the store and leaves
        # `store.session_key` as None, so reading it afterwards looks up nothing.
        key = store.session_key
        before = Session.objects.get(session_key=key).last_seen_at

        request = self.request_for(other, store)
        self.run_middleware(request)

        assert not request.user.is_authenticated, "no row of their own, so no session"
        assert Session.objects.get(session_key=key).last_seen_at == before, (
            "and the owner's clock was not moved by somebody else's request"
        )

    def test_a_row_swept_mid_request_is_not_an_error(self, monkeypatch) -> None:
        """The clock refresh is an UPDATE, not a `save(update_fields=...)`.

        `save(update_fields=...)` raises `DatabaseError("Save with update_fields
        did not affect any rows")` when the row has gone since it was read - the
        session sweep running, or a sign-out-everywhere from another request,
        between the SELECT and the write. That is a 500 on an ordinary request,
        for a timestamp that does not matter. An UPDATE matching nothing is a
        no-op, which is the right answer when the row it would have touched is
        already gone.

        The disappearance is staged where it actually happens: between the read
        and the write, by way of the validity check the middleware makes in
        between.
        """
        from core.models import Session

        user = User.objects.create(discord_user_id=47)
        store = self.signed_in(user)
        key = store.session_key

        def vanish(*args, **kwargs):
            Session.objects.filter(session_key=key).delete()
            return True

        monkeypatch.setattr("core.middleware.session_is_current", vanish)

        request = self.request_for(user, store)
        assert self.run_middleware(request) == "ok"
        assert not Session.objects.filter(session_key=key).exists()


@pytest.mark.django_db(transaction=True)
def test_a_stale_session_row_is_deleted_by_a_real_request(client, monkeypatch) -> None:
    """Round-3 test-quality NIT A2: `row.delete()` in the middleware was
    unasserted, and removing it left the suite green.

    The three assertions that looked like they covered it did not. Each read
    `store.session_key` *after* running the middleware, and `logout()` flushes
    the session store, which sets that attribute to None - so the filter ran on
    `session_key IS NULL`, matched nothing, and passed whether the row was
    deleted or not.

    This signs in through the real login flow, bumps the epoch the way a ban
    does, and makes a second real request. The key is held from before the
    request, so the row is looked for where it actually is. Without the delete
    the row survives every future request too: the middleware only ever reaches
    it when a request carries the matching cookie, and that cookie is gone.
    """
    from django.urls import reverse

    from core.auth_views import STATE_SESSION_KEY
    from core.models import Session

    monkeypatch.setattr(
        "core.auth_views.exchange_code", lambda _code: (901, "identify"), raising=False
    )
    client.get(reverse("login"))
    state = client.session[STATE_SESSION_KEY]["state"]
    client.get(reverse("login-callback"), {"state": state, "code": "abc"})

    user = User.objects.get(discord_user_id=901)
    key = Session.objects.get(user=user).session_key

    user.session_epoch += 1
    User.objects.filter(pk=user.pk).update(session_epoch=user.session_epoch)

    client.get(reverse("login"))

    assert not Session.objects.filter(session_key=key).exists(), (
        "a row nothing will ever accept again is a user id and a timestamp left in the table"
    )


class TestTheAuthorizeUrlCarriesARealApplication:
    """The sign-in path needs settings the stack has to deliver, and did not.

    `compose.yaml` declared six of the twenty-four variables `config/settings.py`
    reads, and `DISCORD_CLIENT_ID` and `DISCORD_REDIRECT_URI` were not among
    them. Both have module defaults - the empty string and
    `http://localhost:8000/auth/callback` - so nothing failed at import and
    nothing failed under test either: the suite has never needed a real client
    id, so every existing assertion about the authorize URL passed against
    `client_id=` and a redirect to the developer's own machine. The deployed
    login button led to an application Discord does not know.

    The delivery is asserted in tests/test_compose.py. This is the other half:
    what the values do when they are there, and what the URL looks like when
    they are not.
    """

    def authorize_url(self, client) -> str:
        from django.urls import reverse

        response = client.get(reverse("login"))
        assert response.status_code == 302
        return response["Location"]

    def test_the_configured_client_id_and_redirect_are_the_ones_discord_is_sent(
        self, client
    ) -> None:
        from urllib.parse import parse_qs, urlparse

        from django.test import override_settings

        with override_settings(
            DISCORD_CLIENT_ID="123456789012345678",
            DISCORD_REDIRECT_URI="https://routes.example.org/auth/callback",
        ):
            url = self.authorize_url(client)

        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["123456789012345678"]
        assert query["redirect_uri"] == ["https://routes.example.org/auth/callback"]
        assert query["scope"] == ["identify"]
        assert query["response_type"] == ["code"]

    def test_an_undelivered_client_id_makes_a_url_that_names_no_application(self, client) -> None:
        """Why the compose assertion exists, stated as behaviour rather than as
        a claim about a YAML file: with the variable undelivered the settings
        default reaches Discord, and the empty `client_id` is the whole of the
        failure. Nothing raises, which is what made it survive four rounds.
        """
        from urllib.parse import parse_qs, urlparse

        from django.test import override_settings

        with override_settings(DISCORD_CLIENT_ID=""):
            url = self.authorize_url(client)

        assert parse_qs(urlparse(url).query).get("client_id", [""]) == [""]

    def test_the_settings_carry_no_usable_default_for_either(self) -> None:
        """Neither may acquire one. A default client id would be another
        deployment's application, and a default redirect sends the browser back
        to localhost after Discord approves the grant - which on a real
        deployment is the point at which the login silently stops working."""
        import os
        from pathlib import Path

        import config.settings as live

        source = Path(live.__file__).read_text()
        assert 'os.environ.get("DISCORD_CLIENT_ID", "")' in source
        assert "http://localhost:8000/auth/callback" in source, (
            "the redirect's default is a developer convenience, and it must stay "
            "obviously unusable in production rather than become a real-looking host"
        )
        # And under an environment that delivers them, they are what arrives.
        assert settings.DISCORD_CLIENT_ID == os.environ.get("DISCORD_CLIENT_ID", "")

"""The two admin-scoping assertions phase 1 owes, plus the credential rule."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.utils import timezone

db = pytest.mark.django_db(transaction=True)


class Request:
    """Just enough of an HttpRequest for the admin's permission hooks."""

    def __init__(self, user):
        self.user = user
        self.GET = {}
        self.META = {}


@db
def test_admin_refuses_an_unauthenticated_request() -> None:
    from core.admin import site

    class Anonymous:
        is_authenticated = False
        is_active = False
        is_staff = False

    assert not site.has_permission(Request(Anonymous()))


@db
def test_admin_refuses_a_signed_in_member_without_derived_staff() -> None:
    """Staff is derived from application standing, so a member of a club is not
    an admin. Exercised against the real user model rather than a stub: the stub
    version of this test passed against a hand-set attribute and would have
    missed the is_active conjunction entirely."""
    from core.admin import site
    from core.auth_backend import attach_standing

    User = get_user_model()
    user = User.objects.create(discord_user_id=201)
    attach_standing(user)
    assert not site.has_permission(Request(user))


@db
def test_admin_refuses_a_banned_instance_admin() -> None:
    """A ban ends the admin along with everything else. Dropping Django's own
    is_active conjunct, as an earlier version did, would have left it standing."""
    from core.admin import site
    from core.auth_backend import attach_standing

    User = get_user_model()
    user = User.objects.create(discord_user_id=202, is_instance_admin=True, is_banned=True)
    attach_standing(user)
    assert not site.has_permission(Request(user))


@db
def test_admin_admits_an_instance_admin() -> None:
    from core.admin import site
    from core.auth_backend import attach_standing

    User = get_user_model()
    user = User.objects.create(discord_user_id=203, is_instance_admin=True)
    attach_standing(user)
    assert site.has_permission(Request(user))


def test_there_is_no_admin_login_form() -> None:
    """Django's own login is a second credential class this threat model does not
    have. 404 rather than a redirect, so the path does not confirm an admin is
    here."""
    from core.admin import site

    with pytest.raises(Http404):
        site.login(Request(None))


def test_there_is_no_admin_password_change() -> None:
    """Django registers it for any staff user, and it is a path to setting a
    usable password on an account that must never have one."""
    from core.admin import site

    with pytest.raises(Http404):
        site.password_change(Request(None))


def test_derived_state_is_not_editable_in_the_admin() -> None:
    """The pipeline owns border crossings and a rebuild reassigns their ids. A
    hand edit would be overwritten next Tuesday and would desynchronise the graph
    from the crossings table in the meantime."""
    from core.admin import BorderCrossingAdmin, site
    from core.models import BorderCrossing

    model_admin = BorderCrossingAdmin(BorderCrossing, site)
    assert not model_admin.has_add_permission(Request(None))
    assert not model_admin.has_change_permission(Request(None))
    assert not model_admin.has_delete_permission(Request(None))


def test_guild_scoping_declaration_is_mandatory() -> None:
    """The base declares no scope, so every subclass must.

    The earlier version of this test asserted hasattr(cls, "get_queryset"), which
    is true of every ModelAdmin and passes if the whole class is deleted.
    """
    from core.admin import GuildScopedAdmin

    assert GuildScopedAdmin.guild_scope_field is None


# The two assertions phase 1 owes, against real rows and real querysets.


db = pytest.mark.django_db(transaction=True)


@db
def test_a_changelist_never_shows_another_guilds_rows() -> None:
    """The first of the two: no admin list view shows a row the viewing admin's
    guild scope excludes. Asserted on the queryset the changelist would run."""
    from core.admin import ConfiguredGuildAdmin, site
    from core.auth_backend import attach_standing
    from core.models import CachedMembership, ConfiguredGuild, RoleMapping

    User = get_user_model()
    mine = ConfiguredGuild.objects.create(guild_id=1001, name="My Club")
    theirs = ConfiguredGuild.objects.create(guild_id=1002, name="Their Club")

    admin_user = User.objects.create(discord_user_id=101)
    RoleMapping.objects.create(guild=mine, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN)
    CachedMembership.objects.create(
        discord_user_id=101, guild=mine, role_ids=[7], last_confirmed=timezone.now()
    )
    attach_standing(admin_user)

    model_admin = ConfiguredGuildAdmin(ConfiguredGuild, site)
    visible = set(model_admin.get_queryset(Request(admin_user)).values_list("guild_id", flat=True))
    assert visible == {1001}
    assert theirs.guild_id not in visible


@db
def test_an_instance_admin_only_action_is_refused_to_a_guild_admin() -> None:
    """The second: approving an override changes routing for every guild, so one
    club's admin must not be able to do it from the admin any more than from the
    API. Model-level permissions cannot express that."""
    from core.admin import JurisdictionAdmin, OverrideAdmin, site
    from core.auth_backend import attach_standing
    from core.models import CachedMembership, ConfiguredGuild, Jurisdiction, Override, RoleMapping

    User = get_user_model()
    guild = ConfiguredGuild.objects.create(guild_id=1003, name="Club")
    guild_admin = User.objects.create(discord_user_id=102)
    RoleMapping.objects.create(
        guild=guild, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN
    )
    CachedMembership.objects.create(
        discord_user_id=102, guild=guild, role_ids=[7], last_confirmed=timezone.now()
    )
    attach_standing(guild_admin)
    instance_admin = User.objects.create(discord_user_id=103, is_instance_admin=True)
    attach_standing(instance_admin)

    override_admin = OverrideAdmin(Override, site)
    jurisdiction_admin = JurisdictionAdmin(Jurisdiction, site)

    assert guild_admin.is_staff, "they can reach the admin at all"
    for model_admin in (override_admin, jurisdiction_admin):
        assert not model_admin.has_change_permission(Request(guild_admin))
        assert not model_admin.has_add_permission(Request(guild_admin))
        assert not model_admin.has_delete_permission(Request(guild_admin))
        assert model_admin.has_change_permission(Request(instance_admin))


@db
def test_the_approval_flag_itself_is_not_editable() -> None:
    """Locking only the timestamp while leaving the flag editable was backwards:
    approval is the audited action, not the record of when it happened."""
    from core.admin import OverrideAdmin, site
    from core.models import Override

    assert "approved" in OverrideAdmin(Override, site).readonly_fields


@db
def test_a_subclass_without_a_scope_field_refuses_to_serve() -> None:
    """Returning the unfiltered queryset made forgetting the field a silent
    cross-guild leak - the exact failure the base class exists to prevent."""
    from core.admin import GuildScopedAdmin, site
    from core.auth_backend import attach_standing
    from core.models import ConfiguredGuild

    User = get_user_model()
    forgetful = type("Forgetful", (GuildScopedAdmin,), {})(ConfiguredGuild, site)
    user = User.objects.create(discord_user_id=104)
    attach_standing(user)
    with pytest.raises(ImproperlyConfigured, match="guild_scope_field"):
        forgetful.get_queryset(Request(user))


@db
def test_an_instance_admin_sees_every_guild() -> None:
    from core.admin import ConfiguredGuildAdmin, site
    from core.auth_backend import attach_standing
    from core.models import ConfiguredGuild

    User = get_user_model()
    ConfiguredGuild.objects.create(guild_id=1004)
    ConfiguredGuild.objects.create(guild_id=1005)
    admin_user = User.objects.create(discord_user_id=105, is_instance_admin=True)
    attach_standing(admin_user)
    visible = ConfiguredGuildAdmin(ConfiguredGuild, site).get_queryset(Request(admin_user))
    assert visible.count() >= 2


@pytest.fixture
def guild(db):
    from core.models import ConfiguredGuild

    return ConfiguredGuild.objects.create(guild_id=5000, name="Test Club")


@pytest.fixture
def instance_admin(db):
    return get_user_model().objects.create(discord_user_id=9001, is_instance_admin=True)


@pytest.fixture
def guild_admin(db, guild):
    from core.auth_backend import attach_standing
    from core.models import CachedMembership, RoleMapping

    user = get_user_model().objects.create(discord_user_id=9002)
    RoleMapping.objects.create(
        guild=guild, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN
    )
    CachedMembership.objects.create(
        discord_user_id=user.discord_user_id,
        guild=guild,
        role_ids=[7],
        last_confirmed=timezone.now(),
    )
    attach_standing(user)
    return user


class TestTheAuditedHalfOfEveryVisibilityAssertion:
    """Every assertion the plan makes about the admin ends in "and the attempt is
    audited". Until the log existed the refusals were real and the record of them
    was not: a refused edit and nobody having tried looked the same afterwards.
    """

    def test_a_refused_write_is_recorded(self, guild_admin) -> None:
        from core.admin import RoleMappingAdmin, site
        from core.models import AuditLogEntry, RoleMapping

        request = Request(guild_admin)
        assert not RoleMappingAdmin(RoleMapping, site).has_change_permission(request)

        entry = AuditLogEntry.objects.get()
        assert entry.actor == guild_admin
        assert entry.outcome == AuditLogEntry.Outcome.REFUSED
        assert entry.model == "rolemapping"
        assert entry.action == "change"

    def test_a_permitted_check_is_not_an_attempt(self, instance_admin) -> None:
        from core.admin import RoleMappingAdmin, site
        from core.models import AuditLogEntry, RoleMapping

        assert RoleMappingAdmin(RoleMapping, site).has_change_permission(Request(instance_admin))
        assert not AuditLogEntry.objects.filter(outcome=AuditLogEntry.Outcome.REFUSED).exists()

    def test_a_guild_admin_cannot_reach_the_membership_table_or_the_mapping(
        self, guild_admin
    ) -> None:
        """Editing the cached membership table grants any role in any guild;
        editing a mapping decides who holds guild admin."""
        from core.admin import CachedMembershipAdmin, RoleMappingAdmin, site
        from core.models import AuditLogEntry, CachedMembership, RoleMapping

        request = Request(guild_admin)
        assert not CachedMembershipAdmin(CachedMembership, site).has_change_permission(request)
        assert not RoleMappingAdmin(RoleMapping, site).has_add_permission(request)
        assert not RoleMappingAdmin(RoleMapping, site).has_delete_permission(request)

        refused = AuditLogEntry.objects.filter(outcome=AuditLogEntry.Outcome.REFUSED)
        assert {entry.model for entry in refused} == {"cachedmembership", "rolemapping"}

    def test_the_log_is_read_only_to_everyone_including_an_instance_admin(
        self, instance_admin
    ) -> None:
        """A log whose entries can be edited or deleted from the surface it
        audits is not a log."""
        from core.admin import AuditLogEntryAdmin, site
        from core.models import AuditLogEntry

        request = Request(instance_admin)
        page = AuditLogEntryAdmin(AuditLogEntry, site)

        assert page.has_view_permission(request)
        assert not page.has_add_permission(request)
        assert not page.has_change_permission(request)
        assert not page.has_delete_permission(request)

    def test_a_guild_admin_cannot_read_the_log(self, guild_admin) -> None:
        """It names who acted where, which is the same sensitivity as the
        membership cache."""
        from core.admin import AuditLogEntryAdmin, site
        from core.models import AuditLogEntry

        assert not AuditLogEntryAdmin(AuditLogEntry, site).has_view_permission(Request(guild_admin))

    def test_a_guild_admin_sees_only_their_own_guilds_mappings(self, guild_admin, guild) -> None:
        from core.admin import RoleMappingAdmin, site
        from core.models import ConfiguredGuild, RoleMapping

        other = ConfiguredGuild.objects.create(guild_id=6000, name="Another Club")
        RoleMapping.objects.create(guild=other, role_id=9, permission=RoleMapping.Permission.MEMBER)

        visible = RoleMappingAdmin(RoleMapping, site).get_queryset(Request(guild_admin))
        assert {row.guild_id for row in visible} == {guild.id}


class TestTheLastInstanceAdmin:
    """There is no password login and no createsuperuser path on this
    deployment, so an instance admin who clears their own flag cannot be restored
    through the application at all. The recovery is a hand-written UPDATE against
    production, which is a worse position than this refusal creates.
    """

    def test_removing_the_last_instance_admin_is_refused(self, instance_admin) -> None:
        from core.models import LastInstanceAdmin

        instance_admin.is_instance_admin = False
        with pytest.raises(LastInstanceAdmin, match="appoint another first"):
            instance_admin.save()

    def test_banning_or_deleting_the_last_instance_admin_is_refused(self, instance_admin) -> None:
        """A ban takes the admin away as effectively as clearing the flag does,
        which is the whole point of deriving is_staff rather than storing it."""
        from core.models import LastInstanceAdmin

        instance_admin.is_banned = True
        with pytest.raises(LastInstanceAdmin):
            instance_admin.save()

        instance_admin.is_banned = False
        instance_admin.is_deleted = True
        with pytest.raises(LastInstanceAdmin):
            instance_admin.save()

    def test_removing_one_of_two_is_allowed(self, instance_admin) -> None:
        User = get_user_model()
        User.objects.create(discord_user_id=98765, is_instance_admin=True)
        instance_admin.is_instance_admin = False
        instance_admin.save()
        assert User.objects.filter(is_instance_admin=True).count() == 1

    def test_a_banned_admin_does_not_count_as_the_remaining_one(self, instance_admin) -> None:
        """Otherwise the last usable admin can be removed as long as an unusable
        one exists, which is the same failure with an extra step."""
        from core.models import LastInstanceAdmin

        get_user_model().objects.create(
            discord_user_id=98766, is_instance_admin=True, is_banned=True
        )
        instance_admin.is_instance_admin = False
        with pytest.raises(LastInstanceAdmin):
            instance_admin.save()


class TestInstanceAdminSurvivesADegradedDeployment:
    def test_the_admin_holds_when_every_guild_is_degraded_and_the_bot_is_down(
        self, instance_admin, guild
    ) -> None:
        """The case the degraded window exists to be survivable: the bot is down,
        every guild's standing has lapsed, and somebody still has to be able to
        reach the admin and mark a guild revoked."""
        from datetime import timedelta

        from core.admin import site
        from core.auth_backend import attach_standing

        guild.state = "degraded"
        guild.standing_valid_until = timezone.now() - timedelta(days=30)
        guild.save()

        attach_standing(instance_admin)
        assert instance_admin._admin_guild_ids == frozenset()
        assert instance_admin.is_staff, "the instance admin is not guild-derived"
        assert site.has_permission(Request(instance_admin))

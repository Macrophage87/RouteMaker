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

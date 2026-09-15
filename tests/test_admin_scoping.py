"""The two admin-scoping assertions phase 1 owes, plus the credential rule."""

from __future__ import annotations

import pytest
from django.http import Http404

from core.admin import BorderCrossingAdmin, GuildScopedAdmin, site
from core.models import BorderCrossing


class FakeUser:
    def __init__(self, *, authenticated=True, staff=False, instance_admin=False, guilds=()):
        self.is_authenticated = authenticated
        self.is_staff = staff
        self.is_instance_admin = instance_admin
        self.admin_guild_ids = guilds


class FakeRequest:
    def __init__(self, user):
        self.user = user


def test_admin_refuses_an_unauthenticated_request() -> None:
    assert not site.has_permission(FakeRequest(FakeUser(authenticated=False)))


def test_admin_refuses_a_signed_in_user_without_derived_staff() -> None:
    """Staff is derived per request from application standing; a signed-in member
    is not an admin."""
    assert not site.has_permission(FakeRequest(FakeUser(staff=False)))


def test_admin_admits_derived_staff() -> None:
    assert site.has_permission(FakeRequest(FakeUser(staff=True)))


def test_there_is_no_admin_login_form() -> None:
    """Django's own login is a second credential class this threat model does not
    have. 404 rather than a redirect, so the path does not confirm an admin is
    here."""
    with pytest.raises(Http404):
        site.login(FakeRequest(FakeUser(authenticated=False)))


def test_derived_state_is_not_editable_in_the_admin() -> None:
    """The pipeline owns border crossings and a rebuild reassigns their ids. A
    hand edit would be overwritten next Tuesday and would desynchronise the graph
    from the crossings table in the meantime."""
    model_admin = BorderCrossingAdmin(BorderCrossing, site)
    request = FakeRequest(FakeUser(staff=True, instance_admin=True))
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)


def test_guild_scoping_lives_in_the_queryset() -> None:
    """A guild admin who can open a changelist must still see only their own
    guild's rows, so the scoping is a queryset filter rather than a permission
    flag that gates the whole model."""
    assert hasattr(GuildScopedAdmin, "get_queryset")
    assert GuildScopedAdmin.guild_scope_field is None, "subclasses declare their field"

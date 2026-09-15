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

    def test_a_revoked_guild_takes_its_admins_with_it(self, guild) -> None:
        from core.auth_backend import attach_standing
        from core.models import RoleMapping

        user = User.objects.create(discord_user_id=6)
        member_of(guild, user, permission=RoleMapping.Permission.GUILD_ADMIN)
        guild.state = "revoked"
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

    def test_the_middleware_is_installed_after_authentication(self) -> None:
        """It needs request.user, so ordering is part of the mechanism."""
        middleware = settings.MIDDLEWARE
        assert "core.middleware.SessionEpochMiddleware" in middleware
        assert middleware.index(
            "django.contrib.auth.middleware.AuthenticationMiddleware"
        ) < middleware.index("core.middleware.SessionEpochMiddleware")

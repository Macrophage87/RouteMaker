"""Authentication and permissions from application standing.

Django's ModelBackend authenticates a stored password and answers `has_perm`
from `auth_permission` rows. This deployment has neither: there is no usable
password on any account, and with no superuser and no permission rows every
`has_perm` would return false, so the admin would render empty for everyone who
reached it. That is why the plan calls these mechanisms "specified rather than
implied" - Django does none of them by default.

The backend also resolves the guild standing the derived `is_staff` reads, once
per request rather than once per check.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import CachedMembership, ConfiguredGuild, RoleMapping, User
from .standing import MAX_ROW_AGE, MAX_STALE_GRANT


class DiscordStandingBackend:
    """Resolves standing. Authenticates nobody by credential, on purpose."""

    def authenticate(self, request, **kwargs):
        """No credential path exists. A login happens through the Discord
        callback, which fetches the user and calls `django.contrib.auth.login`
        directly; there is nothing here for a password to authenticate against."""
        return None

    def get_user(self, user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
        attach_standing(user)
        return user

    def has_perm(self, user_obj, perm, obj=None) -> bool:
        """Answered from standing, never from permission rows.

        Instance admin may act anywhere. A guild admin may act only within their
        own guilds, and the per-object decision belongs to the admin class,
        which knows what the object is; this grants the module-level access that
        lets them reach the page at all.
        """
        if not getattr(user_obj, "is_active", False):
            return False
        if getattr(user_obj, "is_instance_admin", False):
            return True
        return bool(getattr(user_obj, "_admin_guild_ids", ()))

    def has_module_perms(self, user_obj, app_label) -> bool:
        return self.has_perm(user_obj, f"{app_label}")


def attach_standing(user: User, now=None) -> None:
    """Resolve and cache this user's guild standing on the instance.

    Cached on the object rather than recomputed per check, because `is_staff`,
    every admin queryset and every permission call would otherwise each run the
    same query.
    """
    now = now or timezone.now()

    if user.is_banned or user.is_deleted:
        user._admin_guild_ids = frozenset()
        user._reviewer_guild_ids = frozenset()
        user._member_guild_ids = frozenset()
        return

    usable_guilds = {}
    for guild in ConfiguredGuild.objects.all():
        if guild.state == "revoked":
            continue
        if guild.state == "degraded":
            ceiling = guild.state_since + MAX_STALE_GRANT
            expiry = guild.standing_valid_until
            if expiry is None or now >= min(expiry, ceiling):
                continue
        usable_guilds[guild.id] = guild.guild_id

    rows = CachedMembership.objects.filter(
        discord_user_id=user.discord_user_id, guild_id__in=usable_guilds
    )

    mappings: dict[int, dict[int, str]] = {}
    for mapping in RoleMapping.objects.filter(guild_id__in=usable_guilds):
        mappings.setdefault(mapping.guild_id, {})[mapping.role_id] = mapping.permission

    admin, reviewer, member = set(), set(), set()
    for row in rows:
        if row.pending or row.removed_at is not None:
            continue
        if row.timed_out_until is not None and now < row.timed_out_until:
            continue
        if now - row.last_confirmed > MAX_ROW_AGE:
            continue

        guild_snowflake = usable_guilds[row.guild_id]
        member.add(guild_snowflake)
        for role_id in row.role_ids:
            permission = mappings.get(row.guild_id, {}).get(int(role_id))
            if permission == RoleMapping.Permission.REVIEWER:
                reviewer.add(guild_snowflake)
            elif permission == RoleMapping.Permission.GUILD_ADMIN:
                admin.add(guild_snowflake)

    user._admin_guild_ids = frozenset(admin)
    user._reviewer_guild_ids = frozenset(reviewer)
    user._member_guild_ids = frozenset(member)


def session_is_current(user: User, issued_epoch: int, created_at, last_seen_at, now=None) -> bool:
    """Whether a session survives. See `revocation` for the lifetimes."""
    from .revocation import ABSOLUTE_SESSION_LIFETIME, IDLE_SESSION_LIFETIME

    now = now or timezone.now()
    if issued_epoch != user.session_epoch:
        return False
    if now - created_at >= ABSOLUTE_SESSION_LIFETIME:
        return False
    return now - last_seen_at < IDLE_SESSION_LIFETIME


__all__ = ["DiscordStandingBackend", "attach_standing", "session_is_current", "timedelta"]

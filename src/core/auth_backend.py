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

from django.utils import timezone

from .models import CachedMembership, ConfiguredGuild, RoleMapping, User


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

    # Models only an instance admin may write. A guild admin may reach the admin
    # and see their own guild's rows, but the configured guild list is the
    # deployment's admission control: adding a row self-onboards a server, and
    # editing guild_id is an unaudited remap of the snowflake that every standing
    # check matches against.
    INSTANCE_ADMIN_ONLY_MODELS = frozenset(
        {
            "configuredguild",
            "jurisdiction",
            "override",
            "bantombstone",
            "user",
            # A mapping decides who holds guild admin, so a guild admin editing
            # their own guild's mapping is the definition of privilege
            # escalation.
            "rolemapping",
            # Nobody writes the log, including an instance admin. A log whose
            # entries can be edited from the surface it audits is not a log.
            "auditlogentry",
            # The table that decides which roles a person holds in which guild.
            # A row here grants any role in any guild, so writing one is a
            # broader grant than any mapping. It was reachable because the only
            # thing refusing it was CachedMembershipAdmin's own hook - one
            # override, on one class, with nothing behind it.
            "cachedmembership",
        }
    )
    WRITE_ACTIONS = ("add_", "change_", "delete_")

    def has_perm(self, user_obj, perm, obj=None) -> bool:
        """Answered from standing, never from permission rows.

        The permission string is read rather than ignored. Returning True for
        everything made every guild admin hold every permission on every model,
        so the only thing between them and an editable model was whether that
        particular ModelAdmin happened to override its hooks - and one did not.
        """
        if not getattr(user_obj, "is_active", False):
            return False
        if getattr(user_obj, "is_instance_admin", False):
            return True
        if not getattr(user_obj, "_admin_guild_ids", ()):
            return False

        action, _, model = perm.partition(".")[2].partition("_") if "." in perm else ("", "", "")
        codename = perm.split(".", 1)[-1]
        if any(codename.startswith(prefix) for prefix in self.WRITE_ACTIONS):
            target = codename.split("_", 1)[-1]
            if target in self.INSTANCE_ADMIN_ONLY_MODELS:
                return False
        return True

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

    # Both predicates come from `standing`, which is the module the authorization
    # tests exercise. They used to be reimplemented here - revoked, then
    # degraded, then the clamp; pending, then timeout, then row age - so the rule
    # under test and the rule the admin enforced were two pieces of code that
    # happened to agree, and nothing would have reported it when they stopped.
    usable_guilds = {
        guild.id: guild.guild_id
        for guild in ConfiguredGuild.objects.all()
        if guild.standing().grants_standing(now)
    }

    rows = CachedMembership.objects.filter(
        discord_user_id=user.discord_user_id, guild_id__in=usable_guilds
    )

    mappings: dict[int, dict[int, str]] = {}
    for mapping in RoleMapping.objects.filter(guild_id__in=usable_guilds):
        mappings.setdefault(mapping.guild_id, {})[mapping.role_id] = mapping.permission

    admin, reviewer, member = set(), set(), set()
    for row in rows:
        guild_snowflake = usable_guilds[row.guild_id]
        if not row.as_membership(guild_snowflake).is_usable(now):
            continue

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


__all__ = ["DiscordStandingBackend", "attach_standing", "session_is_current"]

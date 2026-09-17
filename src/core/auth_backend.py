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

from django.core.exceptions import ImproperlyConfigured
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
            # The table that grants any role in any guild. It was missing, so the
            # only thing between a guild admin and it was CachedMembershipAdmin's
            # own has_add_permission - and flipping that override to True left
            # the whole suite green.
            "cachedmembership",
            # Derived state the pipeline owns. A hand edit desynchronises the
            # crossings table from the graph until the next rebuild overwrites it.
            "bordercrossing",
        }
    )
    WRITE_ACTIONS = ("add_", "change_", "delete_")

    # Everything a guild admin holds, named one permission at a time.
    #
    # An allow-list rather than a deny-list, and the difference is not stylistic.
    # The deny-list this replaced answered True for every permission nobody had
    # thought to list, so a guild admin held `core.approve_override`,
    # `auth.add_permission` and `admin.delete_logentry`, and `has_module_perms`
    # answered True for every app label including `admin` and `auth`. Nothing was
    # exploitable only because every registered ModelAdmin happened to override
    # its own hooks - one of them did not, and the next surface to forget would
    # have been the first one that mattered. Phase 1's job is the pattern every
    # later admin surface follows, and the safe default for a permission that
    # does not exist yet is no.
    #
    # Reading only. Every write on every authorization table is an audited
    # action or an instance admin's, never a change form a guild admin can post.
    GUILD_ADMIN_PERMISSIONS = frozenset(
        {
            "core.view_configuredguild",
            "core.view_rolemapping",
            "core.view_cachedmembership",
            "core.view_bordercrossing",
            "core.view_jurisdiction",
            "core.view_override",
            # "the current instance admins are listed to every guild admin".
            # A proxy model with its own view permission, not `view_user`: the
            # account table is every account on the deployment and carries the
            # membership cache's sensitivity, while this one is the
            # instance-admin list and the Discord id. Naming the proxy here is
            # what keeps the two apart.
            "core.view_instanceadminlisting",
        }
    )

    def has_perm(self, user_obj, perm, obj=None) -> bool:
        """Answered from standing, never from permission rows."""
        if not getattr(user_obj, "is_active", False):
            return False
        if getattr(user_obj, "is_instance_admin", False):
            return True
        if not getattr(user_obj, "_admin_guild_ids", ()):
            return False
        return perm in self.GUILD_ADMIN_PERMISSIONS

    def has_module_perms(self, user_obj, app_label) -> bool:
        """Whether this person holds anything at all in that app.

        Answered from the allow-list rather than by handing the app label to
        `has_perm` as if it were a permission string, which is how every guild
        admin came to hold `has_module_perms("admin")` and
        `has_module_perms("auth")`: neither label starts with a write prefix, so
        the deny-list let both through.
        """
        if not getattr(user_obj, "is_active", False):
            return False
        if getattr(user_obj, "is_instance_admin", False):
            return True
        if not getattr(user_obj, "_admin_guild_ids", ()):
            return False
        prefix = f"{app_label}."
        return any(perm.startswith(prefix) for perm in self.GUILD_ADMIN_PERMISSIONS)


def check_guild_admin_allow_list(permissions, instance_admin_only) -> None:
    """A guild admin's allow-list may never name a write on a table that grants
    standing.

    Checked at import rather than left to review, so the two constants cannot
    drift apart silently: `INSTANCE_ADMIN_ONLY_MODELS` is the statement of which
    tables those are, and this is what makes that statement bind on the
    allow-list rather than only on the deny path that used to read it.
    """
    for perm in sorted(permissions):
        codename = perm.split(".", 1)[-1]
        if not codename.startswith(DiscordStandingBackend.WRITE_ACTIONS):
            continue
        target = codename.split("_", 1)[-1]
        if target in instance_admin_only:
            raise ImproperlyConfigured(
                f"{perm} grants a guild admin a write on {target}, which is "
                "instance-admin only; a guild admin editing it is privilege escalation"
            )


check_guild_admin_allow_list(
    DiscordStandingBackend.GUILD_ADMIN_PERMISSIONS,
    DiscordStandingBackend.INSTANCE_ADMIN_ONLY_MODELS,
)


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
            elif permission == RoleMapping.Permission.INSTANCE_ADMIN:
                # Deliberately nothing, and the branch exists so that is a
                # decision on the page rather than an omission.
                #
                # The plan makes instance admin "independent of every guild,
                # deriving from the instance-admin list alone and never from
                # guild membership, role mapping, the bot, or the membership
                # cache, so the people who can fix a broken bot can still sign in
                # when every guild is degraded". Honouring the mapping here would
                # make the deployment's one cross-guild role lapse with a club's
                # gateway connection - the exact failure that sentence rules out.
                #
                # Appointment happens in the user admin instead, audited. That
                # the mapping choice exists at all is an open owner decision;
                # see the note in PLAN.md's visibility section.
                pass

    user._admin_guild_ids = frozenset(admin)
    user._reviewer_guild_ids = frozenset(reviewer)
    user._member_guild_ids = frozenset(member)


def session_is_current(user: User, issued_epoch: int, created_at, last_seen_at, now=None) -> bool:
    """Whether a session survives. See `revocation` for the lifetimes."""
    from .revocation import ABSOLUTE_SESSION_LIFETIME, IDLE_SESSION_LIFETIME

    now = now or timezone.now()
    # Ban and deletion, belt to the epoch's braces. Both bump the epoch, so this
    # is redundant on every path that goes through `bump_session_epoch` - and it
    # is the one check that still refuses the session when a flag was set by a
    # migration, a fixture, or a hand-written UPDATE that never bumped anything.
    if not user.is_active:
        return False
    if issued_epoch != user.session_epoch:
        return False
    if now - created_at >= ABSOLUTE_SESSION_LIFETIME:
        return False
    return now - last_seen_at < IDLE_SESSION_LIFETIME


__all__ = [
    "DiscordStandingBackend",
    "attach_standing",
    "check_guild_admin_allow_list",
    "session_is_current",
]

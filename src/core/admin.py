"""The admin, and the pattern every later admin surface follows.

Three rules established here, because getting them right once is what makes the
phase 4 surfaces safe to add.

Authorization state is displayed, never edited. The admin's change forms would
otherwise sidestep every audited workflow in the plan: editing the cached
membership table grants any role in any guild, and editing a route's owning
guild does by hand what the remap does with preconditions, confirmation,
notification and an audit row.

Querysets are scoped per object, not per model. A guild admin who can open the
changelist for a model must still see only their own guild's rows, which means
the scoping lives in get_queryset rather than in a permission flag.

And the admin introduces no second credential. Django ships a username and
password login, which is a credential class this threat model does not have:
every other path is Discord-only, and a stored password would bypass all of it
and sit in the nightly dump.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404

from .models import BorderCrossing, CachedMembership, ConfiguredGuild, Jurisdiction, Override


class RouteMakerAdminSite(admin.AdminSite):
    """An admin reached only through a Discord session."""

    site_header = "RouteMaker"
    site_title = "RouteMaker"

    def has_permission(self, request) -> bool:
        """Staff status is derived per request from application standing.

        `is_active` is kept in the conjunction, as Django's own implementation
        has it: dropping it would leave a banned or deleted account holding the
        admin, which is precisely what a ban is supposed to end.
        """
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_active", False)
            and getattr(user, "is_staff", False)
        )

    def login(self, request, extra_context=None):
        """There is no admin login form. Returning 404 rather than redirecting
        keeps the path from confirming that an admin exists here."""
        raise Http404

    def password_change(self, request, extra_context=None):
        """Nor a password change. Django registers this for any staff user, and
        it is a path to setting a usable password on an account that must never
        have one."""
        raise Http404


site = RouteMakerAdminSite(name="routemaker_admin")


class GuildScopedAdmin(admin.ModelAdmin):
    """Base class carrying the scoping rule, so no later surface has to remember it.

    A subclass that forgets to declare its scope field raises rather than
    returning everything. The earlier version returned the unfiltered queryset,
    which made forgetting the field a silent cross-guild leak - the exact failure
    the class exists to prevent.
    """

    guild_scope_field: str | None = None

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if getattr(request.user, "is_instance_admin", False):
            return queryset
        if self.guild_scope_field is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} extends GuildScopedAdmin without declaring "
                "guild_scope_field; refusing to serve an unscoped queryset"
            )
        # Read from the resolver's own output rather than the user row, so a
        # guild that has gone revoked or whose degraded window lapsed drops out
        # of the admin as well as out of the API.
        guild_ids = getattr(request.user, "_admin_guild_ids", frozenset())
        return queryset.filter(**{f"{self.guild_scope_field}__in": guild_ids})


class InstanceAdminOnly(admin.ModelAdmin):
    """For deployment-wide content, where one club's admin must not act.

    Approving an override row changes routing for every guild, and a jurisdiction
    polygon decides which authority every route in the region reports. Model-level
    permissions cannot express that, so these are checked per request.
    """

    def _is_instance_admin(self, request) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_add_permission(self, request) -> bool:
        return self._is_instance_admin(request)

    def has_change_permission(self, request, obj=None) -> bool:
        return self._is_instance_admin(request)

    def has_delete_permission(self, request, obj=None) -> bool:
        return self._is_instance_admin(request)


@admin.register(Jurisdiction, site=site)
class JurisdictionAdmin(InstanceAdminOnly, GISModelAdmin):
    """Deployment-wide content: polygons are global and editing one changes what
    every guild sees, which is why this is instance-admin territory."""

    list_display = ("name", "layer", "state", "is_federal_enclave")
    list_filter = ("layer", "state", "is_federal_enclave")
    search_fields = ("name",)


@admin.register(Override, site=site)
class OverrideAdmin(InstanceAdminOnly):
    """Approval changes routing for every guild, so it is instance-admin only.

    The evidence field is required reading rather than a note: a check-only
    source may never be the sole basis for a row.
    """

    list_display = ("kind", "osm_way_id", "approved", "approved_at")
    list_filter = ("kind", "approved")
    search_fields = ("osm_way_id", "reason")
    # The approval flag itself is read-only: approval crosses guilds, so it is
    # an audited action rather than a checkbox on a change form. Locking only the
    # timestamp, as an earlier version did, was backwards.
    readonly_fields = ("approved", "approved_at")


@admin.register(ConfiguredGuild, site=site)
class ConfiguredGuildAdmin(GuildScopedAdmin):
    """A guild admin sees their own guild; an instance admin sees all of them."""

    guild_scope_field = "guild_id"
    list_display = ("guild_id", "name", "state", "state_since")
    list_filter = ("state",)
    readonly_fields = ("state", "state_since", "standing_valid_until")


@admin.register(CachedMembership, site=site)
class CachedMembershipAdmin(GuildScopedAdmin):
    """Displayed, never edited. Editing this table grants any role in any guild,
    which is why every authorization table here is read-only."""

    guild_scope_field = "guild__guild_id"
    list_display = ("discord_user_id", "guild", "last_confirmed", "pending")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(BorderCrossing, site=site)
class BorderCrossingAdmin(GISModelAdmin):
    """Derived state, displayed only. The pipeline owns these rows and a rebuild
    reassigns their ids; editing one by hand would be overwritten next Tuesday
    and would desynchronise the graph from the crossings table in the meantime."""

    list_display = ("node_id", "osm_way_id", "state_a", "state_b")
    search_fields = ("osm_way_id",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

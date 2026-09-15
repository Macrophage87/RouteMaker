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

from .models import (
    AuditLogEntry,
    BorderCrossing,
    CachedMembership,
    ConfiguredGuild,
    Jurisdiction,
    Override,
    RoleMapping,
)


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


def audit(request, action: str, model: str, object_id, outcome: str, detail: str = "") -> None:
    """Record one attempt at a privileged write.

    Every visibility assertion the plan makes about the admin ends in "and the
    attempt is audited". Without this the refusals were real and the record of
    them was not, so a refused edit and nobody having tried looked the same
    afterwards.

    Narrow on purpose, like the membership cache: who acted on what and whether
    it was allowed, never a copy of the row.
    """
    actor = getattr(request, "user", None)
    AuditLogEntry.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        model=model,
        object_id=str(object_id or ""),
        outcome=outcome,
        detail=detail[:2000],
    )


# A refusal is recorded by the very check that causes Django to raise
# PermissionDenied, and the admin runs that check inside `transaction.atomic()`.
# Writing the row there means the rollback that follows takes the record of the
# refusal with it, so the log ends up holding every harmless permission probe on
# a read-only page and none of the refused writes it exists for. These are
# buffered on the request instead and written by AuditFlushMiddleware once the
# response is out and that transaction is over.
PENDING_AUDIT_ATTR = "_routemaker_pending_audit"

# A permission probe on a safe method is not an attempt at anything. Rendering
# the admin index asks every registered model whether this person may add,
# change and delete; logging those made the read of a page indistinguishable
# from twenty-eight attempts to write one.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def defer_audit(request, action, model, object_id, outcome, detail="") -> None:
    """Queue an audit row to be written after the response, outside the atomic block."""
    pending = getattr(request, PENDING_AUDIT_ATTR, None)
    if pending is None:
        pending = []
        setattr(request, PENDING_AUDIT_ATTR, pending)
    actor = getattr(request, "user", None)
    pending.append(
        {
            "actor": actor if getattr(actor, "pk", None) else None,
            "action": action,
            "model": model,
            "object_id": str(object_id or ""),
            "outcome": outcome,
            "detail": detail[:2000],
        }
    )


def flush_deferred_audit(request) -> int:
    """Write the buffered rows. Returns how many, so a test can assert on it."""
    pending = getattr(request, PENDING_AUDIT_ATTR, None) or []
    if not pending:
        return 0
    AuditLogEntry.objects.bulk_create([AuditLogEntry(**row) for row in pending])
    setattr(request, PENDING_AUDIT_ATTR, [])
    return len(pending)


class AuditedAdmin(admin.ModelAdmin):
    """Records what was written, and what was refused.

    The refusal half matters more. Django asks `has_*_permission` and, when the
    answer is no, renders a 403 and calls nothing else - so the attempt leaves no
    trace anywhere unless the check itself writes one.
    """

    def _audited_permission(self, request, action: str, obj, allowed: bool) -> bool:
        if not allowed and getattr(request, "method", "") in WRITE_METHODS:
            defer_audit(
                request,
                action,
                self.model._meta.model_name,
                getattr(obj, "pk", None),
                AuditLogEntry.Outcome.REFUSED,
                detail=f"{type(self).__name__} refused {action}",
            )
        return allowed

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        audit(
            request,
            "change" if change else "add",
            self.model._meta.model_name,
            obj.pk,
            AuditLogEntry.Outcome.ALLOWED,
            detail=", ".join(sorted(form.changed_data)) if form else "",
        )

    def delete_model(self, request, obj) -> None:
        object_id = obj.pk
        super().delete_model(request, obj)
        audit(
            request,
            "delete",
            self.model._meta.model_name,
            object_id,
            AuditLogEntry.Outcome.ALLOWED,
        )


class GuildScopedAdmin(AuditedAdmin):
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


class InstanceAdminOnly(AuditedAdmin):
    """For deployment-wide content, where one club's admin must not act.

    Approving an override row changes routing for every guild, and a jurisdiction
    polygon decides which authority every route in the region reports. Model-level
    permissions cannot express that, so these are checked per request.
    """

    def _is_instance_admin(self, request) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_add_permission(self, request) -> bool:
        return self._audited_permission(request, "add", None, self._is_instance_admin(request))

    def has_change_permission(self, request, obj=None) -> bool:
        return self._audited_permission(request, "change", obj, self._is_instance_admin(request))

    def has_delete_permission(self, request, obj=None) -> bool:
        return self._audited_permission(request, "delete", obj, self._is_instance_admin(request))


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
    """A guild admin sees their own guild and can write almost nothing on it.

    Scoping a queryset is not the same as gating a write, which is the gap an
    earlier version left: adding a row here self-onboards a server and pushes an
    arbitrary roster into the database, and editing `guild_id` is an unaudited
    remap of the snowflake every standing check matches against - the action the
    plan routes through a dedicated workflow with preconditions, confirmation and
    notification. Deleting cascades away every role mapping and membership row.
    """

    guild_scope_field = "guild_id"
    list_display = ("guild_id", "name", "state", "state_since")
    list_filter = ("state",)
    readonly_fields = ("guild_id", "state", "state_since", "standing_valid_until")

    def has_add_permission(self, request) -> bool:
        allowed = bool(getattr(request.user, "is_instance_admin", False))
        return self._audited_permission(request, "add", None, allowed)

    def has_delete_permission(self, request, obj=None) -> bool:
        allowed = bool(getattr(request.user, "is_instance_admin", False))
        return self._audited_permission(request, "delete", obj, allowed)


@admin.register(CachedMembership, site=site)
class CachedMembershipAdmin(GuildScopedAdmin):
    """Displayed, never edited. Editing this table grants any role in any guild,
    which is why every authorization table here is read-only."""

    guild_scope_field = "guild__guild_id"
    list_display = ("discord_user_id", "guild", "last_confirmed", "pending")

    def has_add_permission(self, request) -> bool:
        return self._audited_permission(request, "add", None, False)

    def has_change_permission(self, request, obj=None) -> bool:
        return self._audited_permission(request, "change", obj, False)

    def has_delete_permission(self, request, obj=None) -> bool:
        return self._audited_permission(request, "delete", obj, False)


@admin.register(RoleMapping, site=site)
class RoleMappingAdmin(GuildScopedAdmin):
    """One Discord role to one application permission, within one guild.

    The plan names this page in phase 1 and it was not registered at all, so the
    only way to grant standing in a new guild was a hand-written INSERT. It is
    also the surface the visibility assertions are about: a guild admin who could
    edit another guild's mapping could grant themselves any permission there, and
    one who could edit `guild` could move a mapping wholesale.

    Instance-admin only for writes, because a mapping decides who holds guild
    admin and a guild admin editing their own guild's mapping is the definition
    of privilege escalation. A guild admin sees their own guild's rows and
    nothing else.
    """

    guild_scope_field = "guild__guild_id"
    list_display = ("guild", "role_id", "permission")
    list_filter = ("permission",)
    search_fields = ("role_id",)

    def _is_instance_admin(self, request) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_add_permission(self, request) -> bool:
        return self._audited_permission(request, "add", None, self._is_instance_admin(request))

    def has_change_permission(self, request, obj=None) -> bool:
        return self._audited_permission(request, "change", obj, self._is_instance_admin(request))

    def has_delete_permission(self, request, obj=None) -> bool:
        return self._audited_permission(request, "delete", obj, self._is_instance_admin(request))


@admin.register(AuditLogEntry, site=site)
class AuditLogEntryAdmin(admin.ModelAdmin):
    """Read-only, to everyone, including an instance admin.

    A log whose entries can be edited or deleted from the surface it audits is
    not a log. Instance-admin only to *read*, because it names who acted where
    and that is the same sensitivity as the membership cache.
    """

    list_display = ("at", "actor", "action", "model", "object_id", "outcome")
    list_filter = ("outcome", "action", "model")
    search_fields = ("object_id", "detail")
    readonly_fields = ("at", "actor", "action", "model", "object_id", "outcome", "detail")
    ordering = ("-at",)

    def has_view_permission(self, request, obj=None) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_module_permission(self, request) -> bool:
        return self.has_view_permission(request)

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

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

from functools import update_wrapper

from django import forms
from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.http import Http404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from .audit import record as record_audit
from .models import (
    AuditLogEntry,
    BorderCrossing,
    CachedMembership,
    ConfiguredGuild,
    Jurisdiction,
    LastInstanceAdmin,
    Override,
    RoleMapping,
    User,
    check_last_instance_admin,
)
from .revocation import revoke_guild


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

    def admin_view(self, view, cacheable=False):
        """Django's version redirects an unadmitted request to the login page.

        That is a 302 naming the admin path, on a deployment whose whole posture
        is that the path is not advertised - so `GET <path>/` answered "there is
        an admin here, go and log in" while `login` itself answered 404 and the
        docstring claimed the path did not confirm anything. Refusing with the
        same 404 the rest of the site gives an unknown URL makes the two agree.

        Everything else is Django's own wrapper: never_cache unless the view says
        otherwise, csrf_protect unless it is exempt.
        """

        def inner(request, *args, **kwargs):
            if not self.has_permission(request):
                raise Http404
            return view(request, *args, **kwargs)

        if not cacheable:
            inner = never_cache(inner)
        if not getattr(view, "csrf_exempt", False):
            inner = csrf_protect(inner)
        return update_wrapper(inner, view)

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
    """Record one attempt at a privileged write, with the request's actor."""
    actor = getattr(request, "user", None)
    record_audit(actor, action, model, object_id, outcome, detail)


class AuditedAdmin(admin.ModelAdmin):
    """Records what was written, and what was refused.

    The refusal half is where this was wrong, and wrong in the direction that
    makes a log worse than none.

    Refusals used to be written from inside `has_add_permission` and its
    siblings. Two things follow from that and both were measured. Django calls
    those hooks several times per page while *rendering* - to decide whether to
    draw an Add button, a delete link, an inline - so a read-only changelist GET
    wrote about twenty rows, none of which was an attempt at anything. And
    Django calls them from inside `transaction.atomic` in `changeform_view` and
    `delete_view` and then raises `PermissionDenied`, which rolls the refusal
    row back along with everything else: one row when the call was made outside a
    transaction, zero inside. So the log flooded on navigation and recorded
    nothing on the refusals it exists for.

    Both halves have the same cause: a permission probe is not an attempt. What
    is an attempt is a POST. So the hooks are plain predicates again, and the
    write happens here - around the view, outside the atomic block, after
    `PermissionDenied` has already unwound it. No second connection and no
    `on_commit` (which would be discarded by the rollback); the row is simply
    written where no transaction is holding it.
    """

    def _audit_refusal(self, request, action: str, object_id=None) -> None:
        record_audit(
            getattr(request, "user", None),
            action,
            self.model._meta.model_name,
            object_id,
            AuditLogEntry.Outcome.REFUSED,
            detail=f"{type(self).__name__} refused {action} over {request.method}",
        )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except PermissionDenied:
            self._audit_refusal(request, "change" if object_id else "add", object_id)
            raise

    def delete_view(self, request, object_id, extra_context=None):
        if request.method != "POST":
            return super().delete_view(request, object_id, extra_context)
        try:
            return super().delete_view(request, object_id, extra_context)
        except PermissionDenied:
            self._audit_refusal(request, "delete", object_id)
            raise

    def changelist_view(self, request, extra_context=None):
        if request.method != "POST":
            return super().changelist_view(request, extra_context)
        try:
            return super().changelist_view(request, extra_context)
        except PermissionDenied:
            selected = ",".join(request.POST.getlist("_selected_action"))
            self._audit_refusal(request, "action", selected)
            raise

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

    actions = ("revoke_now",)

    def has_add_permission(self, request) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_change_permission(self, request, obj=None) -> bool:
        """Every field on this form is read-only, so a change POST can only ever
        be a no-op or an attempt at one of them. Instance admins keep the verb
        because the form is how they read a guild; nobody else gets to post to
        it at all."""
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_delete_permission(self, request, obj=None) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def may_revoke(self, request, guild) -> bool:
        """Who may collapse a guild's window at once.

        "Either way an instance admin, or an admin of the affected guild, can
        collapse the window at once with an audited revoke-now action." An admin
        of the affected guild, and of no other: the changelist queryset already
        scopes what they can select, and this is the second half of that, checked
        per object so a hand-built POST cannot reach past it.
        """
        if getattr(request.user, "is_instance_admin", False):
            return True
        return guild.guild_id in getattr(request.user, "_admin_guild_ids", frozenset())

    @admin.action(description="Revoke now - end this guild's standing immediately")
    def revoke_now(self, request, queryset) -> None:
        """The transition the degraded window has had no way into.

        `should_mark_degraded` and `degraded_window` were correct, tested, and
        called from nowhere; nothing wrote `ConfiguredGuild.state` at all, so a
        guild could never be marked degraded or revoked and the plan's audited
        revoke-now existed on no surface.
        """
        now = timezone.now()
        revoked = 0
        for guild in queryset:
            if not self.may_revoke(request, guild):
                self._audit_refusal(request, "revoke_now", guild.pk)
                self.message_user(
                    request,
                    f"Refused: {guild} is not yours to revoke.",
                    level=messages.ERROR,
                )
                continue
            revoke_guild(guild, actor=request.user, now=now, reason="revoke-now from the admin")
            revoked += 1
        if revoked:
            self.message_user(request, f"Revoked {revoked} guild(s).", level=messages.WARNING)


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
        return self._is_instance_admin(request)

    def has_change_permission(self, request, obj=None) -> bool:
        return self._is_instance_admin(request)

    def has_delete_permission(self, request, obj=None) -> bool:
        return self._is_instance_admin(request)


@admin.register(AuditLogEntry, site=site)
class AuditLogEntryAdmin(AuditedAdmin):
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
class BorderCrossingAdmin(AuditedAdmin, GISModelAdmin):
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


class InstanceAdminFlagForm(forms.ModelForm):
    """The one editable thing on an account, with the lockout guard in front.

    `check_last_instance_admin` lives in `User.save()` so every path reaches it,
    and it raises. Raising out of `save_model` would be a 500 on the change form:
    correct refusal, unreadable delivery. Clearing it here turns the same rule
    into the field error the person who tried to clear the box needs to read.
    """

    class Meta:
        model = User
        fields = ("is_instance_admin",)

    def clean_is_instance_admin(self):
        value = self.cleaned_data["is_instance_admin"]
        if self.instance.pk and not value:
            try:
                # `self.instance` still carries the stored values here: the form
                # writes cleaned data onto it later, in _post_clean.
                check_last_instance_admin(self.instance, removing=True)
            except LastInstanceAdmin as error:
                raise forms.ValidationError(str(error)) from error
        return value


@admin.register(User, site=site)
class UserAdmin(InstanceAdminOnly):
    """Appointing instance admins, and nothing else.

    Registered because without it a deployment had exactly one instance admin
    forever: `is_instance_admin` is a stored flag with no surface that writes it,
    there is no password login and no `createsuperuser`, and
    `check_last_instance_admin` refuses to let the one there is step down. The
    plan says instance admins "are then added and removed in the admin, audited",
    and this is that page.

    Deliberately narrow. Accounts are created by signing in, never here, so there
    is no add. Deletion is the account-deletion flow - tombstone, cached rows,
    route reassignment - and a row deleted from a change list is none of that, so
    there is no delete either. Ban and suspension are moderation and arrive with
    the rest of it; every other field is displayed and locked.

    Instance-admin only to *read*, not just to write: this list is every account
    on the deployment, which is the same sensitivity as the membership cache.
    """

    form = InstanceAdminFlagForm
    list_display = ("discord_user_id", "is_instance_admin", "is_banned", "is_deleted", "last_login")
    list_filter = ("is_instance_admin", "is_banned", "is_deleted")
    search_fields = ("discord_user_id",)
    readonly_fields = (
        "discord_user_id",
        "is_banned",
        "is_deleted",
        "session_epoch",
        "created_at",
        "last_login",
    )
    fields = ("discord_user_id", "is_instance_admin", "is_banned", "is_deleted", "last_login")

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def has_view_permission(self, request, obj=None) -> bool:
        return self._is_instance_admin(request)

    def has_module_permission(self, request) -> bool:
        return self._is_instance_admin(request)


@receiver(pre_delete, sender=User, dispatch_uid="core.refuse_deleting_the_last_instance_admin")
def _refuse_deleting_the_last_instance_admin(sender, instance, **kwargs) -> None:
    """The half of the lockout guard `save()` cannot cover.

    `check_last_instance_admin` is called from `User.save()`, so `.delete()` -
    on an instance or on a queryset - walks straight past it and can empty the
    instance-admin list from a management shell. `pre_delete` fires per object
    for both, which closes that.

    `.update()` is not closed and cannot be from here: it issues one UPDATE and
    emits no signal at all. Closing it needs a manager on the model, which lives
    in another owner's file; until then it is a stated limitation, and the two
    paths that a person or a surface actually takes - the admin, which has no
    delete, and `save()` - are both guarded.

    Registered in this module because `django.contrib.admin` imports it on every
    Django setup, so the guard is live for management commands and the worker as
    well as for the admin.
    """
    if instance.is_instance_admin:
        check_last_instance_admin(instance, removing=True)

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
    DriftReport,
    InstanceAdminListing,
    Jurisdiction,
    LastInstanceAdmin,
    Override,
    PendingInstanceAdminRemoval,
    RoleMapping,
    Session,
    User,
    ValhallaUpstream,
    cancel_instance_admin_removal,
    check_last_instance_admin,
    claim_bootstrap_instance_admin,
    schedule_instance_admin_removal,
)
from .revocation import revoke_guild
from .widgets import SelfHostedOpenLayersWidget


class RouteMakerAdminSite(admin.AdminSite):
    """An admin reached only through a Discord session."""

    site_header = "RouteMaker"
    site_title = "RouteMaker"

    def has_permission(self, request) -> bool:
        """Staff status is derived per request from application standing.

        `is_active` is kept in the conjunction, as Django's own implementation
        has it: dropping it would leave a banned or deleted account holding the
        admin, which is precisely what a ban is supposed to end.

        This is also where a new deployment gets its first instance admin. The
        plan's bootstrap id "grants standing only while the instance-admin list
        is empty", and "the first successful admin action writes the bootstrap
        id into the list and permanently disables the environment path,
        audited". The first request this site admits is that first action, so
        the claim is attempted here, before the request is admitted, and
        everything downstream runs as an ordinary instance admin rather than
        under a second kind of standing that every later surface would have to
        know about. `claim_bootstrap_instance_admin` is a no-op - and issues no
        query at all - unless the variable is set and names this account.
        """
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "is_active", False):
            claim_bootstrap_instance_admin(user)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_active", False)
            and getattr(user, "is_staff", False)
        )

    def logout(self, request, extra_context=None):
        """Django's admin logout flushes its own session and leaves this
        deployment's `core.Session` row behind.

        That row is what ban, suspension, deletion and sign-out-everywhere act
        on, and a row nothing will ever accept again is a user id and a pair of
        timestamps sitting in the table until the sweep reaches it. The site's
        own `logout_view` deletes it; this path did not, so whether signing out
        left a trace depended on which of two buttons was pressed.

        The order matters. Django 5's admin logout is `LogoutView`, which is
        POST-only and answers a GET with 405 - but this method runs before that
        dispatch, so deleting first meant a GET deleted the row and *then* got
        its 405: an `<img src="<admin>/logout/">` on any page anywhere signed an
        admin out, with no CSRF token, no audit row and no same-origin check.
        So `super()` goes first and its own dispatch is the gate; the row is
        deleted only on the method Django actually accepted. The check is not a
        decorator here on purpose: wrapping this method would answer the GET
        itself and change the 405 Django owes.
        """
        key = request.session.session_key
        response = super().logout(request, extra_context)
        if key and request.method == "POST":
            Session.objects.filter(session_key=key).delete()
        return response

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

    def password_change_done(self, request, extra_context=None):
        """And nor its confirmation page, which is a separate URL.

        `AdminSite.get_urls` registers `password_change/` and
        `password_change/done/` as two views, and only the first was overridden.
        Measured: a signed-in instance admin got 404 from `password_change/` and
        200 from `password_change/done/` - a page reading "Your password was
        changed" on a deployment where no account has a password and none was
        changed. It is not a way to set one, so this is not an escalation; it is
        a surface that contradicts the rule the line above it states, and the
        first person to reach it would reasonably conclude the password path is
        live. Both halves answer the same 404.
        """
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
            self._refuse_unpermitted_action(request)
            return super().changelist_view(request, extra_context)
        except PermissionDenied:
            selected = ",".join(request.POST.getlist("_selected_action"))
            self._audit_refusal(request, "action", selected)
            raise

    def _refuse_unpermitted_action(self, request) -> None:
        """Posting a bulk action the viewer does not hold is a refused write.

        Django's own answer is to say nothing. `get_actions` filters the action
        list by the viewer's permissions, `changelist_view` calls
        `response_action` only when that filtered list is non-empty, and when it
        is empty the POST falls through to an ordinary render. Measured: a guild
        admin posting `delete_selected` at a table they may read got 200 and the
        message "No action selected", and the audit log recorded nothing - while
        the plan says of exactly this shape of attempt that it is "refused and
        audited".

        So the check is made before the view runs: a named action that is not in
        the viewer's own action list is `PermissionDenied`, which the wrapper
        above records like every other refusal. An action they do hold is not
        touched here and goes through the action's own per-object checks.
        """
        requested = request.POST.get("action", "")
        if requested and requested not in self.get_actions(request):
            raise PermissionDenied

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

    def delete_queryset(self, request, queryset) -> None:
        """The other delete, and the one that had no audit row at all.

        `delete_model` is the single-object confirmation page. The changelist's
        `delete_selected` action never calls it: it calls this, once, with the
        whole queryset. Measured: two role mappings deleted in bulk left zero
        rows in this deployment's audit log - two in `django_admin_log`, which
        is not registered here and is not the log the plan means - and the same
        held on the configured guild, jurisdiction and override pages. A
        deletion that leaves no record is exactly what the log exists to stop
        being possible, and the bulk path is the cheap way to do several.

        Each object is audited individually, with its identity captured before
        the delete because afterwards there is nothing to read it from.
        """
        model_name = self.model._meta.model_name
        doomed = [(obj.pk, str(obj)) for obj in queryset]
        super().delete_queryset(request, queryset)
        for object_id, label in doomed:
            audit(
                request,
                "delete",
                model_name,
                object_id,
                AuditLogEntry.Outcome.ALLOWED,
                detail=f"bulk delete of {label}",
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
    every guild sees, which is why this is instance-admin territory.

    `GISModelAdmin` is what makes the polygon editable by drawing rather than by
    typing WKT into a textarea, which is the whole reason PLAN.md:52 chose
    Django here - "jurisdiction overrides, closures, and way-level corrections
    are edited by drawing on a map in the admin rather than in a second bespoke
    editor". It stays. What does not stay is its default widget: `gis_widget`
    defaults to `OSMWidget`, whose media loads OpenLayers from jsdelivr into an
    instance admin's authenticated session and whose template emits
    `ol.source.OSM()` - the public tile servers PLAN.md:15 rules out. See
    core/widgets.py.
    """

    gis_widget = SelfHostedOpenLayersWidget

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
    """A guild admin sees their own guild and may write its two guild-scoped
    fields on it: `name` and `admin_contact_email`, and nothing else.

    Scoping a queryset is not the same as gating a write, which is the gap an
    earlier version left: adding a row here self-onboards a server and pushes an
    arbitrary roster into the database, and editing `guild_id` is an unaudited
    remap of the snowflake every standing check matches against - the action the
    plan routes through a dedicated workflow with preconditions, confirmation and
    notification. Deleting cascades away every role mapping and membership row.
    All three stay instance-admin only.

    The state columns are read-only to everyone including an instance admin,
    because `state` and `standing_valid_until` are what the degraded window and
    the revoke-now action write; a guild that could type its own standing window
    into a form would not have one.
    """

    guild_scope_field = "guild_id"
    list_display = ("guild_id", "name", "state", "state_since")
    list_filter = ("state",)
    readonly_fields = ("guild_id", "state", "state_since", "standing_valid_until")

    actions = ("revoke_now",)

    def has_add_permission(self, request) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_change_permission(self, request, obj=None) -> bool:
        """A guild admin may edit their own guild's two guild-scoped fields.

        The docstring this replaces said "every field on this form is read-only,
        so a change POST can only ever be a no-op or an attempt at one of them",
        and that was simply not true of the form: `readonly_fields` names four
        columns and the model has six, so `name` and `admin_contact_email` were
        editable and audited the whole time. A permission docstring that
        misdescribes the form it gates is worse than none, because it is what
        the next person reads instead of the field list.

        Which way to resolve it is the plan's, not a judgement call. PLAN.md:208
        puts "the admin contact address" at **guild** scope, "set by that guild's
        admin and applying only to routes whose owning guild it is", and
        PLAN.md:210 gives a guild admin leave to "edit that guild's own
        settings". So the two editable columns are exactly right, and the gate
        widens to match the form rather than the form narrowing to match a
        sentence that was never the plan's.

        Object-level, and that is the whole of it. `get_queryset` already scopes
        the changelist, but scoping a list is not gating a write: a hand-built
        POST at another guild's id has to be refused by something, and this is
        that something. Returning False for `obj is None` is deliberate too -
        Django checks this hook before it checks whether the row was found, so a
        guild admin posting at a row outside their scope gets the 403 and the
        refused audit row the attempt deserves rather than a bare 404.

        What does not widen: `guild_id`, `state`, `state_since` and
        `standing_valid_until` stay in `readonly_fields` for everyone, so the
        unaudited remap and a self-granted standing window remain impossible;
        add and delete remain instance-admin only above and below this.
        """
        if getattr(request.user, "is_instance_admin", False):
            return True
        if obj is None:
            return False
        return obj.guild_id in getattr(request.user, "_admin_guild_ids", frozenset())

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

    list_display = ("at", "actor_label", "action", "model", "object_id", "outcome")
    list_filter = ("outcome", "action", "model")
    search_fields = ("object_id", "detail")
    readonly_fields = (
        "at",
        "actor",
        "actor_user_id",
        "actor_label",
        "action",
        "model",
        "object_id",
        "outcome",
        "detail",
    )
    ordering = ("-at",)

    @admin.display(description="actor", ordering="actor_user_id")
    def actor_label(self, obj) -> str:
        """Who acted, with a deleted account distinguished from no actor.

        The foreign key is `SET_NULL`, so a row a worker wrote and a row a named
        person wrote before their account was deleted were the same row read
        from this page. The plan asks for the id to be kept and the row to read
        "deleted user"; the column beside the key is what makes that possible,
        and this is where it is displayed.
        """
        return obj.actor_label()

    def has_view_permission(self, request, obj=None) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_module_permission(self, request) -> bool:
        """Belt and braces, and currently only braces.

        Flipping this to True changes nothing observable and no test can catch
        it: `AdminSite._build_app_dict` skips any model whose four model perms
        are all False before it ever looks at the app list, and the four below
        are. Recorded so the next person to find it surviving a mutation does not
        spend the afternoon writing a test that cannot exist. It stays because it
        is the correct answer to the question, and because it is what would hold
        if one of the four below ever became True.
        """
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

    # Read-only pages still build the form, and a form still carries its
    # widget's media, so this page loaded the CDN script too. "No CDN reference
    # anywhere in the rendered admin" means every GIS surface, not just the one
    # the finding named.
    gis_widget = SelfHostedOpenLayersWidget

    list_display = ("node_id", "osm_way_id", "state_a", "state_b")
    search_fields = ("osm_way_id",)

    def _relation_exists(self) -> bool:
        """Whether the crossings table is there to be read.

        It is unmanaged and lives in the schema the weekly swap renames, so
        `migrate` does not create it and it does not exist at all until a
        rebuild has run. Opening this changelist on a freshly deployed box
        therefore raised `ProgrammingError` - an unhandled 500 on a read-only
        page, from the one state every new deployment starts in.
        """
        from django.db import connection

        return self.model._meta.db_table in connection.introspection.table_names()

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not self._relation_exists():
            # `none()` is resolved without a query, so the page renders empty
            # rather than reaching for a relation that is not there.
            return queryset.none()
        return queryset

    def changelist_view(self, request, extra_context=None):
        if not self._relation_exists():
            self.message_user(
                request,
                "No tile build has run on this deployment yet, so the border-crossing "
                "table does not exist. The first rebuild creates it.",
                level=messages.WARNING,
            )
        return super().changelist_view(request, extra_context)

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

    # Set per request by `UserAdmin.get_form`. The refusal below is a refused
    # policy write and has to reach the audit log with the actor on it, and a
    # form does not otherwise know who is posting to it.
    request = None

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
                # Recorded here rather than left as a form error alone. This is
                # the deployment's lockout guard refusing a write, which is the
                # definition of what this log is for, and it was the one refusal
                # path that wrote nothing: a 200 with a field error and zero
                # audit rows, indistinguishable from nobody having tried.
                #
                # Written from inside the form's own validation, which runs
                # inside `changeform_view`'s atomic block - and survives,
                # because an invalid form is a rendered 200 rather than an
                # exception, so the transaction commits. The refusals that had
                # to move outside the block are the ones that raise.
                if self.request is not None:
                    record_audit(
                        getattr(self.request, "user", None),
                        "change",
                        "user",
                        self.instance.pk,
                        AuditLogEntry.Outcome.REFUSED,
                        detail=f"refused to remove the last instance admin: {error}",
                    )
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

    def get_form(self, request, obj=None, change=False, **kwargs):
        """Hand the form the request, so its one refusal can be audited.

        `modelform_factory` builds a fresh class per call, so setting the
        attribute here does not leak the request into another request's form.
        """
        form = super().get_form(request, obj, change=change, **kwargs)
        form.request = request
        return form

    def save_model(self, request, obj, form, change) -> None:
        """Removing somebody else's instance admin schedules it; it does not do
        it.

        "Removing an instance admin other than yourself notifies every remaining
        instance admin and the removed party and takes effect after a delay,
        configurable and defaulting to an hour, during which any instance admin
        can cancel it; without that, one admin could remove every peer down to
        themselves in a single audited but unstoppable action." Measured before
        this: three POSTs, one admin left, no delay and nothing to cancel.

        So the flag is left exactly as it was and a pending row is written
        instead. The person stays an instance admin for the length of the
        window, which is what makes the window one - a delay that takes the
        powers away immediately and only records the removal later is a
        notification, not a delay.

        Standing down is not routed through this. The delay guards against being
        removed by somebody else; an admin clearing their own flag has no peer
        to appeal to, and the plan says self-removal is immediate.

        The notification half has no channel in phase 1 - there is no Discord DM
        path and no email path in this deployment - so it is an outstanding gap
        rather than something this pretends to do.
        """
        previous = User.objects.filter(pk=obj.pk).first() if change else None
        removing_someone_else = (
            previous is not None
            and previous.is_instance_admin
            and not obj.is_instance_admin
            and obj.pk != getattr(request.user, "pk", None)
        )
        if removing_someone_else:
            obj.is_instance_admin = True
            pending = schedule_instance_admin_removal(previous, actor=request.user)
            self.message_user(
                request,
                f"{previous} stays an instance admin until {pending.effective_at:%Y-%m-%d %H:%M} "
                "UTC. Any instance admin can cancel it before then, on the pending "
                "instance admin removals page.",
                level=messages.WARNING,
            )
            return
        super().save_model(request, obj, form, change)


@admin.register(PendingInstanceAdminRemoval, site=site)
class PendingInstanceAdminRemovalAdmin(InstanceAdminOnly):
    """The window, and the cancel that is the point of having one.

    Displayed only, with one action. Editing an effective time by hand would
    make the delay whatever the person removing a peer wants it to be, and
    deleting a row from a change list is a cancel with no audit row, so both
    are closed and the action is the way through.
    """

    list_display = ("user", "requested_by", "requested_at", "effective_at")
    readonly_fields = (
        "user",
        "requested_by",
        "requested_by_user_id",
        "requested_at",
        "effective_at",
    )
    ordering = ("effective_at",)
    actions = ("cancel_removal",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def has_view_permission(self, request, obj=None) -> bool:
        return self._is_instance_admin(request)

    def has_module_permission(self, request) -> bool:
        return self._is_instance_admin(request)

    @admin.action(description="Cancel - this removal will not take effect")
    def cancel_removal(self, request, queryset) -> None:
        cancelled = 0
        for pending in queryset:
            cancel_instance_admin_removal(pending, actor=request.user)
            cancelled += 1
        if cancelled:
            self.message_user(
                request, f"Cancelled {cancelled} pending removal(s).", level=messages.INFO
            )


@admin.register(InstanceAdminListing, site=site)
class InstanceAdminListingAdmin(AuditedAdmin):
    """Who holds instance admin, readable by every guild admin.

    "It is visible to the clubs it holds power over: the current instance admins
    are listed to every guild admin." They could see nothing of it: the only
    page naming instance admins is the whole account table, which carries the
    membership cache's sensitivity and is instance-admin only.

    Read-only to everyone, and narrow on purpose: the queryset is the instance
    admins and the column is the Discord id.

    What keeps this apart from the account table is the pair of permission
    overrides below - `has_view_permission`, which refuses every object-level
    request so the change form (which would render the rest of the account row)
    is unreachable, and `has_module_permission`. The allow-list entry
    `core.view_instanceadminlisting` in `DiscordStandingBackend` is what lets a
    guild admin past `has_perm` at all, and naming the proxy there rather than
    `core.view_user` is deliberate - but it grants nothing this class does not
    also allow, so it is redundant-but-correct rather than the separation
    itself. An earlier version of this docstring said the reverse, which would
    have sent the next reader looking at the wrong file.

    Narrow means narrow in three directions, not one.

    The column is the Discord id. The *filters* are none at all, and
    `lookup_allowed` refuses every lookup but that column: `ModelAdmin`'s own
    implementation permits any lookup on a local field, and this proxy's local
    fields are `User`'s, so `?is_banned__exact=1`, `?session_epoch__gt=0` and
    `?last_login__isnull=0` all answered 200 with the matching rows removed from
    the list - which is an oracle over the ban state, the sign-in state and the
    revocation state of every instance admin, readable by any guild admin. That
    is the whole of what this page was supposed not to disclose.

    And the queryset is the admins who actually hold it: `is_instance_admin`
    alone would list a banned or deleted holder as current, while
    `check_last_instance_admin` - the rule that decides whether the list is
    empty - counts neither. A page that answers a different question from the
    rule it is a view of is worse than no page.
    """

    list_display = ("discord_user_id",)
    list_display_links = None
    ordering = ("discord_user_id",)
    # No filters, and nothing to turn into one. `list_filter` is written out
    # rather than left to the default so that adding one is a visible edit.
    list_filter = ()
    search_fields = ()
    date_hierarchy = None

    # The only lookup this page will answer. Not a prefix match: `discord_user_id`
    # exactly, so `discord_user_id__in` and friends cannot be used to binary-search
    # the list either.
    ALLOWED_LOOKUPS = frozenset({"discord_user_id"})

    def lookup_allowed(self, lookup, value, request=None) -> bool:
        return lookup in self.ALLOWED_LOOKUPS

    def get_queryset(self, request):
        # Banned and deleted excluded, matching `check_last_instance_admin`.
        return (
            super()
            .get_queryset(request)
            .filter(is_instance_admin=True, is_banned=False, is_deleted=False)
        )

    def _may_read(self, request) -> bool:
        user = getattr(request, "user", None)
        return bool(
            getattr(user, "is_instance_admin", False)
            or getattr(user, "_admin_guild_ids", frozenset())
        )

    def has_view_permission(self, request, obj=None) -> bool:
        # The list, and only the list. With an object this is the change form,
        # which Django serves read-only to a viewer and which would show the
        # rest of the account row.
        return obj is None and self._may_read(request)

    def has_module_permission(self, request) -> bool:
        return self._may_read(request)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


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


@admin.register(ValhallaUpstream, site=site)
class ValhallaUpstreamAdmin(admin.ModelAdmin):
    """The swap's settings table, displayed only. The rebuild writes it at the
    swap and the rollback writes it back; a hand edit would point the API at a
    build no container is serving."""

    list_display = ("variant", "url", "build_id", "previous_build_id", "updated_at")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(DriftReport, site=site)
class DriftReportAdmin(admin.ModelAdmin):
    """What each swap changed, for the morning after."""

    list_display = (
        "build_id",
        "created_at",
        "segments_before",
        "segments_after",
        "segments_lost",
        "segments_added",
        "segments_regraded",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


from . import admin_operations  # noqa: E402,F401  - the operations page registers on import

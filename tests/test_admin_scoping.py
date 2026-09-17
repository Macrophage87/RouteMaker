"""The two admin-scoping assertions phase 1 owes, plus the credential rule."""

from __future__ import annotations

import pytest
from django.conf import settings
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


ADMIN_WRITE_VERBS = ("add", "change", "delete")

# Every admin surface that fronts a table deciding who holds what. The point of
# naming them here is that the write assertions below are parametrized over this
# list rather than written out one verb at a time: the previous version asserted
# all three verbs on BorderCrossingAdmin, which has no security consequence, and
# one verb each on the two tables that do.
AUTHORIZATION_TABLES = ("cachedmembership", "rolemapping", "configuredguild", "auditlogentry")


def admin_url(name: str, *args) -> str:
    from django.urls import reverse

    return reverse(f"routemaker_admin:{name}", args=args)


def sign_in(client, monkeypatch, user):
    """Sign in over HTTP, through the real Discord flow.

    Not `force_login`: this deployment's sessions only exist once `issue_session`
    has written the `core.Session` row the epoch middleware requires, so a forced
    login is signed straight back out on the next request and every admin
    assertion below would be asserting a redirect to nowhere.
    """
    from django.urls import reverse

    from core.auth_views import STATE_SESSION_KEY

    monkeypatch.setattr(
        "core.auth_views.exchange_code",
        lambda code: (user.discord_user_id, "identify"),
        raising=False,
    )
    client.get(reverse("login"))
    state = client.session[STATE_SESSION_KEY]["state"]
    response = client.get(reverse("login-callback"), {"state": state, "code": "abc"})
    assert response.status_code == 302, "the login itself must work before anything else does"
    return client


@pytest.fixture
def guild(db):
    from core.models import ConfiguredGuild

    return ConfiguredGuild.objects.create(guild_id=5000, name="Test Club")


@pytest.fixture
def other_guild(db):
    from core.models import ConfiguredGuild

    return ConfiguredGuild.objects.create(guild_id=6000, name="Another Club")


@pytest.fixture
def instance_admin(db):
    return get_user_model().objects.create(discord_user_id=9001, is_instance_admin=True)


@pytest.fixture
def guild_admin(db, guild):
    from core.auth_backend import attach_standing
    from core.models import CachedMembership, RoleMapping

    user = get_user_model().objects.create(discord_user_id=9002)
    RoleMapping.objects.create(
        guild=guild, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN
    )
    CachedMembership.objects.create(
        discord_user_id=user.discord_user_id,
        guild=guild,
        role_ids=[7],
        last_confirmed=timezone.now(),
    )
    attach_standing(user)
    return user


@pytest.fixture
def rows(db, guild):
    """One row on each authorization table, all inside `guild`."""
    from core.models import AuditLogEntry, CachedMembership, RoleMapping

    return {
        "configuredguild": guild,
        "rolemapping": RoleMapping.objects.create(
            guild=guild, role_id=11, permission=RoleMapping.Permission.MEMBER
        ),
        "cachedmembership": CachedMembership.objects.create(
            discord_user_id=4242, guild=guild, role_ids=[11], last_confirmed=timezone.now()
        ),
        "auditlogentry": AuditLogEntry.objects.create(
            action="seed", model="seed", object_id="1", outcome=AuditLogEntry.Outcome.ALLOWED
        ),
    }


@pytest.fixture
def as_guild_admin(client, monkeypatch, guild_admin):
    return sign_in(client, monkeypatch, guild_admin)


@pytest.fixture
def as_instance_admin(client, monkeypatch, instance_admin):
    return sign_in(client, monkeypatch, instance_admin)


def refusals():
    from core.models import AuditLogEntry

    return AuditLogEntry.objects.filter(outcome=AuditLogEntry.Outcome.REFUSED)


@db
class TestTheAuditLogRecordsAttemptsAndNotProbes:
    """Driven over HTTP, because the defect this replaces was invisible from
    anywhere else.

    The previous tests called `has_change_permission` directly with a hand-rolled
    request object. Django calls that hook from inside `transaction.atomic` and
    then raises PermissionDenied, which rolls the refusal row back with it - and
    it calls the same hook several times per page while rendering, which flooded
    the log on navigation. Measured over real requests: a read-only changelist
    GET wrote 28 rows and a refused escalation POST wrote none. A test that does
    not make a request cannot see either half.
    """

    def test_a_refused_post_leaves_exactly_one_refused_row(self, as_guild_admin, rows) -> None:
        response = as_guild_admin.post(
            admin_url("core_cachedmembership_change", rows["cachedmembership"].pk),
            {"discord_user_id": 4242},
        )
        assert response.status_code == 403

        entry = refusals().get()
        assert entry.actor.discord_user_id == 9002
        assert (entry.model, entry.action) == ("cachedmembership", "change")

    def test_a_read_only_index_get_writes_nothing(self, as_guild_admin, rows) -> None:
        from core.models import AuditLogEntry

        seeded = AuditLogEntry.objects.count()
        assert as_guild_admin.get(f"/{settings.ADMIN_PATH}").status_code == 200
        assert AuditLogEntry.objects.count() == seeded, "navigation is not an attempt"

    @pytest.mark.parametrize("model", ["configuredguild", "rolemapping", "cachedmembership"])
    def test_reading_a_changelist_writes_nothing(self, as_guild_admin, rows, model) -> None:
        from core.models import AuditLogEntry

        seeded = AuditLogEntry.objects.count()
        response = as_guild_admin.get(admin_url(f"core_{model}_changelist"))
        assert response.status_code == 200
        assert AuditLogEntry.objects.count() == seeded

    def test_a_permitted_post_is_audited_as_allowed(self, as_instance_admin, guild, rows) -> None:
        """`AuditedAdmin.save_model`'s audit call survived deletion, so the
        plan's "admin writes go to the same audit log" was asserted nowhere."""
        from core.models import AuditLogEntry, RoleMapping

        mapping = rows["rolemapping"]
        response = as_instance_admin.post(
            admin_url("core_rolemapping_change", mapping.pk),
            {"guild": guild.pk, "role_id": 12, "permission": RoleMapping.Permission.REVIEWER},
        )
        assert response.status_code == 302, response.context["errors"] if response.context else ""
        mapping.refresh_from_db()
        assert mapping.role_id == 12

        entry = AuditLogEntry.objects.get(outcome=AuditLogEntry.Outcome.ALLOWED, action="change")
        assert (entry.model, entry.object_id) == ("rolemapping", str(mapping.pk))
        assert entry.actor.discord_user_id == 9001

    def test_a_permitted_bulk_delete_is_audited_once_per_object(
        self, as_instance_admin, guild, rows
    ) -> None:
        """The delete the log could not see at all.

        `delete_model` is the single-object confirmation page; the changelist's
        `delete_selected` never calls it, it calls `delete_queryset` once with
        the whole queryset. Measured before this: two role mappings deleted in
        bulk left zero rows in this log - two in `django_admin_log`, which is
        not registered here and is not the log the plan means - and the same
        held on the configured guild, jurisdiction and override pages. Doing
        several at once is the cheap way to do them, which makes it the path
        that most needs the record.
        """
        from core.models import AuditLogEntry, RoleMapping

        first = rows["rolemapping"]
        second = RoleMapping.objects.create(
            guild=guild, role_id=12, permission=RoleMapping.Permission.REVIEWER
        )

        response = as_instance_admin.post(
            admin_url("core_rolemapping_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [str(first.pk), str(second.pk)],
                "index": "0",
                "post": "yes",
            },
        )
        assert response.status_code == 302
        assert not RoleMapping.objects.filter(pk__in=[first.pk, second.pk]).exists()

        deletions = AuditLogEntry.objects.filter(
            model="rolemapping", action="delete", outcome=AuditLogEntry.Outcome.ALLOWED
        )
        assert {entry.object_id for entry in deletions} == {str(first.pk), str(second.pk)}
        assert {entry.actor.discord_user_id for entry in deletions} == {9001}

    def test_a_bulk_action_nobody_holds_is_refused_and_audited(self, as_guild_admin, rows) -> None:
        """A guild admin may read the role mapping table and may write nothing
        on it.

        Django's answer to a bulk action they do not hold is to say nothing:
        `get_actions` filters the list by permission, `changelist_view` calls
        `response_action` only when what is left is non-empty, and an empty list
        falls through to an ordinary render. Measured: 200, the message "No
        action selected", and no audit row - against a plan that says of exactly
        this attempt that it is "refused and audited".
        """
        response = as_guild_admin.post(
            admin_url("core_rolemapping_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [str(rows["rolemapping"].pk)],
                "index": "0",
                "post": "yes",
            },
        )
        assert response.status_code == 403

        entry = refusals().get()
        assert (entry.model, entry.action) == ("rolemapping", "action")
        assert entry.object_id == str(rows["rolemapping"].pk)
        assert entry.actor.discord_user_id == 9002

    def test_a_permitted_delete_is_audited_as_allowed(self, as_instance_admin, rows) -> None:
        """`delete_model`'s audit call survived deletion too."""
        from core.models import AuditLogEntry, RoleMapping

        mapping = rows["rolemapping"]
        response = as_instance_admin.post(
            admin_url("core_rolemapping_delete", mapping.pk), {"post": "yes"}
        )
        assert response.status_code == 302
        assert not RoleMapping.objects.filter(pk=mapping.pk).exists()

        entry = AuditLogEntry.objects.get(outcome=AuditLogEntry.Outcome.ALLOWED, action="delete")
        assert (entry.model, entry.object_id) == ("rolemapping", str(mapping.pk))


@db
class TestEveryWriteVerbOnEveryAuthorizationTable:
    """The tables that decide who holds what, every verb, over real requests.

    Seven guards survived deletion in round 3 - both ConfiguredGuildAdmin write
    hooks, both CachedMembershipAdmin ones, AuditLogEntryAdmin's module
    permission, and both audit calls - because the suite asserted all three verbs
    on BorderCrossingAdmin, which has no security consequence, and one verb each
    on the two tables that do.
    """

    @pytest.mark.parametrize("model", AUTHORIZATION_TABLES)
    @pytest.mark.parametrize("verb", ADMIN_WRITE_VERBS)
    def test_a_guild_admin_is_refused_and_audited(self, as_guild_admin, rows, model, verb) -> None:
        """Twelve cases from two lists, so adding a table or a verb to either
        covers it everywhere rather than in whichever cases somebody wrote out."""
        if verb == "add":
            url, payload = admin_url(f"core_{model}_add"), {}
        elif verb == "change":
            url, payload = admin_url(f"core_{model}_change", rows[model].pk), {}
        else:
            url, payload = admin_url(f"core_{model}_delete", rows[model].pk), {"post": "yes"}

        response = as_guild_admin.post(url, payload)
        assert response.status_code == 403, (model, verb)

        entry = refusals().get()
        assert (entry.model, entry.action) == (model, verb)
        assert entry.actor.discord_user_id == 9002

    @pytest.mark.parametrize("model", AUTHORIZATION_TABLES)
    def test_the_row_is_unchanged_and_still_there(self, as_guild_admin, rows, model) -> None:
        row = rows[model]
        before = type(row).objects.get(pk=row.pk).__dict__.copy()
        for url, payload in (
            (admin_url(f"core_{model}_change", row.pk), {}),
            (admin_url(f"core_{model}_delete", row.pk), {"post": "yes"}),
        ):
            as_guild_admin.post(url, payload)
        after = type(row).objects.get(pk=row.pk)
        assert {k: v for k, v in after.__dict__.items() if not k.startswith("_")} == {
            k: v for k, v in before.items() if not k.startswith("_")
        }

    @pytest.mark.parametrize("model", AUTHORIZATION_TABLES)
    def test_the_guard_on_each_admin_answers_before_anything_else_does(
        self, as_guild_admin, rows, model
    ) -> None:
        """The delete *confirmation* page, which is what isolates each admin's
        own `has_delete_permission` from the cascade.

        Found by mutation: flipping `ConfiguredGuildAdmin.has_delete_permission`
        to True left the POST test green, because deleting a configured guild
        cascades to the membership and mapping tables and Django refuses on
        *those* admins' delete permissions instead - so the POST answered 403
        either way and the guard the test was named for was never exercised.
        Django checks this admin's own hook before it collects the cascade, so
        the GET tells them apart: 403 with the guard, the confirmation page
        without it.
        """
        response = as_guild_admin.get(admin_url(f"core_{model}_delete", rows[model].pk))
        assert response.status_code == 403, model

    def test_nobody_may_write_the_log_including_an_instance_admin(
        self, as_instance_admin, rows
    ) -> None:
        """A log whose entries can be edited from the surface it audits is not a
        log."""
        from core.models import AuditLogEntry

        entry = rows["auditlogentry"]
        assert as_instance_admin.post(admin_url("core_auditlogentry_add"), {}).status_code == 403
        assert (
            as_instance_admin.post(admin_url("core_auditlogentry_change", entry.pk), {}).status_code
            == 403
        )
        assert (
            as_instance_admin.post(
                admin_url("core_auditlogentry_delete", entry.pk), {"post": "yes"}
            ).status_code
            == 403
        )
        assert AuditLogEntry.objects.filter(pk=entry.pk).exists()

    def test_a_guild_admin_cannot_read_the_log_at_all(self, as_guild_admin, rows) -> None:
        """It names who acted where, which is the membership cache's
        sensitivity."""
        assert as_guild_admin.get(admin_url("core_auditlogentry_changelist")).status_code == 403

    def test_an_action_posted_at_a_changelist_they_cannot_read_is_audited(
        self, as_guild_admin, rows
    ) -> None:
        """The third refusal path, which is neither a change form nor a delete.

        Found by mutation: the audit around `changelist_view` could be deleted
        with the suite green, because every other test reached the changelist
        either by GET or on a model the guild admin may read. A bulk action is
        exactly the shape of attempt this log exists for.
        """
        response = as_guild_admin.post(
            admin_url("core_auditlogentry_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [str(rows["auditlogentry"].pk)],
                "index": "0",
            },
        )
        assert response.status_code == 403

        entry = refusals().get()
        assert (entry.model, entry.action) == ("auditlogentry", "action")
        assert entry.object_id == str(rows["auditlogentry"].pk)

    def test_derived_state_is_not_writable_by_an_instance_admin_either(
        self, as_instance_admin
    ) -> None:
        """The pipeline owns border crossings and a rebuild reassigns their ids.
        A hand edit desynchronises the crossings table from the graph until next
        Tuesday overwrites it."""
        assert as_instance_admin.post(admin_url("core_bordercrossing_add"), {}).status_code == 403

    def test_a_guild_admin_cannot_touch_another_guilds_rows(
        self, as_guild_admin, other_guild
    ) -> None:
        """Scoping a queryset is not the same as gating a write; here both
        answer."""
        from core.models import ConfiguredGuild, RoleMapping

        theirs = RoleMapping.objects.create(
            guild=other_guild, role_id=99, permission=RoleMapping.Permission.GUILD_ADMIN
        )
        for url in (
            admin_url("core_rolemapping_change", theirs.pk),
            admin_url("core_configuredguild_change", other_guild.pk),
        ):
            assert as_guild_admin.post(url, {}).status_code in (403, 404)
        assert RoleMapping.objects.get(pk=theirs.pk).role_id == 99
        assert ConfiguredGuild.objects.get(pk=other_guild.pk).name == "Another Club"


@db
class TestTheRevokeNowAction:
    """The transition the degraded window has never had a way into.

    `should_mark_degraded` and `degraded_window` were correct, well tested and
    called from nowhere; nothing wrote `ConfiguredGuild.state`; and the plan's
    "either way an instance admin, or an admin of the affected guild, can
    collapse the window at once with an audited revoke-now action" existed on no
    surface at all.
    """

    def revoke(self, client, guild):
        """Deliberately not followed. A guild admin who revokes their own guild
        loses the standing that admitted them to the admin in the same request,
        so following the redirect lands on a 404 - which is correct, and is
        asserted on its own below rather than smuggled into every case here."""
        return client.post(
            admin_url("core_configuredguild_changelist"),
            {"action": "revoke_now", "_selected_action": [str(guild.pk)], "index": "0"},
        )

    def test_an_instance_admin_can_revoke(self, as_instance_admin, guild) -> None:
        from core.models import AuditLogEntry

        assert self.revoke(as_instance_admin, guild).status_code == 302
        guild.refresh_from_db()
        assert guild.state == "revoked"
        assert guild.standing_valid_until is None

        entry = AuditLogEntry.objects.get(action="revoke_now")
        assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
        assert entry.actor.discord_user_id == 9001
        assert str(guild.guild_id) in entry.detail

    def test_an_admin_of_the_affected_guild_can_revoke_their_own(
        self, as_guild_admin, guild
    ) -> None:
        from core.models import AuditLogEntry

        assert self.revoke(as_guild_admin, guild).status_code == 302
        guild.refresh_from_db()
        assert guild.state == "revoked"
        assert AuditLogEntry.objects.filter(
            action="revoke_now", outcome=AuditLogEntry.Outcome.ALLOWED
        ).exists()

        # And the redirect they were handed now refuses them, because they have
        # just ended the standing that admitted them.
        assert as_guild_admin.get(admin_url("core_configuredguild_changelist")).status_code == 404

    def test_revoking_ends_the_standing_it_was_granting(self, as_guild_admin, guild_admin, guild):
        """The point of the action, asserted through the resolver rather than on
        the column: a revoked guild grants nothing, including to the admin who
        revoked it."""
        from core.auth_backend import attach_standing

        self.revoke(as_guild_admin, guild)
        attach_standing(guild_admin)
        assert guild_admin._admin_guild_ids == frozenset()
        assert not guild_admin.is_staff

    def test_a_guild_admin_cannot_revoke_another_guild(self, as_guild_admin, other_guild) -> None:
        """The first of the two things that stop it: the changelist queryset
        never contains the other guild, so the selection resolves to nothing."""
        self.revoke(as_guild_admin, other_guild)
        other_guild.refresh_from_db()
        assert other_guild.state == "active"

    def unscope(self, monkeypatch) -> None:
        from core.admin import ConfiguredGuildAdmin
        from core.models import ConfiguredGuild

        monkeypatch.setattr(
            ConfiguredGuildAdmin,
            "get_queryset",
            lambda self, request: ConfiguredGuild.objects.all(),
        )

    def test_the_per_object_check_holds_if_the_scoping_ever_stops(
        self, as_guild_admin, other_guild, monkeypatch
    ) -> None:
        """The second, exercised against exactly the regression it exists for.

        Found by mutation: `may_revoke` could be replaced with `return True` and
        the suite stayed green, because the queryset scoping refuses first and
        the guard behind it is never reached. That makes it a guard nobody can
        show works - which is how a scoping change becomes a cross-guild write.
        So the scoping is lifted for this one test and the POST is still real.
        """
        self.unscope(monkeypatch)
        assert self.revoke(as_guild_admin, other_guild).status_code == 302

        other_guild.refresh_from_db()
        assert other_guild.state == "active", "the per-object check refused it on its own"
        assert refusals().filter(action="revoke_now").exists()

    def test_and_their_own_guild_still_goes_through_that_check(
        self, as_guild_admin, guild, monkeypatch
    ) -> None:
        """So the refusal above is the guild and not the unscoped queryset."""
        self.unscope(monkeypatch)
        self.revoke(as_guild_admin, guild)
        guild.refresh_from_db()
        assert guild.state == "revoked"

    def test_a_plain_member_never_reaches_the_action(self, client, monkeypatch, guild) -> None:
        from core.models import CachedMembership, RoleMapping

        User = get_user_model()
        member = User.objects.create(discord_user_id=9003)
        RoleMapping.objects.create(guild=guild, role_id=3, permission=RoleMapping.Permission.MEMBER)
        CachedMembership.objects.create(
            discord_user_id=9003, guild=guild, role_ids=[3], last_confirmed=timezone.now()
        )
        sign_in(client, monkeypatch, member)

        assert self.revoke(client, guild).status_code == 404, "not staff, so no admin at all"

        guild.refresh_from_db()
        assert guild.state == "active"


@db
class TestTheUserAdmin:
    """Registered because without it a deployment had exactly one instance admin
    forever: the flag is stored, nothing wrote it, there is no password login and
    no createsuperuser, and `check_last_instance_admin` refuses to let the one
    there is step down. The plan says instance admins "are then added and removed
    in the admin, audited"; this is that page.
    """

    def test_an_instance_admin_can_appoint_another(self, as_instance_admin) -> None:
        from core.models import AuditLogEntry

        User = get_user_model()
        successor = User.objects.create(discord_user_id=9100)
        response = as_instance_admin.post(
            admin_url("core_user_change", successor.pk), {"is_instance_admin": "on"}
        )
        assert response.status_code == 302
        successor.refresh_from_db()
        assert successor.is_instance_admin
        assert AuditLogEntry.objects.filter(
            model="user", action="change", outcome=AuditLogEntry.Outcome.ALLOWED
        ).exists()

    def test_and_can_then_stand_down(self, as_instance_admin, instance_admin) -> None:
        User = get_user_model()
        successor = User.objects.create(discord_user_id=9101, is_instance_admin=True)
        response = as_instance_admin.post(admin_url("core_user_change", instance_admin.pk), {})
        assert response.status_code == 302
        instance_admin.refresh_from_db()
        assert not instance_admin.is_instance_admin
        assert successor.is_instance_admin

    def test_the_last_one_is_refused_as_a_form_error_not_a_crash(
        self, as_instance_admin, instance_admin
    ) -> None:
        """`check_last_instance_admin` raises; raising out of save_model would be
        a 500 on the change form - a correct refusal delivered unreadably."""
        response = as_instance_admin.post(admin_url("core_user_change", instance_admin.pk), {})
        assert response.status_code == 200
        assert "appoint another first" in response.content.decode()
        instance_admin.refresh_from_db()
        assert instance_admin.is_instance_admin

    def test_the_last_one_refusal_reaches_the_audit_log(
        self, as_instance_admin, instance_admin
    ) -> None:
        """A refused policy write, recorded like every other one.

        It was the one refusal path that wrote nothing: a 200 with a field
        error and zero audit rows, which is indistinguishable from nobody having
        tried. The error message is what makes the refusal readable and stays
        exactly where it was; the row is what makes it a refusal on the record.
        """

        response = as_instance_admin.post(admin_url("core_user_change", instance_admin.pk), {})
        assert response.status_code == 200
        assert "appoint another first" in response.content.decode()

        entry = refusals().get()
        assert (entry.model, entry.action) == ("user", "change")
        assert entry.object_id == str(instance_admin.pk)
        assert entry.actor_id == instance_admin.pk
        assert "last instance admin" in entry.detail

    def test_a_guild_admin_cannot_see_the_page_at_all(self, as_guild_admin) -> None:
        """It lists every account on the deployment, which is the membership
        cache's sensitivity."""
        assert as_guild_admin.get(admin_url("core_user_changelist")).status_code == 403

    def test_a_guild_admin_cannot_appoint_themselves(self, as_guild_admin, guild_admin) -> None:
        response = as_guild_admin.post(
            admin_url("core_user_change", guild_admin.pk), {"is_instance_admin": "on"}
        )
        assert response.status_code in (403, 404)
        guild_admin.refresh_from_db()
        assert not guild_admin.is_instance_admin

    def test_accounts_are_neither_created_nor_deleted_here(
        self, as_instance_admin, instance_admin
    ) -> None:
        """Signing in creates them; deletion is the tombstone-and-reassignment
        flow, and a row deleted from a changelist is none of that."""
        User = get_user_model()
        other = User.objects.create(discord_user_id=9102)
        assert as_instance_admin.post(admin_url("core_user_add"), {}).status_code == 403
        assert (
            as_instance_admin.post(
                admin_url("core_user_delete", other.pk), {"post": "yes"}
            ).status_code
            == 403
        )
        assert User.objects.filter(pk=other.pk).exists()


@db
class TestTheAdminPathDoesNotAnnounceItself:
    def test_an_unauthenticated_request_gets_a_404_and_not_a_redirect(self, client) -> None:
        """Django redirects an unadmitted request to the admin login page, which
        is a 302 naming the path - so the path confirmed an admin was here while
        `login` itself answered 404 and the docstring claimed otherwise."""
        response = client.get(f"/{settings.ADMIN_PATH}")
        assert response.status_code == 404
        assert "Location" not in response

    def test_a_signed_in_non_admin_gets_the_same_404(self, client, monkeypatch) -> None:
        User = get_user_model()
        sign_in(client, monkeypatch, User.objects.create(discord_user_id=9200))
        assert client.get(f"/{settings.ADMIN_PATH}").status_code == 404

    def test_the_login_page_does_not_answer(self, client) -> None:
        assert client.get(f"/{settings.ADMIN_PATH}login/").status_code == 404

    def test_an_admin_still_reaches_it(self, as_instance_admin) -> None:
        assert as_instance_admin.get(f"/{settings.ADMIN_PATH}").status_code == 200


@db
class TestDeletingTheLastInstanceAdmin:
    """`check_last_instance_admin` lives in `save()`, so `.delete()` walked past
    it and could empty the instance-admin list from a management shell."""

    def test_deleting_the_last_one_is_refused(self, instance_admin) -> None:
        from core.models import LastInstanceAdmin

        with pytest.raises(LastInstanceAdmin):
            instance_admin.delete()
        assert get_user_model().objects.filter(pk=instance_admin.pk).exists()

    def test_a_queryset_delete_is_refused_too(self, instance_admin) -> None:
        from core.models import LastInstanceAdmin

        with pytest.raises(LastInstanceAdmin):
            get_user_model().objects.filter(is_instance_admin=True).delete()

    def test_deleting_one_of_two_is_allowed(self, instance_admin) -> None:
        User = get_user_model()
        User.objects.create(discord_user_id=9300, is_instance_admin=True)
        instance_admin.delete()
        assert User.objects.filter(is_instance_admin=True).count() == 1

    def test_queryset_update_is_a_stated_limitation(self, instance_admin) -> None:
        """`.update()` issues one UPDATE and emits no signal, so nothing in this
        layer can see it. Closing it needs a manager on the model, which is
        another owner's file. Recorded here so it is a known hole rather than a
        forgotten one, and the two paths a person or a surface actually takes -
        the admin, which has no delete, and `save()` - are both guarded.
        """
        User = get_user_model()
        User.objects.filter(pk=instance_admin.pk).update(is_instance_admin=False)
        assert not User.objects.filter(is_instance_admin=True).exists()


class TestTheLastInstanceAdmin:
    """There is no password login and no createsuperuser path on this
    deployment, so an instance admin who clears their own flag cannot be restored
    through the application at all. The recovery is a hand-written UPDATE against
    production, which is a worse position than this refusal creates.
    """

    def test_removing_the_last_instance_admin_is_refused(self, instance_admin) -> None:
        from core.models import LastInstanceAdmin

        instance_admin.is_instance_admin = False
        with pytest.raises(LastInstanceAdmin, match="appoint another first"):
            instance_admin.save()

    def test_banning_or_deleting_the_last_instance_admin_is_refused(self, instance_admin) -> None:
        """A ban takes the admin away as effectively as clearing the flag does,
        which is the whole point of deriving is_staff rather than storing it."""
        from core.models import LastInstanceAdmin

        instance_admin.is_banned = True
        with pytest.raises(LastInstanceAdmin):
            instance_admin.save()

        instance_admin.is_banned = False
        instance_admin.is_deleted = True
        with pytest.raises(LastInstanceAdmin):
            instance_admin.save()

    def test_removing_one_of_two_is_allowed(self, instance_admin) -> None:
        User = get_user_model()
        User.objects.create(discord_user_id=98765, is_instance_admin=True)
        instance_admin.is_instance_admin = False
        instance_admin.save()
        assert User.objects.filter(is_instance_admin=True).count() == 1

    def test_a_banned_admin_does_not_count_as_the_remaining_one(self, instance_admin) -> None:
        """Otherwise the last usable admin can be removed as long as an unusable
        one exists, which is the same failure with an extra step."""
        from core.models import LastInstanceAdmin

        get_user_model().objects.create(
            discord_user_id=98766, is_instance_admin=True, is_banned=True
        )
        instance_admin.is_instance_admin = False
        with pytest.raises(LastInstanceAdmin):
            instance_admin.save()


class TestInstanceAdminSurvivesADegradedDeployment:
    def test_the_admin_holds_when_every_guild_is_degraded_and_the_bot_is_down(
        self, instance_admin, guild
    ) -> None:
        """The case the degraded window exists to be survivable: the bot is down,
        every guild's standing has lapsed, and somebody still has to be able to
        reach the admin and mark a guild revoked."""
        from datetime import timedelta

        from core.admin import site
        from core.auth_backend import attach_standing

        guild.state = "degraded"
        guild.standing_valid_until = timezone.now() - timedelta(days=30)
        guild.save()

        attach_standing(instance_admin)
        assert instance_admin._admin_guild_ids == frozenset()
        assert instance_admin.is_staff, "the instance admin is not guild-derived"
        assert site.has_permission(Request(instance_admin))


@db
class TestTheBootstrapInstanceAdmin:
    """How a new deployment gets its first instance admin, which it could not.

    `is_instance_admin` is a stored flag whose only surface is an admin page
    only an instance admin may reach; there is no password login, no
    `createsuperuser`, and `check_last_instance_admin` refuses to let the one
    there is step down. On an empty database every signed-in account got a 404
    at the admin and the only way in was a hand-written UPDATE against
    production.

    The plan: the environment holds one bootstrap Discord id, "and that value
    grants standing only while the instance-admin list is empty. The first
    successful admin action writes the bootstrap id into the list and
    permanently disables the environment path, audited, after which anyone
    holding `.env` read access holds nothing."
    """

    def bootstrap(self, monkeypatch, discord_user_id) -> None:
        monkeypatch.setattr(
            settings, "BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID", discord_user_id, raising=False
        )

    def test_the_bootstrap_id_reaches_the_admin_on_an_empty_list(self, client, monkeypatch) -> None:
        from core.models import AuditLogEntry

        User = get_user_model()
        user = User.objects.create(discord_user_id=7777)
        self.bootstrap(monkeypatch, 7777)
        signed_in = sign_in(client, monkeypatch, user)

        assert signed_in.get(f"/{settings.ADMIN_PATH}").status_code == 200

        user.refresh_from_db()
        assert user.is_instance_admin, "the first admin request writes the id into the list"

        entry = AuditLogEntry.objects.get(action="bootstrap_instance_admin")
        assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
        assert entry.actor_id == user.pk
        assert (entry.model, entry.object_id) == ("user", str(user.pk))

    def test_the_variable_grants_nothing_once_the_list_is_not_empty(
        self, client, monkeypatch, instance_admin
    ) -> None:
        """The half that makes `.env` read access worth nothing on a running
        deployment: the path is inert afterwards even though it still names
        somebody."""
        from core.models import AuditLogEntry

        User = get_user_model()
        hopeful = User.objects.create(discord_user_id=7778)
        self.bootstrap(monkeypatch, 7778)
        signed_in = sign_in(client, monkeypatch, hopeful)

        assert signed_in.get(f"/{settings.ADMIN_PATH}").status_code == 404

        hopeful.refresh_from_db()
        assert not hopeful.is_instance_admin
        assert not AuditLogEntry.objects.filter(action="bootstrap_instance_admin").exists()

    def test_it_grants_nothing_to_anyone_else_even_on_an_empty_list(
        self, client, monkeypatch
    ) -> None:
        User = get_user_model()
        someone = User.objects.create(discord_user_id=7779)
        self.bootstrap(monkeypatch, 7777)
        signed_in = sign_in(client, monkeypatch, someone)

        assert signed_in.get(f"/{settings.ADMIN_PATH}").status_code == 404
        someone.refresh_from_db()
        assert not someone.is_instance_admin

    def test_an_unset_variable_grants_nothing(self, client, monkeypatch) -> None:
        """The deployed state once bootstrapping is done, and the state of every
        checkout."""
        User = get_user_model()
        someone = User.objects.create(discord_user_id=7780)
        self.bootstrap(monkeypatch, None)
        signed_in = sign_in(client, monkeypatch, someone)

        assert signed_in.get(f"/{settings.ADMIN_PATH}").status_code == 404
        someone.refresh_from_db()
        assert not someone.is_instance_admin

    def test_a_banned_bootstrap_holder_claims_nothing(self, monkeypatch) -> None:
        """A ban ends every path, including this one. Asserted against the
        claim itself, because a banned account cannot complete the login that
        would drive it over HTTP."""
        from core.models import claim_bootstrap_instance_admin

        User = get_user_model()
        banned = User.objects.create(discord_user_id=7781, is_banned=True)
        self.bootstrap(monkeypatch, 7781)

        assert claim_bootstrap_instance_admin(banned) is False
        banned.refresh_from_db()
        assert not banned.is_instance_admin

    def test_the_claim_happens_once(self, monkeypatch) -> None:
        """A second call is a no-op rather than a second audit row, which is
        what "permanently disables the environment path" has to mean."""
        from core.models import AuditLogEntry, claim_bootstrap_instance_admin

        User = get_user_model()
        user = User.objects.create(discord_user_id=7782)
        self.bootstrap(monkeypatch, 7782)

        assert claim_bootstrap_instance_admin(user) is True
        assert claim_bootstrap_instance_admin(user) is False
        assert AuditLogEntry.objects.filter(action="bootstrap_instance_admin").count() == 1


@db
class TestTheInstanceAdminRemovalWindow:
    """ "Removing an instance admin other than yourself notifies every remaining
    instance admin and the removed party and takes effect after a delay,
    configurable and defaulting to an hour, during which any instance admin can
    cancel it; without that, one admin could remove every peer down to
    themselves in a single audited but unstoppable action."

    Measured before this existed: three POSTs, one admin left, no delay and
    nothing to cancel. The notification half has no channel in phase 1 - this
    deployment has no Discord DM path and no email path - so it is an
    outstanding gap rather than something these tests pretend about.
    """

    @pytest.fixture
    def peer(self, db):
        return get_user_model().objects.create(discord_user_id=9400, is_instance_admin=True)

    def test_removing_another_admin_schedules_it_and_leaves_the_flag_set(
        self, as_instance_admin, instance_admin, peer
    ) -> None:
        from core.models import AuditLogEntry, PendingInstanceAdminRemoval

        response = as_instance_admin.post(admin_url("core_user_change", peer.pk), {})
        assert response.status_code == 302

        peer.refresh_from_db()
        assert peer.is_instance_admin, (
            "a delay that takes the powers away now and records the removal later "
            "is a notification, not a delay"
        )

        pending = PendingInstanceAdminRemoval.objects.get(user=peer)
        assert pending.requested_by_id == instance_admin.pk
        assert pending.effective_at - timezone.now() > settings.INSTANCE_ADMIN_REMOVAL_DELAY / 2
        assert pending.effective_at - timezone.now() <= settings.INSTANCE_ADMIN_REMOVAL_DELAY

        entry = AuditLogEntry.objects.get(action="schedule_removal")
        assert (entry.model, entry.object_id) == ("user", str(peer.pk))
        assert entry.actor_id == instance_admin.pk

    def test_the_delay_is_the_plans_hour_by_default(self) -> None:
        """A configurable delay defaulting to something else is not this."""
        from datetime import timedelta

        assert settings.INSTANCE_ADMIN_REMOVAL_DELAY == timedelta(hours=1)

    def test_standing_down_is_still_immediate(self, as_instance_admin, instance_admin, peer):
        """The delay guards against being removed by somebody else; an admin
        clearing their own flag has no peer to appeal to."""
        from core.models import PendingInstanceAdminRemoval

        response = as_instance_admin.post(admin_url("core_user_change", instance_admin.pk), {})
        assert response.status_code == 302

        instance_admin.refresh_from_db()
        assert not instance_admin.is_instance_admin
        assert not PendingInstanceAdminRemoval.objects.exists()

    def test_any_instance_admin_can_cancel_it(self, as_instance_admin, instance_admin, peer):
        from core.models import (
            AuditLogEntry,
            PendingInstanceAdminRemoval,
            schedule_instance_admin_removal,
        )

        pending = schedule_instance_admin_removal(peer, actor=peer)

        response = as_instance_admin.post(
            admin_url("core_pendinginstanceadminremoval_changelist"),
            {
                "action": "cancel_removal",
                "_selected_action": [str(pending.pk)],
                "index": "0",
            },
        )
        assert response.status_code == 302
        assert not PendingInstanceAdminRemoval.objects.exists()

        peer.refresh_from_db()
        assert peer.is_instance_admin

        entry = AuditLogEntry.objects.get(action="cancel_removal")
        assert entry.actor_id == instance_admin.pk
        assert entry.object_id == str(peer.pk)

    def test_a_due_removal_is_applied_and_audited(self, instance_admin, peer) -> None:
        from core.models import (
            AuditLogEntry,
            PendingInstanceAdminRemoval,
            apply_due_instance_admin_removals,
            schedule_instance_admin_removal,
        )

        pending = schedule_instance_admin_removal(peer, actor=instance_admin)

        assert apply_due_instance_admin_removals() == 0, "not due yet"
        peer.refresh_from_db()
        assert peer.is_instance_admin

        assert apply_due_instance_admin_removals(now=pending.effective_at) == 1
        peer.refresh_from_db()
        assert not peer.is_instance_admin
        assert not PendingInstanceAdminRemoval.objects.exists()

        entry = AuditLogEntry.objects.get(action="apply_removal")
        assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
        assert entry.actor_id is None and entry.actor_user_id is None, "no request, no actor"
        assert entry.object_id == str(peer.pk)

    def test_the_last_instance_admin_is_still_refused_when_it_comes_due(
        self, instance_admin, peer
    ) -> None:
        """The delay does not get to walk past the lockout guard.

        Scheduled while there were two, applied after the other one stood down:
        by then it is the removal of the last instance admin, and there is no
        login path that could restore one.
        """
        from core.models import (
            AuditLogEntry,
            PendingInstanceAdminRemoval,
            apply_due_instance_admin_removals,
            schedule_instance_admin_removal,
        )

        pending = schedule_instance_admin_removal(peer, actor=instance_admin)
        instance_admin.is_instance_admin = False
        instance_admin.save()

        assert apply_due_instance_admin_removals(now=pending.effective_at) == 0
        peer.refresh_from_db()
        assert peer.is_instance_admin
        assert PendingInstanceAdminRemoval.objects.filter(user=peer).exists(), (
            "left pending and visible, where an admin can cancel it or appoint a successor"
        )
        assert AuditLogEntry.objects.filter(
            action="apply_removal", outcome=AuditLogEntry.Outcome.REFUSED
        ).exists()

    def test_scheduling_the_last_ones_removal_is_refused_outright(self, instance_admin) -> None:
        from core.models import (
            LastInstanceAdmin,
            PendingInstanceAdminRemoval,
            schedule_instance_admin_removal,
        )

        with pytest.raises(LastInstanceAdmin, match="appoint another first"):
            schedule_instance_admin_removal(instance_admin, actor=instance_admin)
        assert not PendingInstanceAdminRemoval.objects.exists()

    def test_a_guild_admin_sees_no_pending_removals_page(self, as_guild_admin) -> None:
        assert (
            as_guild_admin.get(admin_url("core_pendinginstanceadminremoval_changelist")).status_code
            == 403
        )


@db
class TestTheAuditLogTellsADeletedActorFromNoActor:
    """`AuditLogEntry.actor` is SET_NULL, so a worker's action and a deleted
    person's action were the same row. The plan wants them told apart: "Audit
    log rows keep the numeric actor id and display 'deleted user'".
    """

    def test_the_two_rows_differ(self, guild, other_guild, instance_admin) -> None:
        from core.models import AuditLogEntry
        from core.revocation import revoke_guild

        User = get_user_model()
        acting_admin = User.objects.create(discord_user_id=9500, is_instance_admin=True)
        acting_admin_pk = acting_admin.pk

        revoke_guild(guild, actor=None, reason="the degraded sweep")
        revoke_guild(other_guild, actor=acting_admin, reason="by hand")
        acting_admin.delete()

        worker_row = AuditLogEntry.objects.get(action="revoke_now", object_id=str(guild.pk))
        person_row = AuditLogEntry.objects.get(action="revoke_now", object_id=str(other_guild.pk))

        assert (worker_row.actor_id, worker_row.actor_user_id) == (None, None)
        assert (person_row.actor_id, person_row.actor_user_id) == (None, acting_admin_pk)
        assert worker_row.actor_label() != person_row.actor_label()
        assert person_row.actor_label() == f"deleted user {acting_admin_pk}"
        assert worker_row.actor_label() == "no actor (worker)"

    def test_a_live_actor_is_named_as_themselves(self, guild, instance_admin) -> None:
        from core.models import AuditLogEntry
        from core.revocation import revoke_guild

        revoke_guild(guild, actor=instance_admin, reason="by hand")
        row = AuditLogEntry.objects.get(action="revoke_now")
        assert row.actor_user_id == instance_admin.pk
        assert row.actor_label() == str(instance_admin)

    def test_the_changelist_shows_the_deleted_actor(self, as_instance_admin, guild) -> None:
        """Over HTTP, because the column has to reach the page an instance admin
        actually reads."""
        from core.revocation import revoke_guild

        User = get_user_model()
        doomed = User.objects.create(discord_user_id=9501, is_instance_admin=True)
        doomed_pk = doomed.pk
        revoke_guild(guild, actor=doomed, reason="by hand")
        doomed.delete()

        response = as_instance_admin.get(admin_url("core_auditlogentry_changelist"))
        assert response.status_code == 200
        assert f"deleted user {doomed_pk}" in response.content.decode()


@db
class TestTheInstanceAdminListIsVisibleToGuildAdmins:
    """ "It is visible to the clubs it holds power over: the current instance
    admins are listed to every guild admin."

    They could see nothing of it. The only page naming instance admins is the
    account table, which is every account on the deployment and carries the
    membership cache's sensitivity, so it is instance-admin only and correctly
    so. This is a separate surface with a separate permission.
    """

    def test_a_guild_admin_can_read_it(self, as_guild_admin, instance_admin) -> None:
        response = as_guild_admin.get(admin_url("core_instanceadminlisting_changelist"))
        assert response.status_code == 200
        assert str(instance_admin.discord_user_id) in response.content.decode()

    def test_it_lists_instance_admins_and_nobody_else(
        self, as_guild_admin, guild_admin, instance_admin
    ) -> None:
        """The narrowing is the point: a page that answered with every account
        would be the account table under another name.

        Asserted against the changelist's own queryset rather than against the
        rendered bytes, because the admin header greets the signed-in guild
        admin by the same number the rows would carry.
        """
        response = as_guild_admin.get(admin_url("core_instanceadminlisting_changelist"))
        listed = set(response.context["cl"].queryset.values_list("discord_user_id", flat=True))
        assert listed == {instance_admin.discord_user_id}
        assert guild_admin.discord_user_id not in listed

    def test_the_account_table_itself_is_still_closed_to_them(
        self, as_guild_admin, instance_admin
    ) -> None:
        """The other direction of the matrix, and the reason this is a proxy
        model with its own permission rather than a filter on `UserAdmin`."""
        assert as_guild_admin.get(admin_url("core_user_changelist")).status_code == 403
        assert (
            as_guild_admin.get(admin_url("core_user_change", instance_admin.pk)).status_code == 403
        )

    def test_a_guild_admin_cannot_open_one_of_the_rows(
        self, as_guild_admin, instance_admin
    ) -> None:
        """The change form is served read-only to a viewer and would show the
        rest of the account row, so the list is the list and nothing else."""
        assert (
            as_guild_admin.get(
                admin_url("core_instanceadminlisting_change", instance_admin.pk)
            ).status_code
            == 403
        )

    def test_nobody_may_write_it(self, as_instance_admin, instance_admin) -> None:
        for url, payload in (
            (admin_url("core_instanceadminlisting_add"), {}),
            (admin_url("core_instanceadminlisting_change", instance_admin.pk), {}),
            (admin_url("core_instanceadminlisting_delete", instance_admin.pk), {"post": "yes"}),
        ):
            assert as_instance_admin.post(url, payload).status_code == 403

    def test_a_plain_member_reaches_no_admin_at_all(
        self, client, monkeypatch, instance_admin
    ) -> None:
        User = get_user_model()
        sign_in(client, monkeypatch, User.objects.create(discord_user_id=9600))
        assert client.get(admin_url("core_instanceadminlisting_changelist")).status_code == 404, (
            "not staff, so no admin at all"
        )


@db
class TestTheAdminLogoutEndsTheApplicationSession:
    def test_the_session_row_goes_with_it(self, as_instance_admin) -> None:
        """Django's admin logout flushes its own session and left this
        deployment's `core.Session` row behind, so whether signing out left a
        user id and two timestamps in the table depended on which of two
        buttons was pressed."""
        from core.models import Session

        assert Session.objects.count() == 1
        response = as_instance_admin.post(f"/{settings.ADMIN_PATH}logout/")
        assert response.status_code in (200, 302)
        assert not Session.objects.exists()


@db
class TestTheCrossingsPageBeforeTheFirstRebuild:
    def test_it_renders_empty_with_a_message(self, as_instance_admin) -> None:
        """`border_crossing` is unmanaged and lives in the schema the weekly
        swap renames, so `migrate` does not create it and it does not exist
        until a rebuild has run. Opening this changelist raised ProgrammingError
        - an unhandled 500 on a read-only page, from the one state every new
        deployment starts in."""
        from django.db import connection

        assert "border_crossing" not in connection.introspection.table_names()

        response = as_instance_admin.get(admin_url("core_bordercrossing_changelist"))
        assert response.status_code == 200
        assert "does not exist" in response.content.decode()

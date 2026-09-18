"""Phase 1 schema: the tables the preprocessing pipeline writes and the
application reads.

Two rules shape this module. Segment data is *rebuilt* weekly into a staging
schema and swapped, so those models are unmanaged and their DDL comes from the
pipeline rather than from migrations. Everything anchored to a segment refers to
it by plain columns rather than a foreign key, because a cross-schema constraint
would make the swap impossible.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.gis.db import models
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import standing

logger = logging.getLogger(__name__)


class StressTier(models.IntegerChoices):
    """Furth LTS. One scale everywhere, never an imported agency score."""

    LTS1 = 1, "Tolerable for most adults and children"
    LTS2 = 2, "Tolerable for most adults"
    LTS3 = 3, "Tolerable for confident cyclists"
    LTS4 = 4, "Strong and fearless only"


class Segment(models.Model):
    """A stretch of way with its derived attributes.

    Keyed by OSM way id plus an ordinal within that way. Preprocessing never
    mints or alters a way id, which is what keeps this key, the trace_attributes
    join, and anchor reconciliation all pointing at the same thing across
    rebuilds.
    """

    osm_way_id = models.BigIntegerField()
    ordinal = models.IntegerField()
    geometry = models.LineStringField(srid=4326)

    stress_tier = models.IntegerField(choices=StressTier.choices)
    stress_rule = models.TextField()
    # Which inputs were assumed rather than measured, and where the volume came
    # from. Carried so a reviewer weighing a tier against crash history knows
    # which it is, and so the published derivative can tell which segments a
    # conditionally licensed source touched.
    stress_assumed = models.JSONField(default=list)
    volume_source = models.TextField(null=True, blank=True)

    sinuosity = models.FloatField(null=True)
    is_trail_class = models.BooleanField(default=False)
    # Nullable: absent `surface` is unknown, not paved.
    is_unpaved = models.BooleanField(null=True)
    is_rough = models.BooleanField(default=False)
    lit = models.BooleanField(null=True)

    class Meta:
        managed = False  # DDL comes from the pipeline; see Operations in the plan.
        db_table = "segment"
        constraints = [
            models.UniqueConstraint(fields=["osm_way_id", "ordinal"], name="segment_key")
        ]
        indexes = [models.Index(fields=["osm_way_id"])]

    def __str__(self) -> str:
        return f"way {self.osm_way_id} #{self.ordinal}"


class AuthorityLayer(models.TextChoices):
    """The layers a crossing can change, which are genuinely different questions:
    which state's law applies, who polices it, who owns the right of way, and who
    manages the land. The body that issues a permit is frequently not a police
    agency, which is why scoping this to police would leave the permit issuer
    out."""

    STATE = "state", "State or district"
    POLICE = "police", "Police authority"
    RIGHT_OF_WAY = "row", "Right-of-way owner"
    MANAGER = "manager", "Park or trail manager"


class Jurisdiction(models.Model):
    """A polygon on one of the three authority layers."""

    layer = models.CharField(max_length=16, choices=AuthorityLayer.choices)
    name = models.TextField()
    state = models.CharField(max_length=2, null=True, blank=True)
    # Federal enclaves are never collapsed out of a crossing list however short
    # the crossing, because short is not the same as unimportant when the
    # question is whose permit is needed.
    is_federal_enclave = models.BooleanField(default=False)
    geometry = models.MultiPolygonField(srid=4326)

    class Meta:
        db_table = "jurisdiction"
        indexes = [models.Index(fields=["layer"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.layer})"


class BorderCrossing(models.Model):
    """A synthetic border-control node inserted where a way crosses a state line.

    Valhalla keeps no custom node tags, so the two states a node separates are
    recorded here and the application resolves crossing direction from this
    table. Node ids come from a reserved *positive* range above every id OSM has
    issued (`pipeline.borders.SYNTHETIC_NODE_ID_FLOOR`); a negative range was the
    first design and valhalla_build_tiles rejects it as unsorted input.

    Unmanaged, and in the swapped schema rather than in `public`, for the same
    reason as `Segment`: the ids are reassigned every rebuild, so the table
    describes one particular graph and has to change hands in the same rename
    as the tiles it describes. The first version was a managed table in
    `public` rewritten five stages before the swap, so a rebuild that failed at
    validation left the served graph's node ids resolving against a table
    describing a graph that was never served.
    """

    node_id = models.BigIntegerField(unique=True)
    location = models.PointField(srid=4326)
    osm_way_id = models.BigIntegerField()
    state_a = models.CharField(max_length=2)
    state_b = models.CharField(max_length=2)

    class Meta:
        managed = False  # DDL comes from the pipeline, alongside the segment table.
        db_table = "border_crossing"
        indexes = [models.Index(fields=["osm_way_id"])]

    def __str__(self) -> str:
        return f"{self.state_a}/{self.state_b} on way {self.osm_way_id}"


class Override(models.Model):
    """An audited correction applied during preprocessing.

    The sole path for access corrections. An agency's modelled stress class is
    evidence that seeds a candidate row here for approval, never a direct access
    tag: a stress class is not a legal access finding, and writing one straight
    into the graph would make ways unroutable for every modality with no review.
    """

    class Kind(models.TextChoices):
        ACCESS = "access", "Bicycle access"
        STRESS = "stress", "Stress tier"
        JURISDICTION = "jurisdiction", "Authority assignment"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    osm_way_id = models.BigIntegerField()
    value = models.JSONField()
    reason = models.TextField()
    evidence = models.TextField(
        help_text=(
            "Why this row is correct. A check-only source may never be the sole "
            "basis for an override: a discrepancy it surfaces is resolved by "
            "independent re-derivation from OSM, federal, or CC0 inputs."
        )
    )
    # Approval crosses guilds, so it is instance-admin only; an unapproved row
    # is inert rather than applied-and-flagged.
    approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "override"
        indexes = [models.Index(fields=["osm_way_id", "approved"])]

    def __str__(self) -> str:
        return f"{self.kind} on way {self.osm_way_id}"


class User(AbstractBaseUser):
    """A Discord identity, and nothing that could become a second credential.

    Django's default user carries a usable password, a stored `is_staff` and a
    stored `is_superuser`. All three are credential or grant classes this threat
    model does not have: every path here is Discord-only, standing comes from the
    bot's view of the roster, and a stored password would sit in the nightly
    dump. So the fields are gone and the two flags are derived per request.

    `AbstractBaseUser` rather than `AbstractUser` for the same reason: it brings
    the session and login plumbing without `PermissionsMixin`, which is what
    would add the stored flags and the group and permission tables back.
    """

    discord_user_id = models.BigIntegerField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    # Bumped by ban, suspension, deletion and sign-out-everywhere. Middleware
    # rejects any session issued under an older value, which is how one write
    # revokes this person's sessions and nobody else's; Django's session table
    # has no user column and cannot enumerate them.
    session_epoch = models.IntegerField(default=1)

    is_banned = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    # Deployment-level, held by no club. The only role that may cross guilds.
    is_instance_admin = models.BooleanField(default=False)
    # Deliberately not a plain flag anyone may clear. See `check_last_instance_admin`.

    USERNAME_FIELD = "discord_user_id"

    class Meta:
        db_table = "app_user"

    def __str__(self) -> str:
        return f"discord:{self.discord_user_id}"

    def save(self, *args, **kwargs):
        # Enforced at the model layer rather than left to the creation path, so
        # no code path anywhere can give an account a usable password.
        if self.has_usable_password():
            self.set_unusable_password()

        # And the deployment must not be left with nobody who can administer it.
        # Checked here rather than in the admin so every path reaches it: the
        # admin, a management command, and the deletion flow all go through save.
        if self.pk is not None:
            previous = (
                User.objects.filter(pk=self.pk)
                .only("is_instance_admin", "is_banned", "is_deleted")
                .first()
            )
            if previous is not None and previous.is_instance_admin:
                losing_it = (
                    not self.is_instance_admin
                    or (self.is_banned and not previous.is_banned)
                    or (self.is_deleted and not previous.is_deleted)
                )
                check_last_instance_admin(previous, removing=losing_it)

            # A ban or a deletion that leaves the person signed in is neither.
            # The epoch was a column the middleware read and nothing anywhere
            # incremented, so both actions took effect on paper and on no live
            # session. Bumped here rather than at the call sites for the same
            # reason the lockout guard is: the admin, a management command and
            # the deletion flow all go through save(), and one of them would have
            # been the one that forgot.
            if previous is not None and (
                (self.is_banned and not previous.is_banned)
                or (self.is_deleted and not previous.is_deleted)
            ):
                self.session_epoch += 1
                update_fields = kwargs.get("update_fields")
                if update_fields is not None:
                    kwargs["update_fields"] = {*update_fields, "session_epoch"}

        return super().save(*args, **kwargs)

    @property
    def is_staff(self) -> bool:
        """Derived per request, never stored.

        A stored grant outlives the standing it came from: a guild admin who
        loses the role, or whose guild goes degraded, would keep the admin until
        someone noticed. This resolves instead, so a banned or lapsed admin loses
        the admin along with everything else.
        """
        if self.is_banned or self.is_deleted:
            return False
        if self.is_instance_admin:
            return True
        return bool(getattr(self, "_admin_guild_ids", ()))

    @property
    def is_superuser(self) -> bool:
        """Always false. Superuser short-circuits the per-object permission
        checks this whole design depends on, so there is no way to become one."""
        return False

    @property
    def is_active(self) -> bool:
        return not (self.is_banned or self.is_deleted)

    # Django resolves permissions through PermissionsMixin, which is also what
    # brings the stored is_staff, the stored is_superuser and the group and
    # permission tables - the whole credential class this model exists to avoid.
    # So the three methods the admin calls are written out here and delegate to
    # the configured backends, which answer from application standing.
    #
    # Without them the admin raises AttributeError on every request it admits.
    # That matters beyond the crash: the obvious repair is to add
    # PermissionsMixin, which would silently restore the stored flags and undo
    # the reason this model is custom at all.

    def has_perm(self, perm: str, obj=None) -> bool:
        from django.contrib.auth import get_backends

        if not self.is_active:
            return False
        return any(
            backend.has_perm(self, perm, obj)
            for backend in get_backends()
            if hasattr(backend, "has_perm")
        )

    def has_perms(self, perm_list, obj=None) -> bool:
        return all(self.has_perm(perm, obj) for perm in perm_list)

    def has_module_perms(self, app_label: str) -> bool:
        from django.contrib.auth import get_backends

        if not self.is_active:
            return False
        return any(
            backend.has_module_perms(self, app_label)
            for backend in get_backends()
            if hasattr(backend, "has_module_perms")
        )


class InstanceAdminListing(User):
    """The instance-admin list, as a surface a guild admin may read.

    The plan makes the role "visible to the clubs it holds power over: the
    current instance admins are listed to every guild admin". Guild admins could
    see nothing of it: the only surface naming instance admins is `UserAdmin`,
    which is the whole account table and carries the membership cache's
    sensitivity, so it is instance-admin only and correctly so.

    A proxy rather than a filtered view of that page, because the permission is
    what has to be different, not just the queryset. This model gets its own
    `view_` permission, which is the one thing a guild admin's allow-list names;
    `core.view_user` stays out of it, so widening this list can never widen what
    is readable about an ordinary account. The queryset is filtered to instance
    admins and the page shows the id and nothing else.

    A proxy adds no table and no column; the migration is a no-op against the
    database.
    """

    class Meta:
        proxy = True
        verbose_name = "instance admin"
        verbose_name_plural = "instance admins"


class ConfiguredGuild(models.Model):
    """A Discord guild an instance admin has admitted to the deployment.

    A guild the bot is in but that is not configured is inert: it ingests no
    members, caches nothing and grants no standing. That, rather than the bot's
    Public Bot flag, is the admission control.
    """

    guild_id = models.BigIntegerField(unique=True)
    name = models.TextField(blank=True)
    # Entered by an instance admin, not harvested from Discord, and the channel
    # for alerts about the bot itself - which cannot travel through the bot.
    admin_contact_email = models.EmailField(blank=True)

    state = models.CharField(
        max_length=16,
        choices=[("active", "Active"), ("degraded", "Degraded"), ("revoked", "Revoked")],
        default="active",
    )
    state_since = models.DateTimeField(auto_now_add=True)
    # Clamped against the stated maximum when read; a column is not trusted to
    # carry a window of arbitrary length.
    standing_valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "configured_guild"

    def __str__(self) -> str:
        return self.name or str(self.guild_id)

    def standing(self) -> standing.GuildStanding:
        """This row as the resolver's value object.

        The mapping lives here so there is one of it. The permission path used to
        reimplement `grants_standing` inline - revoked, then degraded, then the
        clamp against the stated maximum - which meant the rule the test suite
        exercised and the rule the admin enforced were two pieces of code that
        happened to agree.
        """
        return standing.GuildStanding(
            guild_id=self.guild_id,
            state=standing.GuildState[self.state.upper()],
            state_since=self.state_since,
            standing_valid_until=self.standing_valid_until,
        )


class RoleMapping(models.Model):
    """One Discord role to one application permission, within one guild."""

    class Permission(models.TextChoices):
        MEMBER = "member", "Member"
        REVIEWER = "reviewer", "Reviewer"
        GUILD_ADMIN = "guild_admin", "Guild admin"
        INSTANCE_ADMIN = "instance_admin", "Instance admin"

    guild = models.ForeignKey(ConfiguredGuild, on_delete=models.CASCADE, related_name="roles")
    role_id = models.BigIntegerField()
    permission = models.CharField(max_length=20, choices=Permission.choices)

    class Meta:
        db_table = "role_mapping"
        constraints = [
            models.UniqueConstraint(fields=["guild", "role_id"], name="one_mapping_per_role")
        ]


class CachedMembership(models.Model):
    """What the bot last saw of one person in one guild.

    Deliberately narrow: guild, roles, timeout, and when it was last confirmed.
    No usernames, avatars, nicknames or join dates. For a tool whose threat model
    includes unpermitted rides, who organizes with whom is the sensitive part,
    which is also why this table is excluded from the nightly dump and rebuilt
    from the bot's backfill on restore.
    """

    discord_user_id = models.BigIntegerField()
    guild = models.ForeignKey(ConfiguredGuild, on_delete=models.CASCADE, related_name="members")
    role_ids = models.JSONField(default=list)
    last_confirmed = models.DateTimeField()
    pending = models.BooleanField(default=False)
    timed_out_until = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cached_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["discord_user_id", "guild"], name="one_membership_row_per_guild"
            )
        ]
        indexes = [models.Index(fields=["discord_user_id"])]

    def as_membership(self, guild_snowflake: int) -> standing.Membership:
        """This row as the resolver's value object.

        Takes the snowflake rather than reading it through the foreign key, so a
        caller that has already loaded the guilds does not issue a query per row.
        """
        return standing.Membership(
            guild_id=guild_snowflake,
            role_ids=frozenset(int(role) for role in self.role_ids),
            last_confirmed=self.last_confirmed,
            pending=self.pending,
            timed_out_until=self.timed_out_until,
            removed_at=self.removed_at,
        )


class BanTombstone(models.Model):
    """A keyed tombstone that survives account deletion.

    HMAC rather than a plain hash: a Discord id is a structured 64-bit value
    whose candidate set any guild's member list resolves directly, so an unkeyed
    hash gives no privacy at all against whoever holds a dump. The key lives in
    SSM and never appears in one.

    This table is deliberately *not* excluded from the nightly dump, and the
    decision is recorded here rather than left to be re-argued. With a real key
    the dump is safe by design: the tombstone is an HMAC under a secret that is
    never written to the database and never appears in a backup, so a dump hands
    an attacker nothing they can invert or enumerate. That is the whole reason
    the construction is keyed. Excluding it would instead mean a restore comes
    up with the ban list empty, which silently readmits every banned account -
    a worse failure than the one the exclusion would be guarding against.

    The exclusion list exists for the tables whose *plaintext* is the
    sensitivity - the membership cache, which names who organizes with whom, and
    the session table. Neither is recoverable by the bot from a keyed digest;
    both are rebuilt on restore. This one is not that shape.

    It does mean the key is load-bearing for the backup's safety as well as the
    database's, which is why `settings.TOMBSTONE_KEY` is derived from
    KEY_ENCRYPTION_KEY with no default at all: a published key would make every
    tombstone in every dump reversible against any guild's member list.
    """

    tombstone = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "ban_tombstone"


class AuditLogEntry(models.Model):
    """One attempt at a privileged write, permitted or refused.

    The visibility assertions the plan makes about the admin all end in "and the
    attempt is audited" - a guild admin cannot edit a membership row, a role
    mapping, or a route's owning guild, and the attempt is on the record. Without
    a log those assertions have a half that cannot be implemented, so a refusal
    was indistinguishable from nobody having tried.

    Deliberately narrow, for the same reason the membership cache is: it records
    who acted on what and whether it was allowed, not what the row contained.
    Where a value matters - the guild snowflake every standing check matches
    against - it is named in `detail` rather than the whole object being copied.
    """

    class Outcome(models.TextChoices):
        ALLOWED = "allowed", "Allowed"
        REFUSED = "refused", "Refused"

    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, related_name="audit_entries"
    )
    # The actor's numeric id, kept alongside the foreign key and written at
    # record time. SET_NULL alone makes two different rows identical: an action
    # a worker took with no actor at all, and an action a named person took
    # whose account was afterwards deleted. The plan wants those distinguished -
    # "Audit log rows keep the numeric actor id and display 'deleted user'" - so
    # null here as well as on the FK means "no actor", and a number with a null
    # FK means "the person who has since been deleted".
    #
    # The application's own primary key rather than the Discord id, and the
    # choice matters: the same section says deletion "retains only a tombstone
    # of the Discord id", keyed, precisely so the id itself does not survive in
    # the clear. Denormalising the Discord id into every audit row would keep in
    # plaintext, forever, the identifier the deletion flow goes to some trouble
    # to destroy. The pk identifies the actor within this deployment, which is
    # all an audit trail needs, and it means nothing outside it.
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=32)
    model = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    detail = models.TextField(blank=True)

    class Meta:
        db_table = "audit_log"
        indexes = [
            models.Index(fields=["-at"]),
            models.Index(fields=["actor", "-at"]),
            models.Index(fields=["model", "-at"]),
        ]

    def __str__(self) -> str:
        return f"{self.actor_id} {self.outcome} {self.action} {self.model} {self.object_id}"

    def actor_label(self) -> str:
        """Who acted, including when the account is gone.

        Three distinct answers, which is the point of carrying the id as well as
        the foreign key: a live account, a deleted one, and no actor at all.
        """
        if self.actor_id is not None:
            return str(self.actor)
        if self.actor_user_id is not None:
            return f"deleted user {self.actor_user_id}"
        return "no actor (worker)"


class ScheduledRun(models.Model):
    """One run of one periodic task, successful or not.

    The alerts read this table rather than a log stream, because the failures
    that matter most here are the ones that produce nothing to read: a rebuild
    that stopped being scheduled and a backup that stopped being taken both emit
    no error at all. An alert built on the absence of an error would stay silent
    through exactly those, so what is watched is the absence of a recent success.
    """

    task = models.CharField(max_length=64)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    succeeded = models.BooleanField(default=False)
    detail = models.TextField(blank=True)

    class Meta:
        db_table = "scheduled_run"
        indexes = [models.Index(fields=["task", "-started_at"])]

    def __str__(self) -> str:
        state = "succeeded" if self.succeeded else ("running" if not self.finished_at else "failed")
        return f"{self.task} {state} at {self.started_at:%Y-%m-%d %H:%M}"


class ValhallaUpstream(models.Model):
    """Where the API's routing client finds each tile variant's Valhalla, and
    which build it is serving.

    This is the "settings table the API watches" in the plan's swap. The swap
    writes it *before* it renames the schema, so the inconsistency window is a
    live segment table describing the older graph rather than a graph nobody is
    serving; rollback writes the previous values back. The previous build is
    kept on the row so a rollback needs nothing but the row.

    Nothing reads `url` yet - the routing client is phase 2 - but the row has to
    exist and be written now, because the swap's ordering argument depends on
    it and a swap without it is only half a swap.
    """

    variant = models.CharField(max_length=16, unique=True)
    url = models.CharField(max_length=200)
    # The dated build directory being served, e.g. 20260917T080000Z, and the
    # one before it. Both are directory names under TILES_DIR/<variant>.
    build_id = models.CharField(max_length=32, blank=True)
    previous_build_id = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valhalla_upstream"

    def __str__(self) -> str:
        return f"{self.variant} -> {self.url} ({self.build_id or 'no build'})"


class DriftReport(models.Model):
    """What changed between the graph just retired and the one just promoted.

    The plan's reconciliation job re-resolves anchors after each swap and emits
    a drift report. Anchors are phase 2 - there are no routes yet to anchor
    anything to - so in phase 1 the report is the segment-level half only: how
    many segments the new build lost, gained, or re-graded, measured against the
    retired schema while it still exists. `unresolved_anchors` stays null until
    there are anchors to resolve, and is not zero, because zero would be a
    claim.
    """

    build_id = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    segments_before = models.IntegerField()
    segments_after = models.IntegerField()
    segments_lost = models.IntegerField()
    segments_added = models.IntegerField()
    segments_regraded = models.IntegerField()
    crossings_before = models.IntegerField()
    crossings_after = models.IntegerField()
    unresolved_anchors = models.IntegerField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = "drift_report"
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self) -> str:
        return (
            f"build {self.build_id}: {self.segments_lost} lost, {self.segments_added} added, "
            f"{self.segments_regraded} regraded"
        )


class Session(models.Model):
    """A session, carrying the user and the epoch it was issued under.

    Django's own session table has neither, which is why ban, suspension,
    deletion and sign-out-everywhere had no mechanism: the only global lever was
    rotating the secret key, which signs everybody out.
    """

    session_key = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    issued_epoch = models.IntegerField()
    # Both timestamps are written explicitly rather than by auto_now_add and
    # auto_now. Under auto_now the middleware's own assignment to last_seen_at
    # was overwritten on save, so the field it updates was set by Django rather
    # than by the request; and neither an aged session nor an idle one could be
    # constructed through save() at all, which is why the absolute and idle
    # expiry branches had no test.
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        db_table = "app_session"
        indexes = [models.Index(fields=["user"])]


class LastInstanceAdmin(RuntimeError):
    """The deployment would be left with nobody who can administer it."""


def check_last_instance_admin(user: User, *, removing: bool) -> None:
    """Refuse the change that would leave no instance admin at all.

    There is no password login and no `createsuperuser` path on this deployment -
    the model forces an unusable password and `is_superuser` has no setter - so
    an instance admin who clears their own flag, or is banned or deleted, cannot
    be restored through the application at all. The recovery is a hand-written
    UPDATE against production by whoever has database access, which is a worse
    position than the one this refusal creates.

    Checked here rather than in the admin so that every path reaches it: the
    admin, a management command, and the deletion flow all go through save().
    """
    if not removing or not user.is_instance_admin:
        return
    remaining = (
        User.objects.filter(is_instance_admin=True, is_banned=False, is_deleted=False)
        .exclude(pk=user.pk)
        .exists()
    )
    if not remaining:
        raise LastInstanceAdmin(
            "refusing to remove the last instance admin; there is no login path that "
            "could restore one, so appoint another first"
        )


class PendingInstanceAdminRemoval(models.Model):
    """A removal of an instance admin that has been requested and not yet taken
    effect.

    The plan: "Removing an instance admin other than yourself notifies every
    remaining instance admin and the removed party and takes effect after a
    delay, configurable and defaulting to an hour, during which any instance
    admin can cancel it; without that, one admin could remove every peer down to
    themselves in a single audited but unstoppable action." Measured before this
    existed: three POSTs, one admin left, no delay and nothing to cancel.

    So the removal writes a row here instead of clearing the flag. The flag is
    still set while this row exists - the person remains an instance admin, with
    every power that carries, until `apply_due_instance_admin_removals` passes
    over them - which is what makes the window a real window rather than a
    notification about something that already happened.

    Self-removal does not come through here. The plan makes the delay a guard
    against being removed by somebody else, and an admin standing down has no
    peer to appeal to; `check_last_instance_admin` is what stops that emptying
    the list.

    The notification half is not built. Phase 1 has no channel to send it on -
    no Discord DM path and no email path exists in this deployment - so this
    carries the delay and the cancel, and the notification is an outstanding
    gap rather than something silently dropped.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="pending_instance_admin_removal"
    )
    # Who asked. SET_NULL for the same reason the audit log's actor is, and the
    # id is kept beside it so a deleted requester is not indistinguishable from
    # a removal nobody requested.
    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="requested_admin_removals"
    )
    requested_by_user_id = models.BigIntegerField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    # Read from the row rather than recomputed from the setting at application
    # time: changing the delay must not move a removal that is already pending.
    effective_at = models.DateTimeField()

    class Meta:
        db_table = "pending_instance_admin_removal"
        indexes = [models.Index(fields=["effective_at"])]

    def __str__(self) -> str:
        return f"remove {self.user} at {self.effective_at:%Y-%m-%d %H:%M}"

    def is_due(self, now=None) -> bool:
        return (now or timezone.now()) >= self.effective_at


def schedule_instance_admin_removal(user: User, actor=None, now=None):
    """Request the removal of `user`'s instance admin, to take effect later.

    Refuses the same removal `save()` would refuse: scheduling the removal of
    the last instance admin is the lockout, only an hour later, and an hour is
    long enough for everyone to forget it was coming.

    Requesting a removal that is already pending updates who asked and leaves
    the clock where it is unless the new time is later. The row's own comment
    already says the effective time is read from the row rather than recomputed
    "because changing the delay must not move a removal that is already
    pending", and `update_or_create` overwrote it from the setting on every
    request, so a second request under a shortened delay moved a window that was
    already running *forwards*. Never earlier, in one direction only: the window
    exists to be long enough to notice, and nobody may shorten one that is
    already ticking by asking for the same removal again.
    """
    from .audit import record

    check_last_instance_admin(user, removing=True)
    now = now or timezone.now()
    effective_at = now + settings.INSTANCE_ADMIN_REMOVAL_DELAY
    existing = PendingInstanceAdminRemoval.objects.filter(user=user).first()
    if existing is not None:
        effective_at = max(existing.effective_at, effective_at)
    pending, _created = PendingInstanceAdminRemoval.objects.update_or_create(
        user=user,
        defaults={
            "requested_by": actor if getattr(actor, "pk", None) else None,
            "requested_by_user_id": getattr(actor, "pk", None),
            "effective_at": effective_at,
        },
    )
    record(
        actor,
        "schedule_removal",
        "user",
        user.pk,
        AuditLogEntry.Outcome.ALLOWED,
        detail=f"instance admin removal takes effect at {effective_at.isoformat()}",
    )
    return pending


def cancel_instance_admin_removal(pending: PendingInstanceAdminRemoval, actor=None) -> None:
    """Call off a pending removal. Any instance admin may, which is the half of
    the plan's sentence that makes the delay worth having."""
    from .audit import record

    user_id = pending.user_id
    pending.delete()
    record(
        actor,
        "cancel_removal",
        "user",
        user_id,
        AuditLogEntry.Outcome.ALLOWED,
        detail="pending instance admin removal cancelled",
    )


def apply_due_instance_admin_removals(now=None) -> int:
    """Clear the flag for every removal whose delay has run out, and audit each.

    Returns the number applied.

    Separated from any scheduler on purpose: the worker's task module is another
    owner's file, so this is the callable the existing periodic sweep calls, and
    it takes `now` so a test does not have to wait an hour. It has no request and
    therefore no actor; the requester is on the row and in the scheduling audit
    entry.

    A removal that has become the last one is left pending and audited as
    refused rather than dropped: `check_last_instance_admin` is the deployment's
    lockout guard and the delay does not get to walk past it, and a row still
    sitting there is visible in the admin, where an instance admin can cancel it
    or appoint a successor.
    """
    from .audit import record

    now = now or timezone.now()
    applied = 0
    for pending in PendingInstanceAdminRemoval.objects.select_related("user").filter(
        effective_at__lte=now
    ):
        user = pending.user
        user.is_instance_admin = False
        try:
            user.save(update_fields=["is_instance_admin"])
        except LastInstanceAdmin as error:
            record(
                None,
                "apply_removal",
                "user",
                user.pk,
                AuditLogEntry.Outcome.REFUSED,
                detail=str(error),
            )
            continue
        pending.delete()
        record(
            None,
            "apply_removal",
            "user",
            user.pk,
            AuditLogEntry.Outcome.ALLOWED,
            detail=(
                "instance admin removed; requested by "
                f"{pending.requested_by_user_id} at {pending.requested_at.isoformat()}"
            ),
        )
        applied += 1
    return applied


class BootstrapClaim(models.Model):
    """The record that the environment bootstrap path has been used.

    PLAN.md:212 says the first successful admin action under the bootstrap id
    "permanently disables the environment path". Permanently is the word that
    was not implemented: the check was `User.objects.filter(is_instance_admin=
    True).exists()`, so the path was disabled only while the list stayed
    non-empty. Measured: claim once (flag set), `.update(is_instance_admin=
    False)` on the only holder - which is what a management shell, a migration
    or the removal of a ban-tombstoned account does - and the same id claimed
    again. Anyone who ever held `.env` read access held a standing offer of
    instance admin against any future moment the list happened to be empty,
    which is exactly what the sentence rules out.

    So the claim is recorded here instead, in a row, in the database that the
    nightly dump carries - not in a module-level flag, which a restart clears,
    and not inferred from the list, which is the state that changes.

    One row, and that is a constraint rather than a convention: `singleton` is
    a constant column with a unique index, so a second INSERT is an
    `IntegrityError` from PostgreSQL rather than a second row that a later
    reader has to interpret. That also closes the race the handoff's §7 records
    as accepted - two simultaneous first requests from the bootstrap id both
    passing the empty-list check - because one of the two INSERTs loses.

    What it costs: once this row exists, an instance-admin list that empties
    cannot be refilled through the application at all. That is the trade the
    plan asks for, and the repair is the same break-glass the handoff already
    names - a hand-written UPDATE against the database by whoever has access.
    `check_last_instance_admin` exists precisely so that the list cannot empty
    through any path the application offers.
    """

    SINGLETON = 1

    singleton = models.PositiveSmallIntegerField(default=SINGLETON, unique=True, editable=False)
    # The id that claimed it, kept as a number rather than only as a relation:
    # the account can be deleted and the record of which id spent the path
    # should outlive it.
    discord_user_id = models.BigIntegerField()
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    claimed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bootstrap_claim"

    def __str__(self) -> str:
        return f"bootstrap claimed by {self.discord_user_id} at {self.claimed_at:%Y-%m-%d %H:%M}"


def claim_bootstrap_instance_admin(user: User) -> bool:
    """Write the bootstrap id into the instance-admin list, once.

    The plan: the environment holds one bootstrap Discord id, "and that value
    grants standing only while the instance-admin list is empty. The first
    successful admin action writes the bootstrap id into the list and
    permanently disables the environment path, audited, after which anyone
    holding `.env` read access holds nothing."

    Before this there was no bootstrap path at all: `is_instance_admin` is a
    stored flag, the only surface that writes it is an admin page that only an
    instance admin may reach, there is no password login and no
    `createsuperuser`, so on an empty database every signed-in account got a 404
    at the admin and the deployment could only be started with a hand-written
    UPDATE against production.

    Reaching the admin at all is the "first successful admin action" - it is the
    first request this deployment admits under the bootstrap standing - so the
    claim happens in `RouteMakerAdminSite.has_permission`, before the request is
    admitted, and everything after it runs as an ordinary instance admin.

    Returns whether the flag was written. False whenever the list is not empty,
    which is what makes the variable inert afterwards even if it still names
    somebody, and false for a banned or deleted account, which must not be
    admitted by any path.

    And false forever once it has succeeded once, which is the other half of
    "permanently disables". The disabling is a `BootstrapClaim` row rather than
    the state of the list: the list is what changes, so a check against it
    re-armed the environment path every time the list happened to empty, and a
    holder of `.env` read access held a standing offer of instance admin rather
    than nothing. Once that row exists, an emptied list is recoverable only by
    the break-glass the handoff records - a hand-written UPDATE against the
    database - and `check_last_instance_admin` is what keeps the application
    from ever emptying it.

    The emptiness test counts the instance admins `check_last_instance_admin`
    counts: banned and deleted holders excluded, because they cannot sign in and
    so are not somebody the deployment can be administered by. The two used to
    disagree, so a deployment whose only instance admin had been banned was one
    the lockout guard called empty and this function called occupied.
    """
    from .audit import record

    bootstrap_id = getattr(settings, "BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID", None)
    if not bootstrap_id or user.is_instance_admin:
        return False
    if user.discord_user_id != bootstrap_id or not user.is_active:
        return False
    if BootstrapClaim.objects.exists():
        logger.warning(
            "the bootstrap instance-admin path has already been spent and will not "
            "be offered again; restoring an empty instance-admin list needs direct "
            "database access"
        )
        return False
    if User.objects.filter(is_instance_admin=True, is_banned=False, is_deleted=False).exists():
        # The list is not empty, so the environment path grants nothing to
        # anyone - including to the id it still names.
        return False

    # The claim row first, and in the same transaction as the flag: if two
    # requests arrive together, the unique index on `singleton` makes one of
    # them lose here rather than both writing the flag.
    #
    # The flag is written with update() rather than save(): nothing else on the
    # row changes, and this is an appointment rather than the moderation path
    # save() carries the epoch and lockout logic for.
    try:
        with transaction.atomic():
            BootstrapClaim.objects.create(discord_user_id=user.discord_user_id, user=user)
            User.objects.filter(pk=user.pk).update(is_instance_admin=True)
    except IntegrityError:
        logger.warning(
            "the bootstrap instance-admin path was spent by a concurrent request; "
            "this one grants nothing"
        )
        return False

    user.is_instance_admin = True
    record(
        user,
        "bootstrap_instance_admin",
        "user",
        user.pk,
        AuditLogEntry.Outcome.ALLOWED,
        detail=(
            "bootstrap Discord id claimed instance admin on an empty list; "
            "the environment path is spent permanently, recorded by a bootstrap_claim row"
        ),
    )
    return True

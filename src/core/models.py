"""Phase 1 schema: the tables the preprocessing pipeline writes and the
application reads.

Two rules shape this module. Segment data is *rebuilt* weekly into a staging
schema and swapped, so those models are unmanaged and their DDL comes from the
pipeline rather than from migrations. Everything anchored to a segment refers to
it by plain columns rather than a foreign key, because a cross-schema constraint
would make the swap impossible.
"""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.gis.db import models

from . import standing


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

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
    AVOID = 5, "Legal but avoid"


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
    # NO-BIKE-PATHS (OWNER-DECISIONS 291): closed on the standard graphs for being
    # mountain-bike class or singletrack, kept for a future MTB mode; and a short
    # `bicycle=dismount` connector routing keeps ("walk your bike here"). The
    # table is unmanaged, so these arrive with a rebuild (pipeline.schema).
    mtb_only = models.BooleanField(default=False)
    walk_bike = models.BooleanField(default=False)
    # The difficulty level of a mountain-bike-only way, 1 to 4, or null (OWNER-DECISIONS
    # 456, 456a-c; `routemaker.singletrack.mtb_level`). Arrives with a rebuild, as above.
    mtb_level = models.SmallIntegerField(null=True)
    # Its name, for the map's label and the road panel (the owner, 2026-10-10).
    mtb_name = models.TextField(null=True)

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
        # v0.7.0: a routing price for a rough or loose surface, not a level
        # (`pipeline.overrides.SURFACE_PENALTIES`). The graph has it from the next rebuild.
        SURFACE = "surface", "Surface penalty"

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

    class Source(models.TextChoices):
        FILE = "file", "Reviewed file"
        ADMIN = "admin", "Typed into the admin"
        PANEL = "panel", "Road panel (Change LTS)"
        # An instance admin's ruling in Review that reopened a closed road (core.stress_review):
        # told apart by this value, never by its words, so the import can list it as one.
        REVIEW = "review", "Review mode (reopened)"

    # Where the row came from. A row a file loaded and a row an instance admin
    # wrote in the road panel are told apart because the loader must never undo
    # the second (see `superseded_by`).
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.FILE)
    # Who wrote and who approved it: the application's own user id, never the
    # Discord id (the audit log's reasoning, `AuditLogEntry.actor_user_id`). The
    # numeric copy survives the account's deletion, which SET_NULL on the key alone
    # would make look like a row nobody wrote. Null on every row the loader or the
    # admin wrote before the road panel's editor existed.
    created_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by_user_id = models.BigIntegerField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_by_user_id = models.BigIntegerField(null=True, blank=True)
    # A later panel edit replaced this row. A superseded row stays approved on
    # purpose: `load_access_overrides` re-approves an unapproved row that matches
    # a file, so unapproving it would let reloading an old file undo the edit.
    # It is inert instead - the rebuild reads only rows that are not superseded
    # (`pipeline.overrides.load_approved`) - and the loader leaves it alone.
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes"
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    # What the way looked like when the panel wrote the row (`pipeline.rematch`
    # shape), so a rebuild can find the way again after OSM splits it. Null on a
    # row typed into the admin.
    fingerprint = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "override"
        indexes = [models.Index(fields=["osm_way_id", "approved"])]
        constraints = [
            # At most one approved, live stress row a way. Two would be applied
            # in id order, which is not a decision anybody made.
            models.UniqueConstraint(
                fields=["osm_way_id"],
                condition=models.Q(kind="stress", approved=True, superseded_by__isnull=True),
                name="override_one_live_stress_row_per_way",
            ),
            # And one live surface row (v0.7.0), for the same reason.
            models.UniqueConstraint(
                fields=["osm_way_id"],
                condition=models.Q(kind="surface", approved=True, superseded_by__isnull=True),
                name="override_one_live_surface_row_per_way",
            ),
        ]

    def clean(self) -> None:
        # A surface row typed into the admin is checked here, not first at the rebuild, where
        # a bad value refuses the whole rebuild (`pipeline.overrides.apply_surface`).
        if self.kind == self.Kind.SURFACE:
            from django.core.exceptions import ValidationError

            from pipeline.overrides import surface_value_problem

            problem = surface_value_problem(self.value)
            if problem:
                raise ValidationError({"value": problem})

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

            # A deleted account keeps no My Go (its Home is a place the rider lives).
            if previous is not None and self.is_deleted and not previous.is_deleted:
                MyGo.objects.filter(user_id=self.pk).delete()
                # Nor its saved settings and routes (v0.7.0: "deleted with the account").
                AccountSettings.objects.filter(user_id=self.pk).delete()
                SavedRoute.objects.filter(user_id=self.pk).delete()
                # Its shared links keep working for those they were sent to, but with Home gone
                # their previews could no longer hide it: no image from now on.
                SharedRoute.objects.filter(owner_id=self.pk).update(
                    preview_image=False, preview_png=None, preview_key="", preview_zone=None
                )

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

        "No actor" is two populations rather than one, and the label says so.
        A scheduled task has no request and so no actor; so does a host operator
        running `manage.py run_rebuild_now` or `rollback_rebuild` through
        `docker compose exec`, which audits with `actor=None` for the same
        reason. Reading an actorless row as "the worker did it" would put a
        human action on the machine's account, and the log has no other column
        that would correct it.
        """
        if self.actor_id is not None:
            return str(self.actor)
        if self.actor_user_id is not None:
            return f"deleted user {self.actor_user_id}"
        return "no actor (worker or host operator)"


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
        state = (
            "succeeded"
            if self.succeeded
            else (
                "running"
                if not self.finished_at
                else ("paused" if self.detail.startswith("paused (") else "failed")
            )
        )
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


def clear_instance_admin_removal_on_appointment(user: User, actor=None) -> int:
    """Drop a removal still pending against an account being appointed, audited.

    A removal requested by a peer outlives the target's own stand-down, which is
    immediate and does not come through the window. Left there, the row comes
    due after a fresh appointment and strips it - a removal nobody requested of
    this appointment, with no window of its own and nothing on the pending page
    anyone would think to cancel. Round 10 reproduced it end to end.

    Called only on the transition from not holding the flag to holding it, so it
    never touches a removal pending against somebody who still holds it: that
    is the window working, and who may cancel it is not decided here.

    The rows are taken `FOR UPDATE`, waited on rather than skipped, so an
    `apply_due_instance_admin_removals` run already applying this row finishes
    before the appointment is written over it, and the appointment is what
    stands. Returns the number cleared.
    """
    from .audit import record

    cleared = 0
    with transaction.atomic():
        for pending in PendingInstanceAdminRemoval.objects.select_for_update().filter(user=user):
            requested_by, requested_at = pending.requested_by_user_id, pending.requested_at
            pending.delete()
            record(
                actor,
                "cancel_removal",
                "user",
                user.pk,
                AuditLogEntry.Outcome.ALLOWED,
                detail=(
                    "pending instance admin removal cleared on re-appointment; requested by "
                    f"{requested_by} at {requested_at.isoformat()}"
                ),
            )
            cleared += 1
    return cleared


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

    Two tasks call this - the five-minute degraded sweep, which is the applier,
    and the six-hourly membership sweep, which is the backstop - onto a worker
    with four slots and no lock between them. Unlocked, both runs read the same
    due row, both clear the same flag and both write an `apply_removal` audit
    entry for it: the outcome is right and the record says the removal was
    applied twice, in an append-only log that is the deployment's account of who
    lost what and when. So the due rows are taken `FOR UPDATE SKIP LOCKED`
    inside the transaction that applies them - skipped rather than waited on,
    because a concurrent run is already applying them and a sweep should not
    hold a worker slot behind one. `of=("self",)` keeps the lock on the pending
    rows; `select_related` would otherwise lock the user rows the admin is
    editing too.
    """
    from .audit import record

    now = now or timezone.now()
    applied = 0
    with transaction.atomic():
        due = (
            PendingInstanceAdminRemoval.objects.select_related("user")
            .select_for_update(skip_locked=True, of=("self",))
            .filter(effective_at__lte=now)
        )
        for pending in due:
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
            # An appointment like the admin's, so a removal left pending from
            # before an emptied list must not come due and strip it.
            clear_instance_admin_removal_on_appointment(user, actor=user)
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


class RateLimitWindow(models.Model):
    """One client's count in the current fixed window of one limit.

    PLAN, Moderation and abuse limits: every limit is counted in a PostgreSQL
    fixed-window table rather than in process memory, because gunicorn runs a
    worker per core and in-memory counters would multiply every stated limit by
    the worker count. `core.ratelimit` does the counting in one upsert, which is
    what makes it correct across workers; this model exists for the migration.

    `client` is a keyed digest of the address, never the address (PLAN, Privacy
    and retention), and the row is reused from window to window, so the table
    grows with the number of clients rather than with time. Rows untouched for
    `core.ratelimit.RETENTION` are purged.
    """

    scope = models.CharField(max_length=32)
    client = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    hits = models.IntegerField()

    class Meta:
        db_table = "rate_limit_window"
        constraints = [
            models.UniqueConstraint(fields=["scope", "client"], name="rate_limit_window_client")
        ]
        indexes = [models.Index(fields=["window_start"], name="rate_limit_window_start")]

    def __str__(self) -> str:
        return f"{self.scope}: {self.hits} since {self.window_start:%H:%M:%S}"


class StressTileCache(models.Model):
    """A drawn stress tile, kept so it is not drawn again (core.tile_cache).

    `version` is the tile's ETag, which names the live segment table's oid,
    the optional columns it has and the tile format, so a promotion, a column
    added in place or a format change makes every older row stale; stale rows
    are deleted by the next pre-draw or eviction. Nothing here is personal and
    nothing is lost with it: the table is excluded from the nightly dump and
    refills itself.
    """

    version = models.CharField(max_length=64)
    z = models.SmallIntegerField()
    x = models.IntegerField()
    y = models.IntegerField()
    body = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stress_tile_cache"
        constraints = [
            models.UniqueConstraint(fields=["version", "z", "x", "y"], name="stress_tile_cache_key")
        ]
        indexes = [models.Index(fields=["created_at"], name="stress_tile_cache_created")]

    def __str__(self) -> str:
        return f"{self.z}/{self.x}/{self.y} ({self.version})"


class StressEdit(models.Model):
    """One road-panel action on a way's traffic stress: what changed, who by.

    The audit log is deliberately narrow (who, what object, allowed or not, never a
    copy of the row), so the before and after of a stress change live here, in a
    table of their own. `before` is what an undo puts back; `after` is what a
    promotion or a rollback re-applies (`core.stress_edits`).

    Nothing here is shown to a rider. The private reason is on the override row.
    """

    class Action(models.TextChoices):
        SET = "set", "Change"
        UNDO = "undo", "Undo"

    at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The application's user id, kept beside the key for the reason
    # `AuditLogEntry.actor_user_id` is; never the Discord id.
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=8, choices=Action.choices)
    # The row this edit created, or that an undo reinstated (null when an undo left
    # the way with no row), and the live row it superseded.
    override = models.ForeignKey(
        Override, on_delete=models.SET_NULL, null=True, blank=True, related_name="edits"
    )
    replaced = models.ForeignKey(
        Override, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Every way's pair, [{"way", "override", "replaced"}] (row ids or null): a named stretch
    # has one a way (HALF-STEP-EDITOR phase 5). `override`/`replaced` above are the first
    # way's; an edit from before phase 5 has only those.
    override_rows = models.JSONField(default=list, blank=True)
    # For an undo, the edit it undid.
    undoes = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="undone_by"
    )
    osm_way_ids = models.JSONField(default=list)
    # {"<way>:<ordinal>": {column: value}} as the live table held it, and as this
    # edit left it. Every column the edit may touch, so either side can be written back.
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    # The live table's oid when applied, the oids of later tables it was re-applied to,
    # and the edit generation after it (it is in the tile ETag).
    applied_to = models.BigIntegerField(null=True, blank=True)
    reapplied_to = models.JSONField(default=list)
    generation = models.IntegerField(default=0)

    class Meta:
        db_table = "stress_edit"
        ordering = ["id"]
        indexes = [models.Index(fields=["-at"], name="stress_edit_at")]

    def __str__(self) -> str:
        return f"{self.action} of ways {self.osm_way_ids} at {self.at:%Y-%m-%d %H:%M}"


class LiveEditGeneration(models.Model):
    """How many panel edits one live segment table has had since it was promoted.

    Keyed by the table's oid, which survives the swap's renames, so a promotion
    starts a new table at generation 0. The generation goes into the stress tile's
    ETag: an in-place update changes the tiles but not the table's oid, and without
    it a browser's revalidation would be answered 304 for the old tile.

    `overrides_read_at` is when the rebuild that made the table read the approved
    rows (set at promotion). A promotion or a rollback re-applies the edits made
    after it.
    """

    table_oid = models.BigIntegerField(unique=True)
    generation = models.IntegerField(default=0)
    overrides_read_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "live_edit_generation"

    def __str__(self) -> str:
        return f"table {self.table_oid}: generation {self.generation}"


class BikeshareFeedCache(models.Model):
    """The bikeshare operator's latest GBFS feeds, one copy for all API workers
    (core.gbfs.DatabaseStore).

    There is exactly one row ( = "current"), replaced in place at every refresh,
    about once a minute: the feeds as the operator published them, and when they were
    read. Nothing here is history: an earlier reading is overwritten, no row is added per
    reading or per station, and nothing is personal. It exists so that the deployment makes
    one request to the operator's feeds a minute rather than one a worker (the operator's
    data licence, OWNER-DECISIONS 300, allows a product to use the feeds, not to hold a
    stand-alone dataset). It is excluded from the nightly dump and from the beta's data
    shipment, and refills itself.

    The saved-route closure check keeps its state here too (key `SAVED_ALERTS`,
    core.saved_route_alerts): a hash and a place reached, nothing personal.

    It holds one more row of the same kind: the live work zones (FOLLOWUP-WORKZONES,
    key `WORKZONES`, written by `core.workzones.refresh` every five minutes), the
    parsed zones of the Maryland and VDOT WZDx feeds as last read. Same life as the
    bikeshare row: replaced in place, no history, excluded from the dump, refills
    itself; shared here rather than in a table of its own to avoid a migration. So
    the table is "one current copy of a live third-party feed per key", and every
    reader filters on its own key (`CURRENT` for GBFS, `core.gbfs.DatabaseStore`).
    """

    CURRENT = "current"
    WORKZONES = "workzones"
    # DC's closures (v0.7.0, `core.closure_sources`): the same kind of row, its own key.
    CLOSURES = "closures"
    SAVED_ALERTS = "saved_alerts"

    key = models.CharField(max_length=16, unique=True)
    payload = models.JSONField(null=True)
    fetched_at = models.DateTimeField(null=True)
    failed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "bikeshare_feed_cache"

    def __str__(self) -> str:
        return f"bikeshare feeds as of {self.fetched_at}"


class SuggestionSettings(models.Model):
    """Who may suggest a change to a road's traffic stress from the road panel (460.4).

    One row (pk 1), edited in the admin. The default is nobody, the safest choice until an
    instance admin opens it (HALF-STEP-EDITOR phase 4; docs/OPERATIONS.md, "Rider
    suggestions").
    """

    class Who(models.TextChoices):
        NOBODY = "nobody", "Nobody"
        SIGNED_IN = "signed_in", "Anyone signed in"
        MEMBERS = "members", "Members of a configured Discord server"

    who = models.CharField(max_length=16, choices=Who.choices, default=Who.NOBODY)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "suggestion_settings"
        verbose_name = "suggestion settings"
        verbose_name_plural = "suggestion settings"

    def __str__(self) -> str:
        return f"Who may suggest: {self.get_who_display()}"

    @classmethod
    def current(cls) -> SuggestionSettings:
        row = cls.objects.filter(pk=1).first()
        return row if row is not None else cls(pk=1)


class StressSuggestion(models.Model):
    """A rider's suggested traffic stress level for one road piece (441h, 460.5).

    Never applied by itself. An instance admin approves it now (it is applied as the admin's
    own edit, `core.stress_edits.apply`), deletes it, or sends it to Discord - a ready-to-paste
    poll (`core.suggestion_post`) - and approves or deletes it later (the owner, 2026-10-10).
    The rider's reason may be quoted in that post without their name; the account is kept
    here only so an admin can see a pattern of abuse, and is never in the post.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for review"
        SENT = "sent_to_discord", "Sent to Discord"
        APPROVED = "approved", "Approved"
        DELETED = "deleted", "Deleted"

    class Kind(models.TextChoices):
        ROAD = "road", "Road piece"
        # v0.7.0 closures: a rider's report that the road is closed (the short form's "Closed"
        # reason). Reviewed with the closures (core.reviewed_closures), never as a level.
        CLOSURE = "closure", "Closure report"

    created_at = models.DateTimeField(default=timezone.now)
    suggester = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggester_user_id = models.BigIntegerField(null=True, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.ROAD)
    osm_way_id = models.BigIntegerField()
    # The spot the rider asked about, and the road as it was then.
    lat = models.FloatField()
    lon = models.FloatField()
    road_name = models.TextField(blank=True)
    current_tier = models.SmallIntegerField()
    current_half = models.BooleanField(default=False)
    tier = models.SmallIntegerField()
    half = models.BooleanField(default=False)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    edit = models.ForeignKey(
        StressEdit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # v0.7.0, signed-out suggestions (core.signed_out_suggestions): sent from the short form by
    # someone not signed in. No account, address or device is kept with it; `reasons` are the
    # one-tap reasons' keys ("fast_traffic", ..., "other"), `reason` their words and any text.
    signed_out = models.BooleanField(default=False)
    reasons = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "stress_suggestion"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="stress_suggestion_open")]
        # One open suggestion per rider per road, held by the database: the check in
        # core.suggestions counts rows, which locks nothing against a second send at once.
        constraints = [
            models.UniqueConstraint(
                fields=["suggester", "osm_way_id"],
                condition=models.Q(status__in=["pending", "sent_to_discord"]),
                name="stress_suggestion_one_open_per_road",
            )
        ]

    def __str__(self) -> str:
        return f"way {self.osm_way_id}: {self.get_status_display()}"

    @property
    def step(self) -> float:
        return self.tier + 0.5 if self.half else self.tier

    @property
    def current_step(self) -> float:
        return self.current_tier + 0.5 if self.current_half else self.current_tier


class StressSuggestionReview(models.Model):
    """A second reviewer's agree or disagree on a waiting road suggestion (v0.7.0;
    core.suggestions.review).

    Advice for the admin who decides, never a decision: approving still takes the review's own
    Approve now. One a reviewer a suggestion, changed in place when they change their mind. The
    review list shows the tallies and the one-line reasons, never who wrote them; the reviewer's
    account is kept for the audit, as the suggester's is.
    """

    suggestion = models.ForeignKey(
        StressSuggestion, on_delete=models.CASCADE, related_name="reviews"
    )
    reviewer = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewer_user_id = models.BigIntegerField()
    agree = models.BooleanField()
    reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "stress_suggestion_review"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["suggestion", "reviewer_user_id"],
                name="stress_suggestion_review_one_per_reviewer",
            )
        ]

    def __str__(self) -> str:
        return f"suggestion {self.suggestion_id}: {'agree' if self.agree else 'disagree'}"


class SignedOutSend(models.Model):
    """One signed-out suggestion's count toward its sender's daily limits (v0.7.0;
    core.signed_out_suggestions): 10 a day per device and one per road.

    `device` is a salted hash of the sender's address and the day (HMAC with a key derived
    from the server's secret, so it cannot be reversed or matched across days); the address
    itself is never stored. Rows older than 24 hours are deleted at every send and nightly
    (`signed_out_suggestions.prune`, by the backup task), so nothing
    here outlives a day. Nothing links a row to its suggestion.
    """

    device = models.CharField(max_length=64)
    osm_way_id = models.BigIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "signed_out_send"
        indexes = [models.Index(fields=["device", "created_at"], name="signed_out_send_device")]

    def __str__(self) -> str:
        return f"way {self.osm_way_id} at {self.created_at:%Y-%m-%d %H:%M}"


class AvoidJunction(models.Model):
    """A junction rated Avoid (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307-310, 335).

    "Would only be added through community (or my) input": never assigned by the
    junction model, only by a person. An instance admin writes or approves each row;
    an unapproved row is inert. The list ships empty.

    Read at request time (`core.avoid_junctions.approved`), so adding one changes the
    next plan with no rebuild: a route that passes it pays `AVOID_JUNCTION_PENALTY_S`
    (30 minutes, 308) in the plan's comparison, and where one is still used the answer
    says so first and offers the best route round it (335).

    Kept apart from `Override` (way-keyed, applied by the rebuild) and from any rider
    suggestion table: a reviewed suggestion becomes a row here with `source`
    "community" and its reference in `suggestion_ref`, so the suggestion flow can feed
    it without this table knowing its shape.

    `plans_through` counts the plans whose answer passed it (335: "how often plans pass
    through them, to keep both rare"): a counter and a date, never the route, the rider
    or the request.
    """

    class Source(models.TextChoices):
        ADMIN = "admin", "Owner or instance admin"
        COMMUNITY = "community", "Community suggestion, reviewed"

    name = models.CharField(
        max_length=200,
        help_text='The junction as riders know it, e.g. "Main St and 1st Ave". Shown to riders.',
    )
    location = models.PointField(
        srid=4326,
        help_text="The junction's centre: where the roads' centre lines meet.",
    )
    reason = models.CharField(
        max_length=300,
        help_text="Why it is rated Avoid, in a few plain words. Shown to riders.",
    )
    evidence = models.TextField(
        blank=True,
        help_text="What the rating rests on (reports, a visit, crashes). Not shown to riders.",
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.ADMIN)
    # The rider suggestion this came from, once suggestions exist (STRESS-SUGGEST): its
    # id or link, as text, so this table does not depend on that one's shape.
    suggestion_ref = models.CharField(max_length=200, blank=True)
    # Approval changes routing for every guild: instance admin only, an audited action
    # (`AvoidJunctionAdmin`), never a checkbox on the form.
    approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_by_user_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by_user_id = models.BigIntegerField(null=True, blank=True)
    plans_through = models.PositiveIntegerField(default=0)
    last_planned_through_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "avoid_junction"
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["approved"], name="avoid_junction_approved")]

    def __str__(self) -> str:
        return f"Avoid-rated junction: {self.name}"


class MassHazard(models.Model):
    """A rider-marked hazard on a road piece, for the Mass Ride map only (FOLLOWUP-MASSRIDE-MAP
    part 3; OWNER-DECISIONS 325, 326, 327).

    "Some stretches can be marked as a caution or warning where we've had problems. They go
    along side like a trail or pbl. ... These hazards will be marked by riders and will be for
    this mode only." (325). Two severity levels chosen by the reporter, with a reason (326:
    "Severity only"): Caution and Warning. Both stay routable; Avoid is a stress rating, not a
    hazard, and a road marked Avoid shows only "Avoid".

    A report is never shown by itself: an instance admin approves it now, deletes it, or sends
    it to Discord (a ready-to-paste poll, `core.suggestion_post.build_hazard`) and decides
    later - the rider suggestions' three actions (`core.mass_hazards`). Once approved it is
    drawn as a side rail on the Mass Ride map and named in the road panel, the legend and a
    Mass Ride's description. An approval replaces an earlier approved hazard on the same way
    (`removed`), and an instance admin can take one off the map in the Django admin.

    Stored by OSM way id only. The rider's position is checked (within 98 ft (30 m) of the
    road) and never kept; the reporter's account is kept for the admin only and is never in
    the post, the map layer or anything a rider reads. The list starts empty.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for review"
        SENT = "sent_to_discord", "Sent to Discord"
        APPROVED = "approved", "Approved: on the Mass Ride map"
        DELETED = "deleted", "Deleted"
        REMOVED = "removed", "Taken off the map"

    class Level(models.TextChoices):
        CAUTION = "caution", "Caution"
        WARNING = "warning", "Warning"

    created_at = models.DateTimeField(default=timezone.now)
    reporter = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reporter_user_id = models.BigIntegerField(null=True, blank=True)
    osm_way_id = models.BigIntegerField()
    road_name = models.TextField(blank=True)
    level = models.CharField(max_length=16, choices=Level.choices)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "mass_hazard"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "osm_way_id"], name="mass_hazard_status_way")]
        # One open report per rider per road piece, held by the database (the count in
        # core.mass_hazards locks nothing against a second send at once).
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "osm_way_id"],
                condition=models.Q(status__in=["pending", "sent_to_discord"]),
                name="mass_hazard_one_open_per_road",
            ),
            # One approved hazard per road piece: a piece has one level at a time, and two
            # approvals at once cannot both land (core.mass_hazards.approve).
            models.UniqueConstraint(
                fields=["osm_way_id"],
                condition=models.Q(status="approved"),
                name="mass_hazard_one_approved_per_road",
            ),
            models.CheckConstraint(
                condition=models.Q(level__in=["caution", "warning"]),
                name="mass_hazard_level_known",
            ),
        ]

    def __str__(self) -> str:
        return f"way {self.osm_way_id}: {self.get_level_display()}, {self.get_status_display()}"


class JunctionSuggestion(models.Model):
    """A rider's suggested danger level for one junction (OWNER-DECISIONS 232, 460.5).

    "In some times the road is fine, but the intersection can be especially dangerous." The
    road suggestions' twin (`StressSuggestion`), for a node: a level in plain words (easy,
    takes patience, hard, or Avoid) and/or "more or less dangerous than shown", with a reason.
    Never applied by itself: an instance admin approves it now (it becomes a
    `JunctionOverride`, or for Avoid an approved `AvoidJunction`), deletes it, or sends it to
    Discord as a ready-to-paste poll (`core.suggestion_post`) and decides later.

    The place kept is the junction's node, where the roads' centre lines meet
    (`core.junction_suggestions.locate`), never the spot the rider clicked or stood at. The
    account is kept only so an admin can see a pattern of abuse, and is never in the post.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for review"
        SENT = "sent_to_discord", "Sent to Discord"
        APPROVED = "approved", "Approved"
        DELETED = "deleted", "Deleted"

    class Direction(models.TextChoices):
        NONE = "", "No comparison"
        MORE = "more", "More dangerous than shown"
        LESS = "less", "Less dangerous than shown"

    created_at = models.DateTimeField(default=timezone.now)
    suggester = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggester_user_id = models.BigIntegerField(null=True, blank=True)
    # The junction's node, (lon, lat) to 6 decimals, and the same as text: the key one open
    # suggestion per rider per junction is held by.
    lon = models.FloatField()
    lat = models.FloatField()
    node = models.CharField(max_length=32)
    # The roads that meet there, as riders know them, busiest first.
    roads = models.JSONField(default=list, blank=True)
    # The level the map showed (2 easy or not marked, 3 orange, 4 red, 5 Avoid) and the level
    # suggested, which a comparison alone resolves one step from the shown level.
    current_level = models.SmallIntegerField()
    level = models.SmallIntegerField(null=True, blank=True)
    direction = models.CharField(
        max_length=8, choices=Direction.choices, default=Direction.NONE, blank=True
    )
    target_level = models.SmallIntegerField()
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # What an approval made: a junction override (levels 2 to 4) or an Avoid junction (5).
    override = models.ForeignKey(
        "JunctionOverride", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    avoid = models.ForeignKey(
        AvoidJunction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "junction_suggestion"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="junction_suggestion_open")]
        # One open suggestion per rider per junction, held by the database (as the roads').
        constraints = [
            models.UniqueConstraint(
                fields=["suggester", "node"],
                condition=models.Q(status__in=["pending", "sent_to_discord"]),
                name="junction_suggestion_one_open_per_node",
            ),
            models.CheckConstraint(
                condition=models.Q(target_level__gte=2, target_level__lte=5),
                name="junction_suggestion_target_level",
            ),
        ]

    def __str__(self) -> str:
        return f"junction {self.node}: {self.get_status_display()}"

    @property
    def name(self) -> str:
        return " and ".join(self.roads[:2]) if self.roads else "An unnamed junction"


class JunctionOverride(models.Model):
    """An approved danger level for one junction (OWNER-DECISIONS 232): the intersection model
    applies it to every route through the junction (`routemaker.intersections.Rating`),
    raising or lowering its cost and marker, even where the roads either side are fine.

    Made only by an instance admin approving a rider's `JunctionSuggestion`; read at plan
    time (`core.junction_suggestions.approved_ratings`), so it changes the next plan with no
    rebuild. Avoid is not a level here: it is an `AvoidJunction`. Withdrawing one (the admin,
    an audited action) turns it off; a later approval at the same junction replaces it.
    """

    class Level(models.IntegerChoices):
        EASY = 2, "Easy: little waiting, and drivers are slow"
        PATIENCE = 3, "Takes patience: you wait for a gap"
        HARD = 4, "Hard: long waits or fast traffic"

    name = models.CharField(max_length=200)
    location = models.PointField(srid=4326)
    level = models.SmallIntegerField(choices=Level.choices)
    # The rider's reason, kept for the admin. Not shown to riders.
    evidence = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by_user_id = models.BigIntegerField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "junction_override"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["active"], name="junction_override_active")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=2, level__lte=4), name="junction_override_level"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name}: {self.get_level_display()}"


class MyGo(models.Model):
    """A signed-in rider's own Go settings (UI-CLEANUP, the owner's choice 2 of 2026-10-11):
    which view the app opens in, the ride type Go uses, and the Home the Go sheet's Home chip
    rides to.

    One row per account, made the first time the rider saves any of it, and nothing else: no
    name, no history, no route. Signed out, the same choices stay in the browser
    (frontend/src/lib/myGo.ts). Home is one point and its label, as the rider picked it; it is
    never put in a log or a suggestion (riding to it puts it in the plan's link, which then says
    so: linkLocationNote in frontend/src/lib/geolocation.ts), and it goes with the account
    (deleted with the row when the account is, and cleared by the account's deletion flag:
    `User.save`).
    """

    class OpenIn(models.TextChoices):
        AUTO = "", "By screen size: a phone opens in Go, a wider screen in Plan"
        GO = "go", "Go"
        PLAN = "plan", "Plan"

    user = models.OneToOneField(
        "User", on_delete=models.CASCADE, primary_key=True, related_name="my_go"
    )
    open_in = models.CharField(max_length=8, choices=OpenIn.choices, blank=True, default="")
    # A ride type id (frontend/src/lib/presets.ts, core.presets.PRESETS); empty is Default.
    ride = models.CharField(max_length=32, blank=True, default="")
    home_lat = models.FloatField(null=True, blank=True)
    home_lon = models.FloatField(null=True, blank=True)
    home_label = models.CharField(max_length=120, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "my_go"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(home_lat__isnull=True, home_lon__isnull=True)
                | models.Q(home_lat__isnull=False, home_lon__isnull=False),
                name="my_go_home_both_or_neither",
            )
        ]

    def __str__(self) -> str:
        return f"My Go for account {self.user_id}"


class AccountSettings(models.Model):
    """A signed-in rider's saved planning settings (v0.7.0 plan, "Discord sign-in on, with saved
    settings and routes", item 2): the choices the device already remembers, kept with the
    account so they follow the rider to another device.

    One row per account, last write wins. `data` is the front end's own settings document
    (frontend/src/lib/accountSettings.ts), checked for shape and size by the API before it is
    written. My Go keeps its own row (`MyGo`), and Home stays there. Deleted with the account.
    """

    user = models.OneToOneField(
        "User", on_delete=models.CASCADE, primary_key=True, related_name="account_settings"
    )
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "account_settings"

    def __str__(self) -> str:
        return f"Settings for account {self.user_id}"


class SavedRoute(models.Model):
    """A route a signed-in rider saved (v0.7.0 plan, item 3).

    The exact line as planned, kept verbatim like a GPX track (`line`), with the plan's inputs
    (start, end, stops, ride type and dials, as the link's fragment and as fields), the name and
    the date. A route from an opened GPX file is kept the same way, its own line verbatim.
    Reopening shows `line` (and, for a planned route, the saved answer) unchanged; nothing is
    re-planned unless the rider asks. Private to the account, never shared between accounts,
    deleted with it, and at most `MAX_PER_ACCOUNT` per account.
    """

    MAX_PER_ACCOUNT = 200

    class Source(models.TextChoices):
        PLAN = "plan", "Planned in RouteMaker"
        GPX = "gpx", "An opened GPX file"

    user = models.ForeignKey("User", on_delete=models.CASCADE, related_name="saved_routes")
    name = models.CharField(max_length=120)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.PLAN)
    # [[lon, lat] or [lon, lat, ele], ...] exactly as planned or as the file had it.
    line = models.JSONField()
    distance_m = models.FloatField()
    # {"hash": the plan link's fragment, "points": [[lon, lat], ...], "preset": id, "dials": {...}}
    inputs = models.JSONField(default=dict)
    # The planned route's whole answer as shown when saved (without the other candidates), so a
    # reopened route shows every panel as it was; null for a GPX file's line.
    answer = models.JSONField(null=True, blank=True)
    # An opened GPX file's own text, byte for byte, so its export is the file as it came (its
    # track points, elevations and waypoint names unchanged); empty for a planned route.
    gpx = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # v0.7.0 closures (core.saved_route_alerts): the closures in force that the line runs along,
    # as last found, shown in My routes; [] where none.
    closure_alerts = models.JSONField(default=list, blank=True)
    closures_checked_at = models.DateTimeField(null=True, blank=True)
    # The line's box, so the check reads a line only where a closure could meet it.
    bbox_west = models.FloatField(null=True, blank=True)
    bbox_south = models.FloatField(null=True, blank=True)
    bbox_east = models.FloatField(null=True, blank=True)
    bbox_north = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "saved_route"
        indexes = [models.Index(fields=["user", "-created_at"], name="saved_route_user_recent")]

    def __str__(self) -> str:
        return f"Saved route {self.pk} for account {self.user_id}"


class SavedRouteVersion(models.Model):
    """An earlier version of a saved route: what it was before it was saved again with changes,
    or before an earlier version was restored (core.api, /me/routes/{id}/versions).

    The same fields as the route itself, kept verbatim, with when that version was saved
    (`saved_at`) and when it stopped being the latest (`replaced_at`). The owner's own, like the
    route: deleted with it, and at most `MAX_PER_ROUTE` per route, the oldest going first. They do
    not count toward the account's `SavedRoute.MAX_PER_ACCOUNT`, but all of an account's versions
    together are at most `MAX_BYTES_PER_ACCOUNT`, the oldest across the account going first.

    An opened GPX file's text is kept once: a version whose file is the same as the version after
    it (or the route itself, for the newest) keeps none and says so (`gpx_same_as_next`); its text
    is that one's (core.api `_version_gpx`).
    """

    MAX_PER_ROUTE = 20
    MAX_BYTES_PER_ACCOUNT = 50 * 1024 * 1024

    route = models.ForeignKey(SavedRoute, on_delete=models.CASCADE, related_name="versions")
    source = models.CharField(
        max_length=8, choices=SavedRoute.Source.choices, default=SavedRoute.Source.PLAN
    )
    line = models.JSONField()
    distance_m = models.FloatField()
    inputs = models.JSONField(default=dict)
    answer = models.JSONField(null=True, blank=True)
    gpx = models.TextField(blank=True, default="")
    gpx_same_as_next = models.BooleanField(default=False)
    # What this version holds, in bytes (its line, inputs, answer and own file text as JSON).
    size_bytes = models.IntegerField(default=0)
    saved_at = models.DateTimeField()
    replaced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saved_route_version"
        indexes = [
            models.Index(fields=["route", "-replaced_at"], name="saved_route_version_recent")
        ]

    def __str__(self) -> str:
        return f"Version {self.pk} of saved route {self.route_id}"


class SharedRoute(models.Model):
    """A route shared with the Share button, kept so the link opens the exact line (v0.7.0;
    core.shared_routes).

    The line exactly as shown, verbatim like a saved route or GPX track (`line`), with the plan's
    inputs (so "Update route" can plan it again with today's map), a planned route's answer
    without the rider's weight, or an opened GPX file's own text. The key is 128 random bits the
    sharer's browser made (32 hex characters); nothing names who shared it but, signed in, the
    account (`owner`): no address, no position. Kept a year after `last_opened_at` (`keep`
    "year", the default), permanently ("forever"), or through `delete_after` ("until"), then
    deleted.

    Shared signed in, the row names its `owner`, so only they can turn the link off or make a new
    one (core.shared_routes.revoke, regenerate); a turned-off link stays as a tombstone with its
    route cleared (`revoked_at`), so the link says it was turned off rather than planning its
    points again. `preview_png` is the link preview's image (core.share_preview), cached under
    `preview_key` (the line and Home's circle it was drawn with; an empty image is "none");
    `preview_image` False when a signed-out sharer's route starts, ends or stops at the Home on
    their device, which the server does not know, and for links from before previews, so no image
    is drawn; `preview_zone` Home's circle frozen when the link was made.
    """

    id = models.CharField(primary_key=True, max_length=32)
    name = models.CharField(max_length=120, blank=True, default="")
    source = models.CharField(max_length=8, default="plan")
    # [[lon, lat] or [lon, lat, ele], ...] exactly as shown or as the file had it.
    line = models.JSONField()
    distance_m = models.FloatField()
    # {"hash": the plan link's fragment, "points": [[lon, lat], ...], "preset": id, "dials": {...}}
    inputs = models.JSONField(default=dict)
    answer = models.JSONField(null=True, blank=True)
    gpx = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    last_opened_at = models.DateTimeField(default=timezone.now)
    keep = models.CharField(max_length=8, default="year")
    delete_after = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(
        "User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shared_routes",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    preview_image = models.BooleanField(default=False)
    # [lon, lat, radius m]: Home's circle when the link was made, if the route ended or stopped
    # in it.
    preview_zone = models.JSONField(null=True, blank=True)
    preview_key = models.CharField(max_length=64, blank=True, default="")
    preview_png = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = "shared_route"
        indexes = [models.Index(fields=["last_opened_at"], name="shared_route_last_opened")]

    def __str__(self) -> str:
        return f"Shared route {self.pk[:6]}…"


class ReviewedClosure(models.Model):
    """A closure a RouteMaker reviewer entered, or confirmed from a rider's report (v0.7.0
    closures; core.reviewed_closures).

    It takes part in routing and the closure check exactly as a feed's closure does
    (`core.workzones.snapshot`), credited "Confirmed by a RouteMaker reviewer". The ways are kept
    with their lines as the segment table had them when it was entered (`lines`, one
    [[lon, lat], ...] per way, or one drawn line with no way), so a rebuild that renumbers or
    moves a way does not move the closure. In force from `start` (null: at once) until `end`
    (null: until a reviewer ends it), and no longer once `ended_at` is set.
    """

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    osm_way_ids = models.JSONField(default=list, blank=True)
    lines = models.JSONField(default=list)
    road = models.CharField(max_length=200, blank=True, default="")
    reason = models.TextField()
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(max_length=500, blank=True, default="")
    # The rider's report it confirms, where it came from one.
    report = models.ForeignKey(
        StressSuggestion, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "reviewed_closure"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["ended_at", "end"], name="reviewed_closure_live")]

    def __str__(self) -> str:
        return f"Closure {self.pk}: {self.road or 'a road'}"


class ReviewItem(models.Model):
    """One road in an instance admin's Review queue (core.stress_review; the owner, 2026-10-16:
    "Add a mode that will allow people with admin access the ability to look at these roads and
    make a ruling").

    Precomputed when a build is installed (`import_cloud_build`'s dry run) or by
    `manage.py compute_review_queue`, never per request: the rebuild's stress changes compare two
    whole segment tables. Each queue's rows are replaced whole when it is computed again; the
    rulings (`ReviewRuling`) keep their own copy of the queue, build and way, so they outlive it.
    """

    class Queue(models.TextChoices):
        REBUILD = "rebuild", "Rebuild changes"
        DISAGREEMENT = "disagreement", "Rating disagreements"
        SIDEPATH = "sidepath", "Use side path, none mapped"
        NARROW_RURAL = "narrow_rural", "Narrow rural roads with no posted speed"
        WORKS_CLOSURE = "works_closure", "Industrial-area closures"
        REMATCH = "rematch", "Overrides that did not re-match"
        PAINTED_LANE = "painted_lane", "Painted lanes on wide two-way roads"
        DC_NO_BIKE = "dc_no_bike", "DC ways closed to bicycles"

    queue = models.CharField(max_length=16, choices=Queue.choices)
    # The build the rebuild changes are of; "" on the other queues.
    build_id = models.CharField(max_length=40, blank=True, default="")
    osm_way_id = models.BigIntegerField()
    name = models.TextField(blank=True, default="")
    area = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")
    # What the queue is filtered by: a change ("4-2", "closed"), the sources that disagree.
    kind = models.CharField(max_length=40, blank=True, default="")
    # The level before and after a rebuild; elsewhere `new_step` is the level now.
    old_step = models.FloatField(null=True, blank=True)
    new_step = models.FloatField(null=True, blank=True)
    old_closed = models.BooleanField(default=False)
    new_closed = models.BooleanField(default=False)
    # Rules, sources and every rating held, for the item's card.
    details = models.JSONField(default=dict, blank=True)
    # The rating sources at either end of a disagreement.
    sources = models.JSONField(default=list, blank=True)
    spread = models.FloatField(null=True, blank=True)
    length_m = models.FloatField(default=0)
    aadt = models.IntegerField(null=True, blank=True)
    score = models.FloatField(default=0)
    geometry = models.MultiLineStringField(srid=4326, null=True, blank=True)
    # The lines simplified for a region's view (Review's map below a street's zoom), and a point
    # on the road (its far view's count badges): both made with the item, never per request.
    simple = models.MultiLineStringField(srid=4326, null=True, blank=True)
    point = models.PointField(srid=4326, null=True, blank=True)
    # A digest of what the road was listed for (its level, access, rule and ratings, or the
    # report's row): an Accept outside the rebuild's changes stands only while it is the same.
    inputs = models.CharField(max_length=32, blank=True, default="")
    # A stretch (`stress_review.group_stretches`; the owner, 2026-10-17: "for review, merge
    # stretches. Go at least from major intersection to major intersection"): the ways of one
    # road joined end to end with the same change, between major junctions, listed as one row.
    # `stretch` is its lead way (the longest), on the lead and every other way of it; null on a
    # way listed alone. The lead's `ways` lists them all, and its length, score and lines are the
    # stretch's; its point stays its own. Each way keeps its own row, so a ruling is still
    # written a way.
    stretch = models.BigIntegerField(null=True, blank=True)
    ways = models.JSONField(default=list, blank=True)
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "review_item"
        constraints = [
            models.UniqueConstraint(
                fields=["queue", "build_id", "osm_way_id"], name="review_item_one_a_way"
            )
        ]
        indexes = [
            models.Index(fields=["queue", "build_id", "kind"], name="review_item_kind"),
            models.Index(fields=["queue", "-score"], name="review_item_score"),
            models.Index(fields=["queue", "-computed_at"], name="review_item_computed"),
            models.Index(fields=["queue", "build_id", "stretch"], name="review_item_stretch"),
        ]

    def __str__(self) -> str:
        return f"{self.queue} way {self.osm_way_id}"


class ReviewRuling(models.Model):
    """An instance admin's ruling on one road of the Review queue (core.stress_review).

    Accept records the decision only. Reject and Change LTS write what the road panel writes:
    a stress change is the editor's own approved override, live edit and `StressEdit` (`edit`),
    so it outranks an agency and the formula and is re-applied by the swap; reopening a closed
    road is an approved access override (`access_override`), applied at the next rebuild.
    """

    class Decision(models.TextChoices):
        ACCEPT = "accept", "Accept"
        REJECT = "reject", "Reject"
        SET = "set", "Change LTS"

    queue = models.CharField(max_length=16, choices=ReviewItem.Queue.choices)
    build_id = models.CharField(max_length=40, blank=True, default="")
    osm_way_id = models.BigIntegerField()
    decision = models.CharField(max_length=8, choices=Decision.choices)
    step = models.FloatField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    edit = models.ForeignKey(
        StressEdit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    access_override = models.ForeignKey(
        Override, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    undone_at = models.DateTimeField(null=True, blank=True)
    undone_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The item's `inputs` when it was ruled on: an Accept lapses when a build changes them.
    inputs = models.CharField(max_length=32, blank=True, default="")
    # The lead way of the stretch the ruling was made on (`ReviewItem.stretch`): every way of it
    # was ruled together, and Undo undoes them together. Null on a way ruled alone.
    stretch = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "review_ruling"
        ordering = ["-at", "-id"]
        indexes = [
            models.Index(fields=["queue", "build_id", "osm_way_id"], name="review_ruling_way")
        ]

    def __str__(self) -> str:
        return f"{self.decision} on way {self.osm_way_id} ({self.queue})"


class ReviewQueueState(models.Model):
    """When each Review queue was last computed, and what it was computed from
    (core.stress_review): a queue read from a rebuild's report says so when the build had none,
    instead of showing an older build's rows as current."""

    queue = models.CharField(max_length=16, choices=ReviewItem.Queue.choices, primary_key=True)
    build_id = models.CharField(max_length=40, blank=True, default="")
    computed_at = models.DateTimeField(default=timezone.now)
    # "" when computed; else why the list is empty ("No report from this build").
    note = models.TextField(blank=True, default="")
    # Unused since the map is served by view (stress_review.map_view): the whole-list maps once
    # kept here. Kept for one release, so a worker still running the release before reads and
    # writes its row through a deploy; written empty. Their columns go in the next release.
    map_low = models.TextField(blank=True, default="")
    map_high = models.TextField(blank=True, default="")
    map_points = models.TextField(blank=True, default="")

    class Meta:
        db_table = "review_queue_state"

    def __str__(self) -> str:
        return f"{self.queue} at {self.computed_at:%Y-%m-%d %H:%M}"

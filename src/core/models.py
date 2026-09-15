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
    """The authority layers a crossing can change."""

    """The three layers a crossing can change, which are genuinely different
    questions: who polices it, who owns the right of way, and who manages the
    land. The body that issues a permit is frequently not a police agency."""

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
    table. Node ids come from a reserved negative range that cannot collide with
    real OSM node ids.
    """

    node_id = models.BigIntegerField(unique=True)
    location = models.PointField(srid=4326)
    osm_way_id = models.BigIntegerField()
    state_a = models.CharField(max_length=2)
    state_b = models.CharField(max_length=2)

    class Meta:
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


class Session(models.Model):
    """A session, carrying the user and the epoch it was issued under.

    Django's own session table has neither, which is why ban, suspension,
    deletion and sign-out-everywhere had no mechanism: the only global lever was
    rotating the secret key, which signs everybody out.
    """

    session_key = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    issued_epoch = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_session"
        indexes = [models.Index(fields=["user"])]

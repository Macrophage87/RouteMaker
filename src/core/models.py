"""Phase 1 schema: the tables the preprocessing pipeline writes and the
application reads.

Two rules shape this module. Segment data is *rebuilt* weekly into a staging
schema and swapped, so those models are unmanaged and their DDL comes from the
pipeline rather than from migrations. Everything anchored to a segment refers to
it by plain columns rather than a foreign key, because a cross-schema constraint
would make the swap impossible.
"""

from __future__ import annotations

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
    is_unpaved = models.BooleanField(default=False)
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
    """The three layers a crossing can change, which are genuinely different
    questions: who polices it, who owns the right of way, and who manages the
    land. The body that issues a permit is frequently not a police agency."""

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

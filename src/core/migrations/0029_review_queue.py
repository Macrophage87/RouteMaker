# The instance admin's Review queue and its rulings (core.models.ReviewItem, ReviewRuling;
# core.stress_review).
#
# Numbered 0029: 0027_suggestion_reviews and 0028_surface_override come from another branch and
# are not on this one's base yet, so `dependencies` names 0026 until they merge.

import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_reviewed_closures"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReviewItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "queue",
                    models.CharField(
                        choices=[
                            ("rebuild", "Rebuild changes"),
                            ("disagreement", "Rating disagreements"),
                            ("sidepath", "Use side path, none mapped"),
                            ("narrow_rural", "Narrow rural roads with no posted speed"),
                            ("works_closure", "Industrial-area closures"),
                            ("rematch", "Overrides that did not re-match"),
                        ],
                        max_length=16,
                    ),
                ),
                ("build_id", models.CharField(blank=True, default="", max_length=40)),
                ("osm_way_id", models.BigIntegerField()),
                ("name", models.TextField(blank=True, default="")),
                ("area", models.TextField(blank=True, default="")),
                ("reason", models.TextField(blank=True, default="")),
                ("kind", models.CharField(blank=True, default="", max_length=40)),
                ("old_step", models.FloatField(blank=True, null=True)),
                ("new_step", models.FloatField(blank=True, null=True)),
                ("old_closed", models.BooleanField(default=False)),
                ("new_closed", models.BooleanField(default=False)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("spread", models.FloatField(blank=True, null=True)),
                ("length_m", models.FloatField(default=0)),
                ("aadt", models.IntegerField(blank=True, null=True)),
                ("score", models.FloatField(default=0)),
                (
                    "geometry",
                    django.contrib.gis.db.models.fields.MultiLineStringField(
                        blank=True, null=True, srid=4326
                    ),
                ),
                (
                    "computed_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
            ],
            options={
                "db_table": "review_item",
                "indexes": [
                    models.Index(fields=["queue", "build_id", "kind"], name="review_item_kind"),
                    models.Index(fields=["queue", "-score"], name="review_item_score"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("queue", "build_id", "osm_way_id"),
                        name="review_item_one_a_way",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ReviewRuling",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "queue",
                    models.CharField(
                        choices=[
                            ("rebuild", "Rebuild changes"),
                            ("disagreement", "Rating disagreements"),
                            ("sidepath", "Use side path, none mapped"),
                            ("narrow_rural", "Narrow rural roads with no posted speed"),
                            ("works_closure", "Industrial-area closures"),
                            ("rematch", "Overrides that did not re-match"),
                        ],
                        max_length=16,
                    ),
                ),
                ("build_id", models.CharField(blank=True, default="", max_length=40)),
                ("osm_way_id", models.BigIntegerField()),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("accept", "Accept"),
                            ("reject", "Reject"),
                            ("set", "Change LTS"),
                        ],
                        max_length=8,
                    ),
                ),
                ("step", models.FloatField(blank=True, null=True)),
                ("reason", models.TextField(blank=True, default="")),
                ("at", models.DateTimeField(default=django.utils.timezone.now)),
                ("actor_user_id", models.BigIntegerField(blank=True, null=True)),
                ("undone_at", models.DateTimeField(blank=True, null=True)),
                (
                    "access_override",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="core.override",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="core.stressedit",
                    ),
                ),
                (
                    "undone_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "review_ruling",
                "ordering": ["-at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["queue", "build_id", "osm_way_id"],
                        name="review_ruling_way",
                    )
                ],
            },
        ),
    ]

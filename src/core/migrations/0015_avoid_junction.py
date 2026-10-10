"""The Avoid-rated junction list (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307-310, 335).

Numbered 0015 because 0013 and 0014 are taken by work in flight (0014 is the
half-step editor's). It depends on 0012, the latest migration on release/v0.4.0
when it was written: re-point `dependencies` at whichever migration is the leaf
when this merges (or add a merge migration), so the graph has one leaf. The table
is new and empty, so the order against the others does not matter.
"""

import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_bikeshare_feed_cache"),
    ]

    operations = [
        migrations.CreateModel(
            name="AvoidJunction",
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
                    "name",
                    models.CharField(
                        help_text='The junction as riders know it, e.g. "Main St and 1st Ave". Shown to riders.',
                        max_length=200,
                    ),
                ),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        help_text="The junction's centre: where the roads' centre lines meet.",
                        srid=4326,
                    ),
                ),
                (
                    "reason",
                    models.CharField(
                        help_text="Why it is rated Avoid, in a few plain words. Shown to riders.",
                        max_length=300,
                    ),
                ),
                (
                    "evidence",
                    models.TextField(
                        blank=True,
                        help_text="What the rating rests on (reports, a visit, crashes). Not shown to riders.",
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("admin", "Owner or instance admin"),
                            ("community", "Community suggestion, reviewed"),
                        ],
                        default="admin",
                        max_length=16,
                    ),
                ),
                ("suggestion_ref", models.CharField(blank=True, max_length=200)),
                ("approved", models.BooleanField(default=False)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by_user_id", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by_user_id", models.BigIntegerField(blank=True, null=True)),
                ("plans_through", models.PositiveIntegerField(default=0)),
                (
                    "last_planned_through_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
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
                "db_table": "avoid_junction",
                "ordering": ["name", "id"],
                "indexes": [
                    models.Index(fields=["approved"], name="avoid_junction_approved")
                ],
            },
        ),
    ]

# Junctions the map has a signal at that are flashing beacons (core.flashing_signals). Generated
# by Django.

import django.contrib.gis.db.models.fields
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0036_connector"),
    ]

    operations = [
        migrations.CreateModel(
            name="FlashingSignal",
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
                    "source",
                    models.CharField(
                        choices=[
                            ("owner", "Owner or instance admin"),
                            ("mdot-sha", "MDOT SHA Traffic Signals (a beacon)"),
                        ],
                        max_length=16,
                    ),
                ),
                ("source_id", models.CharField(max_length=80)),
                ("name", models.CharField(max_length=200)),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("evidence", models.TextField(blank=True)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                (
                    "withdrawn_by",
                    models.CharField(
                        blank=True,
                        choices=[("admin", "An instance admin"), ("list", "Its agency's list")],
                        max_length=8,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "flashing_signal",
                "ordering": ["name", "id"],
                "indexes": [models.Index(fields=["active"], name="flashing_signal_active")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source", "source_id"), name="flashing_signal_one_row"
                    )
                ],
            },
        ),
    ]

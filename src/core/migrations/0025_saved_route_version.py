# Saved-route versions (core.models.SavedRouteVersion): a saved route saved again with changes
# keeps what it was, up to 20 per route. Follows 0024_shared_route_owner_preview, so the chain
# stays linear.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_shared_route_owner_preview"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedRouteVersion",
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
                            ("plan", "Planned in RouteMaker"),
                            ("gpx", "An opened GPX file"),
                        ],
                        default="plan",
                        max_length=8,
                    ),
                ),
                ("line", models.JSONField()),
                ("distance_m", models.FloatField()),
                ("inputs", models.JSONField(default=dict)),
                ("answer", models.JSONField(blank=True, null=True)),
                ("gpx", models.TextField(blank=True, default="")),
                ("saved_at", models.DateTimeField()),
                ("replaced_at", models.DateTimeField(auto_now_add=True)),
                (
                    "route",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="core.savedroute",
                    ),
                ),
            ],
            options={
                "db_table": "saved_route_version",
                "indexes": [
                    models.Index(
                        fields=["route", "-replaced_at"], name="saved_route_version_recent"
                    )
                ],
            },
        ),
    ]

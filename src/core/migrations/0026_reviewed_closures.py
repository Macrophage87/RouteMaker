# v0.7.0 closures: closures a reviewer entered or confirmed (core.models.ReviewedClosure,
# core.reviewed_closures), a rider's closure report as a kind of suggestion, and each saved
# route's closure alerts (core.saved_route_alerts).
#
# Numbered 0026 beside the saved-route versions' 0025 and built on 0024: the dependency is set to
# the chain's last migration when the two are merged.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_shared_route_owner_preview"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stresssuggestion",
            name="kind",
            field=models.CharField(
                choices=[("road", "Road piece"), ("closure", "Closure report")],
                default="road",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="savedroute",
            name="closure_alerts",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="savedroute",
            name="closures_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ReviewedClosure",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("osm_way_ids", models.JSONField(blank=True, default=list)),
                ("lines", models.JSONField(default=list)),
                ("road", models.CharField(blank=True, default="", max_length=200)),
                ("reason", models.TextField()),
                ("start", models.DateTimeField(blank=True, null=True)),
                ("end", models.DateTimeField(blank=True, null=True)),
                ("source_url", models.URLField(blank=True, default="", max_length=500)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
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
                (
                    "ended_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="core.stresssuggestion",
                    ),
                ),
            ],
            options={
                "db_table": "reviewed_closure",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["ended_at", "end"], name="reviewed_closure_live")
                ],
            },
        ),
    ]

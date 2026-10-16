# v0.7.0 "share the identical route" (core.shared_routes, core.models.SharedRoute): the exact line
# a Share link opens, under a 128-bit random id, kept a year after it was last opened. Follows
# 0021_signed_out_suggestions, so the chain stays linear.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_signed_out_suggestions"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedRoute",
            fields=[
                ("id", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("name", models.CharField(blank=True, default="", max_length=120)),
                ("source", models.CharField(default="plan", max_length=8)),
                ("line", models.JSONField()),
                ("distance_m", models.FloatField()),
                ("inputs", models.JSONField(default=dict)),
                ("answer", models.JSONField(blank=True, null=True)),
                ("gpx", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_opened_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "shared_route",
                "indexes": [models.Index(fields=["last_opened_at"], name="shared_route_last_opened")],
            },
        ),
    ]

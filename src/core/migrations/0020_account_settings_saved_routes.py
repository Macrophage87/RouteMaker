# v0.7.0 accounts: a signed-in rider's saved settings and saved routes (core.models.AccountSettings,
# core.models.SavedRoute). Follows 0019_my_go, so the chain stays linear.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_my_go"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountSettings",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="account_settings",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("data", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "account_settings",
            },
        ),
        migrations.CreateModel(
            name="SavedRoute",
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
                ("name", models.CharField(max_length=120)),
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_routes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "saved_route",
                "indexes": [
                    models.Index(
                        fields=["user", "-created_at"], name="saved_route_user_recent"
                    )
                ],
            },
        ),
    ]

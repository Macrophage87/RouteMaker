# My Go (UI-CLEANUP, the owner's choice 2 of 2026-10-11): a signed-in rider's own Go settings,
# saved to the account. Follows 0018_junction_suggestions, so the chain stays linear.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_junction_suggestions"),
    ]

    operations = [
        migrations.CreateModel(
            name="MyGo",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="my_go",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "open_in",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("", "By screen size: a phone opens in Go, a wider screen in Plan"),
                            ("go", "Go"),
                            ("plan", "Plan"),
                        ],
                        default="",
                        max_length=8,
                    ),
                ),
                ("ride", models.CharField(blank=True, default="", max_length=32)),
                ("home_lat", models.FloatField(blank=True, null=True)),
                ("home_lon", models.FloatField(blank=True, null=True)),
                ("home_label", models.CharField(blank=True, default="", max_length=120)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "my_go",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("home_lat__isnull", True), ("home_lon__isnull", True)),
                            models.Q(("home_lat__isnull", False), ("home_lon__isnull", False)),
                            _connector="OR",
                        ),
                        name="my_go_home_both_or_neither",
                    )
                ],
            },
        ),
    ]

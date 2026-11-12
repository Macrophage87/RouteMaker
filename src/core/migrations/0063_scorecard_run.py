# The nightly route scorecard's runs (docs/SCORECARD.md; the owner, 2026-11-12: "Both", nightly on
# beta and on the PC when started). A new table only: the api of the release before never reads it.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0062_connector_draft_archived"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScorecardRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("made_at", models.DateTimeField()),
                ("label", models.CharField(blank=True, max_length=80)),
                ("data", models.JSONField()),
                ("findings", models.TextField(blank=True)),
                ("findings_count", models.IntegerField(default=0)),
                ("failed_count", models.IntegerField(default=0)),
            ],
            options={
                "db_table": "scorecard_run",
                "indexes": [models.Index(fields=["-made_at"], name="scorecard_run_made_at")],
            },
        ),
    ]

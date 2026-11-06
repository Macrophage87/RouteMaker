# A shared link's id once its row is gone (core.models.SharedRouteGone): only the id and when it
# went. The release before knows nothing of the table and deletes rows without it, as it did.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0055_connector_grant_reads_routes_db_default"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedRouteGone",
            fields=[
                (
                    "id",
                    models.CharField(max_length=32, primary_key=True, serialize=False),
                ),
                ("gone_at", models.DateTimeField(db_index=True)),
            ],
            options={
                "db_table": "shared_route_gone",
            },
        ),
    ]

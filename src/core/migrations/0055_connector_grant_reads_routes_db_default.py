# connector_grant.reads_routes keeps a database default of false (0054 added it NOT NULL and, as
# Django does, dropped the default it was filled with). The api of the release before creates
# grants without the column, and without the default those writes fail: in the minutes between
# migrate and the api's recreation, and after a rollback of the images (the database stays
# migrated). The model is unchanged (Django fills `reads_routes` itself), so this is SQL alone,
# as 0050 is for my_go.places.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0054_connector_grant_reads_routes"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE connector_grant ALTER COLUMN reads_routes SET DEFAULT false",
            "ALTER TABLE connector_grant ALTER COLUMN reads_routes DROP DEFAULT",
        ),
    ]

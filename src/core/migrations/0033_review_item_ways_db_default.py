# review_item.ways keeps a database default of '[]' (0032 added it NOT NULL and, as Django
# does, dropped the default it was filled with). A worker or api of the release before writes
# review_item rows without the column (compute_rebuild's INSERT, bulk_create), and without the
# default those writes fail: in the minutes between migrate and the api's recreation, and after
# a rollback of the images that leaves the database at 0032. The model is unchanged (Django
# fills `ways` itself), so this is SQL alone.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_review_stretches"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE review_item ALTER COLUMN ways SET DEFAULT '[]'::jsonb",
            "ALTER TABLE review_item ALTER COLUMN ways DROP DEFAULT",
        ),
    ]

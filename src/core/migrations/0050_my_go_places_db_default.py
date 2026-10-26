# my_go.places keeps a database default of '[]' (0049 added it NOT NULL and, as Django does,
# dropped the default it was filled with). The api of the release before writes my_go rows
# without the column (a rider's first My Go save), and without the default those writes fail:
# in the minutes between migrate and the api's recreation, and after a rollback of the images
# (the database stays migrated). The model is unchanged (Django fills `places` itself), so this
# is SQL alone, as 0033 is for review_item.ways.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0049_my_go_places"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE my_go ALTER COLUMN places SET DEFAULT '[]'::jsonb",
            "ALTER TABLE my_go ALTER COLUMN places DROP DEFAULT",
        ),
    ]

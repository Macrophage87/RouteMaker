# Fixed saved routes (the owner, 2026-11-10): a route kept as its exact line, never planned again.
# Both columns keep a database default of false, as 0057 does for tags: the api of the release
# before saves routes and versions without the column, in the minutes between migrate and the
# api's recreation and after a rollback of the images.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0060_reviewed_closure_on_foot"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedroute",
            name="fixed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunSQL(
            "ALTER TABLE saved_route ALTER COLUMN fixed SET DEFAULT false",
            "ALTER TABLE saved_route ALTER COLUMN fixed DROP DEFAULT",
        ),
        migrations.AddField(
            model_name="savedrouteversion",
            name="fixed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunSQL(
            "ALTER TABLE saved_route_version ALTER COLUMN fixed SET DEFAULT false",
            "ALTER TABLE saved_route_version ALTER COLUMN fixed DROP DEFAULT",
        ),
    ]

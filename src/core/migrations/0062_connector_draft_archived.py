# Archived assistant drafts (the owner, 2026-11-12): an agent's test and check routes are kept out
# of Load route. A nullable column with no default: the api of the release before inserts drafts
# without it (null, listed) in the minutes between migrate and the api's recreation and after a
# rollback of the images, and never reads it.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0061_saved_route_fixed"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectordraft",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

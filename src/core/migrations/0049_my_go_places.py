# Favorite places (Stephen 2026-10-26: "For signed in users, allow for favorite destinations"):
# core.models.MyGo.places, Go's Favorites chip, kept with Home.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0048_route_post_photos"),
    ]

    operations = [
        migrations.AddField(
            model_name="mygo",
            name="places",
            field=models.JSONField(blank=True, default=list),
        ),
    ]

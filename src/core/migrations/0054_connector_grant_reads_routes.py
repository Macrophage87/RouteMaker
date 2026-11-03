# The connector may read My routes where the rider allowed it on a consent page that said so
# (the owner, 2026-11-02: my_routes). Grants given before keep it off: their page said "It can't
# read your saved routes".
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0053_route_post_ride_keys")]

    operations = [
        migrations.AddField(
            model_name="connectorgrant",
            name="reads_routes",
            field=models.BooleanField(default=False),
        ),
    ]

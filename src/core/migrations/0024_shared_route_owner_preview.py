# A shared link's owner can turn it off or make a new one, and the link has a preview image
# (core.shared_routes.revoke and regenerate, core.share_preview).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_shared_route_keep"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharedroute",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="shared_routes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="sharedroute",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sharedroute",
            name="preview_image",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="sharedroute",
            name="preview_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="sharedroute",
            name="preview_png",
            field=models.BinaryField(blank=True, null=True),
        ),
    ]

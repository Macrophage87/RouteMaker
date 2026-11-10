# Assistant drafts listed in Load route (the owner, 2026-11-09): each draft names the first draft
# of the route it revises (`root`), so only the newest revision is listed, and when it was saved to
# My routes (`saved_at`), so a saved one is no longer listed. Both nullable: the release before
# writes drafts knowing nothing of them, and they read as a first draft, unsaved.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0058_route_post_photo_spot"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectordraft",
            name="root",
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
        migrations.AddField(
            model_name="connectordraft",
            name="saved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

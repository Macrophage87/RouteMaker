# Shared routes kept permanently or until a date, as the sharer chooses (the owner, 2026-10-16:
# "For the 1 year deletion, make this the default. For other users, we can offer "keep
# permanently" and "delete after <date>""); core.shared_routes.KEEP_CHOICES.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_shared_route"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharedroute",
            name="keep",
            field=models.CharField(default="year", max_length=8),
        ),
        migrations.AddField(
            model_name="sharedroute",
            name="delete_after",
            field=models.DateField(blank=True, null=True),
        ),
    ]

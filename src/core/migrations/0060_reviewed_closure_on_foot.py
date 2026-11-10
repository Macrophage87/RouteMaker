# Routing hunt 4, C4-1: a reviewer's closure says whether it is closed to people on foot too.
# Nullable: rows from before (Lake Frank's trail closures among them) and the release before,
# which writes rows knowing nothing of it, read as closed on foot (`reviewed_closures.zones_of`).
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0059_connector_draft_root_saved"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewedclosure",
            name="on_foot",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]

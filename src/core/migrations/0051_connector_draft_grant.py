# Connector drafts belong to the app that drafted them (ConnectorDraft.grant), so disconnecting
# the app drops them, and a draft's link goes with its draft (SharedRoute.connector_draft). The
# drafts kept before name no app, so no app could read them again: they go now rather than at
# the sweep. Their links name no draft and cannot be told from other links, so they keep the
# date they were given and are deleted within 8 days of being made.
import django.db.models.deletion
from django.db import migrations, models


def drop_unowned_drafts(apps, schema_editor):
    apps.get_model("core", "ConnectorDraft").objects.filter(grant__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0050_my_go_places_db_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectordraft",
            name="grant",
            field=models.ForeignKey(
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="drafts",
                to="core.connectorgrant",
            ),
        ),
        migrations.AddField(
            model_name="sharedroute",
            name="connector_draft",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="shared_links",
                to="core.connectordraft",
            ),
        ),
        migrations.AlterField(
            model_name="connectordraft",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name="connectordraft",
            name="draft_id",
            field=models.CharField(max_length=40),
        ),
        migrations.RunPython(drop_unowned_drafts, migrations.RunPython.noop),
    ]

# Saved routes' tags, archive and last opened (the owner, 2026-11-07). `tags` keeps a database default of an
# empty list, as 0055 does for connector_grant.reads_routes: the api of the release before saves
# routes without the column, in the minutes between migrate and the api's recreation and after a
# rollback of the images. `archived_at`, `opened_at` and `replaced_by` are nullable, so it needs none for them.
# connector_grant.organizes_routes (the connector's organize_route) keeps a default of false the
# same way, for the release before's grants.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0056_shared_route_gone"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectorgrant",
            name="organizes_routes",
            field=models.BooleanField(default=False),
        ),
        migrations.RunSQL(
            "ALTER TABLE connector_grant ALTER COLUMN organizes_routes SET DEFAULT false",
            "ALTER TABLE connector_grant ALTER COLUMN organizes_routes DROP DEFAULT",
        ),
        migrations.AddField(
            model_name="savedroute",
            name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunSQL(
            "ALTER TABLE saved_route ALTER COLUMN tags SET DEFAULT '[]'::jsonb",
            "ALTER TABLE saved_route ALTER COLUMN tags DROP DEFAULT",
        ),
        migrations.AddField(
            model_name="savedroute",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="savedroute",
            name="opened_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="savedroute",
            name="replaced_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="replaced",
                to="core.savedroute",
            ),
        ),
        # SET_NULL in the database too: the release before knows nothing of replaced_by, so a
        # route it deletes that another route's replaced_by names must not fail the delete.
        migrations.RunSQL(
            """
            DO $$
            DECLARE fk text;
            BEGIN
              SELECT conname INTO fk FROM pg_constraint
              WHERE conrelid = 'saved_route'::regclass AND contype = 'f'
                AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                  WHERE attrelid = 'saved_route'::regclass AND attname = 'replaced_by_id')];
              EXECUTE format('ALTER TABLE saved_route DROP CONSTRAINT %I', fk);
              EXECUTE format('ALTER TABLE saved_route ADD CONSTRAINT %I FOREIGN KEY'
                ' (replaced_by_id) REFERENCES saved_route (id) ON DELETE SET NULL'
                ' DEFERRABLE INITIALLY DEFERRED', fk);
            END $$;
            """,
            migrations.RunSQL.noop,
        ),
    ]

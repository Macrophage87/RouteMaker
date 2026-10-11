import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def refuse_duplicate_live_stress_rows(apps, schema_editor):
    """The new unique index needs at most one approved stress row a way.

    The loader already refuses a second approved row with another tier, but a row
    typed into the admin can duplicate one. Two approved rows are applied in id
    order, which is not a decision anybody made, and picking one here would
    change what the next rebuild applies - so this stops and names the ways, for
    an instance admin to resolve in the admin (leave one approved) before the
    deploy.
    """
    Override = apps.get_model("core", "Override")
    seen: dict[int, int] = {}
    duplicated: set[int] = set()
    for way_id in Override.objects.filter(kind="stress", approved=True).values_list(
        "osm_way_id", flat=True
    ):
        seen[way_id] = seen.get(way_id, 0) + 1
        if seen[way_id] > 1:
            duplicated.add(way_id)
    if duplicated:
        raise RuntimeError(
            "more than one approved stress override on way(s) "
            + ", ".join(str(w) for w in sorted(duplicated)[:50])
            + (" and more" if len(duplicated) > 50 else "")
            + ": resolve them in the admin (leave one approved) before this migration"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_segment_mtb_only_walk_bike"),
    ]

    operations = [
        migrations.AddField(
            model_name="override",
            name="source",
            field=models.CharField(
                choices=[
                    ("file", "Reviewed file"),
                    ("admin", "Typed into the admin"),
                    ("panel", "Road panel (Change LTS)"),
                ],
                default="file",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="override",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="core.user",
            ),
        ),
        migrations.AddField(
            model_name="override",
            name="created_by_user_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="override",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="core.user",
            ),
        ),
        migrations.AddField(
            model_name="override",
            name="approved_by_user_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="override",
            name="superseded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="supersedes",
                to="core.override",
            ),
        ),
        migrations.AddField(
            model_name="override",
            name="superseded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="override",
            name="fingerprint",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.RunPython(refuse_duplicate_live_stress_rows, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="override",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("approved", True), ("kind", "stress"), ("superseded_by__isnull", True)
                ),
                fields=("osm_way_id",),
                name="override_one_live_stress_row_per_way",
            ),
        ),
        migrations.CreateModel(
            name="StressEdit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("at", models.DateTimeField(default=django.utils.timezone.now)),
                ("actor_user_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "action",
                    models.CharField(choices=[("set", "Change"), ("undo", "Undo")], max_length=8),
                ),
                ("osm_way_ids", models.JSONField(default=list)),
                ("before", models.JSONField(default=dict)),
                ("after", models.JSONField(default=dict)),
                ("applied_to", models.BigIntegerField(blank=True, null=True)),
                ("reapplied_to", models.JSONField(default=list)),
                ("generation", models.IntegerField(default=0)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="core.user",
                    ),
                ),
                (
                    "override",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="edits",
                        to="core.override",
                    ),
                ),
                (
                    "replaced",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="core.override",
                    ),
                ),
                (
                    "undoes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="undone_by",
                        to="core.stressedit",
                    ),
                ),
            ],
            options={
                "db_table": "stress_edit",
                "ordering": ["id"],
                "indexes": [models.Index(fields=["-at"], name="stress_edit_at")],
            },
        ),
        migrations.CreateModel(
            name="LiveEditGeneration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("table_oid", models.BigIntegerField(unique=True)),
                ("generation", models.IntegerField(default=0)),
                ("overrides_read_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"db_table": "live_edit_generation"},
        ),
    ]

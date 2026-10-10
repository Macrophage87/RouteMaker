from django.db import migrations, models


class Migration(migrations.Migration):
    """State only: `Segment` is unmanaged, its table is created whole by every
    rebuild (`pipeline.schema.SEGMENT_DDL`), so this runs no SQL. It keeps the
    model in step with the column the mountain-bike levels added (OWNER-DECISIONS
    456; docs/MTB-TOPO-PLAN.md, slice 2)."""

    dependencies = [
        ("core", "0012_bikeshare_feed_cache"),
    ]

    operations = [
        migrations.AddField(
            model_name="segment",
            name="mtb_level",
            field=models.SmallIntegerField(null=True),
        ),
    ]

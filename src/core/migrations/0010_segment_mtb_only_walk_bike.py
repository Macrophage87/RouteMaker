from django.db import migrations, models


class Migration(migrations.Migration):
    """State only: `Segment` is unmanaged, its table is created whole by every
    rebuild (`pipeline.schema.SEGMENT_DDL`), so this runs no SQL. It keeps the
    model in step with the columns NO-BIKE-PATHS added."""

    dependencies = [
        ("core", "0009_stress_tile_cache"),
    ]

    operations = [
        migrations.AddField(
            model_name="segment",
            name="mtb_only",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="segment",
            name="walk_bike",
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    """State only, as 0013: `Segment` is unmanaged and its table is created whole by
    every rebuild (`pipeline.schema.SEGMENT_DDL`). It keeps the model in step with the
    mountain-bike trail's name (the owner, 2026-10-10: "Also, for mountain bikes, try to
    make sure trail names are added in if they are available.")."""

    dependencies = [
        ("core", "0013_segment_mtb_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="segment",
            name="mtb_name",
            field=models.TextField(null=True),
        ),
    ]

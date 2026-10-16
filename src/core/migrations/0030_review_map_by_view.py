# Review's map served by view (core.stress_review.map_view): a simplified line and a point an item,
# made with it; the whole-list maps once kept on the queue's state row go. The items already listed
# get theirs here, as stress_review._write_facts makes them, so the map is whole before the next
# computation.

import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_review_queue"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="reviewqueuestate",
            name="map_high",
        ),
        migrations.RemoveField(
            model_name="reviewqueuestate",
            name="map_low",
        ),
        migrations.RemoveField(
            model_name="reviewqueuestate",
            name="map_points",
        ),
        migrations.AddField(
            model_name="reviewitem",
            name="point",
            field=django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326),
        ),
        migrations.AddField(
            model_name="reviewitem",
            name="simple",
            field=django.contrib.gis.db.models.fields.MultiLineStringField(
                blank=True, null=True, srid=4326
            ),
        ),
        migrations.RunSQL(
            """
            UPDATE review_item
            SET simple = ST_Multi(ST_SimplifyPreserveTopology(geometry, 0.0003)),
                point = ST_ClosestPoint(geometry, ST_Centroid(geometry))
            WHERE geometry IS NOT NULL
            """,
            migrations.RunSQL.noop,
        ),
    ]

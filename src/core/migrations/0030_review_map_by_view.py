# Review's map served by view (core.stress_review.map_view): a simplified line and a point an item,
# made with it. The items already listed get theirs here, as stress_review._write_facts makes them,
# so the map is whole before the next computation. The whole-list maps on the queue's state row
# (map_low, map_high, map_points) are left for one release, unused, so a worker of the release
# before keeps working through the deploy; their columns go in the next release's migration.

import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_review_queue"),
    ]

    operations = [
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

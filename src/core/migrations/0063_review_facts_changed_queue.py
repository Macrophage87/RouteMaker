# Review's "Facts changed since rated" queue (core.stress_review FILE_QUEUES, pipeline.rated_facts;
# the owner, 2026-11-12: a pinned road whose facts changed keeps our level and is queued): its label
# on ReviewItem, ReviewRuling and ReviewQueueState. Choices only; no column changes.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0062_connector_draft_archived"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reviewitem",
            name="queue",
            field=models.CharField(
                choices=[
                    ("rebuild", "Rebuild changes"),
                    ("disagreement", "Rating disagreements"),
                    ("sidepath", "Use side path, none mapped"),
                    ("narrow_rural", "Narrow rural roads with no posted speed"),
                    ("works_closure", "Industrial, golf and track closures"),
                    ("rematch", "Overrides that did not re-match"),
                    ("painted_lane", "Painted lanes on wide two-way roads"),
                    ("dc_no_bike", "DC ways closed to bicycles"),
                    ("facts_changed", "Facts changed since rated"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="reviewqueuestate",
            name="queue",
            field=models.CharField(
                choices=[
                    ("rebuild", "Rebuild changes"),
                    ("disagreement", "Rating disagreements"),
                    ("sidepath", "Use side path, none mapped"),
                    ("narrow_rural", "Narrow rural roads with no posted speed"),
                    ("works_closure", "Industrial, golf and track closures"),
                    ("rematch", "Overrides that did not re-match"),
                    ("painted_lane", "Painted lanes on wide two-way roads"),
                    ("dc_no_bike", "DC ways closed to bicycles"),
                    ("facts_changed", "Facts changed since rated"),
                ],
                max_length=16,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.AlterField(
            model_name="reviewruling",
            name="queue",
            field=models.CharField(
                choices=[
                    ("rebuild", "Rebuild changes"),
                    ("disagreement", "Rating disagreements"),
                    ("sidepath", "Use side path, none mapped"),
                    ("narrow_rural", "Narrow rural roads with no posted speed"),
                    ("works_closure", "Industrial, golf and track closures"),
                    ("rematch", "Overrides that did not re-match"),
                    ("painted_lane", "Painted lanes on wide two-way roads"),
                    ("dc_no_bike", "DC ways closed to bicycles"),
                    ("facts_changed", "Facts changed since rated"),
                ],
                max_length=16,
            ),
        ),
    ]

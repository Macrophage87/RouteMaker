# v0.7.0: the override's surface-penalty kind (pipeline.overrides.apply_surface,
# core.stress_edits.set_surface) and one live surface row a way.
#
# Follows 0027_suggestion_reviews, so the chain stays linear.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_suggestion_reviews"),
    ]

    operations = [
        migrations.AlterField(
            model_name="override",
            name="kind",
            field=models.CharField(
                choices=[
                    ("access", "Bicycle access"),
                    ("stress", "Stress tier"),
                    ("jurisdiction", "Authority assignment"),
                    ("surface", "Surface penalty"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="override",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("approved", True),
                    ("kind", "surface"),
                    ("superseded_by__isnull", True),
                ),
                fields=("osm_way_id",),
                name="override_one_live_surface_row_per_way",
            ),
        ),
    ]

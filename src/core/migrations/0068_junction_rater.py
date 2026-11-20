import django.contrib.gis.db.models.fields
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0067_saved_route_figures"),
    ]

    operations = [
        migrations.CreateModel(
            name="JunctionRater",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("junction", models.CharField(db_index=True, max_length=32)),
                ("node", models.BigIntegerField(unique=True)),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("control", models.CharField(blank=True, max_length=24)),
                ("cross_stress", models.FloatField(null=True)),
                ("cross_delay_s", models.FloatField(null=True)),
                ("left_stress", models.FloatField(null=True)),
                ("left_delay_s", models.FloatField(null=True)),
                ("along_stress", models.FloatField(null=True)),
                ("along_delay_s", models.FloatField(null=True)),
                ("loaded_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
    ]

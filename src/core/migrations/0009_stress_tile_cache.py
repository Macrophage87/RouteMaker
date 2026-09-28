from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_rate_limit_window"),
    ]

    operations = [
        migrations.CreateModel(
            name="StressTileCache",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("version", models.CharField(max_length=64)),
                ("z", models.SmallIntegerField()),
                ("x", models.IntegerField()),
                ("y", models.IntegerField()),
                ("body", models.BinaryField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "stress_tile_cache",
                "indexes": [models.Index(fields=["created_at"], name="stress_tile_cache_created")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("version", "z", "x", "y"), name="stress_tile_cache_key"
                    )
                ],
            },
        ),
    ]

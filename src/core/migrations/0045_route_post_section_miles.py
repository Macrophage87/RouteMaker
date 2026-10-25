from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0044_route_posts"),
    ]

    operations = [
        migrations.AddField(
            model_name="routepostsection",
            name="start_mi",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=6, null=True, verbose_name="From mile"
            ),
        ),
        migrations.AddField(
            model_name="routepostsection",
            name="end_mi",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=6, null=True, verbose_name="To mile"
            ),
        ),
    ]

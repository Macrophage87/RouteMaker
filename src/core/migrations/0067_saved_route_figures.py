from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0066_stress_suggestion_pk_tiebreak"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedroute",
            name="figures",
            field=models.JSONField(blank=True, null=True),
        ),
    ]

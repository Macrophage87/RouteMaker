from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0065_sign_in_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedroute",
            name="figures",
            field=models.JSONField(blank=True, null=True),
        ),
    ]

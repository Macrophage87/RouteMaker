from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0069_survey_spots"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewedclosure",
            name="agent_key",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="reviewedclosure",
            name="extended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0068_junction_rater"),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveyAnswer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("spot_id", models.CharField(db_index=True, max_length=32)),
                ("day", models.DateField()),
                ("answers", models.JSONField(default=dict)),
            ],
            options={"db_table": "survey_answer", "ordering": ("spot_id", "day")},
        ),
        migrations.CreateModel(
            name="SurveyDone",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("spot_id", models.CharField(max_length=32)),
                ("counted", models.BooleanField(default=False)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "survey_done"},
        ),
        migrations.AddConstraint(
            model_name="surveydone",
            constraint=models.UniqueConstraint(
                fields=("user", "spot_id"), name="survey_done_one_per_spot"
            ),
        ),
    ]

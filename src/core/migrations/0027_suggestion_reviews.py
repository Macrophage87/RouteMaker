# v0.7.0: a second reviewer's agree or disagree on a waiting road suggestion
# (core.models.StressSuggestionReview, core.suggestions.review).
#
# Follows 0026_reviewed_closures, so the chain stays linear.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_reviewed_closures"),
    ]

    operations = [
        migrations.CreateModel(
            name="StressSuggestionReview",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("reviewer_user_id", models.BigIntegerField()),
                ("agree", models.BooleanField()),
                ("reason", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "reviewer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "suggestion",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to="core.stresssuggestion",
                    ),
                ),
            ],
            options={
                "db_table": "stress_suggestion_review",
                "ordering": ["created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("suggestion", "reviewer_user_id"),
                        name="stress_suggestion_review_one_per_reviewer",
                    )
                ],
            },
        ),
    ]

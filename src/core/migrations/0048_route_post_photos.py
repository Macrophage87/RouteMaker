# Photos in Featured routes posts (the owner, 2026-10-25: "Allow images to be included in the
# blog posts"): core.models.RoutePostPhoto, kept with the post as its link picture is.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0047_route_post_openable_routes"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoutePostPhoto",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "place",
                    models.PositiveSmallIntegerField(
                        default=0,
                        help_text="0 under About this ride; 1, 2 and on under that highlighted"
                        " section.",
                        verbose_name="Where",
                    ),
                ),
                ("position", models.PositiveSmallIntegerField(default=0)),
                (
                    "alt_text",
                    models.CharField(
                        help_text="What the photo shows, for people who cannot see it.",
                        max_length=300,
                        verbose_name="Alt text",
                    ),
                ),
                ("caption", models.CharField(blank=True, default="", max_length=200)),
                ("image", models.BinaryField(blank=True, null=True)),
                ("key", models.CharField(blank=True, default="", max_length=16)),
                ("width", models.PositiveIntegerField(blank=True, null=True)),
                ("height", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="photos",
                        to="core.routepost",
                    ),
                ),
            ],
            options={
                "db_table": "route_post_photo",
                "ordering": ("place", "position", "id"),
            },
        ),
    ]

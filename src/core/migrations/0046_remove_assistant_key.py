# The AI assistant key is retired (the owner, 2026-10-25: "the old method with the random token,
# we should take it out"): assistants save through the site's own connector, which signs in.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0045_route_post_section_miles"),
    ]

    operations = [
        migrations.DeleteModel(name="AssistantKey"),
    ]

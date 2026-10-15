# v0.7.0 signed-out LTS suggestions (core.signed_out_suggestions): the "signed out" flag and the
# one-tap reasons on a suggestion, and the per-device daily counts (a salted daily hash, kept 24
# hours). Follows 0020_account_settings_saved_routes, so the chain stays linear.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_account_settings_saved_routes"),
    ]

    operations = [
        migrations.AddField(
            model_name="stresssuggestion",
            name="signed_out",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="stresssuggestion",
            name="reasons",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name="SignedOutSend",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device", models.CharField(max_length=64)),
                ("osm_way_id", models.BigIntegerField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "signed_out_send",
                "indexes": [models.Index(fields=["device", "created_at"], name="signed_out_send_device")],
            },
        ),
    ]

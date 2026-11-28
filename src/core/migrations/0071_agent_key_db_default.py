# The agent_key column gets a database default, so v0.30.4's ORM (which knows nothing of the
# column and leaves it out of its INSERT) can still create a ReviewedClosure after a rollback
# that keeps the database.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0070_agent_closures"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reviewedclosure",
            name="agent_key",
            field=models.CharField(blank=True, db_default="", default="", max_length=100),
        ),
    ]

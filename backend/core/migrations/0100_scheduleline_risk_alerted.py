from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0099_seed_construction_categories")]
    operations = [
        migrations.AddField(
            model_name="scheduleline",
            name="risk_alerted",
            field=models.CharField(blank=True, default="", max_length=12),
        ),
    ]

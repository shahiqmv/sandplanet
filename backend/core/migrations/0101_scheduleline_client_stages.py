from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0100_scheduleline_risk_alerted")]
    operations = [
        migrations.AddField(
            model_name="scheduleline",
            name="client_delivered_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scheduleline",
            name="client_chased_on",
            field=models.DateField(blank=True, null=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0305_timesheet_week_lock"),
    ]

    operations = [
        migrations.AddField(
            model_name="boqimport",
            name="error",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="boqimport",
            name="status",
            field=models.CharField(
                choices=[("RUNNING", "Reading the bill"),
                         ("FAILED", "Could not be read"),
                         ("DRAFT", "Under review"),
                         ("COMMITTED", "Loaded into BOQ")],
                default="DRAFT", max_length=10),
        ),
    ]

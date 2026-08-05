from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0134_commercial_pyr_to_finance"),
    ]

    operations = [
        migrations.AddField(
            model_name="scheduleline",
            name="reference_image",
            field=models.FileField(blank=True, null=True,
                                   upload_to="schedule-refs/"),
        ),
    ]

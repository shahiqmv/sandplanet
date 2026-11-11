from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0304_pyr_booking"),
    ]

    operations = [
        migrations.AddField(
            model_name="timesheetmonth",
            name="locked_through",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="timesheetmonth",
            name="locked_through_by",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="timesheetmonth",
            name="locked_through_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

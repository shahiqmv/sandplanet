import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0131_onboarding_pyr_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="stamp",
            field=models.FileField(blank=True, null=True, upload_to="stamps/"),
        ),
        migrations.AddField(
            model_name="onboardingletter",
            name="status",
            field=models.CharField(
                choices=[("ISSUED", "Issued"), ("PENDING", "Pending signatory"),
                         ("SIGNED", "Signed")],
                default="ISSUED", max_length=8),
        ),
        migrations.AddField(
            model_name="onboardingletter",
            name="approved_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="onboardingletter",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

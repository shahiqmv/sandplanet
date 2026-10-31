from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def approve_existing(apps, schema_editor):
    """Every invoice already recorded was live the moment it was saved — it
    stays owed, as approved, on its creation date."""
    ManualInvoice = apps.get_model("core", "ManualInvoice")
    for mi in ManualInvoice.objects.all():
        mi.status = "APPROVED"
        mi.approved_at = mi.created_at
        mi.approved_by_id = mi.created_by_id
        mi.save(update_fields=["status", "approved_at", "approved_by"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0293_part_payment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="manualinvoice", name="status",
            field=models.CharField(choices=[("DRAFT", "Draft"),
                                            ("SUBMITTED", "Submitted"),
                                            ("APPROVED", "Approved")],
                                   db_index=True, default="DRAFT",
                                   max_length=10)),
        migrations.AddField(
            model_name="manualinvoice", name="revision",
            field=models.IntegerField(default=0)),
        migrations.AddField(
            model_name="manualinvoice", name="return_note",
            field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="manualinvoice", name="submitted_by",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.PROTECT,
                                    related_name="+",
                                    to=settings.AUTH_USER_MODEL)),
        migrations.AddField(
            model_name="manualinvoice", name="submitted_at",
            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name="manualinvoice", name="approved_by",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.PROTECT,
                                    related_name="+",
                                    to=settings.AUTH_USER_MODEL)),
        migrations.AddField(
            model_name="manualinvoice", name="approved_at",
            field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(
            model_name="manualinvoice", name="invoice_no",
            field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(
            model_name="manualinvoiceline", name="kind",
            field=models.CharField(choices=[("CHARGE", "Charge"),
                                            ("DEDUCTION", "Deduction")],
                                   default="CHARGE", max_length=10)),
        migrations.AddField(
            model_name="manualinvoiceline", name="before_gst",
            field=models.BooleanField(default=True)),
        migrations.RunPython(approve_existing, migrations.RunPython.noop),
    ]

from django.db import migrations


def submitted_to_checked(apps, schema_editor):
    """The accountant's check now sits between submission and the signatory
    (owner 2026-11-16): SUBMITTED means "with the accountant", CHECKED means
    "with the signatory". Every voucher submitted before this was with the
    signatory, so it moves to CHECKED and stays in their queue."""
    Document = apps.get_model("core", "Document")
    Document.objects.filter(doc_type="PV", status="SUBMITTED").update(
        status="CHECKED")


def checked_to_submitted(apps, schema_editor):
    Document = apps.get_model("core", "Document")
    Document.objects.filter(doc_type="PV", status="CHECKED").update(
        status="SUBMITTED")


class Migration(migrations.Migration):
    dependencies = [("core", "0306_boq_import_running")]
    operations = [migrations.RunPython(submitted_to_checked,
                                       checked_to_submitted)]

from django.db import migrations


def clear_onboarding_pyrs_to_finance(apps, schema_editor):
    """Onboarding fee PYRs carry no approval layer any more — not the site PM
    and not the Director. Move every one still waiting on an approval (SUBMITTED
    or PM_APPROVED) straight to DIRECTOR_APPROVED = ready for Finance's payment
    voucher, and stamp the origin so new logic recognises them (owner
    2026-08-05)."""
    Document = apps.get_model("core", "Document")
    PaymentRequest = apps.get_model("core", "PaymentRequest")
    stuck = Document.objects.filter(
        doc_type="PYR", onboarding_fee__isnull=False,
        status__in=("SUBMITTED", "PM_APPROVED"))
    PaymentRequest.objects.filter(document__in=list(stuck)).update(
        origin="ONBOARDING")
    stuck.update(status="DIRECTOR_APPROVED")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0132_appointment_confirmation"),
    ]

    operations = [
        migrations.RunPython(clear_onboarding_pyrs_to_finance, noop),
    ]

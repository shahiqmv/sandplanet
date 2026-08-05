from django.db import migrations


def clear_commercial_pyrs_to_finance(apps, schema_editor):
    """Commercial (Insurance & Bonds) fee PYRs now carry no approval layer —
    like onboarding fees they clear straight to Finance. Move every one still
    short of Finance (draft / submitted / PM-approved) to DIRECTOR_APPROVED =
    ready for the payment voucher, so the QS's stuck drafts surface for Finance
    (owner 2026-08-05)."""
    Document = apps.get_model("core", "Document")
    Document.objects.filter(
        doc_type="PYR", payment_request__origin="COMMERCIAL",
        status__in=("DRAFT", "SUBMITTED", "PM_APPROVED"),
    ).update(status="DIRECTOR_APPROVED")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0133_onboarding_pyr_to_finance"),
    ]

    operations = [
        migrations.RunPython(clear_commercial_pyrs_to_finance, noop),
    ]

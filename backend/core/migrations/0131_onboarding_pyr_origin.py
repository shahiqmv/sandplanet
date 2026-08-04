from django.db import migrations


def point_onboarding_pyrs_to_director(apps, schema_editor):
    """Re-route in-flight onboarding fee PYRs to the ONBOARDING chain (Director →
    Finance, no site PM). Only touches ones still awaiting approval so nothing
    already paid/cleared is disturbed — unsticks any that were sitting in a
    site PM's queue (owner 2026-08-04)."""
    PaymentRequest = apps.get_model("core", "PaymentRequest")
    PaymentRequest.objects.filter(
        document__onboarding_fee__isnull=False,
        document__status__in=("DRAFT", "SUBMITTED"),
    ).update(origin="ONBOARDING")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0130_alter_paymentrequest_origin"),
    ]

    operations = [
        migrations.RunPython(point_onboarding_pyrs_to_director, noop),
    ]

# Backfill SHP refs for existing shipments (owner 2026-08-28) and bring the
# SHP counter past them, so new bookings continue the series.
from django.db import migrations


def backfill(apps, schema_editor):
    ImportShipment = apps.get_model("core", "ImportShipment")
    DocCounter = apps.get_model("core", "DocCounter")
    n = 0
    for s in ImportShipment.objects.order_by("id"):
        n += 1
        s.ref = f"SHP-{n:03d}"
        s.save(update_fields=["ref"])
    if n:
        DocCounter.objects.update_or_create(
            doc_type="SHP", site=None, defaults={"last_no": n})


class Migration(migrations.Migration):
    dependencies = [("core", "0184_importshipment_ref")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

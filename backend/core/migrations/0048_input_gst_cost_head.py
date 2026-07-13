from django.db import migrations


def create_input_gst_head(apps, schema_editor):
    CostHead = apps.get_model("core", "CostHead")
    CostHead.objects.get_or_create(
        name="Input GST (recoverable)",
        defaults={"is_pool": True, "is_active": True, "sort_order": 90},
    )


def remove_input_gst_head(apps, schema_editor):
    CostHead = apps.get_model("core", "CostHead")
    CostHead.objects.filter(name="Input GST (recoverable)").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_documentline_gst_amount_quotation_gst_applicable"),
    ]

    operations = [
        migrations.RunPython(create_input_gst_head, remove_input_gst_head),
    ]

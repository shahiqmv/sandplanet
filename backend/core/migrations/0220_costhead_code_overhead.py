"""Give every cost head a fixed internal code, and a company-overhead flag.

The name was the key: nine of the fifteen heads were looked up by their exact
text, so renaming "Materials" would have crashed the purchase-order posting
and renaming the GST head would have silently stopped GST recovery. There was
no screen to rename one from, which is the only reason it never happened
(owner 2026-09-07).

`overhead` starts false on every head, including the ones that arguably are
overheads. Which costs leave the project reports is the owner's call, made a
head at a time on the new page — not something a migration decides.
"""
from django.db import migrations, models

# code → the name it carries today. Anything not listed keeps a slug of its
# own name and is not a system head.
SYSTEM = {
    "MATERIALS": "Materials",
    "LABOUR": "Labour & Staff",
    "SUBCONTRACT": "Subcontract",
    "PLANT": "Plant & Equipment",
    "TRANSPORT": "Transport & Freight",
    "SITE_OVERHEADS": "Site Overheads",
    "PERMITS": "Permits & Fees",
    "OTHER": "Other",
    "GENERAL_STOCK": "General Stock",
    "FOREX": "Foreign Exchange",
    "STOCK_ADJUSTMENT": "Stock Adjustment",
    "INPUT_GST": "Input GST (recoverable)",
    "IMPORT_CHARGES": "Import Charges",
    "RECRUITMENT": "Recruitment & Mobilisation",
    "INSURANCE_BONDS": "Insurance & Bonds",
}


def slug(name):
    out = "".join(c if c.isalnum() else "_" for c in (name or "").upper())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")[:30] or "HEAD"


def fill_codes(apps, schema_editor):
    CostHead = apps.get_model("core", "CostHead")
    by_name = {v: k for k, v in SYSTEM.items()}
    taken = set()
    for head in CostHead.objects.all().order_by("id"):
        code = by_name.get(head.name)
        head.is_system = code is not None
        if code is None:                      # a head someone added by hand
            code = slug(head.name)
            base, n = code, 2
            while code in taken:
                code = f"{base[:27]}_{n}"[:30]
                n += 1
        head.code = code
        taken.add(code)
        head.save(update_fields=["code", "is_system"])


def drop_codes(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [("core", "0219_correction_new_lines")]

    operations = [
        migrations.AddField(
            model_name="costhead", name="code",
            field=models.CharField(max_length=30, default="", blank=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="costhead", name="is_system",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="costhead", name="overhead",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_codes, drop_codes),
        migrations.AlterField(
            model_name="costhead", name="code",
            field=models.CharField(max_length=30, unique=True),
        ),
    ]

"""Flag the tool categories so items in them show in the tool catalog.

The is_tool flag (0027) defaulted to False, so existing "Tools & Equipment"
(and "Tool") categories weren't marked as tool categories on live installs —
tool items imported into them didn't appear in the Tools register catalogue.
"""
from django.db import migrations


def flag_tool_categories(apps, schema_editor):
    ItemCategory = apps.get_model("core", "ItemCategory")
    ItemCategory.objects.filter(
        name__in=["Tools & Equipment", "Tool", "Tools and Equipment"]
    ).update(is_tool=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0033_item_is_provisional")]
    operations = [
        migrations.RunPython(flag_tool_categories, migrations.RunPython.noop),
    ]

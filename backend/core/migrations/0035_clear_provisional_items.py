"""Clear provisional flags — the item-approval gate is off for now (owner)."""
from django.db import migrations


def clear_provisional(apps, schema_editor):
    apps.get_model("core", "Item").objects.filter(
        is_provisional=True).update(is_provisional=False)


class Migration(migrations.Migration):
    dependencies = [("core", "0034_flag_tools_category")]
    operations = [
        migrations.RunPython(clear_provisional, migrations.RunPython.noop),
    ]

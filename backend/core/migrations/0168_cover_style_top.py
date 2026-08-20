"""Point the existing settings row at the title-in-the-sky cover.

`cover_style` was added (0165) defaulting to FULL, which wrote FULL into the row
already seeded by 0164. Changing the model default to TOP afterwards does not
touch existing rows, so every database — production included — would have kept
the bottom-title layout and hidden the pool behind the type.

Safe to force: FULL existed for minutes, was never offered in the UI, and
nobody can have chosen it. The picker ships alongside this, so from here it is
the owner's choice and no migration will second-guess it.
"""
from django.db import migrations


def to_top(apps, schema_editor):
    apps.get_model("core", "ProfileSettings").objects.filter(
        cover_style="FULL").update(cover_style="TOP")


def back(apps, schema_editor):
    apps.get_model("core", "ProfileSettings").objects.filter(
        cover_style="TOP").update(cover_style="FULL")


class Migration(migrations.Migration):
    dependencies = [("core", "0167_alter_profilesettings_cover_style")]
    operations = [migrations.RunPython(to_top, back)]

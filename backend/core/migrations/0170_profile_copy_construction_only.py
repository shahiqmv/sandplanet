"""Take resort supplies out of the profile copy, and the em dashes with it.

The owner's words: resort supplies "dilutes my construction portfolio". The
cover subtitles are in the renderer and changed there; the vision statement, the
"Senior management" row and one management biography are database content and
have to be edited here.

Only exact seeded text is replaced. Anything a person has since rewritten is
left alone — a migration has no business overwriting someone's own words.
"""
from django.db import migrations

OLD_VISION = ("To become a competitive leader in the Maldivian construction "
              "industry and in resort supplies, delivering projects that "
              "precisely meet our clients' requirements while upholding "
              "international standards.")
NEW_VISION = ("To become a competitive leader in the Maldivian construction "
              "industry, delivering projects that precisely meet our clients' "
              "requirements while upholding international standards.")

OLD_SHAHIQ = ("Co-founder and Managing Director of Sand Planet, leading the "
              "company's strategy, growth and delivery across construction, "
              "resort supplies and marine works since 2015.")
NEW_SHAHIQ = ("Co-founder and Managing Director of Sand Planet, leading the "
              "company's strategy, growth and delivery across construction, "
              "design-build and marine works since 2015.")

# The senior-management row lists four people with an em dash before each role.
OLD_SENIOR = ("Ahmed Shahiq — Managing Director<br>"
              "Ibrahim Fikury Hussain — Director, Business Development<br>"
              "Muditha Samanthilaka — Director of Projects<br>"
              "Waseem Ali — Director of Marine Projects")
NEW_SENIOR = ("Ahmed Shahiq, Managing Director<br>"
              "Ibrahim Fikury Hussain, Director, Business Development<br>"
              "Muditha Samanthilaka, Director of Projects<br>"
              "Waseem Ali, Director of Marine Projects")


def forward(apps, schema_editor):
    Settings = apps.get_model("core", "ProfileSettings")
    Row = apps.get_model("core", "ProfileCorporateRow")
    Mgmt = apps.get_model("core", "ProfileManagement")

    Settings.objects.filter(vision=OLD_VISION).update(vision=NEW_VISION)
    Row.objects.filter(value=OLD_SENIOR).update(value=NEW_SENIOR)
    Mgmt.objects.filter(intro=OLD_SHAHIQ).update(intro=NEW_SHAHIQ)


def backward(apps, schema_editor):
    Settings = apps.get_model("core", "ProfileSettings")
    Row = apps.get_model("core", "ProfileCorporateRow")
    Mgmt = apps.get_model("core", "ProfileManagement")

    Settings.objects.filter(vision=NEW_VISION).update(vision=OLD_VISION)
    Row.objects.filter(value=NEW_SENIOR).update(value=OLD_SENIOR)
    Mgmt.objects.filter(intro=NEW_SHAHIQ).update(intro=OLD_SHAHIQ)


class Migration(migrations.Migration):
    dependencies = [("core", "0169_profilesettings_divider_focus")]
    operations = [migrations.RunPython(forward, backward)]

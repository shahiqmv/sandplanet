"""Move the profile's hardcoded management and corporate content into the
database, exactly as it reads today.

The four directors and the "company at a glance" table were literals in
profile_render.py, so adding a person or correcting the headcount meant editing
code and deploying (owner 2026-08-19). Seeding the current text means the
generated PDF is identical the moment this lands — the change is only that it
can now be edited.
"""
from django.db import migrations

MANAGEMENT = [
    ("Ahmed Shahiq", "Managing Director",
     "Co-founder and Managing Director of Sand Planet, leading the company's "
     "strategy, growth and delivery across construction, resort supplies and "
     "marine works since 2015."),
    ("Ibrahim Fikury Hussain", "Director, Business Development",
     "Co-founder and Director of Business Development, building the client "
     "relationships and new opportunities that drive the company's work across "
     "the resort sector."),
    ("Muditha Samanthilaka", "Director of Projects",
     "Director of Projects, overseeing planning, execution and quality across "
     "the company's building and fit-out portfolio."),
    ("Waseem Ali", "Director of Marine Projects",
     "Director of Marine Projects, leading the company's marine and coastal "
     "works, including breakwaters, revetments, piling and jetties."),
]

CORPORATE = [
    ("Legal form", "Private Limited Company"),
    ("Shareholders", "Ahmed Shahiq · Ibrahim Fikury Hussain"),
    ("Senior management",
     "Ahmed Shahiq — Managing Director<br>"
     "Ibrahim Fikury Hussain — Director, Business Development<br>"
     "Muditha Samanthilaka — Director of Projects<br>"
     "Waseem Ali — Director of Marine Projects"),
    ("Registered office", "Ma. Maaraadha Aage', Dhanburuh Magu, Malé"),
    ("Registration", "C-0059/2015 · TIN 1052866GST501"),
    ("Bankers", "Bank of Maldives Public Ltd"),
    ("Auditors", "AH Associates"),
    ("Total staff", "106 personnel"),
]

VISION = ("To become a competitive leader in the Maldivian construction "
          "industry and in resort supplies, delivering projects that precisely "
          "meet our clients' requirements while upholding international "
          "standards.")
MISSION = ("To undertake construction with a focus on becoming a competitive "
           "leader in product costing, building excellence in every aspect to "
           "meet stringent requirements for quality, on-time delivery, safety "
           "and environmental care.")


def seed(apps, schema_editor):
    Mgmt = apps.get_model("core", "ProfileManagement")
    Row = apps.get_model("core", "ProfileCorporateRow")
    Settings = apps.get_model("core", "ProfileSettings")

    if not Mgmt.objects.exists():
        for i, (name, role, intro) in enumerate(MANAGEMENT, start=1):
            Mgmt.objects.create(name=name, role=role, intro=intro,
                                sort_order=i * 10)
    if not Row.objects.exists():
        for i, (label, value) in enumerate(CORPORATE, start=1):
            Row.objects.create(label=label, value=value, sort_order=i * 10)
    Settings.objects.get_or_create(
        pk=1, defaults={"vision": VISION, "mission": MISSION})


def unseed(apps, schema_editor):
    # Reversible, but deliberately does NOT delete rows a person has since
    # edited or added — only a clean, untouched seed goes back out.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0163_profilecorporaterow_profilemanagement_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]

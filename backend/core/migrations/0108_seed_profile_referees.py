"""Seed the profile's existing referees so the "Trusted by the industry" page
is editable (add/remove) out of the box. Idempotent."""
from django.db import migrations

REFEREES = [
    ("Soundarajah R", "Director", "V I C M Consultants (Pvt) Ltd"),
    ("TS Chua", "GM, Projects & Engineering", "CDL Hospitality Trusts"),
    ("Mahesh Kumar", "Resident Project Director", "RLB Hooloomann Maldives"),
    ("Nalin Maheepala", "Director of Engineering", "Velaa Private Island"),
    ("Ibrahim Ayyoob", "Director of Engineering", "Baglioni Maldives"),
    ("Mohamed Adam", "Chief Engineer", "Jumeirah Maldives"),
    ("Shanawaz Khan", "Chief Engineer", "Cheval Blanc Randheli"),
]


def seed(apps, schema_editor):
    Referee = apps.get_model("core", "ProfileReferee")
    if Referee.objects.exists():
        return
    for i, (name, role, org) in enumerate(REFEREES, 1):
        Referee.objects.create(name=name, role=role, org=org, sort_order=i * 10)


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("core", "0107_profilereferee")]
    operations = [migrations.RunPython(seed, unseed)]

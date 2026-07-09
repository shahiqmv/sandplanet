"""Seed master data per the Build Brief M1: sites (spec §2), admin user,
manpower categories (spec §5.1/§5.2), company parameters (spec §6A.3).
Idempotent — safe to re-run."""

import os

from django.core.management.base import BaseCommand

from core.models import CompanyParameter, ManpowerCategory, Site, User

SITES = [  # spec §2: current sites at go-live, imported as Active
    ("SJR", "Soneva Jani"),
    ("SFR", "Soneva Fushi"),
    ("SSR", "Soneva Secret"),
    ("VKR", "Vakkaru Maldives"),
    ("SSL", "Six Senses Laamu"),
    ("BVR", "Bvlgari Ranfushi"),
    ("RCM", "The Ritz-Carlton Maldives"),
    ("MXR", "Max Royal"),
    ("WAM", "Waldorf Astoria Maldives"),
    ("CNR", "Conrad Maldives"),
    ("HPI", "The Halcyon Private Isles"),
]

DPR_CATEGORIES = {  # spec §5.1
    "STAFF": [
        "Project Manager", "Site Engineer", "MEP Engineer", "QS/QC",
        "Supervisor", "Foreman", "Site Admin/Storekeeper",
    ],
    "LABOUR": [
        "Mason", "Carpenter", "Steel Fixer/Bar Bender", "Welder", "Plumber",
        "Electrician", "Painter/Tiler", "Skilled Labour", "Unskilled Labour",
        "Driver/Kappi/Cleaner",
    ],
}

TWS_CATEGORIES = {  # spec §5.2 (coarser list)
    "STAFF": ["Project Manager", "Site Engineer", "Supervisor/Foreman", "Other staff"],
    "LABOUR": [
        "Mason/Tiler", "Carpenter", "Steel Fixer/Welder", "Plumber/Electrician",
        "Painter", "Skilled/Unskilled Labour",
    ],
}

PARAMETERS = [
    # Defaults per Maldives Employment Act practice — PENDING owner
    # confirmation (Build Brief: confirm during M1).
    ("ot_multiplier", 1.25,
     "Overtime pay multiplier. DEFAULT — confirm with payroll practice."),
    ("hourly_rate_divisor", 240,
     "Monthly basic pay ÷ this = hourly rate (30 days × 8 h). DEFAULT — confirm."),
    # External PO stationery (values from the company's current PO format)
    ("gst_rate", 8, "GST %% applied on Purchase Orders."),
    ("company_legal_name", "Sand Planet Pvt Ltd", "Legal name on external documents."),
    ("company_tin", "1052866GST501", "TIN shown in the PO footer."),
    ("company_address", "Ma. Maaraadha aage | Maldives", "PO footer address."),
    ("company_email", "sales@sandplanet.mv", "PO footer email."),
    ("company_website", "http://sandplanet.mv", "PO footer website."),
    ("company_tagline", "WE GO ABOVE AND BEYOND ON EVERY JOB, PERIOD",
     "PO footer tagline."),
]


class Command(BaseCommand):
    help = "Seed sites, admin user, manpower categories, company parameters."

    def handle(self, *args, **options):
        for code, name in SITES:
            _, created = Site.objects.get_or_create(
                code=code, defaults={"name": name, "status": Site.Status.ACTIVE}
            )
            if created:
                self.stdout.write(f"  site {code} — {name}")
        Site.objects.get_or_create(
            code="MLE",
            defaults={
                "name": "Head Office, Male'",
                "is_head_office": True,
                "status": Site.Status.ACTIVE,
            },
        )

        if not User.objects.filter(username="admin").exists():
            password = os.environ.get("SEED_ADMIN_PASSWORD", "sandplanet-admin")
            User.objects.create_superuser(
                username="admin",
                password=password,
                full_name="System Administrator",
                role=User.Role.ADMIN,
            )
            self.stdout.write("  admin user created (change the password!)")

        # One company-wide worker list (owner: the DPR/TWS split is retired).
        # Stored under list_type="DPR" for the existing unique constraint.
        order = 0
        for grp, names in DPR_CATEGORIES.items():
            for name in names:
                order += 10
                ManpowerCategory.objects.get_or_create(
                    list_type="DPR", name=name,
                    defaults={"grp": grp, "sort_order": order},
                )

        for key, value, description in PARAMETERS:
            CompanyParameter.objects.get_or_create(
                key=key, defaults={"value": value, "description": description}
            )

        self.stdout.write(self.style.SUCCESS("Seed complete."))

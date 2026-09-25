"""First start of the Sandplanet Marine instance (MARINE_BUILD_BRIEF.md
§3): the company's own identity, brand and switches, its head-office site,
the worker categories and the admin user. Idempotent — safe to run again.
Sand Planet's sites are NOT created here."""
import os
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from core.models import CompanyParameter, ManpowerCategory, Site, User

COMPANY = [
    ("company_legal_name", "SANDPLANET MARINE PRIVATE LIMITED"),
    ("company_reg_no", "C21442026"),
    ("company_tin", "1184934"),
    ("company_address", "Fehiali, Gn. Fuvahmulah, Republic of Maldives"),
    ("company_website", "www.sandplanet.mv"),
    ("company_tagline", "Marine works and heavy-vehicle rental"),
    ("brand_name", "SANDPLANET MARINE"),
    ("brand_tagline", "Marine & Fleet"),
    ("brand_short_code", "SPM"),
    # The palette is applied by the brand_palette command (the "marine"
    # preset) after the parameters below, so it stays in one place.
    ("features", {"trading": False, "rental": True, "profile": False}),
    ("apps", [{"key": "sandplanet", "name": "Sand Planet Projects", "url": "/"}]),
]

FILES = [  # (storage name, asset file)
    ("company/logo.png", "spm-logo.png"),
    ("company/mark.png", "spm-emblem.png"),
    ("company/emblem.png", "spm-emblem.png"),
    ("company/wordmark-white.png", "spm-wordmark-white.png"),
]


class Command(BaseCommand):
    help = "Seed the Sandplanet Marine instance: identity, brand, HO site, admin."

    def handle(self, *args, **options):
        from django.core.management import call_command
        for key, value in COMPANY:
            _, created = CompanyParameter.objects.get_or_create(
                key=key, defaults={"value": value, "description": "Sandplanet Marine"})
            if created:
                self.stdout.write(f"  parameter {key}")
        if not CompanyParameter.objects.filter(key="brand_primary").exists():
            call_command("brand_palette", "marine")
        assets = Path(settings.BASE_DIR) / "pdf_templates" / "assets" / "marine"
        for name, asset in FILES:
            if default_storage.exists(name):
                continue
            src = assets / asset
            if src.exists():
                default_storage.save(name, ContentFile(src.read_bytes()))
                self.stdout.write(f"  brand file {name}")
        Site.objects.get_or_create(
            code="FVM", defaults={"name": "Head Office, Fuvahmulah",
                                  "is_head_office": True, "status": Site.Status.ACTIVE})
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                password=os.environ.get("SEED_ADMIN_PASSWORD", "sandplanet-marine-admin"),
                full_name="System Administrator", role=User.Role.ADMIN)
            self.stdout.write("  admin user created (change the password!)")
        from core.management.commands.seed import DPR_CATEGORIES
        order = 0
        for grp, names in DPR_CATEGORIES.items():
            for name in names:
                order += 10
                ManpowerCategory.objects.get_or_create(
                    list_type="DPR", name=name, defaults={"grp": grp, "sort_order": order})
        from core import brand
        brand.invalidate()
        self.stdout.write(self.style.SUCCESS("Sandplanet Marine seed complete."))

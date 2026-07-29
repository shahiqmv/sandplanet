"""Seed the completed + marine reference projects — extracted from the owner's
full 109-page profile PDF (core/profile_seed/completed_manifest.json + heroes) —
as COMPLETED ProfileEntry rows, so the generator renders them in the new-design
reference grid. Idempotent; --reset rebuilds. Left UNLOCKED so the owner can fix
any residual OCR wording in the UI.

    python manage.py seed_profile_completed [--reset]
"""
import json
import re
from datetime import date
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _completed_date(start):
    """'January 2026' / '1st December 2023' → date(y, m, 1); None if no year."""
    s = (start or "").lower()
    y = re.search(r"(20\d\d)", s)
    if not y:
        return None
    mo = next((_MONTHS[k] for k in _MONTHS if k in s), 1)
    return date(int(y.group(1)), mo, 1)


class Command(BaseCommand):
    help = "Seed completed + marine reference projects from the extracted set."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing completed entries first.")

    def handle(self, *args, **opts):
        from core import profile as pf
        from core.models import ProfileEntry, User
        base = Path(__file__).resolve().parents[2] / "profile_seed"
        manifest = json.loads(
            (base / "completed_manifest.json").read_text(encoding="utf-8"))
        photos = base / "completed"
        actor = User.objects.filter(role="ADMIN").first()
        if opts["reset"]:
            ProfileEntry.objects.filter(status="COMPLETED").delete()
        if ProfileEntry.objects.filter(status="COMPLETED").exists():
            self.stdout.write(self.style.WARNING(
                "Completed entries already exist — use --reset to rebuild."))
            return
        n = 0
        for i, p in enumerate(manifest, 1):
            start, months = p.get("start", ""), p.get("months", "")
            period = (start + (" · " + months if months else "")).strip()
            e = ProfileEntry.objects.create(
                status="COMPLETED", snapshot_locked=False, sort_order=i * 10,
                project_name=p["title"], client_display=p.get("client", ""),
                summary="", start_label="Completed", start_value=period,
                completed_at=_completed_date(start), created_by=actor)
            hero = p.get("hero")
            if hero and (photos / hero).exists():
                with open(photos / hero, "rb") as fh:
                    pf.set_featured(e, SimpleUploadedFile(
                        hero, fh.read(), "image/jpeg"), actor)
            n += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {n} completed / marine reference projects."))

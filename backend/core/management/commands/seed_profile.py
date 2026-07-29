"""Seed the six current ongoing Company-Profile entries with their real photos
(owner-supplied, committed under core/profile_seed/photos/). Idempotent; --reset
rebuilds the ongoing set. Photo p{page}_0 is the featured (square) image, the
rest are gallery (3:2). Metadata + summaries are the owner's own copy.

    python manage.py seed_profile [--reset]
"""
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand

# page, client, title, commenced, summary — in display order.
PROJECTS = [
    (15, "Soneva Jani",
     "North Jetty Villa Renovation, So Permeative & IVD Building", "April 2026",
     "Full renovation of the north jetty villas alongside construction of the "
     "So Permeative and IVD buildings — delivered inside a live resort, with "
     "every stage phased around guest operations and marine access."),
    (11, "Six Senses Laamu", "14 Nos Water Villa Pool Construction", "April 2026",
     "Construction of fourteen water-villa swimming pools including structure, "
     "waterproofing and MEP works, executed over water with materials delivered "
     "by scheduled resort supply boats."),
    (13, "Vakkaru Maldives", "Water Villa Pool Construction Work", "May 2026",
     "Water-villa swimming pool construction works, delivered to resort "
     "specification with full structural and finishing scope."),
    (9, "Gulf Craft", "Main Pool Construction", "October 2025",
     "Construction of the resort's main pool — a complex freeform structure "
     "with integrated water features, built to exacting finish standards."),
    (17, "Soneva Secret",
     "Villa Renovation, Privacy Fence & Garden Wall, Bicycle Hut Fabrication",
     "June 2026",
     "Villa renovation with privacy fence and garden wall construction, plus "
     "bicycle-hut fabrication — a multi-trade package across the resort."),
    (19, "Soneva Secret", "Laundry Extension", "June 2026",
     "Extension of the resort laundry facility, completed to a tight programme "
     "with full civil and MEP scope."),
]


class Command(BaseCommand):
    help = "Seed the six ongoing Company-Profile entries with their photos."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing ongoing entries first.")

    def handle(self, *args, **opts):
        from core import profile as pf
        from core.models import ProfileEntry, User
        photos = Path(__file__).resolve().parents[2] / "profile_seed" / "photos"
        if not photos.exists():
            self.stdout.write(self.style.ERROR(f"No photos at {photos}."))
            return
        actor = User.objects.filter(role="ADMIN").first()
        if opts["reset"]:
            ProfileEntry.objects.filter(status="ONGOING").delete()
        if ProfileEntry.objects.filter(status="ONGOING").exists():
            self.stdout.write(self.style.WARNING(
                "Ongoing entries already exist — use --reset to rebuild."))
            return

        def upload(name):
            with open(photos / name, "rb") as fh:
                return SimpleUploadedFile(name, fh.read(), "image/jpeg")

        for i, (page, client, title, start, summary) in enumerate(PROJECTS, 1):
            e = ProfileEntry.objects.create(
                status="ONGOING", sort_order=i * 10, project_name=title,
                client_display=client, summary=summary,
                start_label="Commenced", start_value=start, created_by=actor)
            pf.set_featured(e, upload(f"p{page}_0.jpg"), actor)
            idx = 1
            while (photos / f"p{page}_{idx}.jpg").exists() and idx <= pf.MAX_GALLERY:
                pf.add_gallery(e, upload(f"p{page}_{idx}.jpg"), actor)
                idx += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(PROJECTS)} ongoing profile entries with photos."))

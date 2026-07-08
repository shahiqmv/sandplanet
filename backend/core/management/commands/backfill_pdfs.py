"""Generate archived PDFs for issued/verified documents that are missing them
(e.g. documents issued while the PDF engine was unavailable — DECISIONS.md D4).

--force additionally REGENERATES every existing archived PDF in place —
same revision, same milestone — used when the stationery/templates change
(dev/template work only: archived PDFs are immutable in production use)."""

from django.core.management.base import BaseCommand

from core.models import Document
from core.pdf import generate_pdf


class Command(BaseCommand):
    help = "Backfill archived PDFs for issued documents that have none."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Regenerate even when PDFs exist (dev/template work only — "
                 "archived PDFs are immutable in production use).",
        )

    def handle(self, *args, **options):
        for doc in Document.objects.order_by("id"):
            existing = list(
                doc.attachments.filter(kind="GENERATED_PDF")
                .select_related("revision").order_by("id")
            )
            if existing and not options["force"]:
                continue

            # Which (revision, milestone) PDFs should this document have?
            pairs = []
            for att in existing:
                prefix = f"{doc.ref}-{att.revision.rev_label}-"
                milestone = (att.file_name[len(prefix):-4]
                             if att.file_name.startswith(prefix)
                             and att.file_name.endswith(".pdf") else "issue")
                if milestone.startswith("restyle"):
                    continue  # dev scratch from template work — drop
                if not any(r.id == att.revision_id and m == milestone
                           for r, m in pairs):
                    pairs.append((att.revision, milestone))
            if not pairs and doc.status in ("ISSUED", "VERIFIED") \
                    and not doc.is_void:
                pairs = [(doc.current_revision, "issue")]
                if doc.status == "VERIFIED":
                    pairs.append((doc.current_revision, "verified"))
            if not pairs:
                continue

            for old in existing:
                old.file.delete(save=False)
                old.delete()
            made = []
            for revision, milestone in pairs:
                att = generate_pdf(doc, revision, milestone)
                made.append(att.file.name if att
                            else f"{milestone}: SKIPPED — engine missing")
            self.stdout.write(f"{doc.ref} ({doc.status}): " + ", ".join(made))
        self.stdout.write(self.style.SUCCESS("Backfill complete."))

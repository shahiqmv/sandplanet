"""Generate archived PDFs for issued/verified documents that are missing them
(e.g. documents issued while the PDF engine was unavailable — DECISIONS.md D4)."""

from django.core.management.base import BaseCommand

from core.models import Document
from core.pdf import generate_pdf


class Command(BaseCommand):
    help = "Backfill archived PDFs for issued documents that have none."

    def handle(self, *args, **options):
        qs = Document.objects.filter(
            status__in=["ISSUED", "VERIFIED"], is_void=False
        )
        for doc in qs:
            if doc.attachments.filter(kind="GENERATED_PDF").exists():
                continue
            issue_pdf = generate_pdf(doc, doc.current_revision, "issue")
            verified_pdf = (
                generate_pdf(doc, doc.current_revision, "verified")
                if doc.status == "VERIFIED"
                else None
            )
            self.stdout.write(
                f"{doc.ref} ({doc.status}): "
                f"{issue_pdf.file.name if issue_pdf else 'SKIPPED — engine missing'}"
                + (f", {verified_pdf.file.name}" if verified_pdf else "")
            )
        self.stdout.write(self.style.SUCCESS("Backfill complete."))

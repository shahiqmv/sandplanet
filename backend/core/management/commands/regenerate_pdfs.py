"""Regenerate stored GENERATED_PDF attachments with the CURRENT templates.

Use after a PDF-layout change so already-issued documents adopt the new
format:

    python manage.py regenerate_pdfs            # DPRs (default)
    python manage.py regenerate_pdfs --type ALL # every document type

For each affected, non-void document it removes the old generated PDF(s)
and renders a fresh one at the same milestone. Source data is untouched.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Regenerate stored PDFs with the current templates."

    def add_arguments(self, parser):
        parser.add_argument("--type", default="DPR",
                            help="Document type to regenerate, or ALL.")

    def handle(self, *args, **opts):
        from core.models import Document
        from core.pdf import generate_pdf

        dt = opts["type"].upper()
        qs = Document.objects.filter(
            is_void=False, attachments__kind="GENERATED_PDF").distinct()
        if dt != "ALL":
            qs = qs.filter(doc_type=dt)

        done, failed = 0, 0
        for doc in qs.order_by("doc_type", "ref"):
            rev = doc.current_revision
            if rev is None:
                continue
            latest = doc.attachments.filter(
                kind="GENERATED_PDF").order_by("-id").first()
            milestone = "issue"
            if latest:
                stem = latest.file.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                bits = stem.split("-", 1)  # e.g. R0-issue -> issue
                if len(bits) == 2:
                    milestone = bits[1]
            try:
                for old in list(doc.attachments.filter(kind="GENERATED_PDF")):
                    old.file.delete(save=False)
                    old.delete()
                if generate_pdf(doc, rev, milestone) is not None:
                    done += 1
                    self.stdout.write(f"  [ok] {doc.ref} ({milestone})")
                else:
                    failed += 1
                    self.stderr.write(f"  ! {doc.ref}: PDF engine unavailable")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.stderr.write(f"  ! {doc.ref}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Regenerated {done} PDF(s); {failed} failed."))

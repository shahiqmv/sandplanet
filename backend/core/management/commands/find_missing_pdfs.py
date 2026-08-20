"""Find issued documents that have no generated PDF, and optionally make it.

MAR-STN-022 was issued with a 56-page enclosure. Compiling it took 455 seconds
against a 120-second worker timeout, so the worker was killed part-way: the
document was marked ISSUED, the PDF was never written, and nothing anywhere
said so. It was found because a person went looking for the file (owner
2026-08-20).

The compression is now fast enough that this should not recur, but "should not"
is not "cannot" — a wedged render still leaves a document short a PDF, and the
only thing worse than that is not knowing.

    python manage.py find_missing_pdfs                 # report
    python manage.py find_missing_pdfs --fix           # and generate them
    python manage.py find_missing_pdfs --type MAR

Only document types that HAVE a PDF template are considered; a PYR has no
rendered form and its absence means nothing.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report (and optionally regenerate) issued documents with no PDF."

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true",
                            help="Generate the missing PDFs.")
        parser.add_argument("--type", default=None,
                            help="Limit to one document type, e.g. MAR.")
        parser.add_argument("--all", action="store_true",
                            help="Include documents not yet issued, which "
                                 "normally have no PDF yet.")

    def handle(self, *args, **opts):
        from django.db.models import Count, Q

        from core import pdf as pdf_mod
        from core.models import Document

        qs = (Document.objects.filter(is_void=False)
              .exclude(status="DRAFT")
              .select_related("current_revision")
              .annotate(pdfs=Count("attachments",
                                   filter=Q(attachments__kind="GENERATED_PDF")))
              .filter(pdfs=0).order_by("doc_type", "ref"))
        if opts["type"]:
            qs = qs.filter(doc_type=opts["type"].upper())

        missing = []
        for doc in qs:
            rev = doc.current_revision
            if rev is None:
                continue
            # Only types with a template — a PYR has no rendered form, so its
            # having no PDF is normal and not a fault.
            if not pdf_mod._render_target(doc, rev):
                continue
            # And only documents that have actually been ISSUED. A PDF is
            # written at a milestone (issue / approved / sent / departed), so a
            # document still at SUBMITTED or PM_APPROVED has none YET and is
            # not damaged. Reporting those trains people to ignore the report.
            if not opts["all"] and rev.issued_at is None:
                continue
            missing.append((doc, rev))

        if not missing:
            self.stdout.write(self.style.SUCCESS(
                "Every issued document that should have a PDF has one."))
            return

        self.stdout.write(f"{len(missing)} document(s) with no PDF:")
        for doc, _rev in missing:
            encl = doc.attachments.filter(kind="ENCLOSURE").count()
            note = f"  ({encl} enclosure(s))" if encl else ""
            self.stdout.write(f"    {doc.ref:18} {doc.doc_type:5} "
                              f"{doc.status:14}{note}")

        if not opts["fix"]:
            self.stdout.write("\nRe-run with --fix to generate them.")
            return

        made = failed = 0
        for doc, rev in missing:
            try:
                att = pdf_mod.generate_pdf(doc, rev, "issue")
            except Exception as exc:              # keep going; report at the end
                self.stdout.write(self.style.ERROR(
                    f"    {doc.ref}: {type(exc).__name__} {exc}"))
                failed += 1
                continue
            if att is None:
                failed += 1
                self.stdout.write(f"    {doc.ref}: engine returned nothing")
            else:
                made += 1
                self.stdout.write(self.style.SUCCESS(
                    f"    {doc.ref}: {att.file.size / 1048576:.1f} MB"))
        self.stdout.write(self.style.SUCCESS(
            f"generated {made}; {failed} still missing."))

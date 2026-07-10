"""Render the demo instance's generated PDFs (the on-letterhead 'filled
formats' the client/vendor receives) to PNG for the user guide.

    python manage.py render_pdfs --settings=config.settings_demo

Reads the stored GENERATED_PDF attachments from the demo media tree and
also fetches the on-demand Payment Voucher and Programme PDFs, rendering
the first page of each to guide/screenshots/pdf-<name>.png. Demo-only.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# One representative milestone per document type — the most complete PDF.
PREFERRED = {
    "DPR": "issue", "TWS": "issue", "DMA": "issue",
    "IR": "result", "MAR": "result", "MR": "sent",
    "PR": "approved", "LM": "departed", "GRN": "verified",
}


class Command(BaseCommand):
    help = "Render demo generated PDFs to PNG for the user guide."

    def add_arguments(self, parser):
        parser.add_argument("--scale", type=float, default=2.0,
                            help="Render scale (2.0 ≈ 144 dpi).")
        parser.add_argument("--out", default=None,
                            help="Output dir (default guide/screenshots).")

    def handle(self, *args, **opts):
        name = str(settings.DATABASES["default"]["NAME"])
        if "demo" not in name:
            raise CommandError("Run with --settings=config.settings_demo.")
        import pypdfium2 as pdfium
        from core.models import Attachment

        out = Path(opts["out"] or (settings.BASE_DIR.parent / "guide"
                                   / "screenshots"))
        out.mkdir(parents=True, exist_ok=True)
        scale = opts["scale"]
        n = 0

        def render(pdf_bytes, stem):
            nonlocal n
            doc = pdfium.PdfDocument(pdf_bytes)
            page = doc[0]  # first page is the form; annexes follow
            pil = page.render(scale=scale).to_pil()
            target = out / f"pdf-{stem}.png"
            pil.save(target)
            n += 1
            self.stdout.write(f"  [ok] {target.name}  ({len(doc)} page[s])")

        # 1) Stored milestone PDFs (one preferred milestone per document).
        seen = set()
        for att in (Attachment.objects.filter(kind="GENERATED_PDF")
                    .select_related("document").order_by("document__doc_type")):
            doc = att.document
            milestone = Path(att.file.name).stem.split("-", 1)[-1]  # R0-issue -> issue
            want = PREFERRED.get(doc.doc_type)
            key = doc.doc_type
            if want and want not in att.file.name:
                continue
            if key in seen:
                continue
            try:
                render(att.file.read(), f"{doc.doc_type.lower()}-{doc.ref}")
                seen.add(key)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.WARNING(
                    f"  ! {doc.ref} {milestone}: {exc}"))

        # 2) On-demand PDFs (not stored as attachments): Payment Voucher +
        #    Programme. Rendered straight from their view functions.
        self._render_ondemand(render)

        self.stdout.write(self.style.SUCCESS(f"Rendered {n} PDF page(s)."))

    def _render_ondemand(self, render):
        """Payment Voucher + Programme PDFs are produced on demand by their
        endpoints, not stored — fetch them through the real API."""
        from rest_framework.test import APIClient

        from core.models import Document, Project, User

        client = APIClient()
        finance = User.objects.filter(role=User.Role.FINANCE).first()
        pm = User.objects.filter(role=User.Role.PM).first()

        pv = Document.objects.filter(doc_type="PV").order_by("ref").first()
        if pv is not None and finance is not None:
            client.force_authenticate(finance)
            r = client.get(f"/api/v1/payment-vouchers/{pv.ref}/pdf")
            if r.status_code == 200:
                render(b"".join(r.streaming_content)
                       if getattr(r, "streaming", False) else r.content,
                       f"pv-{pv.ref}")
            else:
                self.stderr.write(self.style.WARNING(
                    f"  ! PV pdf: {r.status_code}"))

        proj = Project.objects.order_by("id").first()
        if proj is not None and pm is not None:
            client.force_authenticate(pm)
            r = client.get(f"/api/v1/projects/{proj.id}/programme.pdf")
            if r.status_code == 200:
                render(b"".join(r.streaming_content)
                       if getattr(r, "streaming", False) else r.content,
                       f"programme-{proj.code}")
            else:
                self.stderr.write(self.style.WARNING(
                    f"  ! programme pdf: {r.status_code}"))

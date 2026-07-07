"""PDF generation (design §4): WeasyPrint over plain HTML/CSS templates in
pdf_templates/, one per form. Generated at issue and at each subsequent
milestone; stored immutably as an attachment (kind GENERATED_PDF).

Local Windows dev may lack WeasyPrint's GTK libraries; when PDF_REQUIRED is
false the failure is recorded and issuing proceeds (DECISIONS.md D4).
Staging/production set PDF_REQUIRED=1 — there, generation failures block.
"""

import logging
import os
import sys

from django.conf import settings

if sys.platform == "win32":  # point WeasyPrint at a GTK3 runtime (D4)
    # tschoonj build required — its Pango is new enough for WeasyPrint >= 53
    _candidates = [
        os.environ.get("GTK_DLL_DIR"),
        r"C:\Program Files\GTK3-Runtime Win64\bin",
    ]
    for _gtk in _candidates:
        if _gtk and os.path.isdir(_gtk):
            os.environ.setdefault("WEASYPRINT_DLL_DIRECTORIES", _gtk)
            break
from django.core.files.base import ContentFile
from django.template.loader import render_to_string

from .models import Attachment, ManpowerCategory

logger = logging.getLogger(__name__)


def _dpr_context(document, revision):
    site = document.site
    payload = revision.payload or {}
    categories = {
        c.id: c
        for c in ManpowerCategory.objects.filter(list_type="DPR")
    }
    manpower_rows = []
    total = 0
    counts = payload.get("manpower", {}) or {}
    for cat in sorted(categories.values(), key=lambda c: (c.grp, c.sort_order)):
        count = int(counts.get(str(cat.id), 0) or 0)
        total += count
        manpower_rows.append({"grp": cat.grp, "name": cat.name, "count": count})
    photos = []
    for p in document.attachments.filter(kind="PHOTO").order_by("id"):
        try:
            src = f"file:///{p.file.path}"  # filesystem storage
        except NotImplementedError:
            src = p.file.url  # S3/Spaces: (presigned) URL, fetched by the engine
        photos.append({"src": src, "caption": p.caption})
    approvals = list(document.approvals.select_related("actor").all())
    return {
        "doc": document,
        "site": site,
        "payload": payload,
        "manpower_rows": manpower_rows,
        "manpower_total": total,
        "photos": photos,
        "approvals": approvals,
        "rev": revision,
    }


def generate_pdf(document, revision, milestone):
    """Render and archive the PDF for a workflow milestone. Returns the
    Attachment or None when the engine is unavailable locally."""
    template = {"DPR": "dpr.html"}.get(document.doc_type)
    if template is None:
        return None
    html = render_to_string(f"pdf/{template}", _dpr_context(document, revision))
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html, base_url=str(settings.MEDIA_ROOT)).write_pdf()
    except Exception:
        if settings.PDF_REQUIRED:
            raise
        logger.warning("PDF engine unavailable; skipped PDF for %s", document.ref)
        return None
    attachment = Attachment(
        document=document,
        revision=revision,
        kind="GENERATED_PDF",
        file_name=f"{document.ref}-{revision.rev_label}-{milestone}.pdf",
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
    )
    attachment.file.save(
        f"{revision.rev_label}-{milestone}.pdf", ContentFile(pdf_bytes), save=True
    )
    return attachment

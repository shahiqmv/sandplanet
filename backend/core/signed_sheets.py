"""The signed sheet (owner 2026-10-26, HSE forms brief §B).

Planet prints a form with everything it already knows filled in; people
sign it by hand; the site uploads the signed copy and the upload completes
the record. The site's upload is usually phone photos — several pages, one
photo each — so they are joined here into ONE PDF, the copy the record
keeps. A PDF straight off a scanner is taken as it is.
"""
import io

from django.core.files.base import ContentFile

IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic",
               "image/heif")
PDF_TYPES = ("application/pdf",)
MAX_BYTES = 25 * 1024 * 1024          # per file
MAX_FILES = 12
# A printed sheet not uploaded within this long shows on My Tasks.
OVERDUE_HOURS = 48


def _kind(upload):
    ctype = (getattr(upload, "content_type", "") or "").lower()
    name = (getattr(upload, "name", "") or "").lower()
    if ctype in PDF_TYPES or name.endswith(".pdf"):
        return "pdf"
    if ctype in IMAGE_TYPES or name.endswith((".jpg", ".jpeg", ".png",
                                               ".webp", ".heic", ".heif")):
        return "image"
    return None


def join(uploads):
    """(ContentFile, error) — the uploads as one PDF, pages in the order
    given. Photos become one page each, fitted to A4."""
    import fitz
    uploads = [u for u in (uploads or []) if u]
    if not uploads:
        return None, "Choose the signed copy — a PDF or photos of each page."
    if len(uploads) > MAX_FILES:
        return None, f"At most {MAX_FILES} files at a time."
    out = fitz.open()
    for u in uploads:
        kind = _kind(u)
        if kind is None:
            return None, f"{u.name}: upload a PDF or photos (JPG, PNG, HEIC)."
        if u.size > MAX_BYTES:
            return None, f"{u.name} is over 25 MB."
        data = u.read()
        try:
            if kind == "pdf":
                src = fitz.open(stream=data, filetype="pdf")
            else:
                img = fitz.open(stream=data,
                                filetype=(u.name.rsplit(".", 1)[-1] or "jpg"))
                src = fitz.open("pdf", img.convert_to_pdf())
        except Exception:
            return None, f"{u.name} could not be read."
        a4 = fitz.paper_rect("a4")
        for page in src:
            if kind == "pdf":
                out.insert_pdf(src, from_page=page.number, to_page=page.number)
                continue
            # a photo: fit it inside A4, keeping its proportions
            r = page.rect
            scale = min(a4.width / r.width, a4.height / r.height)
            w, h = r.width * scale, r.height * scale
            target = fitz.Rect((a4.width - w) / 2, (a4.height - h) / 2,
                               (a4.width + w) / 2, (a4.height + h) / 2)
            new = out.new_page(width=a4.width, height=a4.height)
            new.show_pdf_page(target, src, page.number)
    buf = io.BytesIO()
    out.save(buf, garbage=3, deflate=True)
    return ContentFile(buf.getvalue(), name="signed.pdf"), None

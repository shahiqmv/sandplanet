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


def logo_src():
    """Company logo for all PDFs: the file uploaded on the Company page
    when present, else the bundled image (extracted from the owner's
    printed stationery)."""
    from django.core.files.storage import default_storage

    for name in ("company/logo.png", "company/logo.jpg"):
        if default_storage.exists(name):
            try:
                return f"file:///{default_storage.path(name)}"  # local disk
            except NotImplementedError:
                return default_storage.url(name)                # Spaces URL
    asset = settings.BASE_DIR / "pdf_templates" / "assets" / "sp-logo.png"
    return f"file:///{asset}"


def mark_src():
    """The ring brandmark used on official-correspondence letterheads."""
    asset = settings.BASE_DIR / "pdf_templates" / "assets" / "sp-mark.svg"
    return f"file:///{asset}"


def company_stamp_bytes():
    """Raw bytes of the uploaded company seal (company/stamp.png|jpg), or None.
    Used to overlay the round company stamp on the IM30 visa form and letters so
    HR needn't print, stamp and scan (owner 2026-08-05)."""
    from django.core.files.storage import default_storage
    for name in ("company/stamp.png", "company/stamp.jpg"):
        if default_storage.exists(name):
            try:
                with default_storage.open(name, "rb") as fh:
                    return fh.read()
            except Exception:
                return None
    return None


def _img_data_uri(raw):
    """A data: URI for raw image bytes (PNG/JPEG), sniffing the mime from the
    file header — WeasyPrint-safe (no filesystem path)."""
    if not raw:
        return ""
    import base64
    mime = "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def company_stamp_data_uri():
    """The company seal as a data: URI for HTML letters, or '' if none uploaded."""
    return _img_data_uri(company_stamp_bytes())


def _font_dir():
    """file:// URL of the bundled-fonts directory. The letter templates point
    their @font-face rules here; if the TTFs aren't present WeasyPrint falls
    back to Helvetica cleanly (see pdf_templates/fonts/README.md)."""
    d = settings.BASE_DIR / "pdf_templates" / "fonts"
    return f"file:///{str(d).replace(chr(92), '/')}"


def company_info():
    """Company identity block shown on every PDF footer (owner request:
    tax info, registration no, address on the reports)."""
    return {
        "legal_name": _param("company_legal_name", "Sand Planet Pvt Ltd"),
        "reg_no": _param("company_reg_no", "C-0059/2015"),
        "tin": _param("company_tin", "ST00042609"),
        "address": _param("company_address", ""),
        "phone": _param("company_phone", ""),
        "email": _param("company_email", ""),
        "website": _param("company_website", "www.sandplanet.mv"),
        "tagline": _param("company_tagline", ""),
        # The person who signs official forms on the company's behalf (the IM30
        # visa form's sponsor block); editable via company parameters.
        "signee_name": _param("company_signee_name", "Ahmed Shahiq"),
        "signee_designation": _param("company_signee_designation",
                                     "Managing Director"),
        "signee_mobile": _param("company_signee_mobile", "7992611"),
        # Bank / remittance details shown on invoices so the client knows where
        # to pay = the primary company bank account (owner 2026-07-24: the bank
        # accounts are now a managed list, used for receipts + PVs too).
        "bank": _primary_bank(),
    }


def _primary_bank():
    """The remittance ('pay to') account printed on client invoices — the
    account flagged primary, else the first active one; falls back to the
    legacy company_bank_* parameters if no account exists yet."""
    from .models import CompanyBankAccount
    b = (CompanyBankAccount.objects.filter(is_active=True, is_primary=True)
         .first()
         or CompanyBankAccount.objects.filter(is_active=True).first())
    if b:
        return {"name": b.bank_name, "account_name": b.account_name,
                "account_no": b.account_no, "currency": b.currency,
                "swift": b.swift, "iban": b.iban, "branch": b.branch}
    return {
        "name": _param("company_bank_name", ""),
        "account_name": _param("company_bank_account_name", ""),
        "account_no": _param("company_bank_account_no", ""),
        "currency": _param("company_bank_currency", ""),
        "swift": _param("company_bank_swift", ""),
        "iban": _param("company_bank_iban", ""),
        "branch": _param("company_bank_branch", ""),
    }


def _pad(rows, minimum, keys):
    """Blank filler rows so the printed grid matches the owner's fixed-row
    form layout."""
    return rows + [{k: "" for k in keys} for _ in range(minimum - len(rows))]


def _dpr_context(document, revision, filters=None):
    site = document.site
    payload = revision.payload or {}
    # A scoped report (owner 2026-07-14): filter WORK DONE to one project
    # and/or trade so a client can get e.g. an MEP-only or per-project DPR off
    # the single site DPR. Site-wide sections (manpower/materials/photos) are
    # hidden in scoped mode until they carry project/trade tags (phase 2).
    filters = filters or {}
    fp = (filters.get("project") or "").strip()
    ft = (filters.get("trade") or "").strip()
    scoped = bool(fp or ft)
    categories = {
        c.id: c
        for c in ManpowerCategory.objects.filter(list_type="DPR")
    }
    staff, labour = [], []
    total = 0
    counts = payload.get("manpower", {}) or {}
    for cat in sorted(categories.values(), key=lambda c: (c.grp, c.sort_order)):
        count = int(counts.get(str(cat.id), 0) or 0)
        total += count
        if count <= 0:
            continue  # only the categories actually on site today (owner)
        (staff if cat.grp == "STAFF" else labour).append((cat.name, count))
    # For a project report, manpower comes from that day's DMA allocation to
    # the project (tasks tagged project + category + workers), not the site-wide
    # DPR count (owner phase 2b). Falls back to an empty section if no DMA.
    manpower_from_dma = False
    if fp:
        from .models import Document
        dma = Document.objects.filter(
            doc_type="DMA", site=site, doc_date=document.doc_date,
            is_void=False).select_related("current_revision").first()
        cat_by_name = {c.name: c for c in categories.values()}
        agg = {}
        if dma and dma.current_revision:
            for t in (dma.current_revision.payload or {}).get("tasks", []):
                if (t.get("project") or "").strip() != fp:
                    continue
                name = (t.get("category") or "").strip() or "Unassigned"
                try:
                    agg[name] = agg.get(name, 0) + int(t.get("workers") or 0)
                except (TypeError, ValueError):
                    pass
        staff, labour, total = [], [], 0
        for name, w in agg.items():
            if w <= 0:
                continue
            total += w
            cat = cat_by_name.get(name)
            grp = cat.grp if cat else "LABOUR"
            (staff if grp == "STAFF" else labour).append((name, w))
        manpower_from_dma = True
    # Staff | Trades/Labour side by side, as on the owner's printed form
    depth = max(len(staff), len(labour), 1)
    staff += [("", "")] * (depth - len(staff))
    labour += [("", "")] * (depth - len(labour))
    manpower_pairs = [(s[0], s[1], t[0], t[1]) for s, t in zip(staff, labour)]

    def norm(row, keys):
        return {k: row.get(k, "") for k in keys}

    work_keys = ("activity", "trade", "location", "progress_today",
                 "progress_todate", "remarks", "project")
    work_rows = []
    for row in payload.get("work_done", []):
        if fp and (row.get("project") or "").strip() != fp:
            continue
        if ft and (row.get("trade") or "").strip().lower() != ft.lower():
            continue
        r = norm(row, work_keys)
        if not r["progress_todate"]:
            r["progress_todate"] = row.get("progress_pct", "")
        # Flag rows the site logged against a project but outside its programme
        r["off_programme"] = bool(r["project"]) and not row.get("activity_id")
        work_rows.append(r)
    # Group project-wise so the client reads each award separately
    # (owner, R8); untagged rows collect under General Works, last.
    titles = {p.code: p.title for p in site.projects.all()}
    grouped, order = {}, []
    for r in work_rows:
        key = (r.get("project") or "").strip()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(r)
    order.sort(key=lambda k: k == "")  # General Works last
    show_group_headers = any(k for k in order)
    work_groups, number = [], 0
    for key in order:
        for r in grouped[key]:
            number += 1
            r["no"] = number
        label = f"{key} — {titles[key]}" if key in titles else \
            (key or "General Works")
        work_groups.append({"label": label, "rows": grouped[key]})
    # No blank filler rows — the report shows only the day's actual work
    # (owner: fixed-grid padding looked empty for a digital report).

    # Materials/machinery/photos are tagged by project (phase 2) — filter them
    # to the project when the report is project-scoped. They are not trade-
    # tagged, so a trade-only report shows the work narrative + site context.
    def keep(row):
        return not fp or (row.get("project") or "").strip() == fp
    machinery_keys = ("item", "nos", "remarks", "project")
    machinery_rows = [norm(r, machinery_keys)
                      for r in payload.get("machinery", []) if keep(r)]
    material_keys = ("material", "unit", "opening", "received", "consumed",
                     "balance", "remarks", "project")
    material_rows = [norm(r, material_keys)
                     for r in payload.get("materials", []) if keep(r)]

    photos = []
    photo_qs = document.attachments.filter(kind="PHOTO").order_by("id")
    if fp:
        photo_qs = photo_qs.filter(project_code=fp)
    for p in photo_qs:
        try:
            src = f"file:///{p.file.path}"  # filesystem storage
        except NotImplementedError:
            src = p.file.url  # S3/Spaces: (presigned) URL, fetched by the engine
        photos.append({"src": src, "caption": p.caption})
    approvals = list(document.approvals.select_related("actor").all())
    scope_bits, scope_pm = [], ""
    if fp:
        scope_bits.append(titles.get(fp, fp))
        proj = site.projects.filter(code=fp).select_related("pm").first()
        if proj and proj.pm_id:
            scope_pm = proj.pm.full_name
    if ft:
        scope_bits.append(ft)
    scope_title = (" · ".join(scope_bits) + " — DAILY PROGRESS REPORT").upper() \
        if scoped else "DAILY PROGRESS REPORT"
    return {
        "doc": document,
        "logo_src": logo_src(),
        "co": company_info(),
        "site": site,
        "payload": payload,
        "form_subline": f"Form No: FRM-PRJ-01  |  Rev: {revision.rev_label}",
        "scoped": scoped,
        "scope_project": bool(fp),
        "scope_title": scope_title,
        "scope_label": " · ".join(scope_bits),
        "scope_pm": scope_pm,
        "work_groups": work_groups,
        "show_group_headers": show_group_headers,
        "manpower_pairs": manpower_pairs,
        "manpower_total": total,
        "manpower_from_dma": manpower_from_dma,
        "machinery_rows": machinery_rows,
        "material_rows": material_rows,
        "photos": photos,
        "photo_date": document.doc_date.strftime("%d.%m.%Y"),
        "approvals": approvals,
        "rev": revision,
    }


def _render_target(document, revision, filters=None):
    """(template, context) for a document's PDF/HTML render, or None if the
    type has no printable form. The single source of truth shared by the PDF
    archiver and the client-portal HTML/PDF viewers."""
    if document.doc_type == "DPR":
        return "dpr.html", _dpr_context(document, revision, filters)
    if document.doc_type == "PO":
        # R2 said no site names on this document. SUPERSEDED (owner
        # 2026-08-13): the supplier needs to know which site the goods are
        # for, so the site code and name now print. Internal references (the
        # PR ref, project codes) stay off it.
        return "po.html", _po_context(document, revision)
    if document.doc_type in LINE_FORMS:
        return "lines_form.html", _lines_context(document, revision)
    if document.doc_type in ("IR", "MAR", "SD", "MS", "TWS", "DMA"):
        from . import pdf_qa

        builder = {"IR": pdf_qa.ir_context, "MAR": pdf_qa.mar_context,
                   "SD": pdf_qa.sd_context, "MS": pdf_qa.ms_context,
                   "TWS": pdf_qa.tws_context,
                   "DMA": pdf_qa.dma_context}[document.doc_type]
        return "qa_form.html", builder(document, revision)
    return None


def document_html(document, revision, filters=None):
    """The rendered report as an HTML string (same template as the PDF), or
    None. Used by the client portal to show a report inline in the browser —
    image src's resolve to Spaces URLs in production."""
    target = _render_target(document, revision, filters)
    if not target:
        return None
    return render_to_string(f"pdf/{target[0]}", target[1])


def _enclosure_divider(label, filename):
    """A one-page PDF separator ('ENCLOSURE — Technical Data Sheet')."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()               # A4
    w = page.rect.width
    NAVY, GREY, MUTE = (0.05, 0.23, 0.36), (0.4, 0.5, 0.6), (0.5, 0.5, 0.5)
    page.insert_textbox(fitz.Rect(50, 300, w - 50, 330), "ENCLOSURE",
                        fontsize=11, align=1, color=GREY)
    page.insert_textbox(fitz.Rect(50, 335, w - 50, 400), label or "Enclosure",
                        fontsize=22, align=1, color=NAVY, fontname="helv")
    if filename:
        page.insert_textbox(fitz.Rect(50, 405, w - 50, 430), filename,
                            fontsize=9, align=1, color=MUTE)
    out = doc.tobytes()
    doc.close()
    return out


# Downsampling budget for merged enclosures — the big lever on file size.
# Oversized embedded images (scanned datasheets, product photos) are shrunk to
# this longest edge (~150 DPI on A4) and re-saved as JPEG; text and vector
# diagrams are untouched, so they stay sharp.
_IMG_MAX_SIDE = 1600
_IMG_JPEG_QUALITY = 65


def _shrink_images(doc):
    """Downsample + recompress oversized embedded images in-place. Best-effort:
    any image that can't be processed is left as-is."""
    import io

    from PIL import Image
    done = set()
    for page in doc:
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in done:
                continue
            done.add(xref)
            try:
                info = doc.extract_image(xref)
                ext = (info.get("ext") or "").lower()
                im = Image.open(io.BytesIO(info["image"]))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                big = max(im.size) > _IMG_MAX_SIDE
                if not big and ext in ("jpg", "jpeg"):
                    continue                        # already small + compressed
                if big:
                    im.thumbnail((_IMG_MAX_SIDE, _IMG_MAX_SIDE))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=_IMG_JPEG_QUALITY,
                        optimize=True)
                page.replace_image(xref, stream=buf.getvalue())
            except Exception:
                continue


# Above this, the thorough compression pass is not attempted. It is a structural
# sanitiser whose cost scales with how complex the content is, not how big the
# file is, and it has no time limit: on MAR-STN-022 — a 56-page vector-heavy
# enclosure — it took 455 SECONDS against a 120-second worker timeout. The
# worker was killed mid-write, so the document was marked ISSUED with no PDF at
# all and nobody was told (owner 2026-08-20).
_CLEAN_MAX_BYTES = 3 * 1024 * 1024


def _compress_merged(doc):
    """Compress the merged submittal, spending time only where it pays.

    The cheap pass took 3.8s and produced 14.0MB; the thorough one took 455s
    for 9.9MB. Four megabytes is not worth a document that never exists, so the
    thorough pass runs only on files small enough for it to finish quickly.
    `_shrink_images` above is the real size lever anyway, and that costs 3s.
    """
    cheap = doc.tobytes(garbage=1, deflate=True, deflate_images=True,
                        deflate_fonts=True)
    if len(cheap) > _CLEAN_MAX_BYTES:
        logger.info("submittal PDF %.1fMB — skipping the deep clean pass",
                    len(cheap) / 1048576)
        return cheap
    try:
        return doc.tobytes(garbage=4, deflate=True, deflate_images=True,
                           deflate_fonts=True, clean=True)
    except Exception:                            # pragma: no cover - defensive
        logger.exception("deep clean failed; keeping the cheap compression")
        return cheap


def compile_enclosures(document, pdf_bytes):
    """Append a submittal's uploaded enclosure files after the form pages — each
    behind a labelled divider — then compress the result (oversized images are
    downsampled + re-JPEGed, the big file-size lever). PDFs merge directly,
    images become a page (Pillow); an unreadable file is replaced by a short
    note rather than failing the whole PDF. Applies to the MAR / Shop Drawing /
    Method Statement submittals. Returns the input unchanged when there are no
    enclosures or PyMuPDF is unavailable."""
    if document.doc_type not in ("MAR", "SD", "MS") or not pdf_bytes:
        return pdf_bytes
    encs = list(document.attachments.filter(kind="ENCLOSURE").order_by("id"))
    if not encs:
        return pdf_bytes
    try:
        import io

        import fitz
        out = fitz.open(stream=pdf_bytes, filetype="pdf")     # the MAR form
        for att in encs:
            label = (att.caption or "Enclosure").strip()
            name = att.file_name or ""
            div = fitz.open(stream=_enclosure_divider(label, name),
                            filetype="pdf")
            out.insert_pdf(div)
            div.close()
            try:
                with att.file.open("rb") as fh:
                    data = fh.read()
                if "pdf" in (att.content_type or "").lower() \
                        or name.lower().endswith(".pdf"):
                    src = fitz.open(stream=data, filetype="pdf")
                else:                                          # image → a page
                    from PIL import Image
                    im = Image.open(io.BytesIO(data)).convert("RGB")
                    buf = io.BytesIO()
                    im.save(buf, format="PDF")
                    src = fitz.open(stream=buf.getvalue(), filetype="pdf")
                out.insert_pdf(src)
                src.close()
            except Exception:
                note = fitz.open(stream=_enclosure_divider(
                    "Could not read this file", name), filetype="pdf")
                out.insert_pdf(note)
                note.close()
        _shrink_images(out)                                    # downsample images
        merged = _compress_merged(out)
        out.close()
        return merged
    except Exception:
        logger.warning("Enclosure compile failed for %s", document.ref)
        return pdf_bytes


def document_pdf_bytes(document, revision, filters=None):
    """The report rendered to PDF bytes on demand (no attachment stored), or
    None when the engine is unavailable. Used by the client 'Download PDF'
    button so the client always gets the live report."""
    html = document_html(document, revision, filters)
    if html is None:
        return None
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html,
                         base_url=str(settings.MEDIA_ROOT)).write_pdf()
        return compile_enclosures(document, pdf_bytes)
    except Exception:
        if settings.PDF_REQUIRED:
            raise
        logger.warning("PDF engine unavailable; skipped PDF for %s",
                       document.ref)
        return None


def generate_pdf(document, revision, milestone):
    """Render and archive the PDF for a workflow milestone. Returns the
    Attachment or None when the engine is unavailable locally."""
    target = _render_target(document, revision)
    if not target:
        return None
    template, context = target
    html = render_to_string(f"pdf/{template}", context)
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html, base_url=str(settings.MEDIA_ROOT)).write_pdf()
        pdf_bytes = compile_enclosures(document, pdf_bytes)
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


# ===== Line-form PDFs: MR / PR / LM / GRN (shared letterhead + table) =====

LINE_FORMS = {
    "MR": {
        "title": "MATERIAL REQUISITION",
        "form_no": "FRM-PRC-01 · R1",
        "columns": [
            ("Item Description", "description", False),
            ("Unit", "unit", False),
            ("Required Qty", "qty_required", True),
            ("Site Stock", "qty_stock", True),
            ("Qty to Order", "qty_to_order", True),
            ("Priority", "priority", False),
            ("Remarks", "remarks", False),
        ],
        "header_keys": [("Planned Loading/Trip", "planned_loading"),
                        ("Trades Covered", "trades_covered"),
                        ("Required On Site By", "required_by")],
        "sigs": [("Prepared By — Site Admin", "SEND"),
                 ("Approved By — Project Manager", "APPROVE"),
                 ("", None)],
        "notes": "Unsigned MRs will be returned. Mark urgent lines with reason. "
                 "One consolidated MR per loading (Instructions sheet).",
    },
    "PR": {
        "title": "PROCUREMENT REQUISITION",
        "form_no": "FRM-PRC-02 · R0",
        "columns": [
            ("Vendor", "vendor", False),
            ("Quotation Ref", "quotation_ref", False),
            ("Terms", "payment_terms", False),
            ("PO / Payment Ref", "_po_or_payment", False),
            ("Cash (MVR)", "amount_cash", True),
            ("Credit (MVR)", "amount_credit", True),
            ("Total (MVR)", "_row_total", True),
        ],
        "header_keys": [("Requested Delivery", "requested_delivery")],
        "sigs": [("Prepared By — Purchasing", "SUBMIT"),
                 ("Approved By — Sr PM / Director, Projects", "APPROVE"),
                 ("Finance — Payment / PO Issued", "PAYMENT_RECORDED")],
    },
    "LM": {
        "title": "LOADING MANIFEST",
        "form_no": "FRM-PRC-03 · R0",
        "columns": [
            ("Item Description", "description", False),
            ("Unit", "unit", False),
            ("Qty Loaded", "qty_loaded", True),
            ("Qty Pending", "qty_pending", True),
            ("Condition / Remarks", "remarks", False),
        ],
        "header_keys": [("Vessel/Boat", "vessel"),
                        ("Departure Point", "departure_point"),
                        ("Expected Arrival", "expected_arrival"),
                        ("Trip/Load No.", "trip_no")],
        "sigs": [("Prepared By — Purchasing", "DEPART"),
                 ("Loaded/Checked By — Boat Crew", None),
                 ("Received At Site By (via GRN)", None)],
    },
    "GRN": {
        "title": "GOODS RECEIVED NOTE",
        "form_no": "FRM-PRC-04 · R1",
        "columns": [
            ("Item Description", "description", False),
            ("Unit", "unit", False),
            ("Qty as per Manifest", "qty_manifest", True),
            ("Qty Received", "qty_received", True),
            ("Shortage/Excess", "_shortage", True),
            ("Condition/Remarks", "remarks", False),
        ],
        "header_keys": [("Manifest Ref", "manifest_ref"),
                        ("Vessel/Boat", "vessel"),
                        ("Date Received", "date_received")],
        "sigs": [("Received/Counted By — Site Admin / Storekeeper", "COUNT"),
                 ("Verified By — Site Engineer / PM", "VERIFY"),
                 ("", None)],
    },
}


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _stamp_for(approvals, action):
    for a in approvals:
        if a.action == action:
            return (f"{a.actor.full_name} — {a.actor_role} — "
                    f"{a.acted_at.strftime('%d/%m/%y %H:%M')} — "
                    f"approved electronically via Sand Planet Project Management App")
    return ""


def _lines_context(document, revision):
    from decimal import Decimal

    config = LINE_FORMS[document.doc_type]
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))

    lines = []
    totals_acc = {field: Decimal("0") for field in config.get("totals", [])}
    for line in revision.lines.select_related("item"):
        cells = []
        for _label, field, is_num in config["columns"]:
            if field == "description":
                value = line.description
            elif field == "_shortage":
                if line.qty_received is None or line.qty_manifest is None:
                    value = ""
                else:
                    value = _fmt(float(line.qty_received - line.qty_manifest))
            elif field == "_row_total":
                value = _fmt(float((line.amount_cash or 0) +
                                   (line.amount_credit or 0)))
            elif field == "_po_or_payment":
                # slip no. for cash, PO no. for credit (owner, 2026-07-08)
                value = line.action_taken or line.po_ref or ""
            else:
                value = getattr(line, field, "") or payload.get(field, "")
                if isinstance(value, Decimal):
                    value = float(value)
                value = _fmt(value)
                if field in totals_acc and getattr(line, field) is not None:
                    totals_acc[field] += getattr(line, field)
            cells.append({"value": value, "num": is_num})
        lines.append({"cells": cells, "is_changed": line.is_changed,
                      "is_free_text": line.item_id is None and
                      document.doc_type in ("MR", "LM", "GRN")})

    totals = None
    if config.get("totals"):
        totals = [{"value": "Grand Total", "num": False}]
        # pad to align with columns: description columns before amounts
        pads = len(config["columns"]) - len(config["totals"]) - 2
        totals += [{"value": "", "num": False}] * max(pads, 0)
        for field in config["totals"]:
            totals.append({"value": _fmt(float(totals_acc[field])), "num": True})
        totals.append({"value": "", "num": False})
        totals = [{"value": "", "num": False}] + totals  # No. column

    header_rows, pair = [], []
    for label, key in config["header_keys"]:
        pair += [label, _fmt(payload.get(key, ""))]
        if len(pair) == 4:
            header_rows.append(pair)
            pair = []
    if pair:
        header_rows.append(pair + ["", ""])

    links = []
    for link in document.links_from.select_related("to_document"):
        links.append(link.to_document.ref)
    for link in document.links_to.select_related("from_document"):
        links.append(link.from_document.ref)

    # PR totals as footer rows aligned under Cash/Credit/Total; GST is
    # applied once, on the grand total only (owner, 2026-07-08)
    tax_footer = None
    if document.doc_type == "PR":
        cash = sum((ln.amount_cash or 0)
                   for ln in revision.lines.all()) or Decimal("0")
        credit = sum((ln.amount_credit or 0)
                     for ln in revision.lines.all()) or Decimal("0")
        untaxed = cash + credit
        gst_rate = Decimal(str(payload.get("tax_rate", _param("gst_rate", 8))))
        gst = (untaxed * gst_rate / 100).quantize(Decimal("0.01"))
        tax_footer = {
            # No. + Vendor + Quotation + Terms + PO/Payment = 5 label cells
            "label_colspan": 5,
            "rows": [
                ["Untaxed Amount", _money(cash), _money(credit),
                 _money(untaxed), False],
                [f"GST ({_fmt(float(gst_rate))}%)", "", "", _money(gst),
                 False],
                ["Total incl. GST", "", "", _money(untaxed + gst), True],
            ],
        }

    return {
        "tax_footer": tax_footer,
        "doc": document,
        "rev": revision,
        "site": document.site,
        "logo_src": logo_src(),
        "co": company_info(),
        "form_title": config["title"],
        "form_subline": f"Form No: {config['form_no'].split(' ·')[0]}  |  "
                        f"Rev: {revision.rev_label}",
        "columns": [{"label": c[0], "num": c[2]} for c in config["columns"]],
        "header_rows": header_rows,
        "links_line": " · ".join(sorted(set(links))),
        "lines": lines,
        "totals": totals,
        "notes": config.get("notes", ""),
        "sig_blocks": [
            {"title": title, "stamp": _stamp_for(approvals, action) if action
             else ""}
            for title, action in config["sigs"]
        ],
    }


# ===== Onboarding letters: Letter of Appointment / Sponsor Letter =====

LETTER_TEMPLATES = {
    "LOA": "letter_appointment.html",
    "SPL": "letter_sponsor.html",
    "AC": "letter_confirmation.html",
    "EA": "letter_employment_agreement.html",
}


def store_generated_pdf(document, name, pdf_bytes):
    """Archive rendered PDF bytes as a GENERATED_PDF attachment on a document."""
    attachment = Attachment(
        document=document,
        revision=document.current_revision,
        kind="GENERATED_PDF",
        file_name=name,
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
    )
    attachment.file.save(name, ContentFile(pdf_bytes), save=True)
    return attachment


def render_onboarding_letter(document, kind, ref, fields, issue_date,
                             stamp_src="", seal_src="", draft=False):
    """Render an onboarding letter (LOA/SPL/AC) from HR-supplied merge fields and
    archive it as a GENERATED_PDF attachment on the case. `stamp_src` (a data
    URI) stamps the signatory's approval; `seal_src` overlays the round company
    seal (both applied on the Letter of Appointment so HR needn't stamp by hand);
    `draft` overlays a DRAFT watermark on an unsigned copy. Returns the
    Attachment (or None when the PDF engine is unavailable locally, per D4)."""
    template = LETTER_TEMPLATES[kind]
    context = {
        "mark_src": mark_src(),
        "font_dir": _font_dir(),
        "co": company_info(),
        "ref": ref,
        "issue_date": issue_date,
        "stamp_src": stamp_src,
        "seal_src": seal_src,
        "draft": draft,
        **fields,
    }
    html = render_to_string(f"pdf/{template}", context)
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html,
                         base_url=str(settings.MEDIA_ROOT)).write_pdf()
    except Exception:
        if settings.PDF_REQUIRED:
            raise
        logger.warning("PDF engine unavailable; skipped letter %s", ref)
        return None
    name = f"{ref}-DRAFT.pdf" if draft else f"{ref}.pdf"
    return store_generated_pdf(document, name, pdf_bytes)


# ===== External Purchase Order (owner format, R2) =====


def _param(key, default):
    from .models import CompanyParameter

    try:
        return CompanyParameter.objects.get(key=key).value
    except CompanyParameter.DoesNotExist:
        return default


def _money(value):
    from decimal import Decimal

    return f"{Decimal(value).quantize(Decimal('0.01')):,}"


def _po_context(document, revision):
    from decimal import Decimal

    payload = revision.payload or {}
    supplier = document.supplier
    site = document.site
    lines = []
    untaxed = Decimal("0")
    for line in revision.lines.select_related("item"):
        amount = line.amount if line.amount is not None else (
            (line.qty_required or 0) * (line.rate or 0)
        )
        untaxed += Decimal(amount or 0)
        lines.append({
            "description": line.description,
            "qty": _fmt(float(line.qty_required)) if line.qty_required else "",
            "unit": line.unit,
            "rate": _money(line.rate or 0),
            "amount": _money(amount or 0),
        })
    # Domestic POs are MVR with GST; an import PO (from an IPR) is in the order
    # currency with no domestic GST — both drive this one template via the
    # payload's `currency` and `tax_rate` (owner 2026-07-16).
    currency = payload.get("currency") or "MVR"
    gst_rate = Decimal(str(payload.get("tax_rate", _param("gst_rate", 8))))
    gst = (untaxed * gst_rate / 100).quantize(Decimal("0.01"))
    # Order-level charges from an import PO (owner 2026-08-06): discount off the
    # goods, supplier freight/handling, and a miscellaneous fee.
    disc = Decimal(str(payload.get("discount") or 0))
    freight = Decimal(str(payload.get("freight") or 0))
    misc = Decimal(str(payload.get("misc_fee") or 0))
    grand = untaxed + gst - disc + freight + misc
    # The stamp names who AUTHORISED the order (the signatory), not the clerk
    # who pressed issue (owner 2026-08-25). A credit PO carries its own
    # AUTHORISE; an import PO inherits it from the IPR it was generated for.
    auth = issued = None
    for a in document.approvals.select_related("actor"):
        if a.action == "AUTHORISE":
            auth = a
        elif a.action == "ISSUE":
            issued = a
    if auth is None and payload.get("ipr_ref"):
        from .models import Document
        ipr = Document.objects.filter(ref=payload["ipr_ref"],
                                      doc_type="IPR").first()
        if ipr:
            for a in ipr.approvals.select_related("actor"):
                if a.action == "AUTHORISE":
                    auth = a
    stamp = auth or issued
    issue_stamp = ""
    if stamp:
        issue_stamp = (
            f"{'Authorised' if auth else 'Issued'} by "
            f"{stamp.actor.full_name} — "
            f"{stamp.acted_at.strftime('%d/%m/%Y %H:%M')} — electronically "
            f"via Sand Planet Project Management App")
    # The date payment falls due under the agreed credit terms — the supplier
    # should see the same date Finance is working to (owner 2026-08-22).
    due = None
    try:
        from .models import Payable
        from .procurement import po_pr_line
        ln = po_pr_line(document)
        if ln is not None:
            pay = Payable.objects.filter(document_line=ln).order_by(
                "-id").first()
            due = pay.due_date if pay else None
    except Exception:                           # pragma: no cover - defensive
        due = None
    return {
        "doc": document,
        "payload": payload,
        "supplier": supplier,
        "payment_due": due,
        # Where the goods are going (owner 2026-08-13, superseding R2).
        "site": {"code": site.code, "name": site.name} if site else None,
        # An amended order must be distinguishable from the one the supplier
        # already has in their hands — R0 is the original, so only later
        # revisions are worth announcing.
        "revision_label": (revision.rev_label
                           if revision.rev_label not in ("R0", "", None)
                           else ""),
        "amendment_reason": payload.get("amendment_reason", ""),
        # The supplier's own reference: their quotation on a domestic PO,
        # their proforma invoice on an import PO (owner 2026-08-25).
        "quote_ref": payload.get("quote_ref") or payload.get("pi_ref") or "",
        "logo_src": logo_src(),
        "lines": lines,
        "currency": currency,
        "show_gst": gst_rate > 0,
        "totals": {
            "untaxed": _money(untaxed),
            "gst_rate": _fmt(float(gst_rate)),
            "gst": _money(gst),
            "has_discount": disc > 0, "discount": _money(disc),
            "has_freight": freight > 0, "freight": _money(freight),
            "has_misc": misc > 0, "misc_fee": _money(misc),
            "total": _money(grand),
        },
        "issue_stamp": issue_stamp,
        "company": company_info(),
    }

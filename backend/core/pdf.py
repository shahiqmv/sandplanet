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


def company_info():
    """Company identity block shown on every PDF footer (owner request:
    tax info, registration no, address on the reports)."""
    return {
        "legal_name": _param("company_legal_name", "Sand Planet Pvt Ltd"),
        "reg_no": _param("company_reg_no", ""),
        "tin": _param("company_tin", ""),
        "address": _param("company_address", ""),
        "phone": _param("company_phone", ""),
        "email": _param("company_email", ""),
        "website": _param("company_website", "www.sandplanet.mv"),
        "tagline": _param("company_tagline", ""),
    }


def _pad(rows, minimum, keys):
    """Blank filler rows so the printed grid matches the owner's fixed-row
    form layout."""
    return rows + [{k: "" for k in keys} for _ in range(minimum - len(rows))]


def _dpr_context(document, revision):
    site = document.site
    payload = revision.payload or {}
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
    # Staff | Trades/Labour side by side, as on the owner's printed form
    depth = max(len(staff), len(labour), 1)
    staff += [("", "")] * (depth - len(staff))
    labour += [("", "")] * (depth - len(labour))
    manpower_pairs = [(s[0], s[1], t[0], t[1]) for s, t in zip(staff, labour)]

    def norm(row, keys):
        return {k: row.get(k, "") for k in keys}

    work_keys = ("activity", "location", "progress_today", "progress_todate",
                 "remarks", "project")
    work_rows = []
    for row in payload.get("work_done", []):
        r = norm(row, work_keys)
        if not r["progress_todate"]:
            r["progress_todate"] = row.get("progress_pct", "")
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

    machinery_keys = ("item", "nos", "remarks")
    machinery_rows = [norm(r, machinery_keys)
                      for r in payload.get("machinery", [])]
    material_keys = ("material", "unit", "opening", "received", "consumed",
                     "balance", "remarks")
    material_rows = [norm(r, material_keys)
                     for r in payload.get("materials", [])]

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
        "logo_src": logo_src(),
        "co": company_info(),
        "site": site,
        "payload": payload,
        "form_subline": f"Form No: FRM-PRJ-01  |  Rev: {revision.rev_label}",
        "work_groups": work_groups,
        "show_group_headers": show_group_headers,
        "manpower_pairs": manpower_pairs,
        "manpower_total": total,
        "machinery_rows": machinery_rows,
        "material_rows": material_rows,
        "photos": photos,
        "photo_date": document.doc_date.strftime("%d.%m.%Y"),
        "approvals": approvals,
        "rev": revision,
    }


def generate_pdf(document, revision, milestone):
    """Render and archive the PDF for a workflow milestone. Returns the
    Attachment or None when the engine is unavailable locally."""
    if document.doc_type == "DPR":
        template, context = "dpr.html", _dpr_context(document, revision)
    elif document.doc_type == "PO":
        # External stationery: no site names or internal refs (owner, R2)
        template, context = "po.html", _po_context(document, revision)
    elif document.doc_type in LINE_FORMS:
        template, context = "lines_form.html", _lines_context(document, revision)
    elif document.doc_type in ("IR", "MAR", "TWS", "DMA"):
        from . import pdf_qa

        builder = {"IR": pdf_qa.ir_context, "MAR": pdf_qa.mar_context,
                   "TWS": pdf_qa.tws_context,
                   "DMA": pdf_qa.dma_context}[document.doc_type]
        template, context = "qa_form.html", builder(document, revision)
    else:
        return None
    html = render_to_string(f"pdf/{template}", context)
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
    gst_rate = Decimal(str(payload.get("tax_rate", _param("gst_rate", 8))))
    gst = (untaxed * gst_rate / 100).quantize(Decimal("0.01"))
    issue_stamp = ""
    for a in document.approvals.select_related("actor"):
        if a.action == "ISSUE":
            issue_stamp = (f"{a.actor.full_name} — "
                           f"{a.acted_at.strftime('%d/%m/%Y %H:%M')} — "
                           f"issued electronically via Sand Planet Site "
                           f"Documents")
    return {
        "doc": document,
        "payload": payload,
        "supplier": supplier,
        "logo_src": logo_src(),
        "lines": lines,
        "totals": {
            "untaxed": _money(untaxed),
            "gst_rate": _fmt(float(gst_rate)),
            "gst": _money(gst),
            "total": _money(untaxed + gst),
        },
        "issue_stamp": issue_stamp,
        "company": company_info(),
    }

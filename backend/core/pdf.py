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
    logo = settings.BASE_DIR / "pdf_templates" / "assets" / "sp-logo.svg"
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
        "logo_src": f"file:///{logo}",
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
    if document.doc_type == "DPR":
        template, context = "dpr.html", _dpr_context(document, revision)
    elif document.doc_type == "PO":
        # External stationery: no site names or internal refs (owner, R2)
        template, context = "po.html", _po_context(document, revision)
    elif document.doc_type in LINE_FORMS:
        template, context = "lines_form.html", _lines_context(document, revision)
    elif document.doc_type in ("IR", "MAR", "TWS"):
        from . import pdf_qa

        builder = {"IR": pdf_qa.ir_context, "MAR": pdf_qa.mar_context,
                   "TWS": pdf_qa.tws_context}[document.doc_type]
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
            ("Payment Terms", "payment_terms", False),
            ("Amount Cash/Bank (MVR)", "amount_cash", True),
            ("Amount Credit (MVR)", "amount_credit", True),
            ("PO Ref", "po_ref", False),
            ("Payment (Slip/Voucher)", "action_taken", False),
        ],
        "header_keys": [("Requested Delivery", "requested_delivery"),
                        ("Action Taken", "action_taken")],
        "sigs": [("Prepared By — Purchasing", "SUBMIT"),
                 ("Approved By — Sr PM / Director, Projects", "APPROVE"),
                 ("Finance — Payment / PO Issued", "PAYMENT_RECORDED")],
        "totals": ["amount_cash", "amount_credit"],
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
                    f"approved electronically via Sand Planet Site Documents")
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

    # GST summary on the PR (owner request; rate = gst_rate parameter)
    tax_summary = None
    if document.doc_type == "PR":
        untaxed = totals_acc.get("amount_cash", Decimal("0")) + \
                  totals_acc.get("amount_credit", Decimal("0"))
        gst_rate = Decimal(str(payload.get("tax_rate", _param("gst_rate", 8))))
        gst = (untaxed * gst_rate / 100).quantize(Decimal("0.01"))
        tax_summary = [
            ("Untaxed Amount", _money(untaxed)),
            (f"GST ({_fmt(float(gst_rate))}%)", _money(gst)),
            ("Total incl. GST", _money(untaxed + gst)),
        ]

    logo = settings.BASE_DIR / "pdf_templates" / "assets" / "sp-logo.svg"
    return {
        "tax_summary": tax_summary,
        "doc": document,
        "rev": revision,
        "site": document.site,
        "logo_src": f"file:///{logo}",
        "form_title": config["title"],
        "form_subline": f"{config['form_no']} · Rev {revision.rev_label}",
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
    logo = settings.BASE_DIR / "pdf_templates" / "assets" / "sp-logo.svg"
    return {
        "doc": document,
        "payload": payload,
        "supplier": supplier,
        "logo_src": f"file:///{logo}",
        "lines": lines,
        "totals": {
            "untaxed": _money(untaxed),
            "gst_rate": _fmt(float(gst_rate)),
            "gst": _money(gst),
            "total": _money(untaxed + gst),
        },
        "issue_stamp": issue_stamp,
        "company": {
            "legal_name": _param("company_legal_name", "Sand Planet Pvt Ltd"),
            "tin": _param("company_tin", ""),
            "address": _param("company_address", ""),
            "email": _param("company_email", ""),
            "website": _param("company_website", ""),
            "tagline": _param("company_tagline", ""),
        },
    }

"""Manual client invoices — tax invoices recorded directly in Planet, outside
the progress-claim flow, so a project that came onto the system mid-flight has
complete receivables without rebuilding its BOQ and past claims.

Two origins (see models.ManualInvoice):
  * HISTORICAL — an invoice raised the old way before Planet: back-dated to its
    real date, the client's own invoice number, record-only (optionally with
    the actual invoice PDF attached). Nothing is printed.
  * ISSUED — an invoice raised on Planet for an off-system claim: a Planet
    invoice number and a generated tax-invoice PDF.

Either way it feeds the same receivables aging / statement / receipts as a
claim invoice (see receivables.py). Contracts are USD. Void, never delete, so
the number is never silently reused.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from .audit import audit
from .commercial import (_employer, _fmt_money, _next_invoice_no, _q2,
                         amount_in_words)
from .models import ManualInvoice, Project

ZERO = Decimal("0")

CREATE_ROLES = ("QS", "FINANCE", "DIRECTOR", "ADMIN")


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_lines(raw):
    """Coerce incoming line dicts → clean line records. A line's amount is
    qty × unit_price when both are given, else the amount typed directly."""
    out = []
    for r in (raw or []):
        desc = str(r.get("description") or "").strip()[:300]
        qty = _dec(r.get("quantity"))
        unit = _dec(r.get("unit_price"))
        amt = _dec(r.get("amount"))
        if amt is None and qty is not None and unit is not None:
            amt = qty * unit
        if not desc or amt is None:
            continue
        out.append({"description": desc, "quantity": qty,
                    "unit_price": unit, "amount": _q2(amt)})
    return out


def create_manual_invoice(data, actor):
    """Record a manual invoice from one or more line items. Net = Σ lines, GST
    = net × gst_pct (auto), total = net + GST. HISTORICAL carries the client's
    own number; ISSUED gets the next Planet INV-. Returns (invoice, error)."""
    from django.db import transaction

    from .models import ManualInvoiceLine

    if actor.role not in CREATE_ROLES:
        return None, "You can't record client invoices."
    project = Project.objects.filter(pk=data.get("project_id")).first()
    if project is None:
        return None, "Choose the project this invoice belongs to."
    origin = data.get("origin")
    if origin not in ("HISTORICAL", "ISSUED"):
        return None, "Choose whether this is a historical or an issued invoice."
    if not data.get("invoice_date"):
        return None, "Enter the invoice date."
    lines = _parse_lines(data.get("lines"))
    if not lines:
        return None, ("Add at least one line item — a description and an "
                      "amount.")
    net = _q2(sum((ln["amount"] for ln in lines), ZERO))
    if net <= ZERO:
        return None, "The invoice net must be more than zero."
    gst_pct = _dec(data.get("gst_pct"))
    if gst_pct is None:
        gst_pct = Decimal("8")           # local GST default
    gst = _q2(net * gst_pct / Decimal("100"))
    amount = _q2(net + gst)
    if origin == "ISSUED":
        invoice_no = _next_invoice_no()
    else:
        invoice_no = (data.get("invoice_no") or "").strip()
        if not invoice_no:
            return None, "Enter the client's invoice number."
    # A single-line invoice titles itself from that line unless a summary is set.
    description = (data.get("description") or "").strip()[:300]
    if not description and len(lines) == 1:
        description = lines[0]["description"]
    with transaction.atomic():
        mi = ManualInvoice(
            project=project, origin=origin, invoice_no=invoice_no,
            invoice_date=data["invoice_date"],
            due_date=data.get("due_date") or None,
            currency=(data.get("currency") or "USD")[:3].upper(),
            gst_pct=gst_pct, net_amount=net, gst_amount=gst, amount=amount,
            description=description,
            note=(data.get("note") or "").strip(), created_by=actor)
        att = data.get("attachment")
        if att is not None:
            mi.attachment = att
        mi.save()
        ManualInvoiceLine.objects.bulk_create([
            ManualInvoiceLine(
                invoice=mi, sort_order=i * 10, description=ln["description"],
                quantity=ln["quantity"], unit_price=ln["unit_price"],
                amount=ln["amount"])
            for i, ln in enumerate(lines, 1)])
    audit("project", project.id, "MANUAL_INVOICE_CREATED", actor=actor,
          detail={"invoice_no": invoice_no, "origin": origin,
                  "lines": len(lines), "amount": str(mi.amount)})
    return mi, None


def void_manual_invoice(mi, actor):
    """Void an invoice recorded in error. Blocked while receipts are settled
    against it — those must be removed first (never orphan client cash)."""
    if actor.role not in CREATE_ROLES:
        return "You can't void client invoices."
    if mi.is_void:
        return "This invoice is already void."
    if mi.receipts.exists():
        return ("Receipts are recorded against this invoice — remove them "
                "before voiding it.")
    mi.is_void = True
    mi.save(update_fields=["is_void", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_VOIDED", actor=actor,
          detail={"invoice_no": mi.invoice_no})
    return None


def received_for(mi):
    return _q2(mi.receipts.aggregate(s=Sum("amount"))["s"] or ZERO)


def manual_invoice_dict(mi):
    got = received_for(mi)
    amt = _q2(mi.amount)
    return {
        "id": mi.id, "origin": mi.origin, "invoice_no": mi.invoice_no,
        "project_id": mi.project_id, "project_code": mi.project.code,
        "project_title": mi.project.title, "site_id": mi.project.site_id,
        "invoice_date": mi.invoice_date, "due_date": mi.effective_due_date,
        "currency": mi.currency, "net_amount": mi.net_amount,
        "gst_pct": mi.gst_pct, "gst_amount": mi.gst_amount, "amount": amt,
        "received": got, "outstanding": amt - got,
        "description": mi.description, "note": mi.note,
        "lines": [{"id": ln.id, "description": ln.description,
                   "quantity": ln.quantity, "unit_price": ln.unit_price,
                   "amount": ln.amount} for ln in mi.lines.all()],
        "has_attachment": bool(mi.attachment),
        "can_pdf": mi.origin == "ISSUED",
        "is_void": mi.is_void,
        "created_by": mi.created_by.full_name if mi.created_by_id else "",
        "created_at": mi.created_at,
    }


def list_invoices(site_id=None, include_void=False):
    qs = (ManualInvoice.objects.select_related("project", "project__site")
          .prefetch_related("lines").order_by("-invoice_date", "-id"))
    if site_id is not None:
        qs = qs.filter(project__site_id=site_id)
    if not include_void:
        qs = qs.filter(is_void=False)
    return [manual_invoice_dict(mi) for mi in qs]


def manual_invoice_pdf_context(mi):
    """Context for the ISSUED tax-invoice PDF (branded like the claim invoice)."""
    from .pdf import company_info, logo_src
    net = _q2(mi.net_amount or ZERO)
    gst = _q2(mi.gst_amount or ZERO)
    amount = _q2(mi.amount)
    lines = [{
        "description": ln.description,
        "quantity": (f"{ln.quantity:g}" if ln.quantity is not None else ""),
        "unit_price": (_fmt_money(ln.unit_price, 2)
                       if ln.unit_price is not None else ""),
        "amount_f": _fmt_money(ln.amount, 2),
    } for ln in mi.lines.all()]
    return {
        "logo_src": logo_src(), "co": company_info(),
        "employer": _employer(mi.project), "mi": mi, "project": mi.project,
        "currency": mi.currency, "lines": lines,
        "gst_pct": f"{mi.gst_pct:g}",
        "net_f": _fmt_money(net, 2), "gst_f": _fmt_money(gst, 2),
        "amount_f": _fmt_money(amount, 2),
        "amount_words": amount_in_words(amount, mi.currency),
    }

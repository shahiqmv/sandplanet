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


def create_manual_invoice(data, actor):
    """Record a manual invoice. HISTORICAL carries the client's own number;
    ISSUED gets the next Planet INV- number. Returns (invoice, error)."""
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
    net = _dec(data.get("net_amount"))
    gst = _dec(data.get("gst_amount"))
    amount = _dec(data.get("amount"))
    # If only the net + GST are given, the total builds up from them.
    if amount is None and net is not None:
        amount = net + (gst or ZERO)
    if amount is None or amount <= ZERO:
        return None, "Enter the invoice amount."
    if origin == "ISSUED":
        invoice_no = _next_invoice_no()
    else:
        invoice_no = (data.get("invoice_no") or "").strip()
        if not invoice_no:
            return None, "Enter the client's invoice number."
    mi = ManualInvoice(
        project=project, origin=origin, invoice_no=invoice_no,
        invoice_date=data["invoice_date"], due_date=data.get("due_date") or None,
        currency=(data.get("currency") or "USD")[:3].upper(),
        net_amount=net, gst_amount=gst, amount=_q2(amount),
        description=(data.get("description") or "").strip()[:300],
        note=(data.get("note") or "").strip(), created_by=actor)
    att = data.get("attachment")
    if att is not None:
        mi.attachment = att
    mi.save()
    audit("project", project.id, "MANUAL_INVOICE_CREATED", actor=actor,
          detail={"invoice_no": invoice_no, "origin": origin,
                  "amount": str(mi.amount)})
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
        "gst_amount": mi.gst_amount, "amount": amt,
        "received": got, "outstanding": amt - got,
        "description": mi.description, "note": mi.note,
        "has_attachment": bool(mi.attachment),
        "can_pdf": mi.origin == "ISSUED",
        "is_void": mi.is_void,
        "created_by": mi.created_by.full_name if mi.created_by_id else "",
        "created_at": mi.created_at,
    }


def list_invoices(site_id=None, include_void=False):
    qs = (ManualInvoice.objects.select_related("project", "project__site")
          .order_by("-invoice_date", "-id"))
    if site_id is not None:
        qs = qs.filter(project__site_id=site_id)
    if not include_void:
        qs = qs.filter(is_void=False)
    return [manual_invoice_dict(mi) for mi in qs]


def manual_invoice_pdf_context(mi):
    """Context for the ISSUED tax-invoice PDF (branded like the claim invoice)."""
    from .pdf import company_info, logo_src
    net = mi.net_amount
    gst = mi.gst_amount
    amount = _q2(mi.amount)
    return {
        "logo_src": logo_src(), "co": company_info(),
        "employer": _employer(mi.project), "mi": mi, "project": mi.project,
        "currency": mi.currency,
        "has_breakdown": net is not None,
        "net_f": _fmt_money(net or ZERO, 2), "gst_f": _fmt_money(gst or ZERO, 2),
        "amount_f": _fmt_money(amount, 2),
        "amount_words": amount_in_words(amount, mi.currency),
    }

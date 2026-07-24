"""Official receipts — the finance-issued acknowledgement of money received
from a client, allocated across one or more tax invoices (progress claims).

A receipt carries a running number (OR-####), the receipt date, how the money
came in (TT / cheque / cash …) with its reference, and the company bank account
credited. Its allocation lines are ClientReceipt rows (so the receivables aging
and per-claim settlement keep working unchanged): one line for a part payment,
several for a lump remittance settling multiple invoices.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .audit import audit
from .commercial import _q2, amount_in_words, claim_valuation, set_claim_status
from .models import (ClientReceipt, CompanyBankAccount, OfficialReceipt,
                     ProgressClaim, Site)

ZERO = Decimal("0")


def _dec(v):
    try:
        return Decimal(str(v))
    except Exception:
        return None


def next_receipt_no():
    n = OfficialReceipt.objects.count() + 1
    return f"OR-{n:04d}"


def _invoice_due(claim):
    return _q2(claim_valuation(claim)["waterfall"]["net_to_pay"])


def _received(claim, exclude_or=None):
    qs = ClientReceipt.objects.filter(claim=claim)
    if exclude_or is not None:
        qs = qs.exclude(official_receipt=exclude_or)
    return _q2(qs.aggregate(s=Sum("amount"))["s"] or ZERO)


def outstanding(claim):
    """What is still owed on an invoice = its value less all money received."""
    return _invoice_due(claim) - _received(claim)


def _settle(claim, actor):
    """Mark a certified claim Paid once fully received; revert a Paid claim to
    Certified if a deleted receipt leaves it short."""
    due = _invoice_due(claim)
    got = _received(claim)
    if claim.status == "CERTIFIED" and got >= due and due > ZERO:
        set_claim_status(claim, "PAID", actor)
    elif claim.status == "PAID" and got < due:
        claim.status = "CERTIFIED"
        claim.save(update_fields=["status"])


@transaction.atomic
def create_official_receipt(data, actor):
    """Create an official receipt from remittance details + a set of invoice
    allocations. Returns (receipt, error)."""
    site = Site.objects.filter(pk=data.get("site")).first()
    if site is None:
        return None, "Choose the client the payment is from."
    if not data.get("receipt_date"):
        return None, "Enter the receipt date."
    method = data.get("method") or "TT"
    if method not in OfficialReceipt.Method.values:
        return None, "Choose how the payment was received."
    bank = None
    if data.get("bank_account"):
        bank = CompanyBankAccount.objects.filter(
            pk=data["bank_account"]).first()
        if bank is None:
            return None, "That bank account no longer exists."

    rows = data.get("allocations") or []
    parsed = []
    for row in rows:
        amt = _dec(row.get("amount"))
        if amt is None or amt <= ZERO:
            continue                       # skip blank / zero lines
        claim = ProgressClaim.objects.filter(
            pk=row.get("claim_id"), project__site=site,
            status__in=["CERTIFIED", "PAID"]).exclude(invoice_no="").first()
        if claim is None:
            return None, "An invoice on this receipt isn't a certified " \
                         "invoice for this client."
        due = outstanding(claim)
        if amt > due + Decimal("0.01"):
            return None, (f"{amt:,.2f} exceeds the {due:,.2f} outstanding on "
                          f"invoice {claim.invoice_no}.")
        parsed.append((claim, _q2(amt)))
    if not parsed:
        return None, "Add at least one invoice and amount to receipt."

    receipt = OfficialReceipt.objects.create(
        site=site, receipt_no=next_receipt_no(),
        receipt_date=data["receipt_date"], method=method,
        reference=data.get("reference") or "", bank_account=bank,
        note=data.get("note") or "", recorded_by=actor)
    for claim, amt in parsed:
        ClientReceipt.objects.create(
            project=claim.project, claim=claim, official_receipt=receipt,
            amount=amt, received_on=receipt.receipt_date,
            reference=receipt.reference, recorded_by=actor)
    for claim, _ in parsed:
        _settle(claim, actor)
    audit("site", site.id, "OFFICIAL_RECEIPT", actor=actor,
          detail={"receipt_no": receipt.receipt_no,
                  "amount": str(receipt.total)})
    return receipt, None


@transaction.atomic
def delete_official_receipt(receipt, actor):
    claims = [r.claim for r in receipt.receipts.all() if r.claim]
    no = receipt.receipt_no
    receipt.receipts.all().delete()
    receipt.delete()
    for claim in claims:
        _settle(claim, actor)
    audit("site", 0, "OFFICIAL_RECEIPT_DELETED", actor=actor,
          detail={"receipt_no": no})
    return None


# ---- serialisation -------------------------------------------------------

def receipt_dict(receipt):
    lines = []
    for r in receipt.receipts.select_related("claim", "project").all():
        c = r.claim
        lines.append({
            "id": r.id, "amount": r.amount,
            "invoice_no": c.invoice_no if c else "",
            "claim_ref": c.ref if c else "",
            "project_code": r.project.code,
            "invoice_amount": _invoice_due(c) if c else None,
        })
    ba = receipt.bank_account
    return {
        "id": receipt.id, "receipt_no": receipt.receipt_no,
        "receipt_date": receipt.receipt_date,
        "method": receipt.method, "method_label": receipt.get_method_display(),
        "reference": receipt.reference, "note": receipt.note,
        "site_id": receipt.site_id, "site_code": receipt.site.code,
        "client": receipt.site.client_name or receipt.site.name,
        "bank_account": ba.label if ba else "",
        "currency": receipt.currency, "total": receipt.total,
        "lines": lines,
        "recorded_by": (receipt.recorded_by.full_name
                        if receipt.recorded_by else ""),
    }


def list_receipts(site_id=None):
    qs = OfficialReceipt.objects.select_related("site", "bank_account") \
        .prefetch_related("receipts__claim", "receipts__project")
    if site_id is not None:
        qs = qs.filter(site_id=site_id)
    return [receipt_dict(r) for r in qs]


def receipt_pdf_context(receipt):
    from .pdf import company_info, logo_src
    site = receipt.site
    d = receipt_dict(receipt)
    ba = receipt.bank_account
    inv_list = ", ".join(l["invoice_no"] for l in d["lines"] if l["invoice_no"])
    return {
        "logo_src": logo_src(), "co": company_info(),
        "receipt": receipt, "r": d, "currency": receipt.currency,
        "payer": {
            "name": site.client_name or site.name,
            "address": site.client_address,
            "contact": site.client_contact,
            "designation": site.client_designation,
        },
        "bank_account": {
            "label": ba.label, "bank_name": ba.bank_name,
            "account_name": ba.account_name, "account_no": ba.account_no,
            "currency": ba.currency,
        } if ba else None,
        "invoice_list": inv_list,
        "amount_words": amount_in_words(receipt.total, receipt.currency),
    }

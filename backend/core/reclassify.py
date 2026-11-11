"""Putting a head-office payment where it belongs (owner 2026-11-10).

The head-office site showed USD 1.9m of "cost" for 2026. Almost none of it
was: USD 927k was dollars bought for rufiyaa (a contra — money in one
currency for money in another), 463k was cheques honouring purchase orders
the sites had already booked as cost when the Signatory signed them, 163k
was GST handed on to MIRA, 88k were creditors from before the books. The
payment request was the wrong instrument for every one of those, and once a
request is approved nothing let Finance say so.

Two actions, both reversing the ledger rather than editing it:

* reclassify — the request becomes a currency exchange, a tax payment, a
  prior-period creditor (pool postings every cost report ignores), or stays
  a cost under another head, site or project. Its postings are reversed and
  re-posted on the original dates.
* apply to payables — the request paid the vendor's payables (the cheque
  against the statement). Its own postings are reversed, the payables it
  paid settle with the request as the reference, and the Paid leg posts
  against the order at the site, where the cost already sits.

Both are Finance's, audited with a reason.
"""
import re
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import costing, fx
from .audit import audit
from .models import CostHead, CostPosting, Document, Payable, Project, Site
from .vouchers import _live, awaiting_payables

NON_COST = ("CURRENCY_EXCHANGE", "GST_SETTLEMENT", "PRIOR_PERIOD")
BOOKINGS = ("COST",) + NON_COST
LIVE = ("AUTHORISED", "PART_PAID", "PAID")


def _why_fixed(doc):
    """Why a request cannot be reclassified: it posts by a rule of its own,
    or it never posted."""
    if doc.doc_type != "PYR" or not hasattr(doc, "payment_request"):
        return "Only a payment request is reclassified."
    pr = doc.payment_request
    if doc.is_void or doc.status not in LIVE:
        return ("Only an authorised or paid request is reclassified — "
                "before that, return it and raise it again.")
    if pr.payment_type in ("PETTY_CASH_REPLENISH", "SALARY_ADVANCE",
                           "ADVANCE"):
        return "An advance or a petty-cash float posts by its own rule."
    if pr.is_capitalized or pr.vehicle_id or pr.subcontract_agreement_id:
        return ("A fleet cost, an import charge or a subcontract payment "
                "posts by its own rule.")
    if doc.salary_advances.exists():
        return "A salary advance posts by its own rule."
    if pr.booking == "PAYABLE_SETTLEMENT":
        return "This request already settles payables."
    return None


def _originals(doc):
    """The request's own live postings: originals not yet reversed."""
    reversed_ids = set(CostPosting.objects.filter(
        reversal_of__document=doc).values_list("reversal_of_id", flat=True))
    return [p for p in CostPosting.objects.filter(
        document=doc, reversal_of__isnull=True).order_by("id")
        if p.id not in reversed_ids]


def reclassify(doc, actor, *, booking=None, cost_head=None, site=None,
               project=None, shared_cost=None, reason=""):
    """Change what a request is, or where it belongs. Returns an error
    string or None."""
    why = _why_fixed(doc)
    if why:
        return why
    if not (reason or "").strip():
        return "Say why — this moves money between the company's books."
    pr = doc.payment_request
    booking = (booking or pr.booking).upper()
    if booking not in BOOKINGS:
        return "That kind of payment is not one a request can be."
    site = site or doc.site
    if booking != "COST":
        if not site.is_head_office:
            return ("A currency exchange, a tax payment or a prior-period "
                    "creditor is head office's, not a site's.")
        head = costing.by_code(costing.BOOKING_HEADS[booking])
        if head is None:
            return "The pool head for that kind of payment is missing."
        project = None
    else:
        head = cost_head or pr.cost_head
        if head.is_pool or head.trading or head.rental:
            return "That cost head is not a project head."
    if project is not None and project.site_id != site.id:
        return "That project is not at that site."
    before = {"booking": pr.booking, "cost_head": pr.cost_head.name,
              "site": doc.site.code,
              "project": doc.project.code if doc.project_id else None,
              "shared_cost": doc.shared_cost}
    after = {"booking": booking, "cost_head": head.name, "site": site.code,
             "project": project.code if project is not None else None,
             "shared_cost": bool(shared_cost) if shared_cost is not None
             else (doc.shared_cost if booking == "COST" else False)}
    if before == after:
        return "Nothing would change."
    pool = booking in NON_COST
    with transaction.atomic():
        for p in _originals(doc):
            costing.post(site=p.site, cost_head=p.cost_head, state=p.state,
                         source=p.source, amount=-p.amount,
                         currency=p.currency, document=doc,
                         is_stock_pool=p.is_stock_pool, reversal_of=p,
                         actor=actor, posted_on=p.posted_on)
            costing.post(site=site, cost_head=head, state=p.state,
                         source=p.source, amount=p.amount,
                         currency=p.currency, document=doc,
                         is_stock_pool=pool, voucher_line=p.voucher_line,
                         actor=actor, posted_on=p.posted_on)
        pr.booking, pr.cost_head = booking, head
        pr.save(update_fields=["booking", "cost_head"])
        doc.site, doc.project = site, project
        doc.shared_cost = after["shared_cost"]
        doc.save(update_fields=["site", "project", "shared_cost",
                                "updated_at"])
    audit("document", doc.id, "PYR_RECLASSIFIED", actor=actor,
          detail={"ref": doc.ref, "from": before, "to": after,
                  "reason": reason.strip()})
    return None


# ---- applying a request to payables ----------------------------------------

def _tokens(text):
    stop = {"pvt", "ltd", "private", "limited", "plc", "co", "company",
            "the", "and", "maldives", "hardware", "investment", "holdings",
            "express", "group", "services"}
    return {t for t in re.split(r"[^a-z0-9&]+", (text or "").lower())
            if len(t) > 2 and t not in stop}


def vendor_matches(payee, vendor):
    """Does the payee on a request look like this payable's vendor? Sonee
    Hardware Pvt Ltd and SONEE HARDWARE are one vendor; so are Scalling
    Holdings and Scaling Holdings Pvt Ltd (a shared token of five letters
    or a shared prefix)."""
    a, b = _tokens(payee), _tokens(vendor)
    if not a or not b:
        return False
    if a & b:
        return True
    return any(x[:5] == y[:5] and len(x) >= 5 and len(y) >= 5
               for x in a for y in b)


def payable_candidates(doc):
    """Outstanding order payables a request could have paid: not on any
    voucher, in the request's currency, the vendor's own first."""
    pr = doc.payment_request
    on_voucher = set(_live(source_payable__isnull=False)
                     .values_list("source_payable_id", flat=True))
    out = []
    for p in (awaiting_payables().filter(document__doc_type="PR",
                                         currency=pr.currency)
              .select_related("document", "document_line", "site")):
        if p.id in on_voucher:
            continue
        out.append({
            "payable_id": p.id, "vendor": p.vendor, "site": p.site.code,
            "ref": p.document.ref,
            "po_ref": (p.document_line.po_ref or "").strip()
            if p.document_line_id else "",
            "amount": p.amount, "currency": p.currency,
            "due_date": p.due_date, "terms": p.terms,
            "vendor_match": vendor_matches(pr.payee, p.vendor)})
    out.sort(key=lambda r: (not r["vendor_match"], r["due_date"] or date.max,
                            r["payable_id"]))
    return out


def apply_to_payables(doc, payable_ids, actor, reason=""):
    """The request paid these payables. Returns (summary, error)."""
    why = _why_fixed(doc)
    if why:
        return None, why
    if not (reason or "").strip():
        return None, "Say why — this moves money between the company's books."
    pr = doc.payment_request
    wanted = [int(i) for i in (payable_ids or [])]
    if not wanted:
        return None, "Pick the payables this payment settled."
    candidates = {c["payable_id"]: c for c in payable_candidates(doc)}
    missing = [i for i in wanted if i not in candidates]
    if missing:
        return None, ("A payable picked is not open, is on a voucher, or is "
                      "in another currency.")
    total = sum((candidates[i]["amount"] for i in wanted), Decimal("0"))
    paid = pr.amount_paid if pr.amount_paid is not None \
        else pr.amount_requested
    if total > paid + Decimal("0.01"):
        return None, (f"Those payables come to {pr.currency} {total:,.2f}, "
                      f"more than the {pr.currency} {paid:,.2f} this "
                      "request paid.")
    from .procurement import post_pr_vendor_paid
    on = pr.paid_date or timezone.localdate()
    settled = []
    with transaction.atomic():
        for p in _originals(doc):
            costing.post(site=p.site, cost_head=p.cost_head, state=p.state,
                         source=p.source, amount=-p.amount,
                         currency=p.currency, document=doc,
                         is_stock_pool=p.is_stock_pool, reversal_of=p,
                         actor=actor, posted_on=p.posted_on)
        for pid in wanted:
            p = Payable.objects.select_for_update().get(pk=pid)
            if p.status != "OUTSTANDING":
                transaction.set_rollback(True)
                return None, f"{p.vendor}'s payable is no longer open."
            post_pr_vendor_paid(p.document, p.document_line, actor, doc.ref,
                                side="credit", posted_on=on)
            p.refresh_from_db()
            p.settled_by_request = doc
            p.save(update_fields=["settled_by_request"])
            settled.append({"payable_id": p.id, "vendor": p.vendor,
                            "ref": p.document.ref, "site": p.site.code,
                            "amount": str(p.amount)})
        pr.booking = "PAYABLE_SETTLEMENT"
        pr.save(update_fields=["booking"])
    summary = {"ref": doc.ref, "payables": settled, "total": str(total),
               "paid": str(paid), "difference": str(paid - total),
               "currency": pr.currency}
    audit("document", doc.id, "PYR_APPLIED_TO_PAYABLES", actor=actor,
          detail={**summary, "reason": reason.strip()})
    return summary, None


# ---- the backlog -----------------------------------------------------------

_CURRENCY = re.compile(r"dollar|usd sell|\bds[ -]|exchange|forex|\bfx\b")
_GST = re.compile(r"\bmira\b|\bgst\b")
_PRIOR = re.compile(r"\b2025\b|untill|until 30|up to 04-08|opening balance")
_DUES = re.compile(r"outstanding|dues|due bill|due cheque|cheque|statement"
                   r"|\bsoa\b|invoices|balance payment")


def suggest(pr, doc, vendors):
    """What a head-office request most likely is, from its own words:
    ("CURRENCY_EXCHANGE" | "GST_SETTLEMENT" | "PRIOR_PERIOD" | "PAYABLES"
    | ""), with the matching open payables for PAYABLES."""
    text = f"{pr.payee} {pr.purpose}".lower()
    if _CURRENCY.search(text):
        return "CURRENCY_EXCHANGE", []
    if _GST.search(text):
        return "GST_SETTLEMENT", []
    matches = [v for v in vendors if v["currency"] == pr.currency
               and vendor_matches(pr.payee, v["vendor"])]
    if _PRIOR.search(text):
        return "PRIOR_PERIOD", matches
    if matches or _DUES.search(text):
        return "PAYABLES", matches
    return "", []


def backlog():
    """Head-office requests still booked as cost, each with a suggestion."""
    rate = fx.usd_rate()
    vendors = [{"payable_id": p.id, "vendor": p.vendor, "amount": p.amount,
                "currency": p.currency, "site": p.site.code}
               for p in awaiting_payables().filter(document__doc_type="PR")
               .select_related("site")]
    rows = []
    qs = (Document.objects.filter(doc_type="PYR", status__in=LIVE,
                                  is_void=False, site__is_head_office=True,
                                  payment_request__booking="COST")
          .select_related("payment_request__cost_head", "site", "project")
          .order_by("doc_date", "id"))
    for doc in qs:
        if _why_fixed(doc):
            continue
        pr = doc.payment_request
        kind, matches = suggest(pr, doc, vendors)
        rows.append({
            "ref": doc.ref, "date": doc.doc_date, "status": doc.status,
            "payee": pr.payee, "purpose": pr.purpose,
            "amount": pr.amount_requested, "currency": pr.currency,
            "usd": fx.to_usd(pr.amount_requested, pr.currency, rate)
            .quantize(Decimal("0.01")),
            "cost_head": pr.cost_head.name,
            "project": doc.project.code if doc.project_id else None,
            "suggestion": kind,
            "open_payables": len(matches),
            "open_payables_total": sum((m["amount"] for m in matches),
                                       Decimal("0")),
        })
    return rows


def heads_for_picker():
    return [{"id": h.id, "name": h.name} for h in CostHead.objects.filter(
        is_active=True, is_pool=False, trading=False, rental=False)
        .order_by("sort_order", "name")]


def sites_for_picker():
    return [{"id": s.id, "code": s.code, "name": s.name,
             "is_head_office": s.is_head_office}
            for s in Site.objects.order_by("code")]


def projects_for(site):
    return [{"id": p.id, "code": p.code, "title": p.title}
            for p in Project.objects.filter(site=site).order_by("code")]

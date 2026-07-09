"""Petty cash — imprest system (§6B, M6e).

One fixed float per site, held by a named custodian. Expenses are recorded
by the custodian, PM-approved (posting Incurred cost once), and reimbursed
when the cycle's replenishment PYR is paid. The replenishment PYR carries
the Paid leg, so each expense is counted once, not twice (§6C.3.3).
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import costing
from .audit import audit
from .models import (CostHead, Document, DocumentRevision, PaymentRequest,
                     PettyCashCycle, PettyCashEntry, PettyCashFloat,
                     PettyCashReconciliation)
from .numbering import next_ref

CUSTODIAN_ROLES = {"SITE_ADMIN", "PM", "ADMIN"}
LIVE_ENTRY = ("RECORDED", "APPROVED")


# ---- Float + cycle --------------------------------------------------------

def setup_float(site, imprest_amount, custodian, trigger_pct=30,
                per_txn_cap=1500):
    """Create or update a site's float (§6B.1). HO/Finance/Admin only —
    enforced at the view."""
    imprest = Decimal(str(imprest_amount))
    fl, created = PettyCashFloat.objects.update_or_create(
        site=site,
        defaults={"imprest_amount": imprest, "custodian": custodian,
                  "trigger_pct": int(trigger_pct),
                  "per_txn_cap": Decimal(str(per_txn_cap)),
                  "is_active": True})
    if created or not fl.cycles.exists():
        PettyCashCycle.objects.get_or_create(
            float=fl, cycle_no=1,
            defaults={"opening_float": imprest, "status": "OPEN"})
    return fl


def current_cycle(fl):
    """The open (or replenishment-requested) cycle; opens cycle 1 if the
    float has none yet."""
    cyc = fl.cycles.exclude(status="REPLENISHED").order_by("-cycle_no").first()
    if cyc is None:
        cyc = PettyCashCycle.objects.create(
            float=fl, cycle_no=(fl.cycles.count() + 1),
            opening_float=fl.imprest_amount, status="OPEN")
    return cyc


def _spent(cycle):
    """Cash spent this cycle — recorded + approved entries, not voided."""
    total = Decimal("0")
    for e in cycle.entries.filter(status__in=LIVE_ENTRY):
        total += e.amount
    return total


def cash_in_hand(fl):
    """Imprest less expenses since the last replenishment (§6B.2)."""
    cyc = current_cycle(fl)
    return cyc.opening_float - _spent(cyc)


def approved_unreimbursed_total(fl):
    """What the next replenishment PYR will claim back."""
    cyc = current_cycle(fl)
    total = Decimal("0")
    for e in cyc.entries.filter(status="APPROVED"):
        total += e.amount
    return total


# ---- Expense entries ------------------------------------------------------

def add_entry(fl, data, user):
    """Record a petty-cash expense (§6B.2). Blocked above the per-txn cap."""
    cyc = current_cycle(fl)
    if cyc.status != "OPEN":
        return None, ("This cycle's replenishment has been requested; the "
                      "schedule is locked until the float is restored.")
    try:
        amount = Decimal(str(data.get("amount") or 0))
    except (TypeError, ValueError):
        return None, "Amount is invalid."
    if amount <= 0:
        return None, "Amount must be greater than zero."
    if amount > fl.per_txn_cap:
        return None, (f"Above the petty-cash cap of MVR {fl.per_txn_cap:,.0f} "
                      "— raise a Payment Request (PYR) for this instead.")
    try:
        cost_head = CostHead.objects.get(pk=data.get("cost_head_id"),
                                         is_active=True)
    except CostHead.DoesNotExist:
        return None, "A valid cost head is required."
    if cost_head.is_pool:
        return None, "That cost head is a Head Office pool, not a site head."
    if not (data.get("payee") or "").strip():
        return None, "Payee / purpose is required."
    # multipart sends booleans as strings ("false" is truthy) — normalise
    flag = str(data.get("has_receipt")).lower() in ("true", "1", "yes", "on")
    has_receipt = flag or data.get("receipt") is not None
    reason = (data.get("no_receipt_reason") or "").strip()
    if not has_receipt and not reason:
        return None, ("Attach a receipt, or give a reason for having none.")
    entry = PettyCashEntry.objects.create(
        cycle=cyc, entry_date=data.get("entry_date") or date.today(),
        amount=amount, cost_head=cost_head,
        payee=(data.get("payee") or "").strip(),
        purpose=(data.get("purpose") or "").strip(),
        receipt=data.get("receipt"), has_receipt=has_receipt,
        no_receipt_reason=reason, entered_by=user)
    audit("petty_cash_entry", entry.id, "PC_ENTRY_ADDED", actor=user,
          detail={"site": fl.site.code, "amount": str(amount)})
    return entry, None


def approve_entries(fl, entry_ids, user):
    """PM approves recorded entries (§6B.2) — posts Incurred cost per entry."""
    cyc = current_cycle(fl)
    entries = cyc.entries.filter(id__in=entry_ids, status="RECORDED")
    n = 0
    with transaction.atomic():
        for e in entries:
            e.status = "APPROVED"
            e.approved_by = user
            e.approved_at = timezone.now()
            e.save(update_fields=["status", "approved_by", "approved_at"])
            costing.post(site=fl.site, cost_head=e.cost_head, state="INCURRED",
                         source="PETTY_CASH", amount=e.amount,
                         petty_cash_entry=e, posted_on=e.entry_date, actor=user)
            n += 1
    audit("petty_cash", fl.id, "PC_ENTRIES_APPROVED", actor=user,
          detail={"site": fl.site.code, "count": n})
    return n


def void_entry(entry, user):
    """Void an entry before reimbursement; reverses its Incurred posting if
    it was approved (§4A)."""
    if entry.status == "REIMBURSED":
        return "A reimbursed entry cannot be voided."
    if entry.status == "APPROVED":
        costing.reverse_petty_cash_entry(entry, actor=user)
    entry.status = "VOID"
    entry.save(update_fields=["status"])
    audit("petty_cash_entry", entry.id, "PC_ENTRY_VOID", actor=user)
    return None


# ---- Replenishment cycle --------------------------------------------------

def request_replenishment(fl, user):
    """Raise a PYR of type Petty cash replenishment, pre-filled with the
    total of approved, unreimbursed expenses and their schedule (§6B.3)."""
    cyc = current_cycle(fl)
    if cyc.status != "OPEN":
        return None, "A replenishment has already been requested."
    approved = list(cyc.entries.filter(status="APPROVED"))
    if not approved:
        return None, ("No approved expenses to claim — a PM must approve "
                      "the entries first.")
    total = sum((e.amount for e in approved), Decimal("0"))
    schedule = [{"date": str(e.entry_date), "amount": str(e.amount),
                 "cost_head": e.cost_head.name, "payee": e.payee,
                 "purpose": e.purpose, "has_receipt": e.has_receipt}
                for e in approved]
    overheads = CostHead.objects.filter(name="Site Overheads").first() \
        or CostHead.objects.filter(is_pool=False).first()
    with transaction.atomic():
        ref = next_ref("PYR", fl.site)
        doc = Document.objects.create(
            doc_type="PYR", ref=ref, site=fl.site, doc_date=date.today(),
            status="DRAFT", created_by=user)
        revision = DocumentRevision.objects.create(
            document=doc, rev_label="R0",
            payload={"petty_cash_schedule": schedule,
                     "petty_cash_cycle": cyc.cycle_no}, created_by=user)
        doc.current_revision = revision
        doc.save(update_fields=["current_revision"])
        PaymentRequest.objects.create(
            document=doc, payment_type="PETTY_CASH_REPLENISH",
            cost_head=overheads, payee=f"Petty cash float — {fl.site.code}",
            payment_method="BANK", currency="MVR", amount_requested=total,
            purpose=(f"Replenish the site petty-cash float (cycle "
                     f"{cyc.cycle_no}): {len(approved)} approved expenses."),
            has_supporting_doc=True, petty_cash_cycle=cyc)
        cyc.status = "REQUESTED"
        cyc.save(update_fields=["status"])
    audit("petty_cash", fl.id, "PC_REPLENISH_REQUESTED", actor=user,
          detail={"site": fl.site.code, "pyr": ref, "amount": str(total)})
    return doc, None


def on_replenish_paid(pyr_doc, actor):
    """Called from the PYR pay action when a replenishment PYR is paid:
    post the Paid leg per expense (per cost head), mark the covered entries
    Reimbursed, close the cycle immutably, and open the next one (§6B.3.4)."""
    pr = pyr_doc.payment_request
    cyc = pr.petty_cash_cycle
    if cyc is None or cyc.status == "REPLENISHED":
        return
    fl = cyc.float
    paid_on = pr.paid_date or date.today()
    with transaction.atomic():
        for e in cyc.entries.filter(status="APPROVED"):
            costing.post(site=fl.site, cost_head=e.cost_head, state="PAID",
                         source="PETTY_CASH", amount=e.amount,
                         petty_cash_entry=e, document=pyr_doc,
                         posted_on=paid_on, actor=actor)
            e.status = "REIMBURSED"
            e.save(update_fields=["status"])
        cyc.status = "REPLENISHED"
        cyc.closing_float = fl.imprest_amount
        cyc.closed_at = timezone.now()
        cyc.save(update_fields=["status", "closing_float", "closed_at"])
        PettyCashCycle.objects.create(
            float=fl, cycle_no=cyc.cycle_no + 1,
            opening_float=fl.imprest_amount, status="OPEN")
    audit("petty_cash", fl.id, "PC_REPLENISHED", actor=actor,
          detail={"site": fl.site.code, "cycle": cyc.cycle_no,
                  "pyr": pyr_doc.ref})


# ---- Reconciliation -------------------------------------------------------

def reconcile(fl, counted_cash, explanation, user, is_handover=False,
              incoming=None):
    """Record a physical cash count against the system balance (§6B.4)."""
    counted = Decimal(str(counted_cash))
    system = cash_in_hand(fl)
    variance = counted - system
    if variance != 0 and not (explanation or "").strip():
        return None, "A variance explanation is required."
    if is_handover and incoming is None:
        return None, "A handover needs the incoming custodian."
    recon = PettyCashReconciliation.objects.create(
        float=fl, recon_date=date.today(), counted_cash=counted,
        system_balance=system, variance=variance,
        explanation=(explanation or "").strip(), is_handover=is_handover,
        outgoing_custodian=fl.custodian if is_handover else None,
        incoming_custodian=incoming, recorded_by=user)
    if is_handover and incoming is not None:
        fl.custodian = incoming
        fl.save(update_fields=["custodian", "updated_at"])
    audit("petty_cash", fl.id, "PC_RECONCILED", actor=user,
          detail={"site": fl.site.code, "variance": str(variance)})
    return recon, None

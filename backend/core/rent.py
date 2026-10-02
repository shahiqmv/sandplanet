"""Rent the company pays (owner 2026-10-02: "set all rentals and post dues
automatically so that accounts can create PV").

A RentContract is something rented period after period — an office, staff
accommodation, a warehouse, a vehicle on hire. As each period comes up its
rent is raised by itself: a RentDue with a Payable, which Finance finds on
the payables list and puts on a payment voucher like any other payable. The
cost goes into Planet's cost ledger for the period it belongs to, and is
marked paid when the payable is settled.

A daily job (`manage.py rent_dues`) raises what has come up; the same thing
can be done from the screen.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import costing
from .audit import audit
from .models import (CostHead, CostPosting, Payable, PaymentVoucherLine,
                     RentContract, RentDue, Site)

VIEW_ROLES = ("FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA")
EDIT_ROLES = ("FINANCE", "ADMIN")
ZERO = Decimal("0")
MAX_CATCH_UP = 36          # periods one contract may raise in one go


def q2(v):
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _date(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _today():
    return timezone.localdate()


def add_months(d, n):
    """The same day `n` months on; the last day where that month is shorter."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def gst_rate():
    from .procurement import company_gst_rate
    return company_gst_rate()


# ---- periods ---------------------------------------------------------------------

def period(contract, k):
    """The k-th period of a contract, counted from its start date."""
    n = RentContract.MONTHS[contract.frequency]
    start = add_months(contract.start_date, k * n)
    end = add_months(contract.start_date, (k + 1) * n) - timedelta(days=1)
    return start, end


def due_date_for(contract, start, end):
    """Rent in advance falls due as the period starts, in arrears as it
    ends — on the agreed day of that month where one is set."""
    anchor = start if contract.in_advance else end
    if contract.due_day:
        day = min(contract.due_day, calendar.monthrange(anchor.year,
                                                        anchor.month)[1])
        return date(anchor.year, anchor.month, day)
    return anchor


def rate_at(contract, on):
    """The rent per period in force on a date: the latest agreed change on
    or before it, else the contract's own amount."""
    amount = contract.amount
    for step in sorted(contract.steps or [], key=lambda s: s.get("from", "")):
        d = _date(step.get("from"))
        if d and d <= on:
            amount = Decimal(str(step.get("amount")))
    return q2(amount)


def period_label(contract, start, end):
    if contract.frequency == "MONTHLY" and start.day == 1:
        return f"{start:%b %Y}"
    return f"{start:%d %b %Y} – {end:%d %b %Y}"


def figures(contract, start, end):
    """Net, GST and total for a period. A last period cut short by the end
    of the contract pays for its days only."""
    net = rate_at(contract, start)
    if contract.end_date and contract.end_date < end:
        whole = (end - start).days + 1
        part = (contract.end_date - start).days + 1
        net = q2(net * part / whole)
        end = contract.end_date
    gst = q2(net * gst_rate() / 100) if contract.gst_applicable else ZERO
    return net, gst, net + gst, end


def upcoming(contract, today=None, limit=MAX_CATCH_UP, ahead=False):
    """The periods of a contract that have come up and have no live due:
    [(start, end, due_date)], oldest first. With `ahead`, also the next one
    not yet up — for raising a period early."""
    today = today or _today()
    if contract.status != "ACTIVE":
        return []
    # a cancelled due keeps its period: it is raised again only on purpose
    have = set(contract.dues.values_list("period_start", flat=True))
    out, k = [], 0
    while len(out) < limit and k < 1200:
        start, end = period(contract, k)
        k += 1
        if contract.end_date and start > contract.end_date:
            break
        if end < contract.dues_from:
            continue                      # paid outside Planet, before it
        if start in have:
            continue
        due = due_date_for(contract, start, end)
        if due - timedelta(days=contract.lead_days) > today:
            if ahead:
                out.append((start, end, due))
            break
        out.append((start, end, due))
    return out


# ---- raising, settling, cancelling ------------------------------------------------

def _ho_site():
    from .procurement import _ho_site as ho
    return ho()


def _post(due, state, actor, on):
    """The due's cost in Planet's cost ledger: rent to the contract's site
    and head, GST to the recoverable pool."""
    c = due.contract
    costing.post(site=c.site, cost_head=c.cost_head, state=state,
                 source="RENT", amount=due.amount, currency=due.currency,
                 posted_on=on, rent_due=due, actor=actor)
    if due.gst:
        costing.post(site=_ho_site(),
                     cost_head=costing.by_code(costing.INPUT_GST),
                     state=state, source="RENT", amount=due.gst,
                     currency=due.currency, posted_on=on, rent_due=due,
                     is_stock_pool=True, actor=actor)


def raise_due(contract, start, end, due_on, actor=None):
    net, gst, total, end = figures(contract, start, end)
    if total <= ZERO:
        return None
    with transaction.atomic():
        due = RentDue.objects.create(
            contract=contract, period_start=start, period_end=end,
            due_date=due_on, currency=contract.currency, amount=net, gst=gst,
            total=total, raised_by=actor)
        Payable.objects.create(
            rent_due=due, site=contract.site, vendor=contract.landlord,
            terms=f"Rent · {period_label(contract, start, end)} · "
                  f"{contract.title}"[:300],
            amount=total, due_date=due_on)
        # the cost belongs to the period it pays for
        for state in ("COMMITTED", "INCURRED"):
            _post(due, state, actor, start)
    audit("rent_contract", contract.id, "RENT_DUE_RAISED", actor=actor,
          detail={"ref": contract.ref, "period": str(start),
                  "total": str(total), "due": str(due_on)})
    return due


def raise_dues(today=None, actor=None, contract=None, ahead=False):
    """Raise every period that has come up, for one contract or for all.
    Returns the dues raised."""
    today = today or _today()
    qs = RentContract.objects.filter(status="ACTIVE")
    if contract is not None:
        qs = qs.filter(pk=contract.pk)
    out = []
    for c in qs.select_related("site", "cost_head"):
        for start, end, due_on in upcoming(c, today, ahead=ahead):
            d = raise_due(c, start, end, due_on, actor)
            if d:
                out.append(d)
            if ahead and due_on - timedelta(days=c.lead_days) > today:
                break
    return out


def settle_due(payable, actor, ref):
    """Finance pays a rent payable off its voucher."""
    due = payable.rent_due
    today = _today()
    with transaction.atomic():
        _post(due, "PAID", actor, today)
        payable.status = "SETTLED"
        payable.settled_on = today
        payable.settled_ref = ref or ""
        payable.save(update_fields=["status", "settled_on", "settled_ref"])
        due.status, due.paid_on, due.paid_ref = "PAID", today, (ref or "")[:120]
        due.save(update_fields=["status", "paid_on", "paid_ref"])
    audit("rent_contract", due.contract_id, "RENT_DUE_PAID", actor=actor,
          detail={"ref": due.contract.ref, "period": str(due.period_start),
                  "total": str(due.total), "payment_ref": ref or ""})


def cancel_due(due, actor, reason):
    """Take back a due raised in error, or for a period that will not be
    paid. Its cost is reversed and its payable cancelled."""
    reason = (reason or "").strip()
    if due.status != "RAISED":
        return "Only a due that is still unpaid can be cancelled."
    if not reason:
        return "Say why it is being cancelled."
    payable = due.payable
    line = (PaymentVoucherLine.objects.filter(source_payable=payable,
                                              voucher__is_void=False)
            .exclude(voucher__status="CANCELLED")
            .select_related("voucher").first())
    if line:
        return (f"It is on voucher {line.voucher.ref} — take it off the "
                "voucher first.")
    with transaction.atomic():
        for row in CostPosting.objects.filter(rent_due=due,
                                              reversal_of__isnull=True):
            costing.post(site=row.site, cost_head=row.cost_head,
                         state=row.state, source="RENT", amount=-row.amount,
                         currency=row.currency, posted_on=row.posted_on,
                         rent_due=due, is_stock_pool=row.is_stock_pool,
                         reversal_of=row, actor=actor)
        payable.status = "CANCELLED"
        payable.save(update_fields=["status"])
        due.status, due.cancel_reason = "CANCELLED", reason[:300]
        due.save(update_fields=["status", "cancel_reason"])
    audit("rent_contract", due.contract_id, "RENT_DUE_CANCELLED", actor=actor,
          detail={"ref": due.contract.ref, "period": str(due.period_start),
                  "reason": reason[:200]})
    return None


def raise_again(due, actor):
    """A cancelled period, raised afresh on the contract's present terms —
    after the rent or the dates were corrected."""
    c = due.contract
    if due.status != "CANCELLED":
        return None, "Only a cancelled due is raised again."
    if c.dues.filter(period_start=due.period_start).exclude(
            status="CANCELLED").exists():
        return None, "That period already has a due."
    n = RentContract.MONTHS[c.frequency]
    end = add_months(due.period_start, n) - timedelta(days=1)
    new = raise_due(c, due.period_start, end,
                    due_date_for(c, due.period_start, end), actor)
    if new is None:
        return None, "There is nothing to pay for that period."
    return new, None


# ---- the contract -----------------------------------------------------------------

def _money(v, what, allow_blank=False):
    if v in (None, "") and allow_blank:
        return None
    try:
        return q2(Decimal(str(v).replace(",", "")))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{what} is not a number.")


def save_contract(data, actor, contract=None, agreement=None):
    """Create a contract or change its terms. Returns (contract, error).
    Changing the terms does not touch dues already raised."""
    from .numbering import next_ref
    c = contract or RentContract(created_by=actor)
    try:
        def text(key, limit, required=None):
            if key in data or c.pk is None:
                v = " ".join(str(data.get(key) or "").split())[:limit]
                if required and not v:
                    raise ValueError(required)
                setattr(c, key, v)
        text("title", 200, "Say what is rented.")
        text("landlord", 160, "Give the landlord or owner.")
        text("landlord_tin", 40)
        text("landlord_contact", 200)
        for key in ("payee_account", "notes"):
            if key in data or c.pk is None:
                setattr(c, key, str(data.get(key) or "").strip())
        if "kind" in data or c.pk is None:
            c.kind = data.get("kind") or "OFFICE"
            if c.kind not in RentContract.Kind.values:
                raise ValueError("Unknown kind of rental.")
        if "frequency" in data or c.pk is None:
            c.frequency = data.get("frequency") or "MONTHLY"
            if c.frequency not in RentContract.Frequency.values:
                raise ValueError("Unknown payment frequency.")
        if "site" in data or c.pk is None:
            site = (Site.objects.filter(pk=data.get("site")).first()
                    if data.get("site") else None)
            if site is None:
                raise ValueError("Pick the site that bears the cost.")
            c.site = site
        if "cost_head" in data or c.pk is None:
            head = (CostHead.objects.filter(pk=data.get("cost_head")).first()
                    if data.get("cost_head") else costing.by_code("RENT"))
            if head is None or not head.is_active:
                raise ValueError("Pick the cost head.")
            c.cost_head = head
        if "currency" in data or c.pk is None:
            c.currency = (data.get("currency") or "MVR").upper()[:3]
            if c.currency not in ("MVR", "USD"):
                raise ValueError("Rent is paid in MVR or USD.")
        if "amount" in data or c.pk is None:
            c.amount = _money(data.get("amount"), "The rent")
            if c.amount <= ZERO:
                raise ValueError("Give the rent per period.")
        if "steps" in data:
            steps = []
            for s in data.get("steps") or []:
                d = _date(s.get("from"))
                if d is None and not s.get("amount"):
                    continue
                amt = _money(s.get("amount"), "A changed rent")
                if d is None or amt <= ZERO:
                    raise ValueError("Each change of rent needs the date it "
                                     "applies from and the new amount.")
                steps.append({"from": d.isoformat(), "amount": str(amt)})
            c.steps = sorted(steps, key=lambda s: s["from"])
        for key in ("gst_applicable", "in_advance"):
            if key in data:
                setattr(c, key, bool(data.get(key)))
        if "due_day" in data:
            v = data.get("due_day")
            c.due_day = None if v in (None, "") else int(v)
            if c.due_day is not None and not 1 <= c.due_day <= 28:
                raise ValueError("The due day is between 1 and 28.")
        if "lead_days" in data:
            c.lead_days = int(data.get("lead_days") or 0)
            if not 0 <= c.lead_days <= 30:
                raise ValueError("Raise the due between 0 and 30 days ahead.")
        if "start_date" in data or c.pk is None:
            c.start_date = _date(data.get("start_date"))
            if c.start_date is None:
                raise ValueError("Give the date the rental starts.")
        if "end_date" in data:
            c.end_date = _date(data.get("end_date"))
            if data.get("end_date") and c.end_date is None:
                raise ValueError("The end date is not a date.")
        if c.end_date and c.end_date < c.start_date:
            raise ValueError("The rental ends before it starts.")
        if "dues_from" in data or c.pk is None:
            # past periods were paid outside Planet unless told otherwise
            c.dues_from = (_date(data.get("dues_from"))
                           or max(c.start_date, _today()))
        if "deposit_amount" in data:
            c.deposit_amount = _money(data.get("deposit_amount"),
                                      "The deposit", allow_blank=True)
        if "status" in data:
            if data["status"] not in RentContract.Status.values:
                raise ValueError("Unknown status.")
            c.status = data["status"]
    except ValueError as exc:
        return None, str(exc)
    new = c.pk is None
    with transaction.atomic():
        if new:
            c.ref = next_ref("RENT", None)
        if agreement is not None:
            c.agreement = agreement
        c.save()
    audit("rent_contract", c.id,
          "RENT_CONTRACT_CREATED" if new else "RENT_CONTRACT_CHANGED",
          actor=actor, detail={"ref": c.ref, "landlord": c.landlord,
                               "amount": str(c.amount),
                               "currency": c.currency, "status": c.status})
    return c, None


# ---- for the screens ----------------------------------------------------------------

def due_dict(d, c=None):
    c = c or d.contract
    p = getattr(d, "payable", None)
    line = None
    if p is not None:
        line = (PaymentVoucherLine.objects.filter(source_payable=p,
                                                  voucher__is_void=False)
                .exclude(voucher__status="CANCELLED")
                .select_related("voucher").order_by("-id").first())
    return {"id": d.id, "period": period_label(c, d.period_start,
                                               d.period_end),
            "period_start": d.period_start, "period_end": d.period_end,
            "due_date": d.due_date, "currency": d.currency,
            "amount": d.amount, "gst": d.gst, "total": d.total,
            "status": d.status, "status_label": d.get_status_display(),
            "paid_on": d.paid_on, "paid_ref": d.paid_ref,
            "cancel_reason": d.cancel_reason,
            "voucher": line.voucher.ref if line else None,
            "overdue": d.status == "RAISED" and d.due_date < _today()}


def contract_dict(c, detail=False, today=None):
    today = today or _today()
    dues = list(c.dues.all())
    open_ = [d for d in dues if d.status == "RAISED"]
    nxt = upcoming(c, today, limit=1, ahead=True)
    out = {
        "id": c.id, "ref": c.ref, "title": c.title, "kind": c.kind,
        "kind_label": c.get_kind_display(), "landlord": c.landlord,
        "landlord_tin": c.landlord_tin,
        "landlord_contact": c.landlord_contact,
        "payee_account": c.payee_account, "site": c.site_id,
        "site_code": c.site.code, "cost_head": c.cost_head_id,
        "cost_head_name": c.cost_head.name, "currency": c.currency,
        "amount": c.amount, "current_amount": rate_at(c, today),
        "steps": c.steps or [], "gst_applicable": c.gst_applicable,
        "frequency": c.frequency,
        "frequency_label": c.get_frequency_display(),
        "in_advance": c.in_advance, "due_day": c.due_day,
        "start_date": c.start_date, "end_date": c.end_date,
        "dues_from": c.dues_from, "lead_days": c.lead_days,
        "deposit_amount": c.deposit_amount, "notes": c.notes,
        "agreement_url": c.agreement.url if c.agreement else None,
        "status": c.status, "status_label": c.get_status_display(),
        "open_count": len(open_),
        "open_total": sum((d.total for d in open_), ZERO),
        "overdue_count": sum(1 for d in open_ if d.due_date < today),
        "next": ({"period": period_label(c, nxt[0][0], nxt[0][1]),
                  "due_date": nxt[0][2]} if nxt else None),
    }
    if detail:
        out["dues"] = [due_dict(d, c) for d in reversed(dues)]
    return out


def meta():
    return {
        "kinds": [{"value": v, "label": lab}
                  for v, lab in RentContract.Kind.choices],
        "frequencies": [{"value": v, "label": lab}
                        for v, lab in RentContract.Frequency.choices],
        "sites": [{"id": s.id, "code": s.code, "name": s.name}
                  for s in Site.objects.order_by("code")],
        "cost_heads": [{"id": h.id, "name": h.name, "code": h.code}
                       for h in CostHead.objects.filter(
                           is_active=True, is_pool=False, trading=False,
                           rental=False).order_by("sort_order", "name")],
        "default_head": getattr(costing.by_code("RENT"), "id", None),
        "gst_rate": gst_rate(),
    }

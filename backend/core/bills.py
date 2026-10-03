"""Phone and utility bills (owner 2026-10-03: "keep record of all individual
accounts so that we could do batch payments upon due").

A BillAccount is one account the company is billed on every month — a mobile
number, an internet line, a meter. The amount differs month to month, so
nothing is raised by a clock: when the bills arrive Finance enters the
month's figures on one sheet (`enter_bills`), and each becomes a BillCharge
with a Payable. The unpaid ones are listed by provider, so a provider's
whole batch goes on one payment voucher. The cost enters Planet's cost
ledger when the bill is entered and is marked paid when it is settled —
the same path a rent due takes (core/rent.py).
"""
import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import costing
from .audit import audit
from .models import (BillAccount, BillCharge, CostHead, CostPosting, Employee,
                     Payable, PaymentVoucherLine, Site)

VIEW_ROLES = ("FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA")
EDIT_ROLES = ("FINANCE", "ADMIN")
ZERO = Decimal("0")


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


def _money(v, what, blank=False):
    if v in (None, "") and blank:
        return None
    try:
        return q2(Decimal(str(v).replace(",", "")))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{what} is not a number.")


def gst_rate():
    from .procurement import company_gst_rate
    return company_gst_rate()


def month_of(v):
    """'2026-09' or a date → the first day of that month."""
    if isinstance(v, date):
        return v.replace(day=1)
    try:
        y, m = str(v or "")[:7].split("-")
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        return None


def default_head(kind):
    return costing.by_code("TELECOM" if kind in BillAccount.TELECOM
                           else "UTILITIES")


# ---- the accounts ----------------------------------------------------------------

def _clean_account(data, acct):
    def text(key, limit):
        return " ".join(str(data.get(key) or "").split())[:limit]
    new = acct.pk is None
    if "provider" in data or new:
        acct.provider = text("provider", 120)
        if not acct.provider:
            raise ValueError("Say which provider bills it.")
    if "account_no" in data or new:
        acct.account_no = text("account_no", 60)
        if not acct.account_no:
            raise ValueError("Give the account or phone number.")
    if "kind" in data or new:
        acct.kind = data.get("kind") or "MOBILE"
        if acct.kind not in BillAccount.Kind.values:
            raise ValueError("Unknown kind of account.")
    for key, limit in (("label", 200), ("provider_tin", 40)):
        if key in data or new:
            setattr(acct, key, text(key, limit))
    if "notes" in data:
        acct.notes = str(data.get("notes") or "").strip()
    if "site" in data or new:
        site = (Site.objects.filter(pk=data.get("site")).first()
                if data.get("site") else None)
        if site is None:
            raise ValueError("Pick the site that bears the cost.")
        acct.site = site
    if "cost_head" in data or new:
        head = (CostHead.objects.filter(pk=data.get("cost_head")).first()
                if data.get("cost_head") else default_head(acct.kind))
        if head is None or not head.is_active:
            raise ValueError("Pick the cost head.")
        acct.cost_head = head
    if "employee" in data:
        acct.employee = (Employee.objects.filter(
            pk=data.get("employee")).first() if data.get("employee") else None)
    if "emp_no" in data and data.get("emp_no"):
        emp = Employee.objects.filter(
            emp_no__iexact=str(data["emp_no"]).strip()).first()
        if emp is None:
            raise ValueError(f"There is no employee {data['emp_no']}.")
        acct.employee = emp
        if not acct.label:
            acct.label = emp.full_name[:200]
    if "currency" in data or new:
        acct.currency = (data.get("currency") or "MVR").upper()[:3]
        if acct.currency not in ("MVR", "USD"):
            raise ValueError("Bills are paid in MVR or USD.")
    if "gst_applicable" in data:
        acct.gst_applicable = bool(data.get("gst_applicable"))
    elif new:
        # phone and internet bills carry GST; electricity and water are exempt
        acct.gst_applicable = acct.kind in BillAccount.TELECOM
    if "monthly_limit" in data:
        acct.monthly_limit = _money(data.get("monthly_limit"), "The limit",
                                    blank=True)
    if "prepaid" in data:
        acct.prepaid = bool(data.get("prepaid"))
    if "fixed_amount" in data:
        acct.fixed_amount = _money(data.get("fixed_amount"),
                                   "The monthly recharge", blank=True)
        if acct.fixed_amount is not None and acct.fixed_amount <= ZERO:
            acct.fixed_amount = None
    if "due_day" in data:
        v = data.get("due_day")
        acct.due_day = None if v in (None, "") else int(v)
        if acct.due_day is not None and not 1 <= acct.due_day <= 28:
            raise ValueError("The due day is between 1 and 28.")
    if "is_active" in data:
        acct.is_active = bool(data.get("is_active"))
    clash = BillAccount.objects.filter(provider__iexact=acct.provider,
                                       account_no__iexact=acct.account_no)
    if acct.pk:
        clash = clash.exclude(pk=acct.pk)
    if clash.exists():
        raise ValueError(f"{acct.provider} {acct.account_no} is already on "
                         "the list.")


def save_account(data, actor, account=None):
    """Add an account or change it. Returns (account, error)."""
    from .numbering import next_ref
    acct = account or BillAccount(created_by=actor)
    new = acct.pk is None
    try:
        _clean_account(data, acct)
    except (ValueError, TypeError) as exc:
        return None, str(exc)
    with transaction.atomic():
        if new:
            acct.ref = next_ref("UTL", None)
        acct.save()
    audit("bill_account", acct.id,
          "BILL_ACCOUNT_ADDED" if new else "BILL_ACCOUNT_CHANGED", actor=actor,
          detail={"ref": acct.ref, "provider": acct.provider,
                  "account_no": acct.account_no})
    return acct, None


def add_many(data, actor):
    """Several accounts of one provider at once — pasted as lines of
    "number, whose it is, limit". All go in, or none. Returns (n, error)."""
    lines = [ln for ln in str(data.get("lines") or "").splitlines()
             if ln.strip()]
    if not lines:
        return 0, "Paste the numbers, one to a line."
    made = 0
    try:
        with transaction.atomic():
            for n, ln in enumerate(lines, 1):
                parts = [p.strip() for p in
                         ln.replace("\t", ",").split(",")]
                row = {**data, "account_no": parts[0],
                       "label": parts[1] if len(parts) > 1 else ""}
                # an employee number in place of the name ties the person
                if re.fullmatch(r"EMP-?\d+", row["label"], re.I):
                    row["emp_no"], row["label"] = row["label"], ""
                if len(parts) > 2 and parts[2]:
                    # a prepaid line gives its recharge; a postpaid one its
                    # allowance
                    row["fixed_amount" if data.get("prepaid")
                        else "monthly_limit"] = parts[2]
                _, msg = save_account(row, actor)
                if msg:
                    raise ValueError(f"Line {n}: {msg}")
                made += 1
    except ValueError as exc:
        return 0, f"{exc} Nothing was added."
    return made, None


def account_dict(a, last=None):
    return {
        "id": a.id, "ref": a.ref, "provider": a.provider,
        "provider_tin": a.provider_tin, "kind": a.kind,
        "kind_label": a.get_kind_display(), "account_no": a.account_no,
        "label": a.label, "employee": a.employee_id,
        "employee_name": (f"{a.employee.emp_no} · {a.employee.full_name}"
                          if a.employee_id else ""),
        "site": a.site_id, "site_code": a.site.code,
        "cost_head": a.cost_head_id, "cost_head_name": a.cost_head.name,
        "currency": a.currency, "gst_applicable": a.gst_applicable,
        "monthly_limit": a.monthly_limit, "due_day": a.due_day,
        "prepaid": a.prepaid, "fixed_amount": a.fixed_amount,
        "notes": a.notes, "is_active": a.is_active,
        "last": ({"period": last.period, "total": last.total,
                  "status": last.status} if last else None),
    }


def _last_charges(account_ids):
    """Each account's latest live bill."""
    out = {}
    for c in (BillCharge.objects.filter(account_id__in=account_ids)
              .exclude(status="CANCELLED").order_by("period", "id")):
        out[c.account_id] = c
    return out


def accounts(include_closed=False):
    qs = BillAccount.objects.select_related("site", "cost_head", "employee")
    if not include_closed:
        qs = qs.filter(is_active=True)
    rows = list(qs)
    last = _last_charges([a.id for a in rows])
    return [account_dict(a, last.get(a.id)) for a in rows]


# ---- a month's bills -------------------------------------------------------------

def usual_due(account, period):
    """Where a bill of this month usually falls due: the account's day in
    the month after, else the end of that month. A prepaid recharge is paid
    up front, as its month starts."""
    if account.prepaid:
        return period
    y, m = (period.year + 1, 1) if period.month == 12 else (
        period.year, period.month + 1)
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(account.due_day or last, last))


def sheet(period, provider=""):
    """The entry sheet for a month: every active account, what is already
    entered for it, and what it was last month."""
    qs = BillAccount.objects.filter(is_active=True).select_related(
        "site", "cost_head", "employee")
    if provider:
        qs = qs.filter(provider__iexact=provider)
    rows = list(qs)
    ids = [a.id for a in rows]
    entered = {c.account_id: c for c in BillCharge.objects.filter(
        account_id__in=ids, period=period).exclude(status="CANCELLED")}
    before = {}
    for c in (BillCharge.objects.filter(account_id__in=ids, period__lt=period)
              .exclude(status="CANCELLED").order_by("period", "id")):
        before[c.account_id] = c
    out = []
    for a in rows:
        c, prev = entered.get(a.id), before.get(a.id)
        out.append({
            **account_dict(a),
            "usual_due": usual_due(a, period),
            "previous": prev.total if prev else None,
            "charge": charge_dict(c, a) if c else None})
    return {"period": period, "rows": out,
            "providers": providers(), "gst_rate": gst_rate()}


def providers():
    return sorted({p for p in BillAccount.objects.filter(is_active=True)
                   .values_list("provider", flat=True)}, key=str.lower)


def recovery_period(emp, y, m):
    """The payroll month a recovery comes off: the bill's month, or the
    first after it whose run has not been drawn up yet — so it is on the
    run from the start and never missed."""
    from . import fines
    site = emp.current_site_id()
    for _ in range(24):
        if fines.monthly_run(emp, site, y, m) is None:
            break
        y, m = fines._next(y, m)
    return y, m


def recoveries_for(employee, year, month):
    """What this person owes on phone bills for a payroll month, in
    rufiyaa. Payroll adds it to the advance it recovers (core/payroll.py
    deductions_for)."""
    return (BillCharge.objects.filter(recover_from=employee,
                                      deduct_year=year, deduct_month=month)
            .exclude(status="CANCELLED")
            .aggregate(t=Sum("recover_amount"))["t"] or ZERO)


def recovery_state(c):
    """Where a bill's recovery stands, for the screens."""
    if not c.recover_amount:
        return None
    from .models import PayrollLine
    line = (PayrollLine.objects.filter(
        employee_id=c.recover_from_id, run__year=c.deduct_year,
        run__month=c.deduct_month, run__kind="MONTHLY")
        .select_related("run").first())
    when = f"{date(c.deduct_year, c.deduct_month, 1):%b %Y}"
    if line is None:
        note, done = f"comes off the {when} salary", False
    elif line.run.status == "LOCKED":
        note, done = f"deducted on payroll {line.run.ref}", True
    else:
        note, done = f"on payroll {line.run.ref}, not yet locked", False
    return {"amount": c.recover_amount, "from": c.recover_from.full_name,
            "emp_no": c.recover_from.emp_no, "month": when, "note": note,
            "deducted": done}


def company_share(charge):
    """The part of a bill the company bears: (net, GST). What runs over the
    allowance is the person's, GST and all."""
    if not charge.recover_amount:
        return charge.amount, charge.gst
    from . import fx
    excess = charge.recover_amount
    if charge.currency != "MVR":
        excess = q2(excess / fx.usd_rate())
    borne = max(charge.total - excess, ZERO)
    if not charge.gst:
        return borne, ZERO
    net = q2(borne * charge.amount / charge.total)
    return net, borne - net


def _post(charge, state, actor, on):
    """The company's share of the bill in Planet's cost ledger; its GST to
    the recoverable pool."""
    a = charge.account
    net, gst = company_share(charge)
    if net:
        costing.post(site=a.site, cost_head=a.cost_head, state=state,
                     source="UTILITY", amount=net, currency=charge.currency,
                     posted_on=on, bill_charge=charge, actor=actor)
    if gst:
        from .procurement import _ho_site
        costing.post(site=_ho_site(),
                     cost_head=costing.by_code(costing.INPUT_GST),
                     state=state, source="UTILITY", amount=gst,
                     currency=charge.currency, posted_on=on,
                     bill_charge=charge, is_stock_pool=True, actor=actor)


def period_label(period):
    return f"{period:%b %Y}"


def enter_bills(period, rows, actor):
    """Enter a month's bills: rows of {account, total, bill_no, bill_date,
    due_date}. The total is what the bill says, GST included. Blank rows are
    skipped. All go in, or none. Returns (charges, error)."""
    period = month_of(period)
    if period is None:
        return None, "Say which month the bills are for."
    today = _today()
    if period > today.replace(day=1):
        return None, "That month has not started."
    made = []
    try:
        with transaction.atomic():
            for r in rows or []:
                if r.get("total") in (None, ""):
                    continue
                a = BillAccount.objects.select_related(
                    "site", "cost_head", "employee").filter(
                    pk=r.get("account")).first()
                if a is None:
                    raise ValueError("One of the accounts is not on the list.")
                who = f"{a.provider} {a.account_no}"
                total = _money(r.get("total"), f"{who}: the amount")
                if total <= ZERO:
                    raise ValueError(f"{who}: the amount must be more than "
                                     "zero.")
                if not a.is_active:
                    raise ValueError(f"{who} is closed.")
                if BillCharge.objects.filter(account=a, period=period) \
                        .exclude(status="CANCELLED").exists():
                    raise ValueError(f"{who} already has a bill for "
                                     f"{period_label(period)}.")
                bill_date = _date(r.get("bill_date")) or today
                due = _date(r.get("due_date")) or usual_due(a, period)
                if bill_date > today:
                    raise ValueError(f"{who}: the bill date is in the "
                                     "future.")
                # the bill's figure includes its GST
                net = (q2(total / (1 + gst_rate() / 100))
                       if a.gst_applicable else total)
                # over the allowance, the rest is the person's own
                extra = {}
                if (a.employee_id and a.monthly_limit is not None
                        and not a.prepaid and total > a.monthly_limit):
                    from . import fx
                    y, m = recovery_period(a.employee, period.year,
                                           period.month)
                    extra = {"recover_amount": q2(fx.to_mvr(
                                 total - a.monthly_limit, a.currency)),
                             "recover_from": a.employee,
                             "deduct_year": y, "deduct_month": m}
                c = BillCharge.objects.create(
                    account=a, period=period,
                    bill_no=str(r.get("bill_no") or "").strip()[:60],
                    bill_date=bill_date, due_date=due, currency=a.currency,
                    amount=net, gst=total - net, total=total,
                    entered_by=actor, **extra)
                Payable.objects.create(
                    bill_charge=c, site=a.site, vendor=a.provider,
                    terms=(f"{a.get_kind_display()} · {a.account_no}"
                           + (f" · {a.label}" if a.label else "")
                           + f" · {period_label(period)}")[:300],
                    amount=total, due_date=due)
                for state in ("COMMITTED", "INCURRED"):
                    _post(c, state, actor, bill_date)
                made.append(c)
    except ValueError as exc:
        return None, f"{exc} Nothing was saved."
    if made:
        audit("bill_account", 0, "BILLS_ENTERED", actor=actor, detail={
            "period": str(period), "count": len(made),
            "total": str(sum((c.total for c in made), ZERO))})
    return made, None


def settle_charge(payable, actor, ref):
    """Finance pays a bill off its voucher."""
    c = payable.bill_charge
    today = _today()
    with transaction.atomic():
        _post(c, "PAID", actor, today)
        payable.status = "SETTLED"
        payable.settled_on = today
        payable.settled_ref = ref or ""
        payable.save(update_fields=["status", "settled_on", "settled_ref"])
        c.status, c.paid_on, c.paid_ref = "PAID", today, (ref or "")[:120]
        c.save(update_fields=["status", "paid_on", "paid_ref"])
    audit("bill_account", c.account_id, "BILL_PAID", actor=actor,
          detail={"ref": c.account.ref, "period": str(c.period),
                  "total": str(c.total), "payment_ref": ref or ""})


def _voucher_line(payable):
    return (PaymentVoucherLine.objects.filter(source_payable=payable,
                                              voucher__is_void=False)
            .exclude(voucher__status="CANCELLED")
            .select_related("voucher").order_by("-id").first())


def cancel_charge(charge, actor, reason):
    """Take back a bill entered wrongly; it can then be entered again."""
    reason = (reason or "").strip()
    if charge.status != "RAISED":
        return "Only a bill that is still unpaid can be cancelled."
    if not reason:
        return "Say why it is being cancelled."
    payable = charge.payable
    line = _voucher_line(payable)
    if line:
        return (f"It is on voucher {line.voucher.ref} — take it off the "
                "voucher first.")
    rec = recovery_state(charge)
    if rec and rec["deducted"]:
        return (f"MVR {charge.recover_amount:,.2f} of it has already been "
                f"{rec['note']} — it can't be cancelled now.")
    with transaction.atomic():
        for row in CostPosting.objects.filter(bill_charge=charge,
                                              reversal_of__isnull=True):
            costing.post(site=row.site, cost_head=row.cost_head,
                         state=row.state, source="UTILITY",
                         amount=-row.amount, currency=row.currency,
                         posted_on=row.posted_on, bill_charge=charge,
                         is_stock_pool=row.is_stock_pool, reversal_of=row,
                         actor=actor)
        payable.status = "CANCELLED"
        payable.save(update_fields=["status"])
        charge.status, charge.cancel_reason = "CANCELLED", reason[:300]
        charge.save(update_fields=["status", "cancel_reason"])
    audit("bill_account", charge.account_id, "BILL_CANCELLED", actor=actor,
          detail={"ref": charge.account.ref, "period": str(charge.period),
                  "reason": reason[:200]})
    return None


def charge_dict(c, a=None, voucher=True):
    a = a or c.account
    line = _voucher_line(c.payable) if voucher and hasattr(c, "payable") \
        else None
    return {
        "id": c.id, "account": a.id, "ref": a.ref, "provider": a.provider,
        "account_no": a.account_no, "label": a.label,
        "kind_label": a.get_kind_display(), "site_code": a.site.code,
        "period": c.period, "period_label": period_label(c.period),
        "bill_no": c.bill_no, "bill_date": c.bill_date,
        "due_date": c.due_date, "currency": c.currency, "amount": c.amount,
        "gst": c.gst, "total": c.total, "status": c.status,
        "paid_on": c.paid_on, "paid_ref": c.paid_ref,
        "cancel_reason": c.cancel_reason,
        "over_limit": (c.total - a.monthly_limit
                       if a.monthly_limit is not None and not a.prepaid
                       and c.total > a.monthly_limit else None),
        "recovery": recovery_state(c),
        "payable": c.payable.id if hasattr(c, "payable") else None,
        "voucher": line.voucher.ref if line else None,
        "voucher_status": line.voucher.status if line else None,
        "overdue": c.status == "RAISED" and c.due_date < _today(),
    }


def to_pay():
    """Every unpaid bill, by provider — what a batch voucher is built from."""
    groups = {}
    for c in (BillCharge.objects.filter(status="RAISED")
              .select_related("account", "account__site", "payable",
                              "recover_from")
              .order_by("account__provider", "due_date",
                        "account__account_no")):
        d = charge_dict(c)
        g = groups.setdefault((c.account.provider, c.currency), {
            "provider": c.account.provider, "currency": c.currency,
            "total": ZERO, "free_total": ZERO, "count": 0,
            "earliest_due": c.due_date, "overdue": 0, "bills": []})
        g["bills"].append(d)
        g["total"] += c.total
        g["count"] += 1
        g["overdue"] += 1 if d["overdue"] else 0
        g["earliest_due"] = min(g["earliest_due"], c.due_date)
        if not d["voucher"]:
            g["free_total"] += c.total
    return list(groups.values())


def history(account):
    return [charge_dict(c, account) for c in
            account.charges.select_related("payable", "recover_from")
            .order_by("-period", "-id")[:36]]


def people(q):
    """Employees to assign a phone to, by number or name."""
    from django.db.models import Q
    q = (q or "").strip()
    if len(q) < 2:
        return []
    qs = Employee.objects.filter(is_active=True).filter(
        Q(emp_no__icontains=q) | Q(full_name__icontains=q))
    return [{"id": e.id, "emp_no": e.emp_no, "name": e.full_name}
            for e in qs.order_by("full_name")[:20]]


def recoveries(limit=200):
    """Phone bill amounts being recovered from salaries, latest first."""
    return [charge_dict(c, voucher=False) for c in (
        BillCharge.objects.filter(recover_amount__gt=0)
        .exclude(status="CANCELLED")
        .select_related("account", "account__site", "recover_from", "payable")
        .order_by("-deduct_year", "-deduct_month", "-id")[:limit])]


def meta():
    return {
        "kinds": [{"value": v, "label": lab, "telecom": v in BillAccount.TELECOM}
                  for v, lab in BillAccount.Kind.choices],
        "sites": [{"id": s.id, "code": s.code, "name": s.name}
                  for s in Site.objects.order_by("code")],
        "cost_heads": [{"id": h.id, "name": h.name, "code": h.code}
                       for h in CostHead.objects.filter(
                           is_active=True, is_pool=False, trading=False,
                           rental=False).order_by("sort_order", "name")],
        "head_telecom": getattr(costing.by_code("TELECOM"), "id", None),
        "head_utilities": getattr(costing.by_code("UTILITIES"), "id", None),
        "providers": providers(), "gst_rate": gst_rate(),
    }

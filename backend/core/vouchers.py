"""Payment Voucher (M6d) — batch authorisation.

Finance batches Director-approved PRs and PYRs onto a voucher; a signatory
approves the voucher (or queries individual lines). Signatory approval is
the commitment point — it replaces the per-document authorise step. Queried
lines return to their raiser; approved lines commit their source
requisition and become payable.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import costing
from .audit import audit
from .models import (Approval, Document, DocumentRevision,
                     ImportPaymentMilestone, Payable, PaymentVoucherLine, Site)
from .numbering import next_ref

# What is ready to go on a voucher, per source type. Vouchers are strictly
# payment instruments: a PR/PYR to be paid, or an overseas TT milestone.
# An import order (IPR) never goes on a voucher — placing it is a commitment,
# not a payment; a signatory authorises the order directly (§6C.2).
AWAITING_STATUS = {"PR": "APPROVED", "PYR": "DIRECTOR_APPROVED"}
# what can go on a voucher: approved, or part paid with a balance left
PYR_PAYING = ("DIRECTOR_APPROVED", "PART_PAID")
PR_PAYING = ("APPROVED", "AUTHORISED", "PAYMENT_PROCESSING")


def ho_site():
    """The Head Office record a voucher is filed under (it batches many
    sites)."""
    site = Site.objects.filter(is_head_office=True).first()
    if site:
        return site
    site, _ = Site.objects.get_or_create(
        code="MLE", defaults={"name": "Head Office, Male'",
                              "is_head_office": True,
                              "status": Site.Status.ACTIVE})
    return site


def _source_amount(doc):
    if doc.doc_type == "PYR":
        return doc.payment_request.amount_requested
    if doc.doc_type == "PR":
        # Only the cash portion is paid on the voucher; credit is a payable.
        from .procurement import pr_cash_total
        return pr_cash_total(doc)
    return Decimal("0")


def source_currency(doc):
    """The currency a requisition would be vouchered / paid in."""
    if doc.doc_type == "PYR":
        return doc.payment_request.currency
    if doc.doc_type == "PR":
        # a local purchase pays in the currency it was bought in
        from .procurement import pr_currency
        return pr_currency(doc)
    return "MVR"


# ---- part payment (owner 2026-10-27) -------------------------------------
# A request used to go on a voucher whole. Finance can now put part of it on
# a voucher and leave the balance for a later one: each voucher line is one
# payment — all of what is owed, or a part — and what it actually paid is
# recorded on the line, with every Paid row it posts tagged to it
# (costing.for_line). The balance is worked out from the lines, never
# stored: the whole, less what is on vouchers not voided or queried, less any
# balance Finance closed with a reason. A PR is paid supplier by supplier —
# the voucher takes the cash rows Finance ticks; one supplier split in two is
# what the quotation's advance % is for.

ZERO = Decimal("0")


def _live(**kw):
    """Lines that still count: on a voucher not voided, not queried."""
    return PaymentVoucherLine.objects.filter(
        voucher__is_void=False, **kw).exclude(status="QUERIED")


def _sum(qs):
    from django.db.models import Sum
    return qs.aggregate(t=Sum("amount"))["t"] or ZERO


def pr_cash_rows(doc):
    if doc.current_revision_id is None:
        return []
    return [ln for ln in doc.current_revision.lines.all()
            if (ln.amount_cash or 0) > 0]


def pr_row_amount(ln):
    """What a cash row costs on a voucher: its cash and the GST share."""
    from .procurement import _gst_share
    cash = ln.amount_cash or ZERO
    return cash + _gst_share(ln, cash)


def line_pr_rows(line):
    """The cash rows a PR line pays — all of them for a line from before
    part payment, which listed none."""
    if line.pr_rows:
        return set(int(i) for i in line.pr_rows)
    return {r.id for r in pr_cash_rows(line.source_document)}


def pr_open_rows(doc):
    """Cash rows still to put on a voucher: not on one, not already paid."""
    taken = set()
    for ln in _live(source_document=doc):
        taken |= line_pr_rows(ln)
    return [r for r in pr_cash_rows(doc)
            if r.id not in taken and not (r.action_taken or "").strip()]


def balance(doc=None, payable=None, milestone=None):
    """{full, vouchered, closed, balance} for one thing Finance pays."""
    closed = ZERO
    if doc is not None:
        if doc.doc_type == "PR":
            full = sum((pr_row_amount(r) for r in pr_cash_rows(doc)), ZERO)
            open_amount = sum((pr_row_amount(r) for r in pr_open_rows(doc)),
                              ZERO)
            return {"full": full, "vouchered": full - open_amount,
                    "closed": ZERO, "balance": open_amount}
        full = doc.payment_request.amount_requested
        closed = doc.payment_request.closed_amount or ZERO
        vouchered = _sum(_live(source_document=doc))
    elif payable is not None:
        full = payable.amount
        closed = payable.closed_amount or ZERO
        vouchered = _sum(_live(source_payable=payable))
    else:
        full = milestone_amount(milestone)
        closed = milestone.closed_amount or ZERO
        vouchered = _sum(_live(source_milestone=milestone))
    return {"full": full, "vouchered": vouchered, "closed": closed,
            "balance": max(full - vouchered - closed, ZERO)}


def paid_so_far(doc=None, payable=None, milestone=None):
    from django.db.models import Sum
    kw = ({"source_document": doc} if doc is not None
          else {"source_payable": payable} if payable is not None
          else {"source_milestone": milestone})
    return (_live(**kw).filter(paid_amount__isnull=False)
            .aggregate(t=Sum("paid_amount"))["t"] or ZERO)


def paid_whole(doc=None, payable=None):
    """Why this has to be paid in one go, or None. A payment that does more
    than move money — restores a float, extends permits, pays a run — is not
    split (owner 2026-10-27)."""
    if payable is not None:
        if payable.payroll_line_id:
            return "a salary is paid whole"
        return None
    if doc is None or doc.doc_type != "PYR":
        return None
    from . import subcontract
    from .payments import _payroll_run_paid_here
    pr = doc.payment_request
    if pr.payment_type == "PETTY_CASH_REPLENISH":
        return "a petty-cash replenishment is paid whole"
    if pr.payment_type == "PERMIT_RENEWAL":
        return "a permit renewal is paid whole"
    if doc.salary_advances.exists():
        return "a salary advance is paid whole"
    if subcontract.is_advance_prepayment(pr):
        return "a subcontract advance is paid whole"
    if _payroll_run_paid_here(doc):
        return "a payroll run is paid whole"
    if hasattr(doc, "onboarding_fee"):
        return "an onboarding fee is paid whole"
    from .models import ProjectBond
    if ProjectBond.objects.filter(pyr=doc).exists():
        return "an insurance or bond premium is paid whole"
    return None


def share(full, line, lines, whole):
    """This line's share of an amount `full` that belongs to a request of
    `whole` paid in parts by `lines` (its own included, in order):
    proportional to what each pays. When the parts cover the whole, the last
    takes the remainder, so they add up to the cent; a balance closed early
    simply leaves its share unposted."""
    if not whole:
        return full
    parts = [(full * ln.amount / whole).quantize(Decimal("0.01"))
             for ln in lines]
    i = [ln.id for ln in lines].index(line.id)
    if i == len(lines) - 1 and sum((ln.amount for ln in lines), ZERO) >= whole:
        return full - sum(parts[:-1], ZERO)
    return parts[i]


def unpaid_line(doc=None, payable=None, milestone=None, voucher=None):
    """The approved part not yet paid — the one a payment now settles."""
    kw = ({"source_document": doc} if doc is not None
          else {"source_payable": payable} if payable is not None
          else {"source_milestone": milestone})
    qs = _live(**kw).filter(status="APPROVED", paid_amount__isnull=True)
    if voucher is not None:
        qs = qs.filter(voucher=voucher)
    return qs.order_by("id").first()


def is_final(line, doc=None, payable=None, milestone=None):
    """Does paying this line finish the request — nothing left to voucher,
    no other approved part waiting?"""
    if balance(doc=doc, payable=payable, milestone=milestone)["balance"] > 0:
        return False
    kw = ({"source_document": doc} if doc is not None
          else {"source_payable": payable} if payable is not None
          else {"source_milestone": milestone})
    return not _live(**kw).filter(status="APPROVED",
                                  paid_amount__isnull=True).exclude(
        pk=line.pk).exists()


def mark_line_paid(line, amount, actor, ref="", local=None):
    line.paid_amount = amount
    line.paid_local = local
    line.paid_on = timezone.localdate()
    line.paid_ref = (ref or "")[:120]
    line.paid_by = actor
    line.save(update_fields=["paid_amount", "paid_local", "paid_on",
                             "paid_ref", "paid_by"])


def close_balance(actor, reason, doc=None, payable=None, milestone=None):
    """Close what is left unpaid on purpose — a discount, a short delivery —
    with a reason (owner 2026-10-27). The unpaid part of the commitment
    comes off the cost ledger and the request counts as paid. For a PYR, a
    PR's credit payable and an overseas TT; a rent due, a bill, a valuation
    or a salary is cancelled or corrected where it was raised instead."""
    from . import costing as _c
    reason = (reason or "").strip()
    if not reason:
        return "Say why the balance is not being paid."
    kw = ({"source_document": doc} if doc is not None
          else {"source_payable": payable} if payable is not None
          else {"source_milestone": milestone})
    if PaymentVoucherLine.objects.filter(
            voucher__is_void=False,
            voucher__status__in=("DRAFT", "SUBMITTED"), **kw).exists():
        return "It is on a voucher still being processed — finish that first."
    if _live(status="APPROVED", paid_amount__isnull=True, **kw).exists():
        return "An approved part is still to be paid — pay or void it first."
    if paid_so_far(doc=doc, payable=payable, milestone=milestone) <= 0:
        return ("Nothing has been paid on it yet — return or cancel it "
                "instead of closing the whole of it.")
    left = balance(doc=doc, payable=payable, milestone=milestone)["balance"]
    if left <= 0:
        return "There is no balance left to close."
    now = timezone.now()
    with transaction.atomic():
        if doc is not None:
            if doc.doc_type != "PYR":
                return "A PR's suppliers are closed by withdrawing the award."
            pr = doc.payment_request
            committed = left
            if pr.currency == "USD":
                from . import fx
                committed = (left * fx.usd_rate()).quantize(Decimal("0.01"))
            if not pr.is_capitalized:
                from .payments import cost_centre
                _c.post(site=doc.site, cost_head=pr.cost_head,
                        state="COMMITTED", source="PYR", amount=-committed,
                        currency="MVR", document=doc, actor=actor,
                        **cost_centre(pr))
            obj, subject = pr, doc
            doc.status = "PAID"
            doc.save(update_fields=["status", "updated_at"])
        elif payable is not None:
            if (payable.rent_due_id or payable.bill_charge_id
                    or payable.payroll_line_id
                    or payable.document.doc_type != "PR"):
                return ("Only a supplier's credit balance is closed here — "
                        "correct a rent due, a bill, a valuation or a salary "
                        "where it was raised.")
            from .procurement import _gst_share, _ho_site, row_currency
            ln = payable.document_line
            net = (left * (ln.amount_credit or 0) / payable.amount).quantize(
                Decimal("0.01")) if payable.amount else left
            gst = _gst_share(ln, net) if ln is not None else ZERO
            head = (ln.cost_head if ln is not None and ln.cost_head_id
                    else _c.by_code(_c.MATERIALS))
            for state in ("COMMITTED", "INCURRED"):
                _c.post(site=payable.document.site, cost_head=head,
                        state=state, source="PR", amount=-net,
                        document=payable.document, document_line=ln,
                        actor=actor, currency=row_currency(ln))
                if gst > 0:
                    _c.post(site=_ho_site(), cost_head=_c.by_code(_c.INPUT_GST),
                            state=state, source="PR", amount=-gst,
                            document=payable.document, document_line=ln,
                            is_stock_pool=True, actor=actor,
                            currency=row_currency(ln))
            payable.status, payable.settled_on = "SETTLED", now.date()
            payable.settled_ref = f"balance closed: {reason}"[:200]
            payable.save(update_fields=["status", "settled_on", "settled_ref"])
            obj, subject = payable, payable.document
        else:
            from .imports import _post_split, ipr_order_total
            order = milestone.order
            total = ipr_order_total(order)
            if total:
                _post_split(order, order.document, "COMMITTED",
                            -(left / total), order.exchange_rate, actor,
                            milestone=milestone)
            milestone.status = "PAID"
            milestone.save(update_fields=["status"])
            obj, subject = milestone, order.document
        obj.closed_amount = left
        obj.closed_reason = reason[:300]
        obj.closed_by, obj.closed_at = actor, now
        obj.save(update_fields=["closed_amount", "closed_reason",
                                "closed_by", "closed_at"])
        Approval.objects.create(document=subject,
                                revision=subject.current_revision,
                                action="CLOSE_BALANCE", actor=actor,
                                actor_role=actor.role,
                                comment=f"Balance {left:,.2f} closed: {reason}")
    audit("document", subject.id, "BALANCE_CLOSED", actor=actor,
          detail={"ref": subject.ref, "closed": str(left), "reason": reason})
    return None


def milestone_amount(m):
    """A milestone's authorisation amount in the order currency — the actual TT
    the signatory authorises (realised FX is settled on payment)."""
    from .imports import ipr_order_total
    return m.due_amount(ipr_order_total(m.order))


def milestone_currency(m):
    return m.order.order_currency


def payable_amount(p):
    return p.amount


def payable_currency(p):
    """Credit payables settle in rufiyaa; a salary payable settles in whatever
    the run pays in, which for the combined staff run is USD. Hard-coding MVR
    put a USD salary on a rufiyaa voucher."""
    if p.payroll_line_id:
        return p.payroll_line.run.currency
    if p.rent_due_id:
        return p.rent_due.currency
    if p.bill_charge_id:
        return p.bill_charge.currency
    return p.currency or "MVR"


def _on_live_payable():
    """Payables sitting on a voucher still being processed (DRAFT/SUBMITTED)."""
    return PaymentVoucherLine.objects.filter(
        voucher__status__in=("DRAFT", "SUBMITTED"),
        voucher__is_void=False,
        source_payable__isnull=False).values_list(
        "source_payable_id", flat=True)


def awaiting_payables():
    """Outstanding credit payables that can be pulled onto a voucher — any of
    them (due or early, an owner may pay ahead if a vendor withdraws credit)."""
    qs = Payable.objects.filter(status="OUTSTANDING").exclude(
        id__in=_on_live_payable()).select_related(
        "document", "site", "rent_due__contract",
        "bill_charge__account").order_by("due_date", "id")
    # one part paid and a balance left still owes; a payable whose whole is
    # already on vouchers does not (a queryset kept, as callers chain on it)
    spent = [p.id for p in qs if balance(payable=p)["balance"] <= 0]
    return qs.exclude(id__in=spent)


def settle_payable(payable, actor, ref, voucher=None):
    """Finance pays a voucher-approved credit payable: posts the PAID leg for
    the source and marks the payable SETTLED (owner 2026-07-15) — or, for one
    part of a payable paid in parts, that part's share, the payable settling
    with the last (owner 2026-10-27)."""
    if payable.status != "OUTSTANDING":
        return "This payable is already settled or cancelled."
    line = unpaid_line(payable=payable, voucher=voucher)
    if line is not None:
        final = is_final(line, payable=payable)
        whole_line = final and line.amount == payable.amount
        if not whole_line:
            return _settle_part(payable, line, actor, ref, final)
        with costing.for_line(line):
            err = _settle_whole(payable, actor, ref)
        if not err:
            mark_line_paid(line, line.amount, actor, ref)
        return err
    return _settle_whole(payable, actor, ref)


def _settle_part(payable, line, actor, ref, final):
    """One part of a payable: its share of the cost Paid, tagged to the
    line; the payable and what it pays for settle with the last part."""
    if payable.payroll_line_id:
        return "A salary is paid whole."
    lines = list(_live(source_payable=payable).order_by("id"))

    def part(v):
        return share(Decimal(str(v or 0)), line, lines, payable.amount)
    today = timezone.localdate()
    with transaction.atomic(), costing.for_line(line):
        if payable.rent_due_id:
            from . import rent
            rent._post(payable.rent_due, "PAID", actor, today, part=part)
        elif payable.bill_charge_id:
            from . import bills
            bills._post(payable.bill_charge, "PAID", actor, today, part=part)
        elif payable.document.doc_type == "SVC":
            from .subcontract import _subcontract_head
            costing.post(site=payable.document.site,
                         cost_head=_subcontract_head(), state="PAID",
                         source="SUBCONTRACT", amount=part(payable.amount),
                         document=payable.document, actor=actor)
        else:
            from .procurement import post_pr_vendor_paid
            post_pr_vendor_paid(payable.document, payable.document_line,
                                actor, ref or "", side="credit", part=part)
        mark_line_paid(line, line.amount, actor, ref)
        if final:
            payable.status = "SETTLED"
            payable.settled_on = today
            payable.settled_ref = ref or ""
            payable.save(update_fields=["status", "settled_on",
                                        "settled_ref"])
            if payable.rent_due_id:
                d = payable.rent_due
                d.status, d.paid_on, d.paid_ref = "PAID", today, (ref or "")[:120]
                d.save(update_fields=["status", "paid_on", "paid_ref"])
            elif payable.bill_charge_id:
                c = payable.bill_charge
                c.status, c.paid_on, c.paid_ref = "PAID", today, (ref or "")[:120]
                c.save(update_fields=["status", "paid_on", "paid_ref"])
            elif (payable.document.doc_type == "SVC"
                  and payable.document.status == "AUTHORISED"):
                payable.document.status = "PAID"
                payable.document.save(update_fields=["status", "updated_at"])
    audit("payable", payable.id, "PAYABLE_PART_PAID", actor=actor,
          detail={"vendor": payable.vendor, "ref": ref,
                  "part": str(line.amount), "of": str(payable.amount),
                  "settled": final})
    return None


def _settle_whole(payable, actor, ref):
    if payable.rent_due_id:
        from . import rent
        rent.settle_due(payable, actor, ref or "")
        return None
    if payable.bill_charge_id:
        from . import bills
        bills.settle_charge(payable, actor, ref or "")
        return None
    if payable.document.doc_type == "SVC":
        from . import subcontract
        subcontract.settle_svc_payable(payable, actor, ref or "")
        return None
    if payable.payroll_line_id:
        from . import payroll
        payroll.settle_salary_payable(payable, actor, ref or "")
        return None
    from .procurement import post_pr_vendor_paid
    post_pr_vendor_paid(payable.document, payable.document_line, actor,
                        ref or "", side="credit")
    audit("document", payable.document_id, "PAYABLE_SETTLED", actor=actor,
          detail={"vendor": payable.vendor, "ref": ref})
    return None


def _on_live_voucher():
    """Source docs sitting on a voucher that is still being processed
    (DRAFT or SUBMITTED). Approved/cancelled vouchers are historical, and a
    withdrawn authorisation frees the source to be vouchered again — the
    source's own status is what gates re-eligibility."""
    return PaymentVoucherLine.objects.filter(
        voucher__status__in=("DRAFT", "SUBMITTED"),
        voucher__is_void=False,
        source_document__isnull=False).values_list(
        "source_document_id", flat=True)


def awaiting_voucher():
    """Director-approved PR / PYR not already on a live voucher.

    A PR reaches Finance only for its CASH side. Its credit orders are signed
    on the PO and settle later as payables, so a fully-credit PR has nothing
    to voucher and used to sit in this queue purely to be authorised — which
    is what held every purchase order behind a Finance payment run (owner
    2026-08-22).
    """
    from .procurement import pr_cash_total
    docs = Document.objects.filter(is_void=False).exclude(
        id__in=_on_live_voucher())
    out = []
    for doc in docs.filter(doc_type="PR", status__in=PR_PAYING) \
            .select_related("site"):
        # by its cash rows not yet on a voucher: a PR paid supplier by
        # supplier stays until the last is vouchered (owner 2026-10-27)
        if pr_cash_total(doc) > 0 and pr_open_rows(doc):
            out.append(doc)
    for doc in docs.filter(doc_type="PYR", status__in=PYR_PAYING) \
            .select_related("site", "payment_request"):
        if balance(doc=doc)["balance"] <= 0:
            continue
        # A payroll PYR whose salaries were raised per person is paid off the
        # payables queue, one transfer per account. Leaving it here too would
        # offer Finance two routes to the same money (owner 2026-09-10).
        if doc.payables.filter(payroll_line__isnull=False).exists():
            continue
        out.append(doc)
    return out


def _on_live_milestone():
    """Milestones sitting on a voucher still being processed."""
    return PaymentVoucherLine.objects.filter(
        voucher__status__in=("DRAFT", "SUBMITTED"),
        voucher__is_void=False,
        source_milestone__isnull=False).values_list(
        "source_milestone_id", flat=True)


def awaiting_milestones():
    """Due overseas TT milestones (on an authorised order) that still need a
    signatory to authorise them on a voucher before Finance can pay."""
    qs = ImportPaymentMilestone.objects.filter(
        status="DUE", order__document__status="AUTHORISED").exclude(
        id__in=_on_live_milestone()).select_related(
        "order__document", "order__supplier")
    spent = [m.id for m in qs if balance(milestone=m)["balance"] <= 0]
    return qs.exclude(id__in=spent)


def _resolve_debit_account(bank_account_id, currency):
    """Look up a debit account and check its currency matches the voucher's
    (a USD voucher cannot be paid from an MVR account). Returns (account, err);
    (None, None) when no account was chosen."""
    if not bank_account_id:
        return None, None
    from .models import CompanyBankAccount
    acc = CompanyBankAccount.objects.filter(pk=bank_account_id,
                                            is_active=True).first()
    if acc is None:
        return None, "That debit account no longer exists."
    if acc.currency and currency and acc.currency != currency:
        return None, (f"The {acc.currency} account {acc.label} can't pay a "
                      f"{currency} voucher — pick a {currency} account.")
    return acc, None


def _part(amounts, key, bal, whole_reason, label):
    """(amount, error): what this voucher pays of something whose balance is
    `bal` — the whole balance unless Finance entered less."""
    raw = (amounts or {}).get(key)
    if raw in (None, ""):
        return bal, None
    try:
        amount = Decimal(str(raw)).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError, TypeError):
        return None, f"{label}: the amount is not a number."
    if amount <= 0:
        return None, f"{label}: enter an amount above zero."
    if amount > bal:
        return None, (f"{label}: {amount:,.2f} is more than the "
                      f"{bal:,.2f} left to pay.")
    if amount != bal and whole_reason:
        return None, f"{label}: {whole_reason}."
    return amount, None


def create_voucher(source_refs, actor, milestone_ids=None, payable_ids=None,
                   bank_account_id=None, amounts=None, pr_rows=None):
    """Finance creates a draft voucher from chosen requisitions, overseas TT
    milestones and/or credit-vendor payables — each whole, or a part of it
    (`amounts`, keyed "DOC:<ref>", "M:<id>", "P:<id>"; for a PR, `pr_rows`
    {ref: [cash row ids]})."""
    source_refs = list(source_refs or [])
    milestone_ids = [int(m) for m in (milestone_ids or [])]
    payable_ids = [int(p) for p in (payable_ids or [])]
    if not source_refs and not milestone_ids and not payable_ids:
        return None, "Select at least one payment to voucher."
    sources = list(Document.objects.filter(ref__in=source_refs,
                                           is_void=False))
    if len(sources) != len(set(source_refs)):
        return None, "One or more references are unknown."
    plan = {}            # key -> (amount, pr row ids)
    for doc in sources:
        ok = {"PR": PR_PAYING, "PYR": PYR_PAYING}.get(doc.doc_type, ())
        if doc.status not in ok:
            return None, (f"{doc.ref} is not a Director-approved PR/PYR "
                          "awaiting payment.")
        if PaymentVoucherLine.objects.filter(
                source_document=doc,
                voucher__status__in=("DRAFT", "SUBMITTED")).exists():
            return None, f"{doc.ref} is already on a voucher."
        if doc.doc_type == "PR":
            open_rows = {r.id: r for r in pr_open_rows(doc)}
            want = [int(i) for i in ((pr_rows or {}).get(doc.ref) or [])]
            want = want or list(open_rows)
            if not want or any(i not in open_rows for i in want):
                return None, (f"{doc.ref}: pick its suppliers still to pay "
                              "— one is already on a voucher or paid.")
            plan[doc.ref] = (sum((pr_row_amount(open_rows[i]) for i in want),
                                 ZERO), want)
            continue
        bal = balance(doc=doc)["balance"]
        if bal <= 0:
            return None, f"{doc.ref} has nothing left to pay."
        amount, err = _part(amounts, f"DOC:{doc.ref}", bal,
                            paid_whole(doc=doc), doc.ref)
        if err:
            return None, err
        plan[doc.ref] = (amount, [])
    milestones = list(ImportPaymentMilestone.objects.filter(
        id__in=milestone_ids).select_related("order__document"))
    if len(milestones) != len(set(milestone_ids)):
        return None, "One or more milestones are unknown."
    for m in milestones:
        if m.status != "DUE" or m.order.document.status != "AUTHORISED":
            return None, (f"{m.order.document.ref} · {m.label} is not a due "
                          "overseas payment awaiting authorisation.")
        if PaymentVoucherLine.objects.filter(
                source_milestone=m,
                voucher__status__in=("DRAFT", "SUBMITTED")).exists():
            return None, f"{m.order.document.ref} · {m.label} is already on a " \
                         "voucher."
        label = f"{m.order.document.ref} · {m.label}"
        amount, err = _part(amounts, f"M:{m.id}",
                            balance(milestone=m)["balance"], None, label)
        if err:
            return None, err
        if amount <= 0:
            return None, f"{label} has nothing left to pay."
        plan[f"M:{m.id}"] = (amount, [])
    # One voucher pays one supplier: a TT has one payee, and that is how the
    # bank and the register see it (owner 2026-08-23).
    if len({m.order.supplier_id for m in milestones}) > 1:
        return None, ("One voucher pays one supplier — pick milestones for a "
                      "single supplier at a time.")
    payables = list(Payable.objects.filter(id__in=payable_ids)
                    .select_related("document"))
    if len(payables) != len(set(payable_ids)):
        return None, "One or more payables are unknown."
    for p in payables:
        if p.status != "OUTSTANDING":
            return None, f"The payable to {p.vendor} is no longer outstanding."
        if PaymentVoucherLine.objects.filter(
                source_payable=p,
                voucher__status__in=("DRAFT", "SUBMITTED")).exists():
            return None, f"The payable to {p.vendor} is already on a voucher."
        amount, err = _part(amounts, f"P:{p.id}", balance(payable=p)["balance"],
                            paid_whole(payable=p), f"The payable to {p.vendor}")
        if err:
            return None, err
        if amount <= 0:
            return None, f"The payable to {p.vendor} has nothing left to pay."
        plan[f"P:{p.id}"] = (amount, [])
    # A voucher is single-currency (owner 2026-07-13): every chosen payment
    # must share one currency (MVR or a foreign currency), never mixed.
    currencies = ({source_currency(d) for d in sources}
                  | {milestone_currency(m) for m in milestones}
                  | {payable_currency(p) for p in payables})
    if len(currencies) > 1:
        return None, ("A voucher must be a single currency — "
                      + " and ".join(sorted(currencies))
                      + " payments cannot share one voucher.")
    voucher_currency = next(iter(currencies), None)
    debit_account, err = _resolve_debit_account(bank_account_id,
                                                 voucher_currency)
    if err:
        return None, err
    with transaction.atomic():
        ref = next_ref("PV", None)
        pv = Document.objects.create(
            doc_type="PV", ref=ref, site=ho_site(),
            doc_date=timezone.now().date(), status="DRAFT", created_by=actor,
            debit_account=debit_account)
        revision = DocumentRevision.objects.create(
            document=pv, rev_label="R0", payload={}, created_by=actor)
        pv.current_revision = revision
        pv.save(update_fields=["current_revision"])
        for doc in sources:
            amount, rows = plan[doc.ref]
            PaymentVoucherLine.objects.create(
                voucher=pv, source_document=doc, amount=amount,
                pr_rows=rows, currency=source_currency(doc))
        for m in milestones:
            PaymentVoucherLine.objects.create(
                voucher=pv, source_milestone=m, amount=plan[f"M:{m.id}"][0],
                currency=milestone_currency(m))
        for p in payables:
            PaymentVoucherLine.objects.create(
                voucher=pv, source_payable=p, amount=plan[f"P:{p.id}"][0],
                currency=payable_currency(p))
    audit("document", pv.id, "PV_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": ref,
                  "lines": len(sources) + len(milestones) + len(payables)})
    return pv, None


def voucher_currency(pv):
    """The single currency of a voucher's lines (they are all one currency)."""
    line = pv.voucher_lines.first()
    return line.currency if line else None


def set_voucher_debit_account(pv, bank_account_id, actor):
    """Set or change the bank account a voucher is paid from. Allowed at any
    status (owner 2026-07-24: back-fill the debit account on live vouchers);
    it records which account paid, it doesn't move money."""
    acc, err = _resolve_debit_account(bank_account_id, voucher_currency(pv))
    if err:
        return None, err
    pv.debit_account = acc
    pv.save(update_fields=["debit_account", "updated_at"])
    audit("document", pv.id, "PV_DEBIT_ACCOUNT", actor=actor,
          detail={"ref": pv.ref, "account": acc.label if acc else None})
    return pv, None


def submit_voucher(pv, actor):
    if pv.status != "DRAFT":
        return "Only a draft voucher can be submitted."
    if not pv.voucher_lines.filter(status="INCLUDED").exists():
        return "The voucher has no requisitions."
    pv.status = "SUBMITTED"
    pv.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=pv, revision=pv.current_revision,
                            action="SUBMIT", actor=actor,
                            actor_role=actor.role)
    audit("document", pv.id, "PV_SUBMITTED", actor=actor,
          from_state="DRAFT", to_state="SUBMITTED", detail={"ref": pv.ref})
    from .notify import notify_document
    notify_document(pv, actor)  # a signatory must approve the voucher
    return None


def authorise_source(doc, actor):
    """Commit a requisition when its voucher line is approved — the logic
    that used to live in the per-document authorise action (§6C.2)."""
    if doc.doc_type == "PR":
        from .procurement import advance_pr_settlement, authorise_pr

        doc.status = "AUTHORISED"
        doc.save(update_fields=["status", "updated_at"])
        authorise_pr(doc, actor)  # COMMITTED + payables + credit POs
        # rows already settled by a PO advance the PR (R3 addendum) — a
        # cash vendor with no slip keeps it in PAYMENT_PROCESSING
        advance_pr_settlement(doc, actor)
    elif doc.doc_type == "PYR":
        pr = doc.payment_request
        pr.authorised_by = actor
        pr.authorised_at = timezone.now()
        pr.save(update_fields=["authorised_by", "authorised_at"])
        # The (MVR) ledger holds the commitment in MVR; a USD request is
        # committed at the company rate (the actual rate lands on payment).
        # A capitalized PYR (import charge already in landed cost) posts
        # nothing, to avoid double counting.
        from . import subcontract

        if not pr.is_capitalized and not subcontract.is_advance_prepayment(pr):
            committed = pr.amount_requested
            if pr.currency == "USD":
                from . import fx
                committed = (pr.amount_requested * fx.usd_rate()).quantize(
                    Decimal("0.01"))
            from .payments import cost_centre
            costing.post(site=doc.site, cost_head=pr.cost_head,
                         state="COMMITTED", source="PYR", amount=committed,
                         currency="MVR", document=doc, actor=actor,
                         **cost_centre(pr))
        doc.status = "AUTHORISED"
        doc.save(update_fields=["status", "updated_at"])
        # An onboarding fee is settled at authorisation — that is when the
        # money leaves — so the stage it was holding clears here rather than
        # waiting on Finance's paid stamp (owner 2026-08-16).
        if hasattr(doc, "onboarding_fee"):
            from . import onboarding
            onboarding.on_fee_settled(doc, actor)
    Approval.objects.create(document=doc, revision=doc.current_revision,
                            action="AUTHORISE", actor=actor,
                            actor_role=actor.role,
                            comment="Authorised on voucher")
    audit("document", doc.id, "AUTHORISE", actor=actor,
          to_state="AUTHORISED", detail={"ref": doc.ref})
    from .notify import notify_document
    notify_document(doc, actor)  # an authorised PYR is Finance's to pay


def authorise_milestone(milestone, pv, actor):
    """Signatory approved this overseas TT on a voucher — it's now cleared for
    Finance to execute, carrying the voucher reference (§6C.2 / book-keeping)."""
    milestone.status = "AUTHORISED"
    milestone.voucher = pv
    milestone.save(update_fields=["status", "voucher"])
    audit("document", milestone.order.document_id, "IPR_MILESTONE_AUTHORISED",
          actor=actor, to_state="AUTHORISED",
          detail={"milestone": milestone.label, "voucher": pv.ref})
    from .notify import notify_document
    notify_document(milestone.order.document, actor)  # Finance's to pay


def _return_source(doc, actor, note):
    """A queried line's requisition goes back to its raiser as a draft."""
    if doc.doc_type == "PYR":
        pr = doc.payment_request
        pr.returned_reason = "SIGNATORY_DECLINED"
        pr.returned_note = note
        pr.returned_by = actor
        pr.returned_at = timezone.now()
        pr.save(update_fields=["returned_reason", "returned_note",
                               "returned_by", "returned_at"])
    doc.status = "DRAFT"
    doc.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=doc, revision=doc.current_revision,
                            action="RETURN", actor=actor,
                            actor_role=actor.role,
                            comment=f"Queried on voucher: {note}")
    audit("document", doc.id, "RETURN", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "note": note})


def _live_rows(qs):
    """Postings in `qs` that have not been reversed."""
    from .models import CostPosting
    reversed_ids = CostPosting.objects.filter(
        reversal_of__in=qs).values_list("reversal_of_id", flat=True)
    return qs.filter(reversal_of__isnull=True).exclude(id__in=reversed_ids)


def _tagged(line):
    """Is this a payment recorded line by line (since part payment), whose
    rows carry the line?"""
    return line.paid_amount is not None or _live_rows(
        line.postings.all()).exists()


def _source_paid(line):
    """Has money actually gone out for this voucher line yet?"""
    if _tagged(line):
        return True
    if line.source_milestone_id:
        return line.source_milestone.status == "PAID"
    if line.source_payable_id:
        return line.source_payable.status == "SETTLED"
    doc = line.source_document
    if doc is None:
        return False
    from .models import CostPosting
    if doc.doc_type == "PR" and line.pr_rows and doc.current_revision_id:
        # a supplier on this part paid, the part not yet whole
        if doc.current_revision.lines.filter(id__in=line.pr_rows).exclude(
                action_taken="").exists():
            return True
    # a payment from before part payment: its rows carry no line. One
    # already reversed does not count — the request may have been
    # re-vouchered since.
    return _live_rows(CostPosting.objects.filter(
        document=doc, state="PAID", voucher_line__isnull=True)).exists()


def _unauthorise_source(doc, actor):
    """Reverse a requisition's authorisation and return it to its pre-voucher
    approved state, ready to be vouchered again."""
    if doc.doc_type == "PR":
        from .procurement import reverse_pr_authorisation
        reverse_pr_authorisation(doc, actor)   # reverse postings + payables
        for link in doc.links_to.filter(link_type="PR_PO"):  # void its POs
            po = link.from_document
            if not po.is_void:
                po.is_void = True
                po.void_reason = "Payment voucher voided"
                po.voided_by = actor
                po.voided_at = timezone.now()
                po.save(update_fields=["is_void", "void_reason",
                                       "voided_by", "voided_at"])
        if doc.current_revision:
            doc.current_revision.lines.exclude(po_ref="").update(po_ref="")
        doc.status = "APPROVED"
    elif doc.doc_type == "PYR":
        costing.reverse_document(doc, actor=actor)
        pr = doc.payment_request
        pr.authorised_by = None
        pr.authorised_at = None
        pr.save(update_fields=["authorised_by", "authorised_at"])
        doc.status = "DIRECTOR_APPROVED"
    doc.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=doc, revision=doc.current_revision,
                            action="RETURN", actor=actor, actor_role=actor.role,
                            comment="Authorisation reversed — voucher voided")
    audit("document", doc.id, "AUTH_REVERSED", actor=actor,
          to_state=doc.status, detail={"ref": doc.ref})


# ---- reversing a payment already recorded (owner 2026-10-27) ------------
# Voiding refused a voucher that had a payment recorded on it — "reverse the
# payment before voiding it" — and nothing anywhere reversed a payment, so a
# voucher paid wrongly could never be voided and its requests never paid
# again. Voiding now takes the payment back first: the Paid rows come off the
# cost ledger as negative mirrors, the paid marks are cleared, and the void
# then returns each request to Finance's queue as before. A payment whose
# effects reach beyond the ledger — a permit extended, a float restored — is
# refused by name rather than half undone.

def _reverse_rows(rows, actor):
    """A negative mirror of every posting in `rows` not already reversed,
    keeping all its links (the drill-down shows the reversal, nothing is
    erased)."""
    from .models import CostPosting
    rows = list(rows.filter(reversal_of__isnull=True))
    done = set(CostPosting.objects.filter(reversal_of__in=rows)
               .values_list("reversal_of_id", flat=True))
    for r in rows:
        if r.id in done:
            continue
        costing.post(
            site=r.site, cost_head=r.cost_head, state=r.state,
            source=r.source, amount=-r.amount, currency=r.currency,
            document=r.document, document_line=r.document_line,
            petty_cash_entry=r.petty_cash_entry, ipr_line=r.ipr_line,
            ipr_milestone=r.ipr_milestone, is_stock_pool=r.is_stock_pool,
            staff_year=r.staff_year, staff_month=r.staff_month,
            work_package=r.work_package, rent_due=r.rent_due,
            bill_charge=r.bill_charge, payroll_run=r.payroll_run,
            payroll_line=r.payroll_line, import_shipment=r.import_shipment,
            reversal_of=r, actor=actor)


def _cannot_unpay(line):
    """Why this paid line's payment can't be taken back here, or None."""
    from .models import Payable, ProjectBond
    if line.source_document_id:
        doc = line.source_document
        if doc.doc_type == "PYR":
            from . import subcontract
            pr = doc.payment_request
            if pr.payment_type == "PETTY_CASH_REPLENISH":
                return (f"{doc.ref} replenished a petty-cash float, which "
                        "was restored when it was paid")
            if doc.salary_advances.exists():
                return (f"{doc.ref} paid a salary advance that payroll "
                        "recovers")
            if subcontract.is_advance_prepayment(pr):
                return (f"{doc.ref} paid a subcontract advance that the "
                        "certificates recover")
            if pr.payment_type == "PERMIT_RENEWAL":
                return (f"{doc.ref} paid a permit renewal, which extended "
                        "the permits")
            if hasattr(doc, "onboarding_fee"):
                return (f"{doc.ref} paid an onboarding fee, which cleared "
                        "its stage")
            if ProjectBond.objects.filter(pyr=doc).exclude(
                    status__in=("PAYMENT_RAISED", "PAID")).exists():
                return f"{doc.ref} paid a premium whose cover is issued"
        if doc.doc_type == "PR" and not _tagged(line):
            settled = Payable.objects.filter(document=doc, status="SETTLED")
            if settled.exists():
                p = settled.first()
                return (f"{doc.ref}'s credit to {p.vendor} has been paid "
                        f"too ({p.settled_ref or 'its own voucher'}) — void "
                        "that payment first")
    if line.source_payable_id and not _tagged(line):
        p = line.source_payable
        dl = p.document_line
        if (not (p.rent_due_id or p.bill_charge_id or p.payroll_line_id)
                and p.document.doc_type == "PR" and dl is not None
                and (dl.amount_cash or 0) > 0 and (dl.amount_credit or 0) > 0):
            return (f"the balance to {p.vendor} was half of an advance-and-"
                    "balance row")
    return None


def _unpay_part(line, actor):
    """A payment recorded on its line (since part payment): exactly the rows
    it posted come off, its marks clear, and the source is restated from
    what its other parts still hold."""
    from .models import ProjectBond
    _reverse_rows(line.postings.all(), actor)
    local = line.paid_local
    line.paid_amount = line.paid_local = line.paid_on = line.paid_by = None
    line.paid_ref = ""
    line.save(update_fields=["paid_amount", "paid_local", "paid_on",
                             "paid_by", "paid_ref"])
    if line.source_milestone_id:
        m = line.source_milestone
        m.mvr_paid = max((m.mvr_paid or ZERO) - (local or ZERO), ZERO) or None
        m.status = "AUTHORISED"
        m.save(update_fields=["mvr_paid", "status"])
        return m.order.document
    if line.source_payable_id:
        p = line.source_payable
        if p.status == "SETTLED":
            p.status, p.settled_on, p.settled_ref = "OUTSTANDING", None, ""
            p.save(update_fields=["status", "settled_on", "settled_ref"])
            for obj in (p.rent_due if p.rent_due_id else None,
                        p.bill_charge if p.bill_charge_id else None):
                if obj is not None and obj.status == "PAID":
                    obj.status, obj.paid_on, obj.paid_ref = "RAISED", None, ""
                    obj.save(update_fields=["status", "paid_on", "paid_ref"])
            if p.document_id and p.document.status == "PAID":
                p.document.status = "AUTHORISED"
                p.document.save(update_fields=["status", "updated_at"])
        return p.document or p.rent_due or p.bill_charge
    doc = line.source_document
    if doc.doc_type == "PYR":
        pr = doc.payment_request
        pr.amount_paid = paid_so_far(doc=doc) or None
        if pr.amount_paid is None:
            pr.fx_rate = pr.paid_date = pr.paid_by = None
            pr.payment_ref = pr.variance_reason = ""
        pr.save(update_fields=["amount_paid", "fx_rate", "paid_date",
                               "paid_by", "payment_ref", "variance_reason"])
        ProjectBond.objects.filter(pyr=doc, status="PAID").update(
            status="PAYMENT_RAISED")
    else:
        doc.current_revision.lines.filter(
            id__in=line_pr_rows(line)).update(action_taken="")
    doc.status = "AUTHORISED"
    doc.save(update_fields=["status", "updated_at"])
    if doc.doc_type == "PR":
        from .procurement import advance_pr_settlement
        advance_pr_settlement(doc, actor)
    return doc


def _unpay(line, actor):
    """Take a recorded payment back: its Paid rows off the ledger, its paid
    marks cleared, the source back where the signatory left it."""
    from .models import CostPosting, ProjectBond
    if _tagged(line) or (line.source_document_id and line.pr_rows):
        subject = _unpay_part(line, actor)
        if not hasattr(subject, "current_revision"):
            subject = None
        if subject is not None:
            Approval.objects.create(
                document=subject, revision=subject.current_revision,
                action="RETURN", actor=actor, actor_role=actor.role,
                comment=f"Payment reversed — voucher {line.voucher.ref} voided")
        audit("voucher_line", line.id, "PAYMENT_REVERSED", actor=actor,
              detail={"voucher": line.voucher.ref, "amount": str(line.amount),
                      "currency": line.currency})
        return
    rows = CostPosting.objects.none()
    if line.source_milestone_id:
        m = line.source_milestone
        rows = CostPosting.objects.filter(ipr_milestone=m, state="PAID")
        _reverse_rows(rows, actor)
        m.status = "AUTHORISED"
        m.tt_ref, m.mvr_paid, m.actual_rate = "", None, None
        m.paid_by, m.paid_at = None, None
        m.save(update_fields=["status", "tt_ref", "mvr_paid", "actual_rate",
                              "paid_by", "paid_at"])
        subject = m.order.document
    elif line.source_payable_id:
        p = line.source_payable
        subject = p.document
        if p.rent_due_id:
            rows = CostPosting.objects.filter(rent_due=p.rent_due,
                                              state="PAID")
            due = p.rent_due
            due.status, due.paid_on, due.paid_ref = "RAISED", None, ""
            due.save(update_fields=["status", "paid_on", "paid_ref"])
        elif p.bill_charge_id:
            rows = CostPosting.objects.filter(bill_charge=p.bill_charge,
                                              state="PAID")
            c = p.bill_charge
            c.status, c.paid_on, c.paid_ref = "RAISED", None, ""
            c.save(update_fields=["status", "paid_on", "paid_ref"])
        elif p.payroll_line_id:
            rows = CostPosting.objects.filter(payroll_line=p.payroll_line,
                                              state="PAID")
        elif p.document.doc_type == "SVC":
            rows = CostPosting.objects.filter(document=p.document,
                                              state="PAID",
                                              source="SUBCONTRACT")
        else:
            rows = CostPosting.objects.filter(document=p.document,
                                              document_line=p.document_line,
                                              state="PAID")
        _reverse_rows(rows, actor)
        p.status, p.settled_on, p.settled_ref = "OUTSTANDING", None, ""
        p.save(update_fields=["status", "settled_on", "settled_ref"])
        if (p.payroll_line_id or p.document.doc_type == "SVC") \
                and p.document.status == "PAID":
            p.document.status = "AUTHORISED"
            p.document.save(update_fields=["status", "updated_at"])
    else:
        doc = subject = line.source_document
        if doc.doc_type == "PYR":
            _reverse_rows(CostPosting.objects.filter(
                document=doc, state__in=("PAID", "INCURRED")), actor)
            pr = doc.payment_request
            pr.amount_paid = pr.fx_rate = pr.paid_date = pr.paid_by = None
            pr.payment_ref = pr.variance_reason = ""
            pr.save(update_fields=["amount_paid", "fx_rate", "paid_date",
                                   "paid_by", "payment_ref",
                                   "variance_reason"])
            ProjectBond.objects.filter(pyr=doc, status="PAID").update(
                status="PAYMENT_RAISED")
        else:   # a PR's cash side
            _reverse_rows(CostPosting.objects.filter(document=doc,
                                                     state="PAID"), actor)
            if doc.current_revision:
                doc.current_revision.lines.filter(
                    amount_cash__gt=0).exclude(action_taken="").update(
                    action_taken="")
        doc.status = "AUTHORISED"
        doc.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=subject,
                            revision=subject.current_revision,
                            action="RETURN", actor=actor,
                            actor_role=actor.role,
                            comment=f"Payment reversed — voucher "
                                    f"{line.voucher.ref} voided")
    audit("document", subject.id, "PAYMENT_REVERSED", actor=actor,
          detail={"ref": subject.ref, "voucher": line.voucher.ref,
                  "amount": str(line.amount), "currency": line.currency})


def void_voucher(pv, actor, reason):
    """Void a payment voucher and unwind its commitments: reverse each approved
    line's source (postings, payables, generated POs) and return the source to
    its pre-voucher approved state so it can be re-vouchered; free a milestone
    back to DUE. Payments recorded on it are reversed first (owner
    2026-10-27); a request paid in parts loses only this voucher's part."""
    if pv.is_void:
        return "This voucher is already void."
    if not (reason or "").strip():
        return "A reason is required to void a voucher."
    lines = list(pv.voucher_lines.select_related(
        "source_document", "source_milestone", "source_payable"))
    paid = [ln for ln in lines if ln.status == "APPROVED" and _source_paid(ln)]
    for ln in paid:
        why = _cannot_unpay(ln)
        if why:
            return (f"This voucher can't be voided here: {why}. That can't "
                    "be undone automatically — ask Admin.")
    with transaction.atomic():
        # payments recorded on it are taken back first, then unwound below
        for ln in paid:
            _unpay(ln, actor)
        for ln in lines:
            if ln.status == "APPROVED":
                if ln.source_document_id:
                    doc = ln.source_document
                    others = _live(source_document=doc,
                                   status="APPROVED").exclude(voucher=pv)
                    if not others.exists():
                        _unauthorise_source(doc, actor)
                    elif doc.doc_type == "PYR":
                        # other parts stand on other vouchers: only this part
                        # goes, the authorisation and commitment stay
                        waiting = others.filter(paid_amount__isnull=True)
                        doc.status = "AUTHORISED" if waiting.exists() \
                            else "PART_PAID"
                        doc.save(update_fields=["status", "updated_at"])
                elif ln.source_milestone_id:
                    m = ln.source_milestone
                    waiting = _live(source_milestone=m, status="APPROVED",
                                    paid_amount__isnull=True).exclude(
                        voucher=pv)
                    m.status = "AUTHORISED" if waiting.exists() else "DUE"
                    m.voucher = None
                    m.save(update_fields=["status", "voucher"])
                # a payable line posted nothing at approval; marking the PV
                # void (below) releases the payable to be vouchered again.
            # Whatever its state, the line lets go of the milestone. The FK
            # is PROTECT, so a voided voucher that keeps holding one freezes
            # that order's payment schedule for good: the schedule is
            # replaced by deleting its rows, and the delete cannot run. Only
            # APPROVED lines were being unwound, so an INCLUDED line on a
            # voucher voided before approval held on — which is exactly what
            # happened to IPR-047 (owner 2026-08-31).
            if ln.source_milestone_id:
                m = ln.source_milestone
                ln.source_note = (ln.source_note
                                  or f"{m.order.document.ref} — {m.label}")
                ln.source_milestone = None
                ln.save(update_fields=["source_note", "source_milestone"])
        pv.is_void = True
        pv.void_reason = reason
        pv.voided_by = actor
        pv.voided_at = timezone.now()
        pv.save(update_fields=["is_void", "void_reason", "voided_by",
                               "voided_at"])
        Approval.objects.create(document=pv, revision=pv.current_revision,
                                action="VOID", actor=actor,
                                actor_role=actor.role, comment=reason)
    audit("document", pv.id, "DOC_VOIDED", actor=actor, from_state=pv.status,
          to_state="VOID", detail={"ref": pv.ref, "reason": reason,
                                   "payments_reversed": len(paid)})
    if paid:
        # money that was marked as gone is back on the books: the Director
        # hears of it (owner 2026-10-27)
        from .notify import _role_users, notify_user
        for u in _role_users("DIRECTOR"):
            notify_user(u, f"{pv.ref} voided — {len(paid)} payment"
                           f"{'s' if len(paid) != 1 else ''} reversed",
                        body=f"{reason[:120]} · by {actor.get_full_name() or actor.username}")
    return None


def approve_voucher(pv, actor, queried_ids=None, note=""):
    """Signatory approves the voucher. Queried lines return to their
    raiser; the rest commit their source requisition."""
    if pv.status != "SUBMITTED":
        return "Only a submitted voucher can be approved."
    # Voiding leaves `status` where it stood and raises is_void, so a voided
    # voucher still reads SUBMITTED. It is out of the approval queue, but
    # nothing here said no (owner 2026-09-01).
    if pv.is_void:
        return "This voucher has been voided."
    queried_ids = set(queried_ids or [])
    with transaction.atomic():
        for line in pv.voucher_lines.filter(status="INCLUDED") \
                .select_related("source_document",
                                "source_milestone__order__document"):
            if line.id in queried_ids:
                line.status = "QUERIED"
                line.query_note = note
                line.save(update_fields=["status", "query_note"])
                # a queried milestone simply stays DUE (nothing to unwind);
                # a queried requisition returns to its raiser — unless part
                # of it is already authorised or paid, when only this part
                # drops and the rest stands (owner 2026-10-27)
                if line.source_document_id and not _live(
                        source_document=line.source_document).exclude(
                        pk=line.pk).exists():
                    _return_source(line.source_document, actor,
                                   note or "queried")
            else:
                line.status = "APPROVED"
                line.save(update_fields=["status"])
                if line.source_milestone_id:
                    authorise_milestone(line.source_milestone, pv, actor)
                elif line.source_document_id:
                    doc = line.source_document
                    first = not _live(source_document=doc,
                                      status="APPROVED").exclude(
                        pk=line.pk).exists()
                    if doc.status in ("DIRECTOR_APPROVED", "APPROVED") or (
                            doc.doc_type == "PR" and first):
                        # the first part authorises the whole — a PR whose
                        # credit order was signed first is already PAYMENT_
                        # PROCESSING, its cash still unauthorised (22 such
                        # PRs could never be vouchered, owner 2026-10-27)
                        authorise_source(doc, actor)
                    elif doc.doc_type == "PYR" and doc.status == "PART_PAID":
                        # a balance: authorised already, committed already
                        doc.status = "AUTHORISED"
                        doc.save(update_fields=["status", "updated_at"])
                        Approval.objects.create(
                            document=doc, revision=doc.current_revision,
                            action="AUTHORISE", actor=actor,
                            actor_role=actor.role,
                            comment=f"Balance authorised on {pv.ref}")
                # A payable line: the commitment was already authorised at PR
                # time, so approval simply green-lights the payment — Finance
                # settles it (posts PAID + marks the payable SETTLED).
        pv.status = "APPROVED"
        pv.save(update_fields=["status", "updated_at"])
        Approval.objects.create(document=pv, revision=pv.current_revision,
                                action="APPROVE", actor=actor,
                                actor_role=actor.role, comment=note)
    audit("document", pv.id, "PV_APPROVED", actor=actor,
          from_state="SUBMITTED", to_state="APPROVED",
          detail={"ref": pv.ref, "queried": len(queried_ids)})
    return None

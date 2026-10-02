"""QuickBooks-style working on top of the ledger (FINANCE_BUILD_BRIEF.md,
stage 2): transactions entered on forms — expense, deposit, transfer — that
post their own journal; a register per bank and cash account; and the two
statements, Profit & Loss and Balance Sheet.

GST follows MIRA's published rules (brief, "What MIRA's published guidance
says"): input tax on a purchase is recoverable only where a valid tax
invoice is held — otherwise it is part of the cost; exempt and out-of-scope
lines carry no tax; the rate is the company setting, never a constant here.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from . import ledger
from .audit import audit
from .ledger import BASE, ZERO, q2
from .models import (JournalLine, LedgerAccount, LedgerTxn, LedgerTxnLine)

T = LedgerAccount.Type
GST = LedgerTxnLine.Gst
MONEY_TYPES = ("BANK", "CREDIT_CARD")     # what a register is kept for


def gst_rate():
    from .procurement import company_gst_rate
    return company_gst_rate()


def meta():
    """What the forms need: the GST rate and treatments, payees to suggest."""
    from .models import Supplier
    return {
        "gst_rate": gst_rate(),
        "gst_treatments": [{"value": v, "label": lab} for v, lab in GST.choices],
        "payees": sorted({s for s in Supplier.objects.filter(is_active=True)
                          .values_list("name", flat=True)}
                         | set(LedgerTxn.objects.exclude(party="")
                               .values_list("party", flat=True)),
                         key=str.lower)[:1500],
        "settings": ledger.settings_dict(),
    }


# ---- building the journal a form stands for ---------------------------------

def _jl(account, debit=ZERO, credit=ZERO, **kw):
    base = {"account": account, "debit": q2(debit), "credit": q2(credit),
            "description": "", "currency": BASE, "amount_fc": None,
            "fx_rate": None, "site": None, "project": None,
            "cost_head": None, "party": ""}
    base.update(kw)
    return base


def _fc(account, amount, rate):
    """The foreign-currency side of a line on an account held in another
    currency: its own amount and the rate."""
    if not account.currency:
        return {}
    return {"currency": account.currency, "amount_fc": q2(amount),
            "fx_rate": rate}


def _journal_lines(txn, lines):
    """The balanced entry for an expense or a deposit. Amounts on the form
    are in the bank account's currency; the books are in rufiyaa."""
    rate = txn.fx_rate or Decimal("1")
    expense = txn.type == "EXPENSE"
    input_gst = ledger.account_for("INPUT_GST")
    output_gst = ledger.account_for("OUTPUT_GST")
    out, total_mvr, tax_mvr = [], ZERO, ZERO
    for ln in lines:
        net = q2(ln["amount"] * rate)
        gst = q2(ln["gst_amount"] * rate)
        claimable = expense and gst and txn.tax_invoice_held
        # GST on a purchase with no valid tax invoice is not recoverable
        # (MIRA): it stays in the cost of what was bought.
        cost = net if (not expense or claimable or not gst) else net + gst
        side = {"debit": cost} if expense else {"credit": net}
        out.append(_jl(ln["account"], description=ln["description"],
                       site=ln["site"], project=ln["project"],
                       party=txn.party, **side))
        total_mvr += cost if expense else net
        if gst and (claimable or not expense):
            tax_mvr += gst
    if tax_mvr:
        acc = input_gst if expense else output_gst
        if acc is None:
            raise ValueError("The chart has no GST account for this — set up "
                             "the standard chart or restore the account.")
        out.append(_jl(acc, party=txn.party, description=(
            f"GST · {txn.tax_invoice_no}" if txn.tax_invoice_no else "GST"),
            **({"debit": tax_mvr} if expense else {"credit": tax_mvr})))
        total_mvr += tax_mvr
    bank = _jl(txn.account, party=txn.party, description=txn.reference,
               **({"credit": total_mvr} if expense else {"debit": total_mvr}),
               **_fc(txn.account, txn.amount, rate))
    return [bank] + out, total_mvr


def _transfer_lines(txn):
    """Money moved between two of the company's own accounts. Rufiyaa value:
    the rufiyaa side if there is one, else the amount at the rate."""
    src, dst = txn.account, txn.to_account
    if not src.currency:
        mvr = q2(txn.amount)
    elif not dst.currency:
        mvr = q2(txn.amount_to)
    else:
        mvr = q2(txn.amount * (txn.fx_rate or 0))
    arrive = txn.amount_to if txn.amount_to is not None else txn.amount

    def side(acc, amt):
        if not acc.currency or not amt:
            return {}
        return {"currency": acc.currency, "amount_fc": q2(amt),
                "fx_rate": (mvr / amt).quantize(Decimal("0.000001"))}
    return [_jl(dst, debit=mvr, description=txn.reference,
                **side(dst, arrive)),
            _jl(src, credit=mvr, description=txn.reference,
                **side(src, txn.amount))], mvr


# ---- saving a form -----------------------------------------------------------

def _dec(v, what):
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:
        raise ValueError(f"{what} is not a number.")


def _clean(data, typ):
    """Validated header + lines from what the form sent. Raises ValueError."""
    from .models import Project, Site
    d = ledger._as_date(data.get("date"))
    if d is None:
        raise ValueError("Give the date.")
    account = LedgerAccount.objects.filter(pk=data.get("account")).first()
    if account is None or account.type not in MONEY_TYPES or account.is_group:
        raise ValueError("Pick the bank or cash account.")
    if not account.is_active:
        raise ValueError(f"{account.name} is closed.")
    head = {
        "date": d, "account": account, "to_account": None,
        "party": (data.get("party") or "").strip()[:160],
        "party_tin": (data.get("party_tin") or "").strip()[:40],
        "reference": (data.get("reference") or "").strip()[:80],
        "memo": (data.get("memo") or "").strip(),
        "currency": account.currency or BASE, "fx_rate": None,
        "amount_to": None,
        "tax_invoice_no": (data.get("tax_invoice_no") or "").strip()[:60],
        "tax_invoice_date": ledger._as_date(data.get("tax_invoice_date")),
        "tax_invoice_held": bool(data.get("tax_invoice_held")),
    }
    if account.currency:
        head["fx_rate"] = _dec(data.get("fx_rate"), "The rate")
        if head["fx_rate"] <= 0:
            raise ValueError(f"Give the {account.currency} rate to rufiyaa.")

    if typ == "TRANSFER":
        to = LedgerAccount.objects.filter(pk=data.get("to_account")).first()
        if to is None or to.type not in MONEY_TYPES or to.is_group:
            raise ValueError("Pick the account the money went to.")
        if to.id == account.id:
            raise ValueError("The two accounts are the same.")
        amount = q2(_dec(data.get("amount"), "The amount"))
        if amount <= 0:
            raise ValueError("Give the amount transferred.")
        head.update(to_account=to, amount=amount)
        if (to.currency or BASE) != (account.currency or BASE):
            arrive = q2(_dec(data.get("amount_to"), "The amount received"))
            if arrive <= 0:
                raise ValueError(
                    f"The accounts are in different currencies — give the "
                    f"{to.currency or BASE} amount that arrived.")
            head["amount_to"] = arrive
            head["fx_rate"] = None
        elif not account.currency:
            head["fx_rate"] = None
        return head, []

    rate = gst_rate()
    lines = []
    for n, r in enumerate(data.get("lines") or [], 1):
        amt = q2(_dec(r.get("amount"), f"Line {n}: the amount"))
        if not r.get("account") and amt == ZERO:
            continue
        acc = LedgerAccount.objects.filter(pk=r.get("account")).first()
        if acc is None:
            raise ValueError(f"Line {n}: pick the account.")
        if acc.is_group or not acc.is_active:
            raise ValueError(f"Line {n}: {acc.code} {acc.name} can't take "
                             "postings.")
        if acc.currency:
            raise ValueError(f"Line {n}: {acc.name} is a {acc.currency} "
                             "account — move money between accounts with a "
                             "transfer.")
        if amt <= ZERO:
            raise ValueError(f"Line {n}: the amount must be more than zero.")
        treat = r.get("gst_treatment") or "NONE"
        if treat not in GST.values:
            raise ValueError(f"Line {n}: unknown GST treatment.")
        gst = ZERO
        if treat == "STANDARD":
            # the form may round or correct the tax to the invoice's figure
            sent = r.get("gst_amount")
            gst = q2(_dec(sent, f"Line {n}: the GST")) if sent not in (
                None, "") else q2(amt * rate / 100)
            if gst < ZERO or gst > amt:
                raise ValueError(f"Line {n}: the GST amount looks wrong.")
        lines.append({
            "account": acc, "description": (r.get("description") or "")[:300],
            "amount": amt, "gst_treatment": treat,
            "gst_rate": rate if treat == "STANDARD" else ZERO,
            "gst_amount": gst,
            "site": Site.objects.filter(pk=r["site"]).first()
            if r.get("site") else None,
            "project": Project.objects.filter(pk=r["project"]).first()
            if r.get("project") else None,
        })
    if not lines:
        raise ValueError("Add at least one line.")
    if typ == "EXPENSE" and not head["party"]:
        raise ValueError("Say who was paid.")
    head["amount"] = sum((ln["amount"] + ln["gst_amount"] for ln in lines),
                         ZERO)
    return head, lines


def save_txn(typ, data, actor, txn=None, attachment=None):
    """Create a transaction, or change one — which reverses its entry and
    posts a new one, so the books keep both. Returns (txn, error)."""
    from .numbering import next_ref
    if typ not in LedgerTxn.Type.values:
        return None, "Unknown kind of transaction."
    if txn is not None and txn.status == "VOID":
        return None, "A void transaction can't be changed."
    try:
        head, lines = _clean(data, typ)
        with transaction.atomic():
            if txn is None:
                txn = LedgerTxn(type=typ, created_by=actor,
                                number=next_ref(LedgerTxn.PREFIX[typ], None))
            else:
                old = txn.journal
                if old is not None:
                    _, msg = ledger.reverse(old, actor, on=old.date,
                                            reason=f"{txn.number} changed")
                    if msg:
                        raise ValueError(
                            msg.replace("entry", "transaction") if "closed"
                            in msg else msg)
            for k, v in head.items():
                setattr(txn, k, v)
            txn.updated_by = actor
            if attachment is not None:
                txn.attachment = attachment
            jl, mvr = (_transfer_lines(txn) if typ == "TRANSFER"
                       else _journal_lines(txn, lines))
            txn.amount_mvr = mvr
            txn.save()
            txn.lines.all().delete()
            LedgerTxnLine.objects.bulk_create([
                LedgerTxnLine(txn=txn, line_no=i, **ln)
                for i, ln in enumerate(lines, 1)])
            label = {"EXPENSE": "Expense", "DEPOSIT": "Deposit",
                     "TRANSFER": "Transfer"}[typ]
            who = txn.party or (f"{txn.account.name} → {txn.to_account.name}"
                                if txn.to_account_id else "")
            txn.journal = ledger.post_entry(
                on=txn.date, actor=actor, kind="TXN",
                memo=" · ".join(x for x in (f"{label} {txn.number}", who,
                                            txn.memo) if x),
                lines=jl, source_type="TXN", source_id=txn.id,
                source_ref=txn.number)
            txn.save(update_fields=["journal"])
    except ValueError as exc:
        return None, str(exc)
    audit("ledger_txn", txn.id, "TXN_SAVED", actor=actor,
          detail={"number": txn.number, "type": typ,
                  "amount_mvr": str(txn.amount_mvr),
                  "journal": txn.journal.ref})
    return txn, None


def void_txn(txn, actor, reason):
    if txn.status == "VOID":
        return f"{txn.number} is already void."
    reason = (reason or "").strip()
    if not reason:
        return "Say why it is being voided."
    with transaction.atomic():
        if txn.journal_id:
            _, msg = ledger.reverse(txn.journal, actor, on=txn.journal.date,
                                    reason=f"{txn.number} voided — {reason}")
            if msg:
                return msg
        txn.status = "VOID"
        txn.void_reason = reason[:300]
        txn.updated_by = actor
        txn.save(update_fields=["status", "void_reason", "updated_by",
                                "updated_at"])
    audit("ledger_txn", txn.id, "TXN_VOIDED", actor=actor,
          detail={"number": txn.number, "reason": reason[:200]})
    return None


# ---- the register ------------------------------------------------------------

def register(account, date_from=None, date_to=None):
    """A bank or cash account as its cheque book reads: each movement with
    who, what for, money out, money in and the balance after it. In the
    account's own currency where it is held in one.

    An entry and its same-day reversal cancel out and are left off — that is
    what an edited or voided transaction leaves behind — so the register
    reads like the statement. They remain in the journals."""
    date_to = date_to or timezone.localdate()
    date_from = date_from or ledger.books_start()
    fc = bool(account.currency)
    base = JournalLine.objects.filter(account=account, entry__status="POSTED")

    def val(ln):
        if not fc:
            return ln.debit - ln.credit
        amt = ln.amount_fc or ZERO
        return amt if ln.debit else -amt

    opening = sum((val(ln) for ln in base.filter(entry__date__lt=date_from)),
                  ZERO)
    rows, bal, paid, got = [], opening, ZERO, ZERO
    qs = (base.filter(entry__date__gte=date_from, entry__date__lte=date_to)
          .select_related("entry", "entry__reversal_of", "entry__reversed_by")
          .order_by("entry__date", "entry_id", "line_no"))
    txns = {t.journal_id: t for t in LedgerTxn.objects.filter(
        journal_id__in=[ln.entry_id for ln in qs])
        .select_related("to_account", "account")
        .prefetch_related("lines__account")}
    for ln in qs:
        e = ln.entry
        mirror = e.reversal_of if e.reversal_of_id else getattr(
            e, "reversed_by", None)
        if mirror is not None and mirror.date == e.date:
            continue
        v = val(ln)
        bal += v
        t = txns.get(e.id)
        tl = list(t.lines.all()) if t else []
        if t and t.type == "TRANSFER":
            other = t.to_account if t.account_id == account.id else t.account
            split = f"Transfer · {other.name}"
        elif len(tl) == 1:
            # one line and its GST is one thing bought, not a split
            split = f"{tl[0].account.code} {tl[0].account.name}"
        else:
            others = list(e.lines.exclude(pk=ln.pk).select_related("account"))
            split = (f"{others[0].account.code} {others[0].account.name}"
                     if len(others) == 1 else "— split —" if others else "")
        rows.append({
            "entry": e.id, "ref": e.ref, "date": e.date,
            "txn": t.id if t else None, "txn_type": t.type if t else None,
            "number": t.number if t else e.ref,
            "payee": (t.party if t and t.party else ln.party) or "",
            "memo": ((t.memo or (tl[0].description if tl else "")) if t
                     else (ln.description or e.memo)),
            "reference": t.reference if t else "",
            "split": split,
            "payment": -v if v < 0 else ZERO, "deposit": v if v > 0 else ZERO,
            "balance": bal,
        })
        if v < 0:
            paid += -v
        else:
            got += v
    return {"account": {"id": account.id, "code": account.code,
                        "name": account.name,
                        "currency": account.currency or BASE},
            "date_from": date_from, "date_to": date_to, "opening": opening,
            "payments": paid, "deposits": got, "closing": bal, "rows": rows}


# ---- the statements ------------------------------------------------------------

def _balances(date_from, date_to, types):
    """account id → debit less credit over the period (posted only)."""
    qs = JournalLine.objects.filter(entry__status="POSTED",
                                    account__type__in=types)
    if date_from:
        qs = qs.filter(entry__date__gte=date_from)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    return {r["account"]: (r["d"] or ZERO) - (r["c"] or ZERO)
            for r in qs.values("account").annotate(d=Sum("debit"),
                                                   c=Sum("credit"))}


def _section(typ, bal, accounts):
    """A statement section: the accounts of one type, sub-accounts indented
    under their parents with a subtotal, on the type's normal side."""
    sign = 1 if typ in LedgerAccount.DEBIT_NORMAL else -1
    kids = {}
    for a in accounts:
        if a.type == typ:
            kids.setdefault(a.parent_id, []).append(a)
    rows = []

    def walk(pid, depth):
        total = ZERO
        for a in sorted(kids.get(pid, []), key=lambda x: x.code):
            own = bal.get(a.id, ZERO) * sign
            at = len(rows)
            rows.append(None)
            sub = walk(a.id, depth + 1)
            amount = own + sub
            if amount == ZERO and not sub:
                if own == ZERO:
                    rows.pop(at)
                    continue
            rows[at] = {"account": a.id, "code": a.code, "name": a.name,
                        "depth": depth, "is_group": a.is_group or bool(sub),
                        "amount": amount}
            total += amount
        return total
    # top level: accounts whose parent is not of this type's tree
    ids = {a.id for a in accounts if a.type == typ}
    tops = [a for a in accounts if a.type == typ
            and (a.parent_id is None or a.parent_id not in ids)]
    kids[None] = tops
    total = walk(None, 0)
    return {"type": typ, "label": dict(T.choices)[typ],
            "rows": [r for r in rows if r], "total": total}


def profit_and_loss(date_from=None, date_to=None):
    date_to = date_to or timezone.localdate()
    date_from = date_from or date(date_to.year, 1, 1)
    date_from = max(date_from, ledger.books_start())
    types = ("INCOME", "COGS", "EXPENSE", "OTHER_INCOME", "OTHER_EXPENSE")
    bal = _balances(date_from, date_to, types)
    accounts = list(LedgerAccount.objects.filter(type__in=types))
    sec = {t: _section(t, bal, accounts) for t in types}
    gross = sec["INCOME"]["total"] - sec["COGS"]["total"]
    operating = gross - sec["EXPENSE"]["total"]
    net = operating + sec["OTHER_INCOME"]["total"] - sec["OTHER_EXPENSE"]["total"]
    return {"date_from": date_from, "date_to": date_to, "sections": sec,
            "gross_profit": gross, "operating_profit": operating,
            "net_profit": net}


def balance_sheet(as_of=None):
    as_of = as_of or timezone.localdate()
    bs = LedgerAccount.BALANCE_SHEET
    bal = _balances(None, as_of, bs)
    accounts = list(LedgerAccount.objects.filter(type__in=bs))
    sec = {t: _section(t, bal, accounts) for t in bs}
    # Profit not yet moved to retained earnings: this year's, and any
    # earlier year not yet closed. Shown as their own lines under equity, as
    # QuickBooks does, so the sheet balances on any date.
    year_start = max(date(as_of.year, 1, 1), ledger.books_start())
    pl = ("INCOME", "COGS", "EXPENSE", "OTHER_INCOME", "OTHER_EXPENSE")
    this_year = -sum(_balances(year_start, as_of, pl).values(), ZERO)
    agg = JournalLine.objects.filter(
        entry__status="POSTED", account__type__in=pl,
        entry__date__lt=year_start).aggregate(d=Sum("debit"), c=Sum("credit"))
    earlier = (agg["c"] or ZERO) - (agg["d"] or ZERO)
    current_assets = sum(sec[t]["total"] for t in
                         ("BANK", "AR", "OTHER_CURRENT_ASSET"))
    assets = (current_assets + sec["FIXED_ASSET"]["total"]
              + sec["OTHER_ASSET"]["total"])
    current_liab = sum(sec[t]["total"] for t in
                       ("AP", "CREDIT_CARD", "OTHER_CURRENT_LIABILITY"))
    liabilities = current_liab + sec["LONG_TERM_LIABILITY"]["total"]
    equity = sec["EQUITY"]["total"] + this_year + earlier
    return {"as_of": as_of, "sections": sec,
            "current_assets": current_assets, "total_assets": assets,
            "current_liabilities": current_liab,
            "total_liabilities": liabilities,
            "net_profit_this_year": this_year,
            "net_profit_earlier_years": earlier,
            "total_equity": equity,
            "total_liabilities_and_equity": liabilities + equity,
            "balanced": assets == liabilities + equity}


def txn_filter(qs, params):
    if params.get("type"):
        qs = qs.filter(type=params["type"])
    if params.get("account"):
        qs = qs.filter(Q(account_id=params["account"])
                       | Q(to_account_id=params["account"]))
    d1, d2 = ledger._as_date(params.get("from")), ledger._as_date(params.get("to"))
    if d1:
        qs = qs.filter(date__gte=d1)
    if d2:
        qs = qs.filter(date__lte=d2)
    t = (params.get("q") or "").strip()
    if t:
        qs = qs.filter(Q(number__icontains=t) | Q(party__icontains=t)
                       | Q(memo__icontains=t) | Q(reference__icontains=t)
                       | Q(tax_invoice_no__icontains=t))
    return qs

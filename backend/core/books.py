"""QuickBooks-style working on top of the ledger (FINANCE_BUILD_BRIEF.md,
stage 2): transactions entered on forms — expense, deposit, transfer, bill
and its payment, sales invoice and its receipt — that post their own
journal; a register per bank and cash account; suppliers and customers with
what is owed either way; and the two statements, Profit & Loss and Balance
Sheet.

GST follows MIRA's published rules (brief, "What MIRA's published guidance
says"): input tax on a purchase is recoverable only where a valid tax
invoice is held — otherwise it is part of the cost; exempt and out-of-scope
lines carry no tax; the rate is the company setting, never a constant here.
"""
from datetime import date
from decimal import Decimal

from datetime import timedelta

from django.db import transaction
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import ledger
from .audit import audit
from .ledger import BASE, ZERO, q2
from .models import (JournalLine, LedgerAccount, LedgerParty, LedgerTxn,
                     LedgerTxnApply, LedgerTxnLine)

T = LedgerAccount.Type
GST = LedgerTxnLine.Gst
MONEY_TYPES = ("BANK", "CREDIT_CARD")     # what a register is kept for
DOC_TYPES = ("BILL", "INVOICE")           # owed, until a payment settles it
PAY_TYPES = ("BILL_PAY", "RECEIPT")
# the document a payment settles, and whose it is
PAYS = {"BILL_PAY": "BILL", "RECEIPT": "INVOICE"}
KIND = {"BILL": "SUPPLIER", "BILL_PAY": "SUPPLIER",
        "INVOICE": "CUSTOMER", "RECEIPT": "CUSTOMER"}
# the control account a document sits on: its type, and the usual one
CONTROL = {"BILL": ("AP", "AP_TRADE"), "INVOICE": ("AR", "AR_TRADE")}
LABEL = {"EXPENSE": "Expense", "DEPOSIT": "Deposit", "TRANSFER": "Transfer",
         "BILL": "Bill", "INVOICE": "Invoice", "BILL_PAY": "Bill payment",
         "RECEIPT": "Payment received"}


def gst_rate():
    from .procurement import company_gst_rate
    return company_gst_rate()


def meta():
    """What the forms need: the GST rate and treatments, names to suggest."""
    from .models import Customer, Site, Supplier
    suppliers = set(Supplier.objects.filter(is_active=True)
                    .values_list("name", flat=True))
    known = {k: set(LedgerParty.objects.filter(kind=k, is_active=True)
                    .values_list("name", flat=True))
             for k in ("SUPPLIER", "CUSTOMER")}
    customers = (set(Customer.objects.values_list("name", flat=True))
                 | set(Site.objects.exclude(client_name="")
                       .values_list("client_name", flat=True)))

    def names(*sets):
        seen = {}
        for group in sets:
            for n in group:
                n = " ".join((n or "").split())
                if n:
                    seen.setdefault(n.lower(), n)
        return sorted(seen.values(), key=str.lower)[:1500]
    return {
        "gst_rate": gst_rate(),
        "gst_treatments": [{"value": v, "label": lab} for v, lab in GST.choices],
        "payees": names(suppliers, known["SUPPLIER"],
                        LedgerTxn.objects.exclude(party="")
                        .filter(type__in=("EXPENSE", "DEPOSIT"))
                        .values_list("party", flat=True)),
        "suppliers": names(known["SUPPLIER"], suppliers),
        "customers": names(known["CUSTOMER"], customers),
        "settings": ledger.settings_dict(),
    }


# ---- suppliers and customers -------------------------------------------------

def party_for(kind, ref=None, name="", tin=""):
    """The supplier or customer a form names — the one on file under that
    name, or a new one (QuickBooks' quick add), tied to Purchasing's
    supplier or Trading's customer where the name is theirs."""
    from .models import Customer, Supplier
    p = LedgerParty.objects.filter(pk=ref, kind=kind).first() if ref else None
    if p is None:
        name = " ".join((name or "").split())[:160]
        if not name:
            raise ValueError("Say which supplier." if kind == "SUPPLIER"
                             else "Say which customer.")
        p = LedgerParty.objects.filter(kind=kind, name__iexact=name).first()
        if p is None:
            p = LedgerParty(kind=kind, name=name)
            if kind == "SUPPLIER":
                src = Supplier.objects.filter(name__iexact=name).first()
                if src:
                    p.supplier, p.credit_days = src, src.credit_days
                    p.address = src.address
                    cur = (src.default_currency or "").upper()
                    p.currency = cur if cur and cur != BASE else ""
            else:
                src = Customer.objects.filter(name__iexact=name).first()
                if src:
                    p.customer, p.credit_days = src, src.credit_days
                    p.tin, p.address = src.tin, src.billing_address
                    cur = (src.default_currency or "").upper()
                    p.currency = cur if cur and cur != BASE else ""
            p.save()
    tin = (tin or "").strip()[:40]
    if tin and not p.tin:
        p.tin = tin
        p.save(update_fields=["tin"])
    return p


def save_party(data, actor, party=None):
    """Create or correct a supplier / customer. Returns (party, error)."""
    kind = party.kind if party else data.get("kind")
    if kind not in LedgerParty.Kind.values:
        return None, "Say whether it is a supplier or a customer."
    name = " ".join((data.get("name") or (party.name if party else "")).split())
    if not name:
        return None, "Give the name."
    clash = LedgerParty.objects.filter(kind=kind, name__iexact=name)
    if party:
        clash = clash.exclude(pk=party.pk)
    if clash.exists():
        return None, f"{name} is already on the list."
    party = party or LedgerParty(kind=kind)
    party.name = name[:160]
    for f, n in (("tin", 40), ("contact", 200), ("address", None)):
        if f in data:
            setattr(party, f, (data.get(f) or "").strip()[:n])
    if "currency" in data:
        cur = (data.get("currency") or "").strip().upper()[:3]
        party.currency = "" if cur == BASE else cur
    if "credit_days" in data:
        cd = data.get("credit_days")
        try:
            party.credit_days = None if cd in (None, "") else max(0, int(cd))
        except (TypeError, ValueError):
            return None, "Credit days is a number of days."
    if "is_active" in data:
        party.is_active = bool(data.get("is_active"))
    party.save()
    audit("ledger_party", party.id, "PARTY_SAVED", actor=actor,
          detail={"kind": kind, "name": party.name})
    return party, None


def _paid(prefix="applied__", as_of=None):
    """Annotations: how much of a document posted payments have settled."""
    live = Q(**{f"{prefix}payment__status": "POSTED"})
    if as_of:
        live &= Q(**{f"{prefix}payment__date__lte": as_of})
    money = DecimalField(max_digits=16, decimal_places=2)
    return {
        "paid": Coalesce(Sum(f"{prefix}amount", filter=live), ZERO,
                         output_field=money),
        "paid_mvr": Coalesce(Sum(f"{prefix}amount_mvr", filter=live), ZERO,
                             output_field=money),
    }


def docs(typ=None):
    """Bills / invoices with what has been paid against each."""
    qs = LedgerTxn.objects.filter(type__in=[typ] if typ else DOC_TYPES)
    return qs.annotate(**_paid())


def parties(kind):
    """The list, each with what is open between us, in rufiyaa."""
    doc_type = "BILL" if kind == "SUPPLIER" else "INVOICE"
    owed = {}
    for d in docs(doc_type).filter(status="POSTED"):
        bal = d.amount_mvr - d.paid_mvr
        if d.amount - d.paid > ZERO:
            row = owed.setdefault(d.party_ref_id, [ZERO, 0])
            row[0] += bal
            row[1] += 1
    out = []
    for p in LedgerParty.objects.filter(kind=kind):
        bal, n = owed.get(p.id, (ZERO, 0))
        out.append({**party_dict(p), "balance": bal, "open": n})
    return out


def party_dict(p):
    return {"id": p.id, "kind": p.kind, "name": p.name, "tin": p.tin,
            "address": p.address, "contact": p.contact,
            "credit_days": p.credit_days, "currency": p.currency or BASE,
            "is_active": p.is_active,
            "linked": ("Purchasing's supplier list" if p.supplier_id else
                       "Trading's customer list" if p.customer_id else "")}


def party_statement(party):
    """Everything between us and one supplier or customer, oldest first,
    with the balance running in rufiyaa."""
    doc_type = "BILL" if party.kind == "SUPPLIER" else "INVOICE"
    rows, bal = [], ZERO
    txns = (LedgerTxn.objects.filter(party_ref=party, status="POSTED")
            .order_by("date", "id"))
    for t in txns:
        if t.type == doc_type:
            change = t.amount_mvr
        else:
            change = -sum((a.amount_mvr for a in t.applies.all()), ZERO)
        bal += change
        rows.append({"id": t.id, "number": t.number, "type": t.type,
                     "type_label": LABEL[t.type], "date": t.date,
                     "reference": t.reference, "due_date": t.due_date,
                     "currency": t.currency, "amount": t.amount,
                     "change": change, "balance": bal,
                     "is_opening": t.is_opening})
    return {"party": party_dict(party), "rows": rows, "balance": bal}


def aging(kind, as_of=None):
    """What is owed, per supplier or customer, by how long past its due
    date — in rufiyaa, at the value each bill stands at in the books — and
    whether it agrees with the control accounts."""
    as_of = as_of or timezone.localdate()
    doc_type = "BILL" if kind == "SUPPLIER" else "INVOICE"
    qs = (LedgerTxn.objects.filter(type=doc_type, status="POSTED",
                                   date__lte=as_of)
          .annotate(**_paid(as_of=as_of)).select_related("party_ref"))
    buckets = ("current", "d30", "d60", "d90", "older")
    by, total = {}, dict.fromkeys(buckets + ("total",), ZERO)
    for d in qs:
        bal = d.amount_mvr - d.paid_mvr
        if d.amount - d.paid <= ZERO or bal == ZERO:
            continue
        late = (as_of - (d.due_date or d.date)).days
        b = ("current" if late <= 0 else "d30" if late <= 30 else
             "d60" if late <= 60 else "d90" if late <= 90 else "older")
        row = by.setdefault(d.party_ref_id, {
            "party": d.party_ref_id, "name": d.party_ref.name if d.party_ref
            else d.party, **dict.fromkeys(buckets + ("total",), ZERO),
            "docs": []})
        row[b] += bal
        row["total"] += bal
        total[b] += bal
        total["total"] += bal
        row["docs"].append({"id": d.id, "number": d.number,
                            "reference": d.reference, "date": d.date,
                            "due_date": d.due_date, "days_late": max(late, 0),
                            "currency": d.currency,
                            "balance_fc": d.amount - d.paid, "balance": bal})
    # the same figure, per the books
    typ, sign = ("AP", -1) if kind == "SUPPLIER" else ("AR", 1)
    books_bal = sign * sum(_balances(None, as_of, (typ,)).values(), ZERO)
    return {"kind": kind, "as_of": as_of,
            "rows": sorted(by.values(), key=lambda r: r["name"].lower()),
            "total": total, "per_books": books_bal,
            "difference": books_bal - total["total"]}


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
    """The balanced entry for an expense or a deposit — or for a bill or an
    invoice, which are the same thing bought or sold on credit: the total
    lands on the payable or receivable instead of the bank. Amounts on the
    form are in the transaction's currency; the books are in rufiyaa."""
    rate = txn.fx_rate or Decimal("1")
    expense = txn.type in ("EXPENSE", "BILL")
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
    if txn.type in DOC_TYPES:
        fc = ({"currency": txn.currency, "amount_fc": q2(txn.amount),
               "fx_rate": rate} if txn.currency != BASE else {})
    else:
        fc = _fc(txn.account, txn.amount, rate)
    bank = _jl(txn.account, party=txn.party, description=txn.reference,
               **({"credit": total_mvr} if expense else {"debit": total_mvr}),
               **fc)
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


def _control_account(data, typ):
    """The payable or receivable account a bill / invoice sits on."""
    want, usual = CONTROL[typ]
    if data.get("account"):
        account = LedgerAccount.objects.filter(pk=data.get("account")).first()
    else:
        account = ledger.account_for(usual) or LedgerAccount.objects.filter(
            type=want, is_group=False, is_active=True).order_by("code").first()
    what = "payable" if typ == "BILL" else "receivable"
    if account is None or account.type != want or account.is_group:
        raise ValueError(f"Pick the accounts {what} account.")
    if account.currency:
        raise ValueError(f"{account.name} is held in {account.currency}; "
                         f"the {what} account is kept in rufiyaa.")
    return account


def _clean_doc_head(data, typ, head, txn):
    """What a bill or an invoice adds to the header: whose it is, its own
    number, when it falls due, its currency."""
    supplier = typ == "BILL"
    party = party_for(KIND[typ], data.get("party_ref"), data.get("party"),
                      data.get("party_tin"))
    if not head["reference"]:
        raise ValueError("Give the supplier's bill or invoice number."
                         if supplier else "Give the invoice number.")
    twin = LedgerTxn.objects.filter(
        type=typ, status="POSTED", party_ref=party,
        reference__iexact=head["reference"])
    if txn is not None and txn.pk:
        twin = twin.exclude(pk=txn.pk)
    twin = twin.first()
    if twin:
        raise ValueError(f"{head['reference']} from {party.name} is already "
                         f"entered, as {twin.number}." if supplier else
                         f"Invoice {head['reference']} to {party.name} is "
                         f"already entered, as {twin.number}.")
    cur = (data.get("currency") or BASE).strip().upper()[:3]
    if len(cur) != 3 or not cur.isalpha():
        raise ValueError("The currency is a three-letter code, like USD.")
    head.update(party_ref=party, party=party.name,
                party_tin=head["party_tin"] or party.tin, currency=cur,
                is_opening=bool(data.get("is_opening")))
    if cur != BASE:
        head["fx_rate"] = _dec(data.get("fx_rate"), "The rate")
        if head["fx_rate"] <= 0:
            raise ValueError(f"Give the {cur} rate to rufiyaa.")
    due = ledger._as_date(data.get("due_date"))
    if due is None:
        due = head["date"] + timedelta(days=party.credit_days or 0)
    if due < head["date"]:
        raise ValueError("The due date is before the date of the "
                         + ("bill." if supplier else "invoice."))
    head["due_date"] = due
    if supplier:
        if head["tax_invoice_held"]:
            # MIRA's input tax statement lists the invoice and the supplier's
            # TIN; without them the claim does not stand.
            head["tax_invoice_no"] = head["tax_invoice_no"] or head["reference"]
            head["tax_invoice_date"] = head["tax_invoice_date"] or head["date"]
            if not head["party_tin"]:
                raise ValueError("A tax invoice carries the supplier's TIN — "
                                 "enter it to claim the GST.")
    else:
        head["tax_invoice_no"] = head["reference"]
        head["tax_invoice_date"] = head["date"]
        head["tax_invoice_held"] = False
    if head["is_opening"]:
        start = ledger.books_start()
        if head["date"] >= start:
            raise ValueError(
                f"An opening item is dated before the books start "
                f"({start:%d %b %Y}) — it is something still unpaid from "
                "before.")
        amount = q2(_dec(data.get("amount"), "The amount"))
        if amount <= 0:
            raise ValueError("Give the amount still unpaid.")
        head["amount"] = amount


def _clean(data, typ, txn=None):
    """Validated header + lines from what the form sent. Raises ValueError."""
    from .models import Project, Site
    d = ledger._as_date(data.get("date"))
    if d is None:
        raise ValueError("Give the date.")
    if typ in DOC_TYPES:
        account = _control_account(data, typ)
    else:
        account = LedgerAccount.objects.filter(pk=data.get("account")).first()
        if (account is None or account.type not in MONEY_TYPES
                or account.is_group):
            raise ValueError("Pick the bank or cash account.")
    if not account.is_active:
        raise ValueError(f"{account.name} is closed.")
    head = {
        "date": d, "account": account, "to_account": None,
        "party": (data.get("party") or "").strip()[:160],
        "party_tin": (data.get("party_tin") or "").strip()[:40],
        "party_ref": None, "due_date": None, "is_opening": False,
        "reference": (data.get("reference") or "").strip()[:80],
        "memo": (data.get("memo") or "").strip(),
        "currency": account.currency or BASE, "fx_rate": None,
        "amount_to": None,
        "tax_invoice_no": (data.get("tax_invoice_no") or "").strip()[:60],
        "tax_invoice_date": ledger._as_date(data.get("tax_invoice_date")),
        "tax_invoice_held": bool(data.get("tax_invoice_held")),
    }
    if typ in DOC_TYPES:
        _clean_doc_head(data, typ, head, txn)
        if head["is_opening"]:
            return head, []
    elif account.currency:
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
    if (typ == "EXPENSE" and head["tax_invoice_held"]
            and any(ln["gst_amount"] for ln in lines)
            and not (head["party_tin"] and head["tax_invoice_no"])):
        # MIRA's input tax statement lists both for every claim
        raise ValueError("To claim the GST, enter the supplier's TIN and the "
                         "tax invoice number — or untick the tax invoice, "
                         "and the GST goes into the cost.")
    head["amount"] = sum((ln["amount"] + ln["gst_amount"] for ln in lines),
                         ZERO)
    return head, lines


def save_txn(typ, data, actor, txn=None, attachment=None):
    """Create a transaction, or change one — which reverses its entry and
    posts a new one, so the books keep both. Returns (txn, error)."""
    from .numbering import next_ref
    if typ in PAY_TYPES:
        if txn is not None:
            return None, ("A payment isn't changed — void it and enter it "
                          "again.")
        return save_payment(typ, data, actor, attachment=attachment)
    if typ not in LedgerTxn.Type.values:
        return None, "Unknown kind of transaction."
    if txn is not None and txn.status == "VOID":
        return None, "A void transaction can't be changed."
    if txn is not None and (msg := _settled_block(txn, "changed")):
        return None, msg
    try:
        with transaction.atomic():
            head, lines = _clean(data, typ, txn)
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
            if txn.is_opening:
                # already inside the opening balances: no entry of its own
                jl, mvr = None, q2(txn.amount * (txn.fx_rate or 1))
                txn.journal = None
            else:
                jl, mvr = (_transfer_lines(txn) if typ == "TRANSFER"
                           else _journal_lines(txn, lines))
            txn.amount_mvr = mvr
            txn.save()
            txn.lines.all().delete()
            LedgerTxnLine.objects.bulk_create([
                LedgerTxnLine(txn=txn, line_no=i, **ln)
                for i, ln in enumerate(lines, 1)])
            if jl is not None:
                who = txn.party or (
                    f"{txn.account.name} → {txn.to_account.name}"
                    if txn.to_account_id else "")
                txn.journal = ledger.post_entry(
                    on=txn.date, actor=actor, kind="TXN",
                    memo=" · ".join(x for x in (
                        f"{LABEL[typ]} {txn.number}", who,
                        txn.reference if typ in DOC_TYPES else "",
                        txn.memo) if x),
                    lines=jl, source_type="TXN", source_id=txn.id,
                    source_ref=txn.number)
                txn.save(update_fields=["journal"])
    except ValueError as exc:
        return None, str(exc)
    audit("ledger_txn", txn.id, "TXN_SAVED", actor=actor,
          detail={"number": txn.number, "type": typ,
                  "amount_mvr": str(txn.amount_mvr),
                  "journal": txn.journal.ref if txn.journal_id else ""})
    return txn, None


def _settled_block(txn, verb):
    """Why a bill or invoice with a payment against it can't be touched."""
    if txn.type not in DOC_TYPES:
        return None
    pay = (LedgerTxnApply.objects.filter(doc=txn, payment__status="POSTED")
           .select_related("payment").first())
    if pay:
        return (f"{txn.number} has a payment against it "
                f"({pay.payment.number}) — void the payment first, then it "
                f"can be {verb}.")
    return None


def save_payment(typ, data, actor, attachment=None):
    """Pay bills, or receive payment against invoices: one sum through one
    bank or cash account, set against one or more open documents of one
    supplier or customer. Returns (txn, error).

    Each document leaves the books at the rufiyaa value it went in at; where
    the money that actually moved is worth more or less than that — a dollar
    bill paid at a different rate — the difference is an exchange gain or
    loss, as the audited statements' policy has it."""
    from .numbering import next_ref
    pay = typ == "BILL_PAY"
    doc_word = "bill" if pay else "invoice"
    try:
        d = ledger._as_date(data.get("date"))
        if d is None:
            raise ValueError("Give the date.")
        account = LedgerAccount.objects.filter(pk=data.get("account")).first()
        if (account is None or account.type not in MONEY_TYPES
                or account.is_group):
            raise ValueError("Pick the bank or cash account.")
        if not account.is_active:
            raise ValueError(f"{account.name} is closed.")
        want = {}
        for r in data.get("applies") or []:
            amt = q2(_dec(r.get("amount"), "An amount"))
            if amt < ZERO:
                raise ValueError("An amount can't be negative.")
            if amt and r.get("doc"):
                want[int(r["doc"])] = want.get(int(r["doc"]), ZERO) + amt
        if not want:
            raise ValueError(f"Tick at least one {doc_word} and give the "
                             "amount.")
        with transaction.atomic():
            found = list(docs(PAYS[typ]).filter(pk__in=want, status="POSTED")
                         .select_related("account", "party_ref")
                         .order_by("date", "id"))
            if len(found) != len(want):
                raise ValueError(f"One of those {doc_word}s is void or gone "
                                 "— open the list again.")
            if len({x.party_ref_id for x in found}) != 1:
                raise ValueError(f"One payment settles one "
                                 f"{'supplier' if pay else 'customer'}'s "
                                 f"{doc_word}s.")
            if len({x.currency for x in found}) != 1:
                raise ValueError(f"Those {doc_word}s are in different "
                                 "currencies — settle each currency with its "
                                 "own payment.")
            party, cur = found[0].party_ref, found[0].currency
            bank_cur = account.currency or BASE
            applied, carrying, items = ZERO, ZERO, []
            for x in found:
                amt, left = want[x.id], x.amount - x.paid
                if x.date > d:
                    raise ValueError(f"{x.number} is dated {x.date:%d %b %Y}, "
                                     "after this payment.")
                if amt > left:
                    raise ValueError(
                        f"{x.number} has {cur} {left:,.2f} left to settle — "
                        f"{cur} {amt:,.2f} is more than that.")
                # the last of a document takes whatever value is left on it,
                # so the payable or receivable clears to the laari
                mvr = (x.amount_mvr - x.paid_mvr if amt == left
                       else q2(amt * (x.fx_rate or 1)))
                items.append((x, amt, mvr))
                applied += amt
                carrying += mvr
            rate = None
            if cur == bank_cur:
                moved = applied                      # in the bank's currency
                if cur == BASE:
                    value = applied
                else:
                    rate = _dec(data.get("fx_rate"), "The rate")
                    if rate <= 0:
                        raise ValueError(f"Give the {cur} rate to rufiyaa on "
                                         "the day of the payment.")
                    value = q2(applied * rate)
            elif bank_cur == BASE:
                # a foreign bill settled from a rufiyaa account
                moved = value = q2(_dec(data.get("amount"), "The amount"))
                if value <= 0:
                    raise ValueError(
                        f"Give the rufiyaa amount that "
                        f"{'left' if pay else 'reached'} {account.name} for "
                        f"{cur} {applied:,.2f}.")
            elif cur == BASE:
                # a rufiyaa bill settled from a foreign-currency account
                moved = q2(_dec(data.get("amount"), "The amount"))
                if moved <= 0:
                    raise ValueError(
                        f"Give the {bank_cur} amount that "
                        f"{'left' if pay else 'reached'} {account.name}.")
                value = applied
            else:
                raise ValueError(
                    f"{account.name} is in {bank_cur} and the {doc_word}s in "
                    f"{cur} — settle them through a {cur} or a rufiyaa "
                    "account.")
            if bank_cur != BASE:
                rate = (value / moved).quantize(Decimal("0.000001"))
            txn = LedgerTxn.objects.create(
                type=typ, number=next_ref(LedgerTxn.PREFIX[typ], None),
                date=d, account=account, party_ref=party, party=party.name,
                party_tin=party.tin,
                reference=(data.get("reference") or "").strip()[:80],
                memo=(data.get("memo") or "").strip(), currency=bank_cur,
                fx_rate=rate, amount=moved, amount_mvr=value,
                attachment=attachment, created_by=actor, updated_by=actor)
            LedgerTxnApply.objects.bulk_create([
                LedgerTxnApply(payment=txn, doc=x, amount=amt, amount_mvr=mvr)
                for x, amt, mvr in items])
            side, other = (("credit", "debit") if pay else ("debit", "credit"))
            fc = ({"currency": bank_cur, "amount_fc": moved, "fx_rate": rate}
                  if bank_cur != BASE else {})
            jl = [_jl(account, party=party.name, description=txn.reference,
                      **{side: value}, **fc)]
            ctrl = {}
            for x, amt, mvr in items:
                row = ctrl.setdefault(x.account_id, [x.account, ZERO, ZERO, []])
                row[1] += mvr
                row[2] += amt
                row[3].append(x.reference or x.number)
            for acc, mvr, amt, refs in ctrl.values():
                jl.append(_jl(acc, party=party.name,
                              description=", ".join(refs)[:300],
                              **{other: mvr},
                              **({"currency": cur, "amount_fc": amt,
                                  "fx_rate": (mvr / amt).quantize(
                                      Decimal("0.000001"))}
                                 if cur != BASE else {})))
            diff = value - carrying
            if diff:
                loss = (diff > 0) == pay     # paid more, or received less
                fx = ledger.account_for("FX_LOSS" if loss else "FX_GAIN")
                if fx is None:
                    raise ValueError(
                        "The chart has no exchange "
                        f"{'loss' if loss else 'gain'} account for the "
                        "difference — restore it in the chart of accounts.")
                jl.append(_jl(fx, party=party.name,
                              description="Exchange difference",
                              **({"debit": abs(diff)} if loss
                                 else {"credit": abs(diff)})))
            txn.journal = ledger.post_entry(
                on=d, actor=actor, kind="TXN",
                memo=" · ".join(x for x in (
                    f"{LABEL[typ]} {txn.number}", party.name, txn.memo) if x),
                lines=jl, source_type="TXN", source_id=txn.id,
                source_ref=txn.number)
            txn.save(update_fields=["journal"])
    except ValueError as exc:
        return None, str(exc)
    audit("ledger_txn", txn.id, "TXN_SAVED", actor=actor,
          detail={"number": txn.number, "type": typ,
                  "amount_mvr": str(txn.amount_mvr),
                  "settles": [x.number for x, _, _ in items],
                  "journal": txn.journal.ref})
    return txn, None


def void_txn(txn, actor, reason):
    if txn.status == "VOID":
        return f"{txn.number} is already void."
    reason = (reason or "").strip()
    if not reason:
        return "Say why it is being voided."
    if (msg := _settled_block(txn, "voided")):
        return msg
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
        qs = qs.filter(type__in=[t for t in params["type"].split(",") if t])
    if params.get("party"):
        qs = qs.filter(party_ref_id=params["party"])
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

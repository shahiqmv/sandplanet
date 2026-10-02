"""The books — double-entry general ledger (FINANCE_BUILD_BRIEF.md).

Four rules hold everything else up:

  * an entry posts only if its debits equal its credits, in rufiyaa;
  * a posted entry is never edited or deleted — it is reversed;
  * nothing posts before the books start (except the opening balances) or on
    or before the lock date;
  * numbers are gap-free and issued at posting.

Everything here is in rufiyaa. A line in another currency keeps its own
amount and rate beside the rufiyaa value.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .audit import audit
from .models import (CompanyBankAccount, CompanyParameter, JournalEntry,
                     JournalLine, LedgerAccount)

ZERO = Decimal("0")
CENT = Decimal("0.01")
READ_ROLES = ("FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA")
WRITE_ROLES = ("FINANCE", "ADMIN")
BOOKS_START_DEFAULT = "2026-01-01"       # owner 2026-10-02
BASE = "MVR"

T = LedgerAccount.Type


def q2(v):
    return Decimal(str(v or 0)).quantize(CENT)


# ---- settings ---------------------------------------------------------------

def _param(key, default=None):
    try:
        return CompanyParameter.objects.get(key=key).value
    except CompanyParameter.DoesNotExist:
        return default


def _as_date(v):
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def books_start():
    return _as_date(_param("books_start_date")) or date.fromisoformat(
        BOOKS_START_DEFAULT)


def lock_date():
    """Nothing posts on or before this date (a closed period)."""
    return _as_date(_param("books_lock_date"))


def opening_date():
    """Opening balances sit on the last day before the books start, so every
    report of the first year shows them as brought forward."""
    return books_start() - timedelta(days=1)


def settings_dict():
    return {"books_start_date": books_start(), "lock_date": lock_date(),
            "opening_date": opening_date(), "base_currency": BASE}


def save_settings(data, actor):
    if "books_start_date" in data:
        d = _as_date(data["books_start_date"])
        if d is None:
            return "Give the date the books start."
        if d != books_start() and JournalEntry.objects.filter(
                status="POSTED").exists():
            return ("Entries are already posted — the start date can't move "
                    "now.")
        CompanyParameter.objects.update_or_create(
            key="books_start_date", defaults={
                "value": d.isoformat(),
                "description": "First day of the general ledger"})
    if "lock_date" in data:
        raw = data["lock_date"]
        d = _as_date(raw)
        if raw and d is None:
            return "The lock date is not a date."
        CompanyParameter.objects.update_or_create(
            key="books_lock_date", defaults={
                "value": d.isoformat() if d else "",
                "description": "Nothing posts on or before this date"})
        audit("ledger", 0, "BOOKS_LOCK_DATE_SET", actor=actor,
              detail={"lock_date": d.isoformat() if d else None})
    return None


# ---- the standard chart -----------------------------------------------------
# QuickBooks-shaped: each account carries one of QuickBooks' types, and a
# sub-account sits under a parent of the same type. The names follow the
# company's audited statements for 2025; added to them are the accounts
# PLANET's operations need that those statements did not carry — supplier
# payables, retention, client advances, input GST, stock, accumulated
# depreciation. The consultant changes any of it.
# (code, name, type, parent code, is_group, system_key)

G = True
STANDARD_CHART = [
    # Bank
    ("1010", "Cash in hand", T.BANK, None, False, "CASH_IN_HAND"),
    ("1020", "Petty cash — sites", T.BANK, None, False, "PETTY_CASH"),
    ("1100", "Cash at banks", T.BANK, None, G, "BANKS"),
    # Accounts receivable
    ("1210", "Trade receivables — construction clients", T.AR, None, False,
     "AR_TRADE"),
    ("1220", "Trade receivables — resort supply customers", T.AR, None,
     False, "AR_TRADING"),
    ("1230", "Retention receivable", T.AR, None, False,
     "RETENTION_RECEIVABLE"),
    # Other current assets
    ("1300", "Prepayments and advances", T.OTHER_CURRENT_ASSET, None, G, ""),
    ("1310", "Emigration air ticket deposits", T.OTHER_CURRENT_ASSET, "1300",
     False, ""),
    ("1320", "Bid security deposits", T.OTHER_CURRENT_ASSET, "1300", False,
     ""),
    ("1330", "STO scheme", T.OTHER_CURRENT_ASSET, "1300", False, ""),
    ("1340", "Advances to suppliers", T.OTHER_CURRENT_ASSET, "1300", False,
     "SUPPLIER_ADVANCES"),
    ("1350", "Staff advances and loans", T.OTHER_CURRENT_ASSET, "1300",
     False, "STAFF_ADVANCES"),
    ("1360", "Other prepayments", T.OTHER_CURRENT_ASSET, "1300", False, ""),
    ("1400", "Amounts due from directors", T.OTHER_CURRENT_ASSET, None,
     False, ""),
    ("1410", "Amounts due from related parties", T.OTHER_CURRENT_ASSET, None,
     False, ""),
    ("1420", "Other receivables", T.OTHER_CURRENT_ASSET, None, False, ""),
    ("1430", "GST input tax recoverable", T.OTHER_CURRENT_ASSET, None, False,
     "INPUT_GST"),
    ("1500", "Inventories", T.OTHER_CURRENT_ASSET, None, G, ""),
    ("1510", "Materials and goods in stock", T.OTHER_CURRENT_ASSET, "1500",
     False, "INVENTORY"),
    ("1520", "Goods in transit — imports", T.OTHER_CURRENT_ASSET, "1500",
     False, "GOODS_IN_TRANSIT"),
    # Fixed assets
    ("1700", "Property, plant and equipment", T.FIXED_ASSET, None, G, ""),
    ("1710", "Computers and equipment", T.FIXED_ASSET, "1700", False, ""),
    ("1720", "Furniture and fittings", T.FIXED_ASSET, "1700", False, ""),
    ("1730", "Motor vehicles", T.FIXED_ASSET, "1700", False, ""),
    ("1740", "Plant and machinery", T.FIXED_ASSET, "1700", False, ""),
    ("1750", "Tools and equipment", T.FIXED_ASSET, "1700", False, ""),
    ("1790", "Accumulated depreciation", T.FIXED_ASSET, "1700", False,
     "ACCUMULATED_DEPRECIATION"),
    # Other assets (non-current, as the audited statements show it)
    ("1900", "Work in progress", T.OTHER_ASSET, None, False, "WIP"),

    # Accounts payable
    ("2010", "Trade payables — local suppliers", T.AP, None, False,
     "AP_TRADE"),
    ("2020", "Trade payables — overseas suppliers", T.AP, None, False,
     "AP_IMPORT"),
    ("2030", "Subcontractors payable", T.AP, None, False, "AP_SUBCONTRACT"),
    # Other current liabilities
    ("2100", "Due to related parties", T.OTHER_CURRENT_LIABILITY, None, False,
     ""),
    ("2110", "Amounts due to directors", T.OTHER_CURRENT_LIABILITY, None,
     False, ""),
    ("2120", "Accrued expenses — audit fee", T.OTHER_CURRENT_LIABILITY, None,
     False, ""),
    ("2130", "Accrued expenses — other", T.OTHER_CURRENT_LIABILITY, None,
     False, "ACCRUALS"),
    ("2140", "Salaries and wages payable", T.OTHER_CURRENT_LIABILITY, None,
     False, "SALARIES_PAYABLE"),
    ("2150", "Pension contributions payable", T.OTHER_CURRENT_LIABILITY, None,
     False, ""),
    ("2160", "Advances from clients", T.OTHER_CURRENT_LIABILITY, None, False,
     "CLIENT_ADVANCES"),
    ("2170", "Other payables", T.OTHER_CURRENT_LIABILITY, None, False, ""),
    ("2200", "Government payables", T.OTHER_CURRENT_LIABILITY, None, G, ""),
    ("2210", "GST payable", T.OTHER_CURRENT_LIABILITY, "2200", False,
     "OUTPUT_GST"),
    ("2220", "Income tax payable", T.OTHER_CURRENT_LIABILITY, "2200", False,
     "INCOME_TAX_PAYABLE"),
    ("2230", "Withholding tax payable — non-residents",
     T.OTHER_CURRENT_LIABILITY, "2200", False, "WHT_PAYABLE"),
    ("2240", "Employee withholding tax payable", T.OTHER_CURRENT_LIABILITY,
     "2200", False, "EWT_PAYABLE"),
    # Long term liabilities
    ("2500", "Borrowings", T.LONG_TERM_LIABILITY, None, False, ""),

    # Equity
    ("3100", "Share capital", T.EQUITY, None, False, ""),
    ("3200", "Retained earnings", T.EQUITY, None, False, "RETAINED_EARNINGS"),
    ("3900", "Opening balance equity", T.EQUITY, None, False,
     "OPENING_BALANCE"),

    # Income
    ("4110", "Construction revenue", T.INCOME, None, False,
     "REVENUE_CONTRACT"),
    ("4120", "Resort supply sales", T.INCOME, None, False, "REVENUE_TRADING"),

    # Cost of goods sold
    ("5110", "Materials", T.COGS, None, False, "COS_MATERIALS"),
    ("5120", "Freight, customs and clearing", T.COGS, None, False,
     "COS_FREIGHT"),
    ("5130", "Site wages", T.COGS, None, False, "COS_LABOUR"),
    ("5140", "Subcontractors", T.COGS, None, False, "COS_SUBCONTRACT"),
    ("5150", "Site equipment rental", T.COGS, None, False, ""),
    ("5160", "Site transport and vessels", T.COGS, None, False, ""),
    ("5170", "Site accommodation and food", T.COGS, None, False, ""),
    ("5180", "Other site costs", T.COGS, None, False, ""),
    ("5210", "Cost of goods sold — resort supply", T.COGS, None, False,
     "COS_TRADING"),

    # Expenses
    ("6000", "Administrative expenses", T.EXPENSE, None, G, ""),
    ("6100", "Employees salaries and benefits", T.EXPENSE, "6000", G, ""),
    ("6110", "Staff salaries and wages", T.EXPENSE, "6100", False,
     "SALARIES_EXPENSE"),
    ("6120", "Staff food and accommodation", T.EXPENSE, "6100", False, ""),
    ("6130", "Staff travel", T.EXPENSE, "6100", False, ""),
    ("6140", "Staff uniform", T.EXPENSE, "6100", False, ""),
    ("6150", "Staff visa charges", T.EXPENSE, "6100", False, ""),
    ("6160", "Staff welfare", T.EXPENSE, "6100", False, ""),
    ("6170", "Ramazan allowance", T.EXPENSE, "6100", False, ""),
    ("6180", "Staff insurance", T.EXPENSE, "6100", False, ""),
    ("6190", "Staff medical", T.EXPENSE, "6100", False, ""),
    ("6200", "Director remuneration", T.EXPENSE, "6000", False, ""),
    ("6210", "Insurance", T.EXPENSE, "6000", False, ""),
    ("6220", "Rent", T.EXPENSE, "6000", False, ""),
    ("6230", "Meals and entertainment", T.EXPENSE, "6000", False, ""),
    ("6240", "Licenses and permits", T.EXPENSE, "6000", False, ""),
    ("6250", "Audit fee", T.EXPENSE, "6000", False, ""),
    ("6260", "Professional fees", T.EXPENSE, "6000", False, ""),
    ("6270", "Postage and delivery", T.EXPENSE, "6000", False, ""),
    ("6280", "Printing and stationery", T.EXPENSE, "6000", False, ""),
    ("6290", "Office supplies", T.EXPENSE, "6000", False, ""),
    ("6300", "Repairs and maintenance", T.EXPENSE, "6000", False, ""),
    ("6310", "Utilities", T.EXPENSE, "6000", False, ""),
    ("6320", "Electricity", T.EXPENSE, "6000", False, ""),
    ("6330", "Telephone", T.EXPENSE, "6000", False, ""),
    ("6340", "Computer and internet", T.EXPENSE, "6000", False, ""),
    ("6350", "Donations", T.EXPENSE, "6000", False, ""),
    ("6360", "Transportation", T.EXPENSE, "6000", False, ""),
    ("6370", "Business travelling", T.EXPENSE, "6000", False, ""),
    ("6380", "Dues and subscriptions", T.EXPENSE, "6000", False, ""),
    ("6390", "Equipment rental", T.EXPENSE, "6000", False, ""),
    ("6400", "Depreciation", T.EXPENSE, "6000", False, "DEPRECIATION"),
    ("6490", "Other administrative expenses", T.EXPENSE, "6000", False, ""),
    ("7000", "Selling and marketing costs", T.EXPENSE, None, G, ""),
    ("7110", "Advertising and promotion", T.EXPENSE, "7000", False, ""),
    ("7500", "Finance cost", T.EXPENSE, None, G, ""),
    ("7510", "Bank charges", T.EXPENSE, "7500", False, "BANK_CHARGES"),

    # Other income
    ("8010", "Other income", T.OTHER_INCOME, None, False, "OTHER_INCOME"),
    ("8020", "Foreign exchange gain", T.OTHER_INCOME, None, False, "FX_GAIN"),
    # Other expenses
    ("9010", "Foreign exchange loss", T.OTHER_EXPENSE, None, False,
     "FX_LOSS"),
    ("9110", "Income tax expense", T.OTHER_EXPENSE, None, False,
     "INCOME_TAX_EXPENSE"),
]


def setup_standard_chart(actor=None):
    """Create the standard chart, and one account under "Cash at banks" for
    each of the company's bank accounts. Only on empty books."""
    if LedgerAccount.objects.exists():
        return 0, "The chart of accounts is already set up."
    with transaction.atomic():
        by_code = {}
        for code, name, typ, parent, is_group, key in STANDARD_CHART:
            by_code[code] = LedgerAccount.objects.create(
                code=code, name=name, type=typ, is_group=is_group,
                parent=by_code.get(parent), system_key=key, created_by=actor)
        made = len(by_code) + sync_bank_accounts(actor)
    audit("ledger", 0, "CHART_SET_UP", actor=actor, detail={"accounts": made})
    return made, None


def sync_bank_accounts(actor=None):
    """A ledger account for every company bank account that lacks one."""
    banks = LedgerAccount.objects.filter(system_key="BANKS").first()
    if banks is None:
        return 0
    used = set(LedgerAccount.objects.values_list("code", flat=True))
    made = 0
    for b in CompanyBankAccount.objects.filter(
            ledger_account__isnull=True).order_by("sort_order", "id"):
        n = int(banks.code) + 1 if banks.code.isdigit() else 1
        while str(n) in used:
            n += 1
        code = str(n)
        used.add(code)
        LedgerAccount.objects.create(
            code=code, name=b.label, type=banks.type, parent=banks,
            currency="" if (b.currency or BASE) == BASE else b.currency,
            bank_account=b, is_active=b.is_active, created_by=actor)
        made += 1
    return made


def account_for(system_key):
    return LedgerAccount.objects.filter(system_key=system_key).first()


# ---- accounts ---------------------------------------------------------------

def save_account(data, actor, account=None):
    """Create or change an account. Its type and group status are fixed once
    it has postings or children that depend on them."""
    a = account or LedgerAccount(created_by=actor)
    used = account is not None and a.lines.exists()
    code = str(data.get("code", a.code) or "").strip()
    name = str(data.get("name", a.name) or "").strip()
    typ = data.get("type", a.type)
    if not code or not name:
        return None, "An account needs a code and a name."
    if len(code) > 12:
        return None, "Keep the code to 12 characters."
    if LedgerAccount.objects.filter(code=code).exclude(pk=a.pk).exists():
        return None, f"Code {code} is already used."
    if typ not in T.values:
        return None, "Pick the account type."
    if used and typ != a.type:
        return None, ("This account has entries posted to it — its type "
                      "can't change.")
    parent = a.parent
    if "parent" in data:
        parent = (LedgerAccount.objects.filter(pk=data["parent"]).first()
                  if data["parent"] else None)
        if data["parent"] and parent is None:
            return None, "That group no longer exists."
    if parent is not None:
        if not parent.is_group:
            return None, f"{parent.code} {parent.name} is not a group."
        if parent.type != typ:
            return None, (f"An account under {parent.name} must be of the "
                          f"same type ({parent.get_type_display()}).")
        p = parent
        while p is not None:
            if p.pk == a.pk:
                return None, "An account can't sit under itself."
            p = p.parent
    is_group = bool(data.get("is_group", a.is_group))
    if used and is_group:
        return None, ("This account has entries posted to it — it can't "
                      "become a group.")
    if account is not None and not is_group and a.children.exists():
        return None, "It has accounts under it, so it stays a group."
    if account is not None and typ != a.type and a.children.exists():
        return None, "Change the accounts under it first."
    currency = str(data.get("currency", a.currency) or "").upper().strip()
    if currency == BASE:
        currency = ""
    if used and currency != a.currency:
        return None, "The currency can't change once entries are posted."
    is_active = bool(data.get("is_active", a.is_active))
    if not is_active and a.pk and balance_of(a) != ZERO:
        return None, ("It still carries a balance — journal that out before "
                      "closing the account.")
    a.code, a.name, a.type, a.parent = code, name[:120], typ, parent
    a.is_group, a.currency, a.is_active = is_group, currency, is_active
    if "description" in data:
        a.description = data["description"] or ""
    created = a.pk is None
    a.save()
    audit("ledger_account", a.id,
          "ACCOUNT_ADDED" if created else "ACCOUNT_CHANGED", actor=actor,
          detail={"code": a.code, "name": a.name, "type": a.type})
    return a, None


def delete_account(a, actor):
    if a.lines.exists():
        return "It has entries posted to it — close it instead of deleting."
    if a.children.exists():
        return "Move or delete the accounts under it first."
    if a.system_key:
        return ("PLANET posts to this account automatically. Rename or "
                "re-code it, but it can't be deleted.")
    if a.bank_account_id:
        return "It belongs to a company bank account."
    snap = {"code": a.code, "name": a.name}
    aid = a.id
    a.delete()
    audit("ledger_account", aid, "ACCOUNT_DELETED", actor=actor, detail=snap)
    return None


def balance_of(account, as_of=None):
    """Debits less credits, posted entries only."""
    qs = JournalLine.objects.filter(account=account, entry__status="POSTED")
    if as_of:
        qs = qs.filter(entry__date__lte=as_of)
    agg = qs.aggregate(d=Sum("debit"), c=Sum("credit"))
    return (agg["d"] or ZERO) - (agg["c"] or ZERO)


# ---- journals ---------------------------------------------------------------

def _dec(v):
    if v in (None, ""):
        return ZERO
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError("An amount is not a number.")


def clean_lines(rows):
    """Turn posted-in rows into validated line dicts. Raises ValueError with
    a message a bookkeeper can act on."""
    from .models import CostHead, Project, Site
    out = []
    ids = {r.get("account") for r in rows if r.get("account")}
    accounts = {a.id: a for a in LedgerAccount.objects.filter(id__in=ids)}
    for n, r in enumerate(rows, 1):
        debit, credit = q2(_dec(r.get("debit"))), q2(_dec(r.get("credit")))
        if not r.get("account") and debit == ZERO and credit == ZERO:
            continue                          # a blank row on the form
        acc = accounts.get(r.get("account"))
        if acc is None:
            raise ValueError(f"Line {n}: pick the account.")
        if acc.is_group:
            raise ValueError(f"Line {n}: {acc.code} {acc.name} is a group — "
                             "post to an account under it.")
        if not acc.is_active:
            raise ValueError(f"Line {n}: {acc.code} {acc.name} is closed.")
        if debit < ZERO or credit < ZERO:
            raise ValueError(f"Line {n}: amounts can't be negative — use the "
                             "other column.")
        if (debit > ZERO) == (credit > ZERO):
            raise ValueError(f"Line {n}: enter a debit or a credit, one of "
                             "the two.")
        currency = (r.get("currency") or acc.currency or BASE).upper()
        amount_fc = rate = None
        if acc.currency and currency != acc.currency:
            raise ValueError(f"Line {n}: {acc.name} is held in "
                             f"{acc.currency}.")
        if currency != BASE:
            amount_fc, rate = q2(_dec(r.get("amount_fc"))), _dec(r.get("fx_rate"))
            if amount_fc <= ZERO or rate <= ZERO:
                raise ValueError(f"Line {n}: give the {currency} amount and "
                                 "the rate.")
            if abs(q2(amount_fc * rate) - (debit or credit)) > Decimal("0.05"):
                raise ValueError(
                    f"Line {n}: {currency} {amount_fc} at {rate} is "
                    f"{q2(amount_fc * rate)}, not {debit or credit}.")
        out.append({
            "account": acc, "debit": debit, "credit": credit,
            "description": (r.get("description") or "")[:300],
            "currency": currency, "amount_fc": amount_fc, "fx_rate": rate,
            "site": Site.objects.filter(pk=r["site"]).first()
            if r.get("site") else None,
            "project": Project.objects.filter(pk=r["project"]).first()
            if r.get("project") else None,
            "cost_head": CostHead.objects.filter(pk=r["cost_head"]).first()
            if r.get("cost_head") else None,
            "party": (r.get("party") or "")[:160],
        })
    return out


def check_balanced(lines):
    if len(lines) < 2:
        return "An entry needs at least two lines."
    dr = sum((ln["debit"] for ln in lines), ZERO)
    cr = sum((ln["credit"] for ln in lines), ZERO)
    if dr != cr:
        return (f"The entry doesn't balance: debits {dr:,.2f}, credits "
                f"{cr:,.2f} — out by {abs(dr - cr):,.2f}.")
    if dr == ZERO:
        return "The entry has no amounts."
    return None


def check_date(d, kind):
    """Why an entry can't be dated `d`, or None."""
    if kind == JournalEntry.Kind.OPENING:
        return None                            # always the opening date
    if d < books_start():
        return (f"The books start on {books_start():%d %b %Y}. Balances "
                "before that go in as opening balances.")
    lock = lock_date()
    if lock and d <= lock:
        return (f"The books are closed up to {lock:%d %b %Y}. Date the "
                "entry after that, or have the period reopened.")
    if d > timezone.localdate() + timedelta(days=31):
        return "That date is more than a month ahead."
    return None


def save_draft(data, actor, entry=None):
    """Create or replace a draft. Returns (entry, error)."""
    if entry is not None and entry.status != "DRAFT":
        return None, ("A posted entry can't be changed. Reverse it and post "
                      "a new one.")
    kind = data.get("kind") or (entry.kind if entry else "MANUAL")
    if kind not in ("MANUAL", "OPENING"):
        return None, "Unknown kind of entry."
    d = opening_date() if kind == "OPENING" else _as_date(data.get("date"))
    if d is None:
        return None, "Give the entry a date."
    try:
        lines = clean_lines(data.get("lines") or [])
    except ValueError as exc:
        return None, str(exc)
    if not lines:
        return None, "Add the lines."
    with transaction.atomic():
        if entry is None:
            entry = JournalEntry(created_by=actor)
        entry.date, entry.kind = d, kind
        entry.memo = (data.get("memo") or "").strip()
        entry.save()
        entry.lines.all().delete()
        JournalLine.objects.bulk_create([
            JournalLine(entry=entry, line_no=i, **ln)
            for i, ln in enumerate(lines, 1)])
    return entry, None


def post(entry, actor):
    """Make a draft permanent. Returns an error or None."""
    from .numbering import next_ref
    if entry.status != "DRAFT":
        return "This entry is already posted."
    lines = [{"debit": ln.debit, "credit": ln.credit, "account": ln.account}
             for ln in entry.lines.select_related("account")]
    msg = check_balanced(lines) or check_date(entry.date, entry.kind)
    if msg:
        return msg
    for ln in lines:
        if ln["account"].is_group or not ln["account"].is_active:
            return (f"{ln['account'].code} {ln['account'].name} can no "
                    "longer take postings.")
    if not (entry.memo or "").strip():
        return "Say what the entry is for."
    with transaction.atomic():
        entry.ref = next_ref("JV", None)
        entry.status = "POSTED"
        entry.posted_by, entry.posted_at = actor, timezone.now()
        entry.save(update_fields=["ref", "status", "posted_by", "posted_at"])
    audit("journal", entry.id, "JOURNAL_POSTED", actor=actor,
          detail={"ref": entry.ref, "date": entry.date.isoformat(),
                  "kind": entry.kind,
                  "amount": str(sum((ln["debit"] for ln in lines), ZERO))})
    return None


def post_entry(*, on, memo, lines, actor, kind="TXN", source_type="",
               source_id=None, source_ref=""):
    """Post a balanced entry straight to the books — what a transaction form
    or an automatic rule does. `lines` are dicts as clean_lines returns.
    Raises ValueError with the reason if it can't be posted."""
    from .numbering import next_ref
    lines = [ln for ln in lines if ln["debit"] or ln["credit"]]
    msg = check_balanced(lines) or check_date(on, kind)
    if msg:
        raise ValueError(msg)
    for ln in lines:
        acc = ln["account"]
        if acc.is_group or not acc.is_active:
            raise ValueError(f"{acc.code} {acc.name} can't take postings.")
    with transaction.atomic():
        entry = JournalEntry.objects.create(
            date=on, kind=kind, memo=memo[:500], created_by=actor,
            source_type=source_type, source_id=source_id,
            source_ref=source_ref, ref=next_ref("JV", None), status="POSTED",
            posted_by=actor, posted_at=timezone.now())
        JournalLine.objects.bulk_create([
            JournalLine(entry=entry, line_no=i, **ln)
            for i, ln in enumerate(lines, 1)])
    return entry


def reverse(entry, actor, on=None, reason=""):
    """Undo a posted entry with its mirror. Returns (reversal, error)."""
    if entry.status != "POSTED":
        return None, "Only a posted entry is reversed — delete the draft."
    if JournalEntry.objects.filter(reversal_of=entry).exists():
        return None, f"{entry.ref} has already been reversed."
    if entry.kind == "REVERSAL":
        return None, ("This is itself a reversal. Post the entry again "
                      "instead of reversing the reversal.")
    reason = (reason or "").strip()
    if not reason:
        return None, "Say why it is being reversed."
    from . import reconcile
    if (msg := reconcile.reversal_block(entry)):
        return None, msg
    on = on or max(entry.date, timezone.localdate()) \
        if entry.kind != "OPENING" else entry.date
    kind = "OPENING" if entry.kind == "OPENING" else "REVERSAL"
    msg = check_date(on, kind)
    if msg:
        return None, msg
    with transaction.atomic():
        reconcile.release(entry)
        rev = JournalEntry.objects.create(
            date=on, kind="REVERSAL", memo=f"Reversal of {entry.ref} — "
                                            f"{reason}",
            reversal_of=entry, created_by=actor,
            source_type=entry.source_type, source_id=entry.source_id,
            source_ref=entry.source_ref)
        JournalLine.objects.bulk_create([
            JournalLine(entry=rev, line_no=ln.line_no, account=ln.account,
                        description=ln.description, debit=ln.credit,
                        credit=ln.debit, currency=ln.currency,
                        amount_fc=ln.amount_fc, fx_rate=ln.fx_rate,
                        site=ln.site, project=ln.project,
                        cost_head=ln.cost_head, party=ln.party)
            for ln in entry.lines.all()])
        from .numbering import next_ref
        rev.ref = next_ref("JV", None)
        rev.status = "POSTED"
        rev.posted_by, rev.posted_at = actor, timezone.now()
        rev.save(update_fields=["ref", "status", "posted_by", "posted_at"])
    audit("journal", entry.id, "JOURNAL_REVERSED", actor=actor,
          detail={"ref": entry.ref, "by": rev.ref, "reason": reason[:200]})
    return rev, None


# ---- reports ----------------------------------------------------------------

def trial_balance(date_from=None, date_to=None):
    """Every account with a balance or movement: brought forward, the
    period's debits and credits, and carried forward. Posted entries only.
    The two closing columns must agree — that is the test of the books."""
    date_to = date_to or timezone.localdate()
    date_from = date_from or books_start()
    base = JournalLine.objects.filter(entry__status="POSTED",
                                      entry__date__lte=date_to)
    opening = {r["account"]: (r["d"] or ZERO) - (r["c"] or ZERO)
               for r in base.filter(entry__date__lt=date_from)
               .values("account").annotate(d=Sum("debit"), c=Sum("credit"))}
    period = {r["account"]: (r["d"] or ZERO, r["c"] or ZERO)
              for r in base.filter(entry__date__gte=date_from)
              .values("account").annotate(d=Sum("debit"), c=Sum("credit"))}
    rows = []
    tot = {"opening_debit": ZERO, "opening_credit": ZERO, "debit": ZERO,
           "credit": ZERO, "closing_debit": ZERO, "closing_credit": ZERO}
    for a in LedgerAccount.objects.filter(is_group=False).select_related(
            "parent"):
        op = opening.get(a.id, ZERO)
        dr, cr = period.get(a.id, (ZERO, ZERO))
        cl = op + dr - cr
        if op == ZERO and dr == ZERO and cr == ZERO:
            continue
        row = {
            "account": a.id, "code": a.code, "name": a.name, "type": a.type,
            "type_label": a.get_type_display(),
            "group": a.parent.name if a.parent_id else "",
            "opening_debit": op if op > ZERO else ZERO,
            "opening_credit": -op if op < ZERO else ZERO,
            "debit": dr, "credit": cr,
            "closing_debit": cl if cl > ZERO else ZERO,
            "closing_credit": -cl if cl < ZERO else ZERO,
        }
        for k in tot:
            tot[k] += row[k]
        rows.append(row)
    return {"date_from": date_from, "date_to": date_to, "rows": rows,
            "totals": tot,
            "balanced": tot["closing_debit"] == tot["closing_credit"],
            "difference": tot["closing_debit"] - tot["closing_credit"]}


def account_ledger(account, date_from=None, date_to=None):
    """One account's entries in date order with a running balance, shown on
    its normal side (a liability's balance is its credit balance)."""
    date_to = date_to or timezone.localdate()
    date_from = date_from or books_start()
    sign = 1 if account.debit_normal else -1
    lines = JournalLine.objects.filter(account=account,
                                       entry__status="POSTED")
    op = lines.filter(entry__date__lt=date_from).aggregate(
        d=Sum("debit"), c=Sum("credit"))
    opening = ((op["d"] or ZERO) - (op["c"] or ZERO)) * sign
    bal = opening
    rows, dr_t, cr_t = [], ZERO, ZERO
    for ln in (lines.filter(entry__date__gte=date_from,
                            entry__date__lte=date_to)
               .select_related("entry", "site", "project")
               .order_by("entry__date", "entry_id", "line_no")):
        bal += (ln.debit - ln.credit) * sign
        dr_t += ln.debit
        cr_t += ln.credit
        rows.append({
            "entry": ln.entry_id, "ref": ln.entry.ref, "date": ln.entry.date,
            "kind": ln.entry.kind, "memo": ln.entry.memo,
            "description": ln.description, "party": ln.party,
            "site": ln.site.code if ln.site_id else "",
            "project": ln.project.code if ln.project_id else "",
            "currency": ln.currency, "amount_fc": ln.amount_fc,
            "debit": ln.debit, "credit": ln.credit, "balance": bal,
            "source_ref": ln.entry.source_ref,
        })
    return {"account": {"id": account.id, "code": account.code,
                        "name": account.name, "type": account.type,
                        "type_label": account.get_type_display(),
                        "currency": account.currency or BASE,
                        "debit_normal": account.debit_normal},
            "date_from": date_from, "date_to": date_to, "opening": opening,
            "debit": dr_t, "credit": cr_t, "closing": bal, "rows": rows}


def journal_filter(qs, params):
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("kind"):
        qs = qs.filter(kind=params["kind"])
    d1, d2 = _as_date(params.get("from")), _as_date(params.get("to"))
    if d1:
        qs = qs.filter(date__gte=d1)
    if d2:
        qs = qs.filter(date__lte=d2)
    t = (params.get("q") or "").strip()
    if t:
        qs = qs.filter(Q(ref__icontains=t) | Q(memo__icontains=t)
                       | Q(source_ref__icontains=t)
                       | Q(lines__description__icontains=t)
                       | Q(lines__party__icontains=t)).distinct()
    return qs

"""Bank reconciliation — QuickBooks' Reconcile (FINANCE_BUILD_BRIEF.md,
stage 2). A bank or cash account is agreed to the bank's statement at a
date: the lines the bank also shows are ticked off; when the opening
balance plus the ticks equals the statement's closing balance it is
finished, and what is left unticked is outstanding — cheques not yet
presented, deposits not yet credited.

The bank's statement can be read from the file the bank gives (Excel or
CSV); its lines are paired with the books' by amount and date, which ticks
them, and what the bank shows that the books don't — charges, interest, a
direct credit — is listed to be entered.

Amounts are in the account's own currency, as on the statement.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import books, ledger
from .audit import audit
from .ledger import BASE, ZERO, q2
from .models import (BankReconciliation, BankStatementLine, JournalLine,
                     LedgerTxn)

# how far apart a book date and the bank's date may be and still pair: a
# cheque is presented weeks after it is written; the bank is rarely early
EARLIER, LATER = 60, 5


def _value(ln, fc):
    """A line as the account's statement would show it: money in positive."""
    if not fc:
        return ln.debit - ln.credit
    amt = ln.amount_fc or ZERO
    return amt if ln.debit else -amt


def _hidden(entry):
    """An entry and its same-day reversal cancel out (an edited or voided
    transaction) and never reach a statement."""
    mirror = entry.reversal_of if entry.reversal_of_id else getattr(
        entry, "reversed_by", None)
    return mirror is not None and mirror.date == entry.date


def _lines(account, upto):
    return (JournalLine.objects
            .filter(account=account, entry__status="POSTED",
                    entry__date__lte=upto)
            .select_related("entry", "entry__reversal_of",
                            "entry__reversed_by", "cleared_in")
            .order_by("entry__date", "entry_id", "line_no"))


def last_done(account):
    return (BankReconciliation.objects.filter(account=account, status="DONE")
            .order_by("-statement_date", "-id").first())


def draft_of(account):
    return BankReconciliation.objects.filter(account=account,
                                             status="DRAFT").first()


def summary(account):
    """For the account's tile and register: how far it is reconciled."""
    done, draft = last_done(account), draft_of(account)
    return {"reconciled_to": done.statement_date if done else None,
            "reconciled_balance": done.statement_balance if done else None,
            "draft": draft.id if draft else None}


def _dec(v, what):
    try:
        return q2(Decimal(str(v).replace(",", "")))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{what} is not a number.")


def start(account, data, actor):
    """Begin reconciling to a statement. Returns (rec, error)."""
    if account.is_group or account.type not in books.MONEY_TYPES:
        return None, "Only a bank, cash or card account is reconciled."
    if draft_of(account):
        return None, ("A reconciliation of this account is already in "
                      "progress — finish or discard it first.")
    d = ledger._as_date(data.get("statement_date"))
    if d is None:
        return None, "Give the date the statement ends."
    if d > timezone.localdate():
        return None, "The statement date is in the future."
    prev = last_done(account)
    if prev and d <= prev.statement_date:
        return None, (f"This account is already reconciled to "
                      f"{prev.statement_date:%d %b %Y}. Give a later "
                      "statement date.")
    try:
        bal = _dec(data.get("statement_balance"), "The closing balance")
    except ValueError as exc:
        return None, str(exc)
    rec = BankReconciliation.objects.create(
        account=account, statement_date=d, statement_balance=bal,
        opening_balance=prev.statement_balance if prev else ZERO,
        created_by=actor)
    return rec, None


def update(rec, data):
    if rec.status != "DRAFT":
        return "It is finished — reopen it to change it."
    if "statement_date" in data:
        d = ledger._as_date(data.get("statement_date"))
        prev = last_done(rec.account)
        if d is None or d > timezone.localdate():
            return "Give the date the statement ends."
        if prev and d <= prev.statement_date:
            return (f"This account is already reconciled to "
                    f"{prev.statement_date:%d %b %Y}.")
        if d < rec.statement_date:
            # nothing dated after the statement stays ticked
            rec.lines.filter(entry__date__gt=d).update(cleared_in=None)
        rec.statement_date = d
    if "statement_balance" in data:
        try:
            rec.statement_balance = _dec(data.get("statement_balance"),
                                         "The closing balance")
        except ValueError as exc:
            return str(exc)
    rec.save()
    return None


def detail(rec):
    """Everything the reconcile screen shows."""
    acc = rec.account
    fc = bool(acc.currency)
    done = rec.status == "DONE"
    rows, cleared, book = [], ZERO, ZERO
    all_lines = list(_lines(acc, rec.statement_date))
    txns = {t.journal_id: t for t in LedgerTxn.objects.filter(
        journal_id__in={ln.entry_id for ln in all_lines})}
    matched = {s.matched_id: s for s in rec.statement_lines.all()
               if s.matched_id}
    for ln in all_lines:
        v = _value(ln, fc)
        book += v
        if _hidden(ln.entry) or v == ZERO:
            continue
        mine = ln.cleared_in_id == rec.id
        other = ln.cleared_in if (ln.cleared_in_id and not mine) else None
        if other is not None:
            # ticked off on an earlier statement — or, looking back at a
            # finished one, on a later statement: outstanding at this date
            if not (done and other.statement_date > rec.statement_date):
                continue
        if mine:
            cleared += v
        t = txns.get(ln.entry_id)
        st = matched.get(ln.id)
        rows.append({
            "id": ln.id, "date": ln.entry.date,
            "number": t.number if t else ln.entry.ref,
            "payee": (t.party if t and t.party else ln.party) or "",
            "memo": (t.memo if t and t.memo else "") or ln.description
            or ln.entry.memo,
            "reference": t.reference if t else "",
            "amount": v, "ticked": mine, "entry": ln.entry_id,
            "txn": t.id if t else None, "txn_type": t.type if t else None,
            "on_statement": bool(st),
            "statement_date": st.date if st else None,
        })
    closing = rec.opening_balance + cleared
    out_pay = sum((-r["amount"] for r in rows
                   if not r["ticked"] and r["amount"] < 0), ZERO)
    out_dep = sum((r["amount"] for r in rows
                   if not r["ticked"] and r["amount"] > 0), ZERO)
    stmt = [{"id": s.id, "date": s.date, "description": s.description,
             "reference": s.reference, "amount": s.amount,
             "balance": s.balance, "matched": s.matched_id}
            for s in rec.statement_lines.all()]
    return {
        "id": rec.id, "status": rec.status,
        "account": {"id": acc.id, "code": acc.code, "name": acc.name,
                    "currency": acc.currency or BASE},
        "statement_date": rec.statement_date,
        "statement_balance": rec.statement_balance,
        "opening_balance": rec.opening_balance,
        "cleared_balance": closing,
        "difference": rec.statement_balance - closing,
        "rows": rows,
        "ticked_payments": sum((-r["amount"] for r in rows
                                if r["ticked"] and r["amount"] < 0), ZERO),
        "ticked_deposits": sum((r["amount"] for r in rows
                                if r["ticked"] and r["amount"] > 0), ZERO),
        # the proof: the books' balance is the statement's plus what the
        # bank has not yet seen
        "book_balance": book, "outstanding_payments": out_pay,
        "outstanding_deposits": out_dep,
        "statement": stmt,
        "unmatched": [s for s in stmt if not s["matched"]],
        "statement_file": rec.statement_file.url if rec.statement_file else None,
        "finished_by": rec.finished_by.full_name if rec.finished_by_id else "",
        "finished_at": rec.finished_at,
        "created_by": rec.created_by.full_name if rec.created_by_id else "",
    }


def tick(rec, ids, on):
    """Tick lines off against this statement, or untick them."""
    if rec.status != "DRAFT":
        return "It is finished — reopen it to change it."
    qs = JournalLine.objects.filter(
        pk__in=ids, account=rec.account, entry__status="POSTED",
        entry__date__lte=rec.statement_date)
    if on:
        qs.filter(cleared_in__isnull=True).update(cleared_in=rec)
    else:
        mine = list(qs.filter(cleared_in=rec).values_list("pk", flat=True))
        JournalLine.objects.filter(pk__in=mine).update(cleared_in=None)
        rec.statement_lines.filter(matched_id__in=mine).update(matched=None)
    return None


def finish(rec, actor):
    if rec.status != "DRAFT":
        return "It is already finished."
    d = detail(rec)
    if d["difference"] != ZERO:
        cur = d["account"]["currency"]
        return (f"It doesn't agree yet — the statement says {cur} "
                f"{rec.statement_balance:,.2f} and the ticked lines come to "
                f"{cur} {d['cleared_balance']:,.2f}, a difference of "
                f"{abs(d['difference']):,.2f}.")
    rec.status = "DONE"
    rec.finished_by, rec.finished_at = actor, timezone.now()
    rec.save(update_fields=["status", "finished_by", "finished_at"])
    audit("bank_reconciliation", rec.id, "RECONCILED", actor=actor,
          detail={"account": rec.account.code,
                  "to": str(rec.statement_date),
                  "balance": str(rec.statement_balance)})
    return None


def reopen(rec, actor):
    if rec.status != "DONE":
        return "It is not finished."
    if last_done(rec.account).id != rec.id:
        return ("Only the latest reconciliation is reopened — a later "
                "statement was built on this one.")
    if draft_of(rec.account):
        return ("Another reconciliation of this account is in progress — "
                "finish or discard it first.")
    rec.status = "DRAFT"
    rec.finished_by = rec.finished_at = None
    rec.save(update_fields=["status", "finished_by", "finished_at"])
    audit("bank_reconciliation", rec.id, "RECONCILIATION_REOPENED",
          actor=actor, detail={"account": rec.account.code,
                               "to": str(rec.statement_date)})
    return None


def discard(rec):
    if rec.status != "DRAFT":
        return "A finished reconciliation is reopened, not discarded."
    with transaction.atomic():
        rec.lines.update(cleared_in=None)
        rec.delete()
    return None


def release(entry):
    """An entry being reversed leaves any statement in progress."""
    ids = list(entry.lines.filter(cleared_in__isnull=False)
               .values_list("pk", flat=True))
    if ids:
        BankStatementLine.objects.filter(matched_id__in=ids).update(
            matched=None)
        JournalLine.objects.filter(pk__in=ids).update(cleared_in=None)


def reversal_block(entry):
    """Why an entry can't be reversed (so its transaction not changed or
    voided): one of its lines is on a statement already agreed."""
    ln = (entry.lines.filter(cleared_in__status="DONE")
          .select_related("cleared_in", "account").first())
    if ln:
        return (f"{entry.ref} is on the {ln.account.name} statement "
                f"reconciled to {ln.cleared_in.statement_date:%d %b %Y}. "
                "Reopen that reconciliation first.")
    return None


# ---- reading the bank's file ---------------------------------------------------

_HEAD = {
    "date": r"\bdate\b",
    "description": r"descri|particular|narrat|detail|remark|transaction$",
    "reference": r"\bref|cheque|chq|check no",
    # one Amount column with a Dr/Cr marker beside it
    "drcr": r"dr\s*/\s*cr|cr\s*/\s*dr|^type$|^d/c$",
    "debit": r"debit|withdraw|paid out|money out|\bdr\b",
    "credit": r"credit|deposit|paid in|money in|\bcr\b",
    "amount": r"amount",
    "balance": r"balance",
}
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y",
                 "%d/%m/%y", "%d-%b-%y", "%d-%m-%y", "%d %B %Y", "%d.%m.%Y",
                 "%Y/%m/%d", "%d-%B-%Y")


def _cell_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    s = s.split("T")[0] if re.match(r"\d{4}-\d{2}-\d{2}T", s) else s
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:20].strip(), f).date()
        except ValueError:
            continue
    # "02-10-2026 14:31" and the like: try the date part alone
    head = s.split()[0]
    if head != s:
        return _cell_date(head)
    return None


def _cell_money(v):
    """A statement amount, or None. Handles 1,234.50, (1,234.50), 1234.5 DR."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        return q2(Decimal(str(v)))
    s = str(v).strip().upper().replace(",", "").replace("MVR", "").replace(
        "USD", "").strip()
    if not s or s in ("-", "—"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    sign = 1
    if s.endswith("DR"):
        sign, s = -1, s[:-2]
    elif s.endswith("CR"):
        s = s[:-2]
    try:
        n = Decimal(s.strip())
    except InvalidOperation:
        return None
    return q2(-n if neg else n * sign)


def _rows_of(upload):
    """The file as rows of cells."""
    name = (getattr(upload, "name", "") or "").lower()
    raw = upload.read()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            ws = load_workbook(io.BytesIO(raw), read_only=True,
                               data_only=True).active
        except Exception:
            raise ValueError("That Excel file can't be opened — save it "
                             "again as .xlsx or .csv and retry.")
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if name.endswith(".xls"):
        raise ValueError("That is the old Excel format (.xls). Open it and "
                         "save it as .xlsx or .csv, then import that.")
    if name.endswith(".pdf"):
        raise ValueError("A PDF statement can't be read line by line. "
                         "Download the statement from the bank as Excel or "
                         "CSV — or tick the lines off by hand.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("That file can't be read as text.")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def parse_statement(upload):
    """The bank's statement as lines: [{date, description, reference,
    amount (money in positive), balance}]. Finds the header row itself, so
    the bank's title lines above it don't matter. Raises ValueError with
    what is missing."""
    rows = _rows_of(upload)
    cols, head_at = None, None
    for i, row in enumerate(rows[:40]):
        found = {}
        for j, cell in enumerate(row):
            label = str(cell or "").strip().lower()
            if not label or len(label) > 40:
                continue
            for key, pat in _HEAD.items():
                if key not in found and re.search(pat, label):
                    # "value date" is not the date wanted if there is another
                    found[key] = j
                    break
        if "date" in found and ("amount" in found
                                or ("debit" in found and "credit" in found)
                                or "debit" in found or "credit" in found):
            cols, head_at = found, i
            break
    if cols is None:
        raise ValueError(
            "Couldn't find the statement's columns. The file needs a header "
            "row with a Date column and either Debit and Credit columns or "
            "an Amount column.")
    out = []

    def cell(row, key):
        j = cols.get(key)
        return row[j] if j is not None and j < len(row) else None
    for row in rows[head_at + 1:]:
        d = _cell_date(cell(row, "date"))
        if d is None:
            continue
        debit = _cell_money(cell(row, "debit"))
        credit = _cell_money(cell(row, "credit"))
        if debit is None and credit is None:
            amount = _cell_money(cell(row, "amount"))
            mark = str(cell(row, "drcr") or "").strip().upper()
            if amount and mark.startswith("D"):
                amount = -abs(amount)
        else:
            amount = abs(credit or ZERO) - abs(debit or ZERO)
        if not amount:
            continue
        out.append({
            "date": d,
            "description": " ".join(str(cell(row, "description") or "")
                                    .split())[:300],
            "reference": str(cell(row, "reference") or "").strip()[:80],
            "amount": amount, "balance": _cell_money(cell(row, "balance")),
        })
    if not out:
        raise ValueError("No transactions were found under the header row.")
    return out


def import_statement(rec, upload, actor):
    """Read the bank's file into this reconciliation and pair its lines
    with the books'. Returns (result, error)."""
    if rec.status != "DRAFT":
        return None, "It is finished — reopen it to change it."
    try:
        parsed = parse_statement(upload)
    except ValueError as exc:
        return None, str(exc)
    inside = [r for r in parsed if r["date"] <= rec.statement_date]
    if not inside:
        return None, (f"Every line in that file is dated after the statement "
                      f"date ({rec.statement_date:%d %b %Y}).")
    prev = last_done(rec.account)
    if prev:
        inside = [r for r in inside if r["date"] > prev.statement_date]
        if not inside:
            return None, (f"Every line in that file is on or before "
                          f"{prev.statement_date:%d %b %Y}, which is already "
                          "reconciled.")
    with transaction.atomic():
        rec.statement_lines.all().delete()
        BankStatementLine.objects.bulk_create([
            BankStatementLine(reconciliation=rec, line_no=i, **r)
            for i, r in enumerate(inside, 1)])
        upload.seek(0)
        rec.statement_file = upload
        rec.save()
        n = match(rec)
    last = next((r["balance"] for r in reversed(inside)
                 if r["balance"] is not None), None)
    audit("bank_reconciliation", rec.id, "STATEMENT_IMPORTED", actor=actor,
          detail={"lines": len(inside), "matched": n})
    return {"lines": len(inside), "matched": n,
            "skipped_after_date": len(parsed) - len(
                [r for r in parsed if r["date"] <= rec.statement_date]),
            "file_closing_balance": last}, None


def match(rec):
    """Pair the statement's unpaired lines with unticked lines in the books
    of the same amount: one whose reference the bank quotes first, else the
    nearest in date. A pair ticks the book line. Returns how many paired."""
    fc = bool(rec.account.currency)
    free = {}
    for ln in _lines(rec.account, rec.statement_date):
        if ln.cleared_in_id or _hidden(ln.entry):
            continue
        v = _value(ln, fc)
        if v:
            free.setdefault(v, []).append(ln)
    refs = {t.journal_id: t.reference.strip().lower()
            for t in LedgerTxn.objects.filter(
                journal_id__in={ln.entry_id for group in free.values()
                                for ln in group}).exclude(reference="")}
    n = 0
    for s in rec.statement_lines.filter(matched__isnull=True):
        pool = [ln for ln in free.get(s.amount, [])
                if s.date - timedelta(days=EARLIER) <= ln.entry.date
                <= s.date + timedelta(days=LATER)]
        if not pool:
            continue
        text = f"{s.description} {s.reference}".lower()

        def rank(ln):
            ref = refs.get(ln.entry_id, "")
            quoted = bool(ref) and len(ref) >= 4 and ref in text
            return (0 if quoted else 1, abs((s.date - ln.entry.date).days),
                    ln.entry.date, ln.id)
        best = min(pool, key=rank)
        free[s.amount].remove(best)
        best.cleared_in = rec
        best.save(update_fields=["cleared_in"])
        s.matched = best
        s.save(update_fields=["matched"])
        n += 1
    return n

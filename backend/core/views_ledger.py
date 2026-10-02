"""The books — API (`/api/v1/ledger/*`). Rules live in core/ledger.py."""
from io import BytesIO

from django.http import HttpResponse
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import brand, ledger
from .models import JournalEntry, LedgerAccount


def _off():
    # A sister company's instance keeps no books here until its own are set up.
    if not brand.brand()["features"].get("books"):
        return Response({"detail": "The books are not switched on for this "
                                   "company."}, status=403)
    return None


def _read(request):
    if (off := _off()):
        return off
    if request.user.role not in ledger.READ_ROLES:
        return Response({"detail": "The books are open to Finance, the "
                                   "Director and the signatory."}, status=403)
    return None


def _write(request):
    if (off := _off()):
        return off
    if request.user.role not in ledger.WRITE_ROLES:
        return Response({"detail": "Finance keeps the books."}, status=403)
    return None


def _account(a, balances=None):
    bal = (balances or {}).get(a.id)
    return {
        "id": a.id, "code": a.code, "name": a.name, "type": a.type,
        "type_label": a.get_type_display(), "parent": a.parent_id,
        "is_group": a.is_group, "currency": a.currency,
        "system": bool(a.system_key), "is_bank": bool(a.bank_account_id),
        "description": a.description, "is_active": a.is_active,
        "debit_normal": a.debit_normal,
        # on the account's normal side: a liability shows its credit balance
        "balance": None if bal is None else (bal if a.debit_normal else -bal),
    }


def _entry(e, lines=True):
    out = {
        "id": e.id, "ref": e.ref, "date": e.date, "kind": e.kind,
        "kind_label": e.get_kind_display(), "status": e.status, "memo": e.memo,
        "source_ref": e.source_ref,
        "reversal_of": e.reversal_of.ref if e.reversal_of_id else None,
        "reversed_by": (e.reversed_by.ref
                        if getattr(e, "reversed_by", None) else None),
        "created_by": e.created_by.full_name if e.created_by_id else "",
        "posted_by": e.posted_by.full_name if e.posted_by_id else "",
        "posted_at": e.posted_at,
    }
    rows = list(e.lines.select_related("account", "site", "project",
                                       "cost_head"))
    out["total"] = sum((ln.debit for ln in rows), ledger.ZERO)
    if lines:
        out["lines"] = [{
            "id": ln.id, "account": ln.account_id,
            "account_code": ln.account.code, "account_name": ln.account.name,
            "description": ln.description, "debit": ln.debit,
            "credit": ln.credit, "currency": ln.currency,
            "amount_fc": ln.amount_fc, "fx_rate": ln.fx_rate,
            "site": ln.site_id, "site_code": ln.site.code if ln.site_id else "",
            "project": ln.project_id,
            "project_code": ln.project.code if ln.project_id else "",
            "cost_head": ln.cost_head_id, "party": ln.party,
        } for ln in rows]
    return out


# ---- chart of accounts ------------------------------------------------------

@api_view(["GET", "POST"])
def accounts(request):
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        a, msg = ledger.save_account(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(_account(a), status=201)
    from django.db.models import Sum
    from .models import JournalLine
    bal = {r["account"]: (r["d"] or 0) - (r["c"] or 0)
           for r in JournalLine.objects.filter(entry__status="POSTED")
           .values("account").annotate(d=Sum("debit"), c=Sum("credit"))}
    rows = list(LedgerAccount.objects.all())
    # an account held in a foreign currency also shows what it holds in it
    held = {}
    for r in (JournalLine.objects.filter(entry__status="POSTED")
              .exclude(account__currency="").values("account", "debit")
              .annotate(fc=Sum("amount_fc"))):
        fc = r["fc"] or 0
        held[r["account"]] = held.get(r["account"], 0) + (fc if r["debit"] else -fc)
    out = [_account(a, bal) for a in rows]
    # how far each bank account is agreed to its statement
    from .models import BankReconciliation
    recs = {}
    for r in BankReconciliation.objects.order_by("statement_date", "id"):
        row = recs.setdefault(r.account_id, {"reconciled_to": None,
                                             "reconciling": None})
        if r.status == "DONE":
            row["reconciled_to"] = r.statement_date
        else:
            row["reconciling"] = r.id
    for o in out:
        if o["currency"]:
            o["balance_fc"] = held.get(o["id"], 0)
        o.update(recs.get(o["id"], {}))
    return Response({
        "accounts": out,
        "types": [{"value": v, "label": lab}
                  for v, lab in LedgerAccount.Type.choices],
        "can_edit": request.user.role in ledger.WRITE_ROLES,
        "settings": ledger.settings_dict(),
        "posted_entries": JournalEntry.objects.filter(status="POSTED").count(),
    })


@api_view(["PATCH", "DELETE"])
def account_detail(request, pk):
    if (bad := _write(request)):
        return bad
    a = LedgerAccount.objects.filter(pk=pk).first()
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        msg = ledger.delete_account(a, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(status=204)
    a, msg = ledger.save_account(request.data, request.user, account=a)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_account(a))


@api_view(["POST"])
def setup(request):
    """Lay down the standard chart on empty books."""
    if (bad := _write(request)):
        return bad
    made, msg = ledger.setup_standard_chart(request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"accounts": made}, status=201)


@api_view(["POST"])
def sync_banks(request):
    if (bad := _write(request)):
        return bad
    return Response({"added": ledger.sync_bank_accounts(request.user)})


@api_view(["GET", "POST"])
def settings(request):
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if request.user.role != "ADMIN" and "books_start_date" in request.data:
            return Response({"detail": "Only an admin moves the start of the "
                                       "books."}, status=403)
        if (bad := _write(request)):
            return bad
        msg = ledger.save_settings(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
    return Response(ledger.settings_dict())


# ---- journals ---------------------------------------------------------------

@api_view(["GET", "POST"])
def journals(request):
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        e, msg = ledger.save_draft(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        if request.data.get("post"):
            msg = ledger.post(e, request.user)
            if msg:                      # kept as a draft, with the reason
                return Response({"detail": msg, "draft": _entry(e)},
                                status=400)
            e.refresh_from_db()
        return Response(_entry(e), status=201)
    qs = ledger.journal_filter(
        JournalEntry.objects.select_related("created_by", "posted_by",
                                            "reversal_of", "reversed_by"),
        request.GET)
    try:
        limit = min(int(request.GET.get("limit", 50)), 200)
        offset = max(int(request.GET.get("offset", 0)), 0)
    except ValueError:
        limit, offset = 50, 0
    total = qs.count()
    return Response({
        "journals": [_entry(e, lines=False) for e in qs[offset:offset + limit]],
        "total": total, "has_more": offset + limit < total,
        "drafts": JournalEntry.objects.filter(status="DRAFT").count(),
        "can_edit": request.user.role in ledger.WRITE_ROLES,
    })


def _get_entry(pk):
    return (JournalEntry.objects.select_related(
        "created_by", "posted_by", "reversal_of", "reversed_by")
        .filter(pk=pk).first())


@api_view(["GET", "PATCH", "DELETE"])
def journal_detail(request, pk):
    if (bad := _read(request)):
        return bad
    e = _get_entry(pk)
    if e is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "GET":
        return Response(_entry(e))
    if (bad := _write(request)):
        return bad
    if request.method == "DELETE":
        if e.status != "DRAFT":
            return Response({"detail": "A posted entry is never deleted — "
                                       "reverse it."}, status=400)
        e.delete()
        return Response(status=204)
    e, msg = ledger.save_draft(request.data, request.user, entry=e)
    if msg:
        return Response({"detail": msg}, status=400)
    if request.data.get("post"):
        msg = ledger.post(e, request.user)
        if msg:
            return Response({"detail": msg, "draft": _entry(e)}, status=400)
    return Response(_entry(_get_entry(pk)))


@api_view(["POST"])
def journal_action(request, pk, action):
    if (bad := _write(request)):
        return bad
    e = _get_entry(pk)
    if e is None:
        return Response({"detail": "Not found."}, status=404)
    if action == "post":
        msg = ledger.post(e, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(_entry(_get_entry(pk)))
    if action == "reverse":
        rev, msg = ledger.reverse(
            e, request.user, on=ledger._as_date(request.data.get("date")),
            reason=request.data.get("reason"))
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(_entry(_get_entry(rev.id)), status=201)
    return Response({"detail": "Unknown action."}, status=400)


# ---- reports ----------------------------------------------------------------

def _xlsx(title, subtitle, headers, rows, totals=None, widths=None,
          name="report"):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = title[:28]
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = subtitle
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(wrap_text=True)
    r = 5
    for row in rows:
        for i, v in enumerate(row, 1):
            c = ws.cell(row=r, column=i, value=v)
            if isinstance(v, (int, float)) or hasattr(v, "quantize"):
                c.number_format = "#,##0.00"
        r += 1
    if totals:
        for i, v in enumerate(totals, 1):
            c = ws.cell(row=r, column=i, value=v)
            c.font = Font(bold=True)
            if hasattr(v, "quantize"):
                c.number_format = "#,##0.00"
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(), content_type="application/vnd.openxmlformats-"
        "officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
    return resp


@api_view(["GET"])
def trial_balance(request):
    if (bad := _read(request)):
        return bad
    tb = ledger.trial_balance(ledger._as_date(request.GET.get("from")),
                              ledger._as_date(request.GET.get("to")))
    if request.GET.get("export") == "xlsx":
        t = tb["totals"]
        return _xlsx(
            "Trial balance",
            f"{tb['date_from']:%d %b %Y} to {tb['date_to']:%d %b %Y} · MVR",
            ["Code", "Account", "Type", "Opening Dr", "Opening Cr",
             "Debit", "Credit", "Closing Dr", "Closing Cr"],
            [[r["code"], r["name"], r["type_label"], r["opening_debit"],
              r["opening_credit"], r["debit"], r["credit"],
              r["closing_debit"], r["closing_credit"]] for r in tb["rows"]],
            ["", "Total", "", t["opening_debit"], t["opening_credit"],
             t["debit"], t["credit"], t["closing_debit"],
             t["closing_credit"]],
            [9, 44, 14, 15, 15, 15, 15, 15, 15],
            f"trial-balance-{tb['date_to']}")
    return Response(tb)


@api_view(["GET"])
def account_ledger(request, pk):
    if (bad := _read(request)):
        return bad
    a = LedgerAccount.objects.filter(pk=pk).first()
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    if a.is_group:
        return Response({"detail": "A group holds no entries of its own — "
                                   "open an account under it."}, status=400)
    led = ledger.account_ledger(a, ledger._as_date(request.GET.get("from")),
                                ledger._as_date(request.GET.get("to")))
    if request.GET.get("export") == "xlsx":
        return _xlsx(
            f"{a.code} {a.name}",
            f"{led['date_from']:%d %b %Y} to {led['date_to']:%d %b %Y} · MVR",
            ["Date", "Entry", "Memo", "Description", "Party", "Site",
             "Debit", "Credit", "Balance"],
            [["", "", "Brought forward", "", "", "", "", "", led["opening"]]]
            + [[r["date"], r["ref"], r["memo"], r["description"], r["party"],
                r["site"], r["debit"] or None, r["credit"] or None,
                r["balance"]] for r in led["rows"]],
            ["", "", "Total", "", "", "", led["debit"], led["credit"],
             led["closing"]],
            [12, 10, 40, 34, 24, 8, 15, 15, 16],
            f"ledger-{a.code}-{led['date_to']}")
    return Response(led)


# ---- QuickBooks-style transactions (core/books.py) --------------------------

def _txn(t, lines=True):
    out = {
        "id": t.id, "number": t.number, "type": t.type,
        "type_label": t.get_type_display(), "status": t.status, "date": t.date,
        "account": t.account_id, "account_name": t.account.name,
        "to_account": t.to_account_id,
        "to_account_name": t.to_account.name if t.to_account_id else "",
        "party": t.party, "party_tin": t.party_tin, "reference": t.reference,
        "memo": t.memo, "currency": t.currency, "fx_rate": t.fx_rate,
        "amount": t.amount, "amount_mvr": t.amount_mvr,
        "amount_to": t.amount_to, "tax_invoice_no": t.tax_invoice_no,
        "tax_invoice_date": t.tax_invoice_date,
        "tax_invoice_held": t.tax_invoice_held,
        "attachment_url": t.attachment.url if t.attachment else None,
        "journal": t.journal_id, "journal_ref": t.journal.ref if t.journal_id else "",
        "void_reason": t.void_reason,
        "created_by": t.created_by.full_name if t.created_by_id else "",
        "party_ref": t.party_ref_id, "due_date": t.due_date,
        "is_opening": t.is_opening,
    }
    if t.type in ("BILL", "INVOICE"):
        paid = getattr(t, "paid", 0) if t.status == "POSTED" else 0
        out["paid"], out["balance"] = paid, t.amount - paid
        if lines:
            out["payments"] = [{
                "id": a.payment_id, "number": a.payment.number,
                "date": a.payment.date, "amount": a.amount,
            } for a in t.applied.filter(payment__status="POSTED")
                .select_related("payment")]
    elif t.type in ("BILL_PAY", "RECEIPT") and lines:
        out["applies"] = [{
            "doc": a.doc_id, "number": a.doc.number,
            "reference": a.doc.reference, "date": a.doc.date,
            "currency": a.doc.currency, "amount": a.amount,
        } for a in t.applies.select_related("doc")]
    if lines:
        out["lines"] = [{
            "id": ln.id, "account": ln.account_id,
            "account_code": ln.account.code, "account_name": ln.account.name,
            "description": ln.description, "amount": ln.amount,
            "gst_treatment": ln.gst_treatment, "gst_rate": ln.gst_rate,
            "gst_amount": ln.gst_amount, "site": ln.site_id,
            "site_code": ln.site.code if ln.site_id else "",
            "project": ln.project_id,
        } for ln in t.lines.select_related("account", "site")]
    return out


def _txn_qs():
    from . import books
    from .models import LedgerTxn
    return (LedgerTxn.objects.select_related("account", "to_account",
                                             "journal", "created_by")
            .annotate(**books._paid()))


def _txn_data(request):
    """A form sends JSON; with a receipt attached it sends multipart, the
    fields as one JSON string beside the file."""
    import json
    if "payload" in request.data:
        try:
            return json.loads(request.data["payload"])
        except (TypeError, ValueError):
            return {}
    return request.data


@api_view(["GET"])
def books_meta(request):
    if (bad := _read(request)):
        return bad
    from . import books
    return Response(books.meta())


@api_view(["GET", "POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def txns(request):
    from . import books
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        data = _txn_data(request)
        t, msg = books.save_txn(data.get("type"), data, request.user,
                                attachment=request.FILES.get("attachment"))
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(_txn(_txn_qs().get(pk=t.pk)), status=201)
    qs = books.txn_filter(_txn_qs(), request.GET)
    if request.GET.get("status") != "all":
        qs = qs.exclude(status="VOID")
    if request.GET.get("open"):
        # bills / invoices not yet settled in full, the oldest due first
        from django.db.models import F
        qs = (qs.filter(type__in=books.DOC_TYPES, status="POSTED",
                        paid__lt=F("amount")).order_by("due_date", "id"))
    try:
        limit = min(int(request.GET.get("limit", 100)), 300)
    except ValueError:
        limit = 100
    total = qs.count()
    return Response({"txns": [_txn(t, lines=False) for t in qs[:limit]],
                     "total": total,
                     "can_edit": request.user.role in ledger.WRITE_ROLES})


@api_view(["GET", "PATCH"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def txn_detail(request, pk):
    from . import books
    if (bad := _read(request)):
        return bad
    t = _txn_qs().filter(pk=pk).first()
    if t is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if (bad := _write(request)):
            return bad
        data = _txn_data(request)
        t2, msg = books.save_txn(t.type, data, request.user, txn=t,
                                 attachment=request.FILES.get("attachment"))
        if msg:
            return Response({"detail": msg}, status=400)
        t = _txn_qs().get(pk=pk)
    return Response(_txn(t))


@api_view(["POST"])
def txn_void(request, pk):
    from . import books
    if (bad := _write(request)):
        return bad
    t = _txn_qs().filter(pk=pk).first()
    if t is None:
        return Response({"detail": "Not found."}, status=404)
    msg = books.void_txn(t, request.user, request.data.get("reason"))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_txn(_txn_qs().get(pk=pk)))


@api_view(["GET", "POST"])
def parties(request):
    """Suppliers or customers, each with what is open between us."""
    from . import books
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        p, msg = books.save_party(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(books.party_dict(p), status=201)
    kind = request.GET.get("kind")
    if kind not in ("SUPPLIER", "CUSTOMER"):
        return Response({"detail": "kind is SUPPLIER or CUSTOMER."}, status=400)
    return Response({"parties": books.parties(kind),
                     "can_edit": request.user.role in ledger.WRITE_ROLES})


@api_view(["GET", "PATCH"])
def party_detail(request, pk):
    from . import books
    from .models import LedgerParty
    if (bad := _read(request)):
        return bad
    p = LedgerParty.objects.filter(pk=pk).first()
    if p is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if (bad := _write(request)):
            return bad
        p, msg = books.save_party(request.data, request.user, party=p)
        if msg:
            return Response({"detail": msg}, status=400)
    st = books.party_statement(p)
    if request.GET.get("export") == "xlsx":
        return _xlsx(
            p.name, f"{p.get_kind_display()} account · MVR",
            ["Date", "Number", "Type", "Their number", "Due", "Currency",
             "Amount", "Change (MVR)", "Balance (MVR)"],
            [[r["date"], r["number"], r["type_label"], r["reference"],
              r["due_date"], r["currency"], r["amount"], r["change"],
              r["balance"]] for r in st["rows"]],
            ["", "", "Balance", "", "", "", "", "", st["balance"]],
            [12, 11, 18, 20, 12, 9, 15, 15, 16],
            f"account-{p.id}")
    st["can_edit"] = request.user.role in ledger.WRITE_ROLES
    return Response(st)


@api_view(["GET"])
def report_aging(request):
    """What we owe suppliers (kind=SUPPLIER) or are owed by customers
    (kind=CUSTOMER), aged by due date, against the control accounts."""
    from . import books
    if (bad := _read(request)):
        return bad
    kind = request.GET.get("kind")
    if kind not in ("SUPPLIER", "CUSTOMER"):
        return Response({"detail": "kind is SUPPLIER or CUSTOMER."}, status=400)
    r = books.aging(kind, ledger._as_date(request.GET.get("as_of")))
    if request.GET.get("export") == "xlsx":
        cols = ("current", "d30", "d60", "d90", "older", "total")
        return _xlsx(
            "Payables aging" if kind == "SUPPLIER" else "Receivables aging",
            f"As at {r['as_of']:%d %b %Y} · MVR · by due date",
            ["Supplier" if kind == "SUPPLIER" else "Customer", "Not yet due",
             "1–30 days", "31–60 days", "61–90 days", "Over 90 days", "Total"],
            [[row["name"]] + [row[c] or None for c in cols]
             for row in r["rows"]],
            ["Total"] + [r["total"][c] for c in cols],
            [40, 15, 15, 15, 15, 15, 16],
            f"{'payables' if kind == 'SUPPLIER' else 'receivables'}-aging-"
            f"{r['as_of']}")
    return Response(r)


# ---- posting Planet's operations (core/posting.py) ----------------------------

def _rule_names():
    from . import posting
    return {r[0]: r[2] for r in posting.RULES}


def _posting_report(rows):
    names = _rule_names()
    return [{**r, "name": names[r["rule"]]} for r in rows]


def _posting_state(request):
    """What the Posting screen shows — the same after every action."""
    from . import posting
    return {**posting.status(), "heads": posting.heads(),
            "can_edit": request.user.role in ledger.WRITE_ROLES}


@api_view(["GET", "POST"])
def posting_rules(request):
    """GET: the rules, which are on, and each cost head's account.
    POST {on: [...], from}: switch rules on or off, set the date to post
    from."""
    from . import posting
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        msg = posting.save_settings(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
    return Response(_posting_state(request))


@api_view(["POST"])
def posting_action(request, action):
    """preview: what posting would do, nothing saved. run: do it, for the
    rules that are switched on. take-out: reverse a rule's entries."""
    from . import posting
    if (bad := _write(request)):
        return bad
    keys = request.data.get("rules") or []
    if action == "preview":
        if not keys:
            return Response({"detail": "Say which rules."}, status=400)
        return Response({"report": _posting_report(
            posting.run(keys, request.user, commit=False)), "saved": False})
    if action == "run":
        on = posting.rules_on()
        keys = [k for k in (keys or on) if k in on]
        if not keys:
            return Response({"detail": "No rule is switched on."}, status=400)
        return Response({"report": _posting_report(
            posting.run(keys, request.user, commit=True)), "saved": True})
    if action == "take-out":
        n, msg = posting.take_out(request.data.get("rule"), request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response({"reversed": n, **_posting_state(request)})
    return Response({"detail": "Unknown action."}, status=404)


@api_view(["PATCH"])
def posting_head(request, pk):
    from . import posting
    from .models import CostHead
    if (bad := _write(request)):
        return bad
    h = CostHead.objects.filter(pk=pk).first()
    if h is None:
        return Response({"detail": "Not found."}, status=404)
    msg = posting.map_head(h, request.data.get("account"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"heads": posting.heads()})


# ---- GST return (core/gst_return.py) ------------------------------------------

@api_view(["GET"])
def report_gst(request):
    """A taxable period's return figures and the two statements behind
    them; export=output | input gives MIRA's statement as Excel."""
    from . import gst_return
    if (bad := _read(request)):
        return bad
    d1 = ledger._as_date(request.GET.get("from"))
    d2 = ledger._as_date(request.GET.get("to"))
    if d1 is None or d2 is None or d2 < d1:
        return Response({"detail": "Give the taxable period — from and to."},
                        status=400)
    data = gst_return.build(d1, d2)
    which = request.GET.get("export")
    if which in ("output", "input"):
        wb = (gst_return.output_statement_xlsx(data) if which == "output"
              else gst_return.input_statement_xlsx(data))
        buf = BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(), content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"))
        resp["Content-Disposition"] = (
            f'attachment; filename="{which}-tax-statement-{d1}-to-{d2}.xlsx"')
        return resp
    return Response(data)


# ---- import from Excel (core/books_import.py) --------------------------------

@api_view(["GET"])
def import_template(request):
    from . import books_import
    if (bad := _read(request)):
        return bad
    buf = BytesIO()
    books_import.template().save(buf)
    resp = HttpResponse(buf.getvalue(), content_type=(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    resp["Content-Disposition"] = ('attachment; '
                                   'filename="books-import-template.xlsx"')
    return resp


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def imports(request):
    """GET: the files imported so far. POST a file: check it (nothing is
    saved), or with commit=1 import it — whole, or not at all."""
    from . import books_import
    if (bad := _read(request)):
        return bad
    if request.method == "GET":
        return Response({"imports": books_import.history(),
                         "can_edit": request.user.role in ledger.WRITE_ROLES})
    if (bad := _write(request)):
        return bad
    f = request.FILES.get("file")
    if f is None:
        return Response({"detail": "Attach the filled-in template."},
                        status=400)
    res, msg = books_import.run(
        f, request.user, commit=str(request.data.get("commit")) == "1")
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(res, status=201 if res["imported"] else 200)


@api_view(["POST"])
def import_undo(request, pk):
    from . import books_import
    from .models import LedgerImport
    if (bad := _write(request)):
        return bad
    b = LedgerImport.objects.filter(pk=pk).first()
    if b is None:
        return Response({"detail": "Not found."}, status=404)
    msg = books_import.undo(b, request.user, request.data.get("reason"))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"imports": books_import.history()})


# ---- bank reconciliation (core/reconcile.py) ---------------------------------

def _rec_row(r):
    return {"id": r.id, "status": r.status,
            "statement_date": r.statement_date,
            "statement_balance": r.statement_balance,
            "opening_balance": r.opening_balance,
            "finished_by": r.finished_by.full_name if r.finished_by_id else "",
            "finished_at": r.finished_at}


@api_view(["GET", "POST"])
def account_reconciliations(request, pk):
    """An account's reconciliations, newest first; POST starts one."""
    from . import reconcile
    if (bad := _read(request)):
        return bad
    a = LedgerAccount.objects.filter(pk=pk).first()
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        rec, msg = reconcile.start(a, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(reconcile.detail(rec), status=201)
    return Response({
        "account": {"id": a.id, "code": a.code, "name": a.name,
                    "currency": a.currency or ledger.BASE},
        "book_balance": (ledger.balance_of(a) if not a.currency else None),
        "reconciliations": [_rec_row(r) for r in a.reconciliations
                            .select_related("finished_by")],
        "can_edit": request.user.role in ledger.WRITE_ROLES,
        **reconcile.summary(a)})


@api_view(["GET", "PATCH", "DELETE"])
def reconciliation_detail(request, pk):
    from . import reconcile
    from .models import BankReconciliation
    if (bad := _read(request)):
        return bad
    rec = BankReconciliation.objects.select_related(
        "account", "finished_by", "created_by").filter(pk=pk).first()
    if rec is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method in ("PATCH", "DELETE"):
        if (bad := _write(request)):
            return bad
        if request.method == "DELETE":
            msg = reconcile.discard(rec)
            if msg:
                return Response({"detail": msg}, status=400)
            return Response(status=204)
        msg = reconcile.update(rec, request.data)
        if msg:
            return Response({"detail": msg}, status=400)
    d = reconcile.detail(rec)
    if request.GET.get("export") == "xlsx":
        cur = d["account"]["currency"]
        rows = [["Balance per the bank statement", "", "", "", "",
                 d["statement_balance"]], []]
        for title, sign in (("Add: deposits not yet on the statement", 1),
                            ("Less: payments not yet on the statement", -1)):
            rows.append([title])
            for r in d["rows"]:
                if not r["ticked"] and (r["amount"] > 0) == (sign > 0):
                    rows.append([r["date"], r["number"], r["payee"], r["memo"],
                                 r["reference"], r["amount"]])
            rows.append([])
        rows += [["Ticked off against this statement"]] + [
            [r["date"], r["number"], r["payee"], r["memo"], r["reference"],
             r["amount"]] for r in d["rows"] if r["ticked"]]
        return _xlsx(
            f"{d['account']['name']} reconciliation",
            f"Statement to {d['statement_date']:%d %b %Y} · {cur} · "
            f"{rec.get_status_display()}",
            ["Date", "Number", "Payee", "Memo", "Reference", cur], rows,
            ["Balance per the books", "", "", "", "", d["book_balance"]],
            [34, 12, 28, 34, 16, 16],
            f"reconciliation-{d['account']['code']}-{d['statement_date']}")
    d["can_edit"] = request.user.role in ledger.WRITE_ROLES
    return Response(d)


@api_view(["POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def reconciliation_action(request, pk, action):
    from . import reconcile
    from .models import BankReconciliation
    if (bad := _write(request)):
        return bad
    rec = BankReconciliation.objects.select_related("account").filter(
        pk=pk).first()
    if rec is None:
        return Response({"detail": "Not found."}, status=404)
    extra = {}
    if action == "tick":
        ids = request.data.get("lines") or []
        msg = reconcile.tick(rec, ids, bool(request.data.get("on")))
    elif action == "import":
        f = request.FILES.get("file")
        if f is None:
            return Response({"detail": "Attach the statement file."},
                            status=400)
        res, msg = reconcile.import_statement(rec, f, request.user)
        extra = {"imported": res} if res else {}
    elif action == "match":
        if rec.status != "DRAFT":
            msg = "It is finished — reopen it to change it."
        else:
            extra, msg = {"matched_now": reconcile.match(rec)}, None
    elif action == "finish":
        msg = reconcile.finish(rec, request.user)
    elif action == "reopen":
        msg = reconcile.reopen(rec, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=404)
    if msg:
        return Response({"detail": msg}, status=400)
    rec.refresh_from_db()
    d = reconcile.detail(rec)
    d["can_edit"] = True
    d.update(extra)
    return Response(d)


@api_view(["GET"])
def account_register(request, pk):
    from . import books
    if (bad := _read(request)):
        return bad
    a = LedgerAccount.objects.filter(pk=pk).first()
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    if a.is_group or a.type not in books.MONEY_TYPES:
        return Response({"detail": "A register is kept for a bank, cash or "
                                   "card account."}, status=400)
    reg = books.register(a, ledger._as_date(request.GET.get("from")),
                         ledger._as_date(request.GET.get("to")))
    if request.GET.get("export") == "xlsx":
        return _xlsx(
            f"{a.code} {a.name}",
            f"Register · {reg['date_from']:%d %b %Y} to "
            f"{reg['date_to']:%d %b %Y} · {reg['account']['currency']}",
            ["Date", "Number", "Payee", "Memo", "Reference", "Account",
             "Payment", "Deposit", "Balance"],
            [["", "", "Brought forward", "", "", "", "", "", reg["opening"]]]
            + [[r["date"], r["number"], r["payee"], r["memo"], r["reference"],
                r["split"], r["payment"] or None, r["deposit"] or None,
                r["balance"]] for r in reg["rows"]],
            ["", "", "Total", "", "", "", reg["payments"], reg["deposits"],
             reg["closing"]],
            [12, 11, 28, 34, 16, 30, 15, 15, 16],
            f"register-{a.code}-{reg['date_to']}")
    return Response(reg)


def _statement_rows(sec):
    return [[("    " * r["depth"]) + (f"{r['code']} " if r["code"] else "")
             + r["name"], r["amount"]] for r in sec["rows"]]


@api_view(["GET"])
def report_pnl(request):
    from . import books
    if (bad := _read(request)):
        return bad
    site = None
    if request.GET.get("site"):
        from .models import Site
        site = Site.objects.filter(pk=request.GET["site"]).first()
        if site is None:
            return Response({"detail": "No such site."}, status=404)
    r = books.profit_and_loss(ledger._as_date(request.GET.get("from")),
                              ledger._as_date(request.GET.get("to")),
                              site.id if site else None)
    r["site"] = {"id": site.id, "code": site.code} if site else None
    if request.GET.get("export") == "xlsx":
        s = r["sections"]
        rows = []
        for key, total_label in (("INCOME", "Total income"),
                                 ("COGS", "Total cost of goods sold")):
            rows += [[s[key]["label"], None]] + _statement_rows(s[key]) \
                + [[total_label, s[key]["total"]]]
        rows += [["GROSS PROFIT", r["gross_profit"]],
                 [s["EXPENSE"]["label"], None]] + _statement_rows(s["EXPENSE"]) \
            + [["Total expenses", s["EXPENSE"]["total"]],
               ["OPERATING PROFIT", r["operating_profit"]]]
        for key in ("OTHER_INCOME", "OTHER_EXPENSE"):
            rows += [[s[key]["label"], None]] + _statement_rows(s[key]) \
                + [[f"Total {s[key]['label'].lower()}", s[key]["total"]]]
        return _xlsx("Profit and loss" + (f" — {site.code}" if site else ""),
                     f"{r['date_from']:%d %b %Y} to {r['date_to']:%d %b %Y} "
                     "· MVR", ["", "MVR"], rows,
                     ["NET PROFIT", r["net_profit"]], [52, 18],
                     f"profit-and-loss-{r['date_to']}")
    return Response(r)


@api_view(["GET"])
def report_balance_sheet(request):
    from . import books
    if (bad := _read(request)):
        return bad
    r = books.balance_sheet(ledger._as_date(request.GET.get("as_of")))
    if request.GET.get("export") == "xlsx":
        s = r["sections"]
        rows = [["ASSETS", None]]
        for key in ("BANK", "AR", "OTHER_CURRENT_ASSET"):
            rows += [[s[key]["label"], None]] + _statement_rows(s[key])
        rows += [["Total current assets", r["current_assets"]]]
        for key in ("FIXED_ASSET", "OTHER_ASSET"):
            rows += [[s[key]["label"], None]] + _statement_rows(s[key])
        rows += [["TOTAL ASSETS", r["total_assets"]],
                 ["LIABILITIES", None]]
        for key in ("AP", "CREDIT_CARD", "OTHER_CURRENT_LIABILITY",
                    "LONG_TERM_LIABILITY"):
            rows += [[s[key]["label"], None]] + _statement_rows(s[key])
        rows += [["Total liabilities", r["total_liabilities"]],
                 ["EQUITY", None]] + _statement_rows(s["EQUITY"]) \
            + [["Net profit — earlier years, not yet closed",
                r["net_profit_earlier_years"]],
               ["Net profit for the year", r["net_profit_this_year"]],
               ["Total equity", r["total_equity"]]]
        return _xlsx("Balance sheet", f"As at {r['as_of']:%d %b %Y} · MVR",
                     ["", "MVR"], rows,
                     ["TOTAL LIABILITIES AND EQUITY",
                      r["total_liabilities_and_equity"]], [52, 18],
                     f"balance-sheet-{r['as_of']}")
    return Response(r)

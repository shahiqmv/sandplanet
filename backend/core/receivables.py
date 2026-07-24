"""Receivables — the money-in ledger on top of the certified claims (IPCs).

Every certified/paid ProgressClaim carries a tax-invoice number, an amount
(net-to-pay incl. GST from the claim waterfall) and, from the project's client
credit period, a due date. This module turns those into:

  * per-invoice outstanding balances + due dates,
  * an aging analysis (current / 1-30 / 31-60 / 61-90 / 90+ days overdue),
  * a per-client statement of account (invoices raised vs. money received,
    with a running balance).

A "client" is a Site (contracts sit on projects within a site). Contracts are
USD, so receivables are USD — no FX. Read-only: nothing here mutates data.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .commercial import _q2, claim_valuation
from .models import ClientReceipt, ProgressClaim, Site

ZERO = Decimal("0")


def _today():
    return timezone.localdate()


def invoice_date(claim):
    """The tax-invoice date — when the claim was certified (fallback: raised)."""
    if claim.certified_at:
        return timezone.localtime(claim.certified_at).date()
    return claim.created_at.date() if claim.created_at else _today()


def due_date(claim):
    """When this invoice falls due = issue date + the client's credit period.
    No credit period recorded → due on issue."""
    days = claim.project.client_credit_days or 0
    return invoice_date(claim) + timedelta(days=days)


def invoiced_amount(claim):
    """The invoice value (net to pay incl. GST) from the claim waterfall."""
    return _q2(claim_valuation(claim)["waterfall"]["net_to_pay"])


def _received_by_claim(claim_ids):
    rows = (ClientReceipt.objects.filter(claim_id__in=claim_ids)
            .values("claim_id").annotate(s=Sum("amount")))
    return {r["claim_id"]: (r["s"] or ZERO) for r in rows}


def _invoice_claims(site_id=None):
    """Certified/paid claims that carry a tax invoice (the receivables), newest
    invoice first is not needed — callers sort as they wish."""
    qs = (ProgressClaim.objects
          .filter(status__in=["CERTIFIED", "PAID"])
          .exclude(invoice_no="")
          .select_related("project", "project__site"))
    if site_id is not None:
        qs = qs.filter(project__site_id=site_id)
    return list(qs)


def invoice_rows(site_id=None, as_of=None, only_outstanding=False):
    """One row per tax invoice with amount / received / outstanding and its
    aging bucket relative to `as_of` (default today)."""
    as_of = as_of or _today()
    claims = _invoice_claims(site_id)
    received = _received_by_claim([c.id for c in claims])
    rows = []
    for c in claims:
        amt = invoiced_amount(c)
        got = _q2(received.get(c.id, ZERO))
        out = amt - got
        if only_outstanding and out <= 0:
            continue
        dd = due_date(c)
        overdue = (as_of - dd).days
        rows.append({
            "claim_id": c.id, "invoice_no": c.invoice_no, "ref": c.ref,
            "claim_type": c.claim_type,
            "project_id": c.project_id, "project_code": c.project.code,
            "project_title": c.project.title,
            "site_id": c.project.site_id,
            "invoice_date": invoice_date(c), "due_date": dd,
            "days_overdue": max(overdue, 0),
            "amount": amt, "received": got, "outstanding": out,
            "bucket": _bucket(overdue),
            "status": "PAID" if out <= 0 else (
                "OVERDUE" if overdue > 0 else "CURRENT"),
        })
    rows.sort(key=lambda r: (r["due_date"], r["invoice_no"]))
    return rows


BUCKETS = ["current", "d1_30", "d31_60", "d61_90", "d90p"]
BUCKET_LABELS = {
    "current": "Not yet due", "d1_30": "1–30 days", "d31_60": "31–60 days",
    "d61_90": "61–90 days", "d90p": "Over 90 days",
}


def _bucket(overdue_days):
    if overdue_days <= 0:
        return "current"
    if overdue_days <= 30:
        return "d1_30"
    if overdue_days <= 60:
        return "d31_60"
    if overdue_days <= 90:
        return "d61_90"
    return "d90p"


def _empty_buckets():
    return {b: ZERO for b in BUCKETS}


def aging(as_of=None, site_id=None):
    """Aging analysis of every outstanding invoice, grouped by client (site),
    with per-bucket columns and a grand total."""
    as_of = as_of or _today()
    rows = invoice_rows(site_id=site_id, as_of=as_of, only_outstanding=True)
    clients = {}
    for r in rows:
        c = clients.setdefault(r["site_id"], {
            "site_id": r["site_id"], **_empty_buckets(),
            "total": ZERO, "invoices": 0})
        c[r["bucket"]] += r["outstanding"]
        c["total"] += r["outstanding"]
        c["invoices"] += 1
    # attach client names + sort by exposure
    sites = {s.id: s for s in Site.objects.filter(id__in=clients.keys())}
    client_rows = []
    for sid, c in clients.items():
        s = sites.get(sid)
        c["client"] = (s.client_name.strip() if s and s.client_name.strip()
                       else (s.name if s else "—"))
        c["site_code"] = s.code if s else "—"
        client_rows.append(c)
    client_rows.sort(key=lambda c: c["total"], reverse=True)
    totals = _empty_buckets()
    totals["total"] = ZERO
    for c in client_rows:
        for b in BUCKETS:
            totals[b] += c[b]
        totals["total"] += c["total"]
    return {
        "as_of": as_of, "buckets": BUCKETS,
        "bucket_labels": BUCKET_LABELS,
        "clients": client_rows, "totals": totals,
        "invoice_count": len(rows),
    }


def client_accounts(as_of=None):
    """One row per client (site) with an invoice, showing billed / received /
    outstanding — the picker + overview for statements."""
    as_of = as_of or _today()
    rows = invoice_rows(as_of=as_of)
    accts = {}
    for r in rows:
        a = accts.setdefault(r["site_id"], {
            "site_id": r["site_id"], "billed": ZERO, "received": ZERO,
            "outstanding": ZERO, "invoices": 0, "overdue": ZERO})
        a["billed"] += r["amount"]
        a["received"] += r["received"]
        a["outstanding"] += r["outstanding"]
        a["invoices"] += 1
        if r["days_overdue"] > 0 and r["outstanding"] > 0:
            a["overdue"] += r["outstanding"]
    sites = {s.id: s for s in Site.objects.filter(id__in=accts.keys())}
    out = []
    for sid, a in accts.items():
        s = sites.get(sid)
        a["client"] = (s.client_name.strip() if s and s.client_name.strip()
                       else (s.name if s else "—"))
        a["site_code"] = s.code if s else "—"
        out.append(a)
    out.sort(key=lambda a: a["outstanding"], reverse=True)
    return out


def client_statement(site, date_from=None, date_to=None):
    """A client's statement of account: invoices raised (debit) and receipts
    (credit) in date order with a running balance, plus an opening balance for
    anything before `date_from`."""
    date_to = date_to or _today()
    claims = [c for c in _invoice_claims(site.id)
              if invoice_date(c) <= date_to]
    receipts = list(ClientReceipt.objects
                    .filter(project__site=site, received_on__lte=date_to)
                    .select_related("project", "claim"))

    txns = []
    for c in claims:
        txns.append({
            "date": invoice_date(c), "kind": "INVOICE",
            "sort": 0, "ref": c.invoice_no or c.ref,
            "project_code": c.project.code,
            "description": f"Tax invoice — {c.ref} "
                           f"({c.get_claim_type_display()})",
            "due_date": due_date(c),
            "debit": invoiced_amount(c), "credit": ZERO,
        })
    for rc in receipts:
        ref = rc.reference or (rc.claim.invoice_no if rc.claim else "")
        txns.append({
            "date": rc.received_on, "kind": "RECEIPT",
            "sort": 1, "ref": ref,
            "project_code": rc.project.code,
            "description": "Payment received"
                           + (f" — ref {rc.reference}" if rc.reference else ""),
            "due_date": None,
            "debit": ZERO, "credit": _q2(rc.amount),
        })
    txns.sort(key=lambda t: (t["date"], t["sort"], t["ref"]))

    opening = ZERO
    rows = []
    if date_from:
        for t in txns:
            if t["date"] < date_from:
                opening += t["debit"] - t["credit"]
    balance = opening
    billed = received = ZERO
    for t in txns:
        if date_from and t["date"] < date_from:
            continue
        balance += t["debit"] - t["credit"]
        billed += t["debit"]
        received += t["credit"]
        rows.append({**t, "balance": balance})

    client = (site.client_name.strip() if site.client_name.strip()
              else site.name)
    return {
        "site_id": site.id, "site_code": site.code, "client": client,
        "client_address": site.client_address,
        "date_from": date_from, "date_to": date_to,
        "opening": opening, "rows": rows,
        "billed": billed, "received": received, "closing": balance,
    }

"""Receivables and payables aging at the end of the period (owner
2026-11-07): what clients owe us, and what we owe suppliers, by how long
overdue. Payables are company-wide money, so only the ExCom's company view
carries them; a site report shows its own receivables.
"""
from collections import defaultdict
from decimal import Decimal

from . import fx, vouchers
from .imports import payments_due
from .models import Payable, Site
from .receivables import BUCKET_LABELS, BUCKETS, _bucket, invoice_rows
from .reports import col, kpi, section, sum_rows

ZERO = Decimal("0")


def _usd(v, ccy, rate):
    return fx.to_usd(v or ZERO, ccy, rate).quantize(Decimal("0.01"))


def _bucket_cols():
    return [col(b, BUCKET_LABELS[b], "money") for b in BUCKETS]


def build(ctx):
    rate = fx.usd_rate()
    on = ctx.end
    sites = {s.id: s for s in Site.objects.all()}

    # ---- receivables, invoice by invoice
    inv = []
    for sid in ctx.site_ids:
        for r in invoice_rows(site_id=sid, as_of=on, only_outstanding=True):
            s = sites.get(r["site_id"])
            inv.append({
                "site": s.code if s else "", "client": (s.client_name.strip()
                                                       or s.name) if s else "",
                "project": r["project_code"], "invoice": r["invoice_no"],
                "invoice_date": r["invoice_date"], "due": r["due_date"],
                "overdue": max(r["days_overdue"] or 0, 0),
                "outstanding": _usd(r["outstanding"], r["currency"], rate),
                "bucket": r["bucket"]})
    inv.sort(key=lambda r: -r["overdue"])
    by_client = defaultdict(lambda: {b: ZERO for b in BUCKETS})
    for r in inv:
        by_client[(r["site"], r["client"])][r["bucket"]] += r["outstanding"]
    rec_rows = [{"site": k[0], "client": k[1], **v,
                 "total": sum(v.values(), ZERO)}
                for k, v in by_client.items()]
    rec_rows.sort(key=lambda r: -r["total"])
    rec_total = {"site": "", "client": "Total",
                 **sum_rows(rec_rows, list(BUCKETS) + ["total"])}
    sections = [
        section("Receivables by client", [col("site", "Site"),
                                          col("client", "Client", wide=True)]
                + _bucket_cols() + [col("total", "Total", "money")],
                rec_rows, rec_total if rec_rows else None),
        section("Outstanding invoices", [
            col("site", "Site"), col("project", "Project"),
            col("invoice", "Invoice"), col("invoice_date", "Dated", "date"),
            col("due", "Due", "date"), col("overdue", "Days overdue", "int"),
            col("outstanding", "Outstanding", "money")], inv,
            {"site": "", "project": "Total", "invoice": "",
             **sum_rows(inv, ("outstanding",))} if inv else None,
            note="Most overdue first."),
    ]
    kpis = [kpi("Owed by clients", rec_total["total"],
                sub=f"{len(inv)} invoice{'s' if len(inv) != 1 else ''}"),
            kpi("Over 90 days", rec_total["d90p"])]

    # ---- payables, company only
    if ctx.company:
        pay = []
        for p in (Payable.objects.filter(status="OUTSTANDING")
                  .select_related("site", "payroll_line__run", "rent_due",
                                  "bill_charge")):
            bal = vouchers.balance(payable=p)["balance"]
            if bal <= 0:
                continue
            ccy = vouchers.payable_currency(p)
            overdue = (on - p.due_date).days if p.due_date else 0
            pay.append({"vendor": p.vendor or p.ref_label,
                        "site": p.site.code if p.site_id else "HO",
                        "ref": p.ref_label, "due": p.due_date,
                        "overdue": max(overdue, 0),
                        "outstanding": _usd(bal, ccy, rate),
                        "bucket": _bucket(overdue)})
        for m in payments_due():
            o = m.order
            bal = vouchers.balance(milestone=m)["balance"]
            if bal <= 0:
                continue
            due = m.pay_by or m.due_date
            overdue = (on - due).days if due else 0
            pay.append({"vendor": o.supplier.name if o.supplier_id else "",
                        "site": "Import", "ref": f"{o.document.ref} {m.label}",
                        "due": due, "overdue": max(overdue, 0),
                        "outstanding": _usd(bal, o.order_currency, rate),
                        "bucket": _bucket(overdue) if due else "current"})
        pay.sort(key=lambda r: -r["overdue"])
        by_vendor = defaultdict(lambda: {b: ZERO for b in BUCKETS})
        for r in pay:
            by_vendor[r["vendor"]][r["bucket"]] += r["outstanding"]
        pay_rows = [{"vendor": k, **v, "total": sum(v.values(), ZERO)}
                    for k, v in by_vendor.items()]
        pay_rows.sort(key=lambda r: -r["total"])
        pay_total = {"vendor": "Total",
                     **sum_rows(pay_rows, list(BUCKETS) + ["total"])}
        sections += [
            section("Payables by supplier", [col("vendor", "Supplier",
                                                 wide=True)]
                    + _bucket_cols() + [col("total", "Total", "money")],
                    pay_rows, pay_total if pay_rows else None,
                    note="Credit purchases, subcontractor valuations, rent, "
                         "bills, salaries payable and import milestones not "
                         "yet paid. Not yet due counts from the agreed credit "
                         "period, or the import's pay-by date."),
            section("Outstanding payables", [
                col("vendor", "Supplier", wide=True), col("site", "Site"),
                col("ref", "Reference", wide=True), col("due", "Due", "date"),
                col("overdue", "Days overdue", "int"),
                col("outstanding", "Outstanding", "money")], pay,
                {"vendor": "Total", "site": "", "ref": "",
                 **sum_rows(pay, ("outstanding",))} if pay else None),
        ]
        kpis += [kpi("Owed to suppliers", pay_total["total"],
                     sub=f"{len(pay)} item{'s' if len(pay) != 1 else ''}"),
                 kpi("Overdue to suppliers",
                     sum((pay_total[b] for b in BUCKETS if b != "current"),
                         ZERO)),
                 kpi("Net position", rec_total["total"] - pay_total["total"],
                     sub="owed to us less owed by us")]
    return {"kpis": kpis, "sections": sections,
            "notes": [f"As at {on:%d %b %Y}. MVR converted at the company "
                      f"rate of {rate} per USD."]}

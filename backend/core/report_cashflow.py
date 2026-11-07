"""Cash-flow forecast, thirteen weeks from the start of the period (owner
2026-11-07): money due in from clients against money due out, week by week,
from the due dates Planet already holds.

In: outstanding invoices by their due date; anything already overdue falls in
week one. Out: outstanding payables and import milestones by their due or
pay-by dates, and payroll as an estimate, the last locked month's gross
repeated each month, because the next runs do not exist yet. Nothing not yet
raised (claims not certified, orders not placed, rent not yet due) is in it,
and the forecast says so. Company-wide only: cash is the company's.
"""
from datetime import timedelta
from decimal import Decimal

from . import fx, vouchers
from .imports import payments_due
from .models import Payable, PayrollRun, Site
from .payroll import compute_line
from .receivables import invoice_rows
from .reports import col, kpi, section

ZERO = Decimal("0")
WEEKS = 13
PAY_DAY = 7     # salaries go out early in the month


def _usd(v, ccy, rate):
    return fx.to_usd(v or ZERO, ccy, rate)


def build(ctx):
    rate = fx.usd_rate()
    start = ctx.start
    weeks = [(start + timedelta(days=7 * i),
              start + timedelta(days=7 * i + 6)) for i in range(WEEKS)]
    end = weeks[-1][1]
    q2 = lambda v: Decimal(v).quantize(Decimal("0.01"))  # noqa: E731

    def week_of(d):
        if d is None:
            return None
        if d < start:
            return 0
        if d > end:
            return None
        return (d - start).days // 7

    rows = [{"week": f"Wk {i + 1}", "from": a, "to": b,
             "receipts": ZERO, "suppliers": ZERO, "imports": ZERO,
             "payroll": ZERO} for i, (a, b) in enumerate(weeks)]
    beyond = {"receipts": ZERO, "suppliers": ZERO, "imports": ZERO}

    def put(kind, d, amount):
        w = week_of(d)
        if w is None:
            beyond[kind] += amount
        else:
            rows[w][kind] += amount

    site_ids = [s.id for s in Site.objects.all()]
    for sid in site_ids:
        for r in invoice_rows(site_id=sid, as_of=start, only_outstanding=True):
            put("receipts", r["due_date"], _usd(r["outstanding"], r["currency"],
                                                rate))
    for p in Payable.objects.filter(status="OUTSTANDING").select_related(
            "payroll_line__run", "rent_due", "bill_charge"):
        bal = vouchers.balance(payable=p)["balance"]
        if bal > 0:
            put("suppliers", p.due_date, _usd(bal, vouchers.payable_currency(p),
                                              rate))
    for m in payments_due():
        bal = vouchers.balance(milestone=m)["balance"]
        if bal > 0:
            put("imports", m.pay_by or m.due_date or start,
                _usd(bal, m.order.order_currency, rate))

    # payroll: the last locked month's gross, per currency, on the 7th of
    # each month in the window
    last = (PayrollRun.objects.filter(status="LOCKED")
            .order_by("-year", "-month").values_list("year", "month").first())
    monthly = ZERO
    if last:
        for run in PayrollRun.objects.filter(status="LOCKED", year=last[0],
                                             month=last[1]):
            gross = sum((compute_line(ln)["gross"] + compute_line(ln)["rounding"]
                         for ln in run.lines.all()), ZERO)
            monthly += _usd(gross, run.currency, rate)
    y, m = start.year, start.month
    while True:
        d = start.replace(year=y, month=m, day=PAY_DAY)
        if d > end:
            break
        if d >= start:
            put("payroll", d, monthly)
        m += 1
        if m == 13:
            y, m = y + 1, 1

    running = ZERO
    for r in rows:
        r["out"] = r["suppliers"] + r["imports"] + r["payroll"]
        r["net"] = r["receipts"] - r["out"]
        running += r["net"]
        r["cumulative"] = running
        for k in ("receipts", "suppliers", "imports", "payroll", "out", "net",
                  "cumulative"):
            r[k] = q2(r[k])
    tot = {"week": "Total", "from": None, "to": None}
    for k in ("receipts", "suppliers", "imports", "payroll", "out", "net"):
        tot[k] = q2(sum((r[k] for r in rows), ZERO))
    tot["cumulative"] = rows[-1]["cumulative"] if rows else ZERO
    low = min(rows, key=lambda r: r["cumulative"]) if rows else None
    return {
        "kpis": [
            kpi("Due in", tot["receipts"], sub="outstanding invoices"),
            kpi("Due out", tot["out"], sub="suppliers, imports, payroll"),
            kpi("Net over 13 weeks", tot["net"]),
            kpi("Lowest point", low["cumulative"] if low else ZERO,
                sub=f"{low['week']}, from {low['from']:%d %b}" if low else ""),
            kpi("Payroll estimate / month", q2(monthly),
                sub=f"last locked month: {last[1]}/{last[0]}" if last else
                "no locked run"),
        ],
        "sections": [section(
            f"Week by week from {start:%d %b %Y}", [
                col("week", "Week"), col("from", "From", "date"),
                col("to", "To", "date"),
                col("receipts", "In: client receipts due", "money"),
                col("suppliers", "Out: suppliers & bills", "money"),
                col("imports", "Out: import payments", "money"),
                col("payroll", "Out: payroll (estimate)", "money"),
                col("out", "Total out", "money"), col("net", "Net", "money"),
                col("cumulative", "Cumulative", "money")],
            rows, tot,
            note="Week 1 carries everything already overdue. Beyond the 13 "
                 f"weeks: in {q2(beyond['receipts'])}, out "
                 f"{q2(beyond['suppliers'] + beyond['imports'])}.")],
        "notes": [
            "Only money already due or raised is in the forecast: claims not "
            "yet certified, orders not yet placed and rent not yet raised are "
            "not. Payroll is an estimate from the last locked month, placed "
            f"on the {PAY_DAY}th of each month.",
            "Not a bank balance: it starts from zero and shows the movement.",
            f"MVR converted at the company rate of {rate} per USD.",
        ],
    }

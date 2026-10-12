"""One-off repair of the project cost ledger (owner 2026-10-12).

1. Labour. Locking a payroll run used to reverse every labour posting of its
   sites for the month — other runs' payroll included — and a reversed USD
   posting was booked in MVR. For every site and month a locked run touches,
   every existing labour posting is mirrored exactly (same currency, book,
   vehicle) so the old rows net to nothing, and each locked run's labour is
   posted afresh, tagged with the run.
2. Salaries as Paid. Each locked run already paid — one payment, or person by
   person — posts its net as Paid, split by site as its cost was.
3. Imports. Every cleared shipment's project lines post as Incurred at
   landed cost, less what the store has already issued to site.

Dry run by default: everything happens inside a transaction that is rolled
back, and the before/after per site is printed. --apply commits it. Parts 1
and 2 refuse to run twice unless --force.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from core import fx, staff_cost
from core.imports import sync_cleared_incurred
from core.models import (CompanyParameter, CostPosting, ImportShipment,
                         PayrollRun, Site, User)
from core.payroll import labour_shares, post_run_incurred, post_run_paid

FLAG = "repair_cost_ledger_2026_10"


class _DryRun(Exception):
    pass


def _summary():
    rate = fx.usd_rate()
    out = defaultdict(lambda: defaultdict(float))
    for r in (CostPosting.objects.filter(book="PROJECT",
                                         cost_head__overhead=False)
              .values("site__code", "state", "currency")
              .annotate(t=Sum("amount"))):
        out[r["site__code"]][r["state"]] += float(
            fx.to_usd(r["t"] or 0, r["currency"], rate))
    return out


class Command(BaseCommand):
    help = "Repair labour, salary payments and cleared imports in the ledger."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--actor", default="admin")

    def handle(self, *args, **opts):
        actor = User.objects.get(username=opts["actor"])
        done = CompanyParameter.objects.filter(key=FLAG).exists()
        before = _summary()
        try:
            with transaction.atomic():
                if done and not opts["force"]:
                    self.stdout.write("labour + paid already repaired — "
                                      "skipping (use --force)")
                else:
                    self._labour(actor)
                    self._paid(actor)
                    CompanyParameter.objects.update_or_create(
                        key=FLAG, defaults={"value": "done"})
                self._imports(actor)
                after = _summary()
                self._report(before, after)
                if not opts["apply"]:
                    raise _DryRun()
        except _DryRun:
            self.stdout.write("\nDRY RUN — nothing was saved. "
                              "Run again with --apply to commit.")
            return
        self.stdout.write("\nAPPLIED.")

    def _labour(self, actor):
        runs = list(PayrollRun.objects.filter(status="LOCKED")
                    .order_by("locked_at"))
        months = set()
        for run in runs:
            for site, _v, _g, _n, _l in labour_shares(run):
                if site:
                    months.add((site.id, run.year, run.month))
        mirrored = 0
        for site_id, y, m in sorted(months):
            rows = list(CostPosting.objects.filter(
                site_id=site_id, source="STAFF", staff_year=y,
                staff_month=m))
            for row in rows:
                staff_cost.mirror(row, actor)
                mirrored += 1
        posted = 0
        for run in runs:
            posted += len(post_run_incurred(run, actor))
        self.stdout.write(f"labour: {len(months)} site-months, {mirrored} "
                          f"old rows mirrored, {posted} run postings made "
                          f"for {len(runs)} locked runs")

    def _paid(self, actor):
        n = 0
        for run in PayrollRun.objects.filter(status="LOCKED"):
            doc = run.payment_request
            if doc is None:
                continue
            per_head = list(doc.payables.filter(payroll_line__isnull=False,
                                                status="SETTLED"))
            if doc.payables.filter(payroll_line__isnull=False).exists():
                for p in per_head:
                    n += len(post_run_paid(run, actor,
                                           posted_on=p.settled_on,
                                           lines={p.payroll_line_id}))
                continue
            pr = getattr(doc, "payment_request", None)
            if pr and pr.paid_date:
                n += len(post_run_paid(run, actor, posted_on=pr.paid_date,
                                       document=doc))
        self.stdout.write(f"salaries paid: {n} postings")

    def _imports(self, actor):
        n, mvr = 0, 0
        for sh in ImportShipment.objects.filter(status="CLEARED"):
            moved = sync_cleared_incurred(sh, actor)
            if moved:
                n += 1
                mvr += float(moved)
        self.stdout.write(f"imports: {n} cleared shipments posted, "
                          f"MVR {mvr:,.2f}")

    def _report(self, before, after):
        self.stdout.write("\nsite   incurred before -> after      "
                          "paid before -> after   (USD)")
        tot = defaultdict(float)
        for code in sorted(set(before) | set(after), key=str):
            if Site.objects.filter(code=code, is_head_office=True).exists():
                tag = " (head office)"
            else:
                tag = ""
            b, a = before.get(code, {}), after.get(code, {})
            di = a.get("INCURRED", 0) - b.get("INCURRED", 0)
            dp = a.get("PAID", 0) - b.get("PAID", 0)
            tot["i"] += di
            tot["p"] += dp
            if abs(di) < 1 and abs(dp) < 1:
                continue
            self.stdout.write(
                f"{code:5} {b.get('INCURRED', 0):12,.0f} -> "
                f"{a.get('INCURRED', 0):12,.0f} ({di:+11,.0f})   "
                f"{b.get('PAID', 0):11,.0f} -> {a.get('PAID', 0):11,.0f} "
                f"({dp:+10,.0f}){tag}")
        self.stdout.write(f"TOTAL change: incurred {tot['i']:+,.0f}, "
                          f"paid {tot['p']:+,.0f}")

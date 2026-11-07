"""Exceptions: what does not add up, for someone to look at before payroll
and the month-end (owner 2026-11-07). The cases that prompted it: a man
punching in at SJR for three weeks with no attendance anywhere (EMP-0648),
and days filled in at a site he had already left (EMP-0645).

Every row names a person, a day or an item and says what is wrong with it;
the report has no totals to be right about, only things to fix.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal


from . import vouchers
from .biometric import day_punch_window
from .models import (Attendance, AttendanceDevice, DevicePunch, Payable,
                     PayrollRun, Site, SitePmHistory, TimesheetMonth)
from .procurement_pipeline import _operational_lines, line_risk
from .reports import col, kpi, section

ZERO = Decimal("0")


def _local_day(dt):
    start, _ = day_punch_window(dt.date())
    # the window is in Maldives time; shift the instant to the same clock
    return (dt + (start.utcoffset() or timedelta())).date()


def build(ctx):
    on = ctx.end
    sites = {s.id: s for s in Site.objects.filter(id__in=ctx.site_ids)}
    clocked = {d.site_id for d in AttendanceDevice.objects.filter(
        is_active=True, site_id__in=sites)}
    t0, _ = day_punch_window(ctx.start)
    _, t1 = day_punch_window(on)

    all_sites = {s.id: s for s in Site.objects.all()}
    # who was a PM of which site on which days: an approval is judged by the
    # PM of the day, not of today
    pm_days = defaultdict(list)
    for h in SitePmHistory.objects.filter(site_id__in=sites):
        pm_days[(h.site_id, h.pm_user_id)].append((h.from_date, h.to_date))

    def was_pm(site_id, user_id, day):
        # the PM of the day, with a month's grace either side: PM history is
        # entered late, and a man handing over still signs the last days
        grace = timedelta(days=31)
        return any(a - grace <= day and (b is None or day <= b + grace)
                   for a, b in pm_days.get((site_id, user_id), []))

    # punches by (employee, local day) -> set of site ids
    punched = defaultdict(set)
    for emp_id, at, sid in (DevicePunch.objects
                            .filter(employee__isnull=False,
                                    punched_at__gte=t0, punched_at__lt=t1)
                            .values_list("employee_id", "punched_at",
                                         "device__site_id")):
        punched[(emp_id, _local_day(at))].add(sid)
    marks = {}
    for a in (Attendance.objects
              .filter(day__gte=ctx.start, day__lte=on)
              .select_related("employee", "site", "ot_approved_by")):
        marks[(a.employee_id, a.day)] = a

    wrong_site, not_marked, no_punch, ot_approver = [], [], [], []
    for (emp_id, day), where in punched.items():
        a = marks.get((emp_id, day))
        here = {s for s in where if s in sites}
        if a is None:
            for sid in here:
                not_marked.append({"emp": None, "emp_id": emp_id, "day": day,
                                   "site": sites[sid].code})
        elif a.site_id not in where and (a.site_id in sites or here):
            wrong_site.append({
                "emp": f"{a.employee.emp_no} {a.employee.full_name}",
                "day": day, "site": a.site.code,
                "punched_at": ", ".join(sorted(
                    all_sites[s].code for s in where if s in all_sites))})
    # a missing punch means something only from the day the clock first knew
    # the person: terminals went in mid-month and people are enrolled late
    first_punch = {}
    for (emp_id, day), where in punched.items():
        for sid in where:
            k = (emp_id, sid)
            if k not in first_punch or day < first_punch[k]:
                first_punch[k] = day
    for (emp_id, day), a in marks.items():
        if (a.site_id in clocked and a.remark in ("PRESENT", "HALF_DAY")
                and day > first_punch.get((emp_id, a.site_id), day)
                and (emp_id, day) not in punched
                and day.isoweekday() in a.site.working_days):
            no_punch.append({"emp": f"{a.employee.emp_no} "
                                    f"{a.employee.full_name}",
                             "day": day, "site": a.site.code})
        if a.site_id in sites and a.ot_approved and a.ot_approved_by_id:
            u = a.ot_approved_by
            if (u.role not in ("DIRECTOR", "ADMIN")
                    and not was_pm(a.site_id, u.id, day)):
                ot_approver.append({
                    "emp": f"{a.employee.emp_no} {a.employee.full_name}",
                    "day": day, "site": a.site.code,
                    "hours": a.ot_approved, "by": u.full_name,
                    "role": u.get_role_display()})
    if not_marked:
        from .models import Employee
        names = {e.id: f"{e.emp_no} {e.full_name}" for e in
                 Employee.objects.filter(id__in={r["emp_id"]
                                                 for r in not_marked})}
        for r in not_marked:
            r["emp"] = names.get(r["emp_id"], str(r["emp_id"]))

    # days a site marked nobody
    blank_days = []
    marked_days = defaultdict(set)
    for sid, day in (Attendance.objects.filter(
            site_id__in=sites, day__gte=ctx.start, day__lte=on)
            .values_list("site_id", "day").distinct()):
        marked_days[sid].add(day)
    for sid, s in sites.items():
        if s.is_head_office:
            continue
        missing = [ctx.start + timedelta(days=i)
                   for i in range((on - ctx.start).days + 1)
                   if (ctx.start + timedelta(days=i)).isoweekday()
                   in s.working_days
                   and (ctx.start + timedelta(days=i)) not in marked_days[sid]]
        if missing and marked_days[sid]:
            blank_days.append({"site": s.code, "days": len(missing),
                               "first": missing[0], "last": missing[-1]})

    # payroll not locked for months before this one
    unlocked = []
    first_of_month = on.replace(day=1)
    for r in (PayrollRun.objects.filter(site_id__in=sites)
              .exclude(status="LOCKED").select_related("site")
              .order_by("year", "month")):
        if (r.year, r.month) < (first_of_month.year, first_of_month.month):
            unlocked.append({"site": r.site.code,
                             "month": f"{r.month:02d}/{r.year}",
                             "status": r.get_status_display()})
    ts = []
    for t in (TimesheetMonth.objects.filter(site_id__in=sites)
              .exclude(status="LOCKED").select_related("site")):
        if (t.year, t.month) < (first_of_month.year, first_of_month.month):
            ts.append({"site": t.site.code, "month": f"{t.month:02d}/{t.year}",
                       "status": "attendance not closed"})

    # money waiting with nothing raised
    overdue_pay = []
    for p in (Payable.objects.filter(status="OUTSTANDING", due_date__lt=on)
              .select_related("site")):
        if ctx.company or p.site_id in sites:
            bal = vouchers.balance(payable=p)
            if bal["balance"] > 0 and not bal["vouchered"]:
                overdue_pay.append({"ref": p.ref_label, "vendor": p.vendor,
                                    "site": p.site.code if p.site_id else "HO",
                                    "due": p.due_date,
                                    "days": (on - p.due_date).days,
                                    "amount": bal["balance"]})
    overdue_pay.sort(key=lambda r: -r["days"])

    # procurement late or at risk
    late = []
    for ln in _operational_lines():
        site = ln.schedule.site
        if site.id not in sites:
            continue
        r = line_risk(ln)
        if r["level"] in ("LATE", "AT_RISK"):
            late.append({"site": site.code,
                         "project": ln.project.code if ln.project_id else "",
                         "item": ln.description[:80],
                         "required": ln.required_date,
                         "level": "Late" if r["level"] == "LATE" else "At risk",
                         "reason": r["reason"]})
    late.sort(key=lambda r: (r["level"] != "Late", r["required"] or on))

    for lst in (wrong_site, not_marked, no_punch, ot_approver):
        lst.sort(key=lambda r: (r["emp"], r["day"]))
    person = [col("emp", "Person", wide=True), col("day", "Day", "date"),
              col("site", "Site")]
    return {
        "kpis": [
            kpi("Marked at one site, punched at another", len(wrong_site), "int"),
            kpi("Punched, not marked", len(not_marked), "int"),
            kpi("Marked present, no punch", len(no_punch), "int"),
            kpi("OT approved off-site", len(ot_approver), "int"),
            kpi("Payables overdue, nothing raised", len(overdue_pay), "int"),
            kpi("Procurement late or at risk", len(late), "int"),
        ],
        "sections": [
            section("Marked at one site while the clock had them at another",
                    person + [col("punched_at", "Clocked in at")], wrong_site,
                    note="The register and the terminal disagree about where "
                         "the person was. One of them is wrong; the pay "
                         "follows the register."),
            section("Clocked in but not on any register", person, not_marked,
                    note="Nobody marked the day, so it will not be paid."),
            section("Marked present with no punch at a site with a clock",
                    person, no_punch,
                    note="From the day the terminal first saw the person. "
                         "Present by the register, absent by the terminal: "
                         "often a missed punch, sometimes not."),
            section("Overtime approved by someone not the site's PM",
                    person + [col("hours", "Hours", "num"),
                              col("by", "Approved by", wide=True),
                              col("role", "Role")], ot_approver),
            section("Working days with no register at all", [
                col("site", "Site"), col("days", "Days", "int"),
                col("first", "First", "date"), col("last", "Last", "date")],
                blank_days),
            section("Months not closed", [
                col("site", "Site"), col("month", "Month"),
                col("status", "Status")], unlocked + ts,
                note="Payroll runs and attendance months before the current "
                     "one that are still open."),
            section("Payables overdue with no voucher raised", [
                col("ref", "Reference", wide=True),
                col("vendor", "Supplier", wide=True), col("site", "Site"),
                col("due", "Due", "date"), col("days", "Days overdue", "int"),
                col("amount", "Amount", "money")], overdue_pay,
                note="In the payable's own currency."),
            section("Procurement late or at risk", [
                col("site", "Site"), col("project", "Project"),
                col("item", "Item", wide=True),
                col("required", "Required on site", "date"),
                col("level", "Standing"), col("reason", "Why", wide=True)],
                late),
        ],
        "notes": [
            "Clock checks cover only sites with a terminal: "
            + (", ".join(sorted(sites[s].code for s in clocked)) or "none")
            + ".",
            f"As at {on:%d %b %Y}.",
        ],
    }

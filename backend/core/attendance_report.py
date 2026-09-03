"""Attendance record for the client — a date range, no overtime.

Project teams send the client a daily and a monthly attendance list so the
resort can plan housekeeping and food for the men on site (owner
2026-09-03). That is a headcount question, so the sheet carries the marks
and the counts — present, half day, absent, leave, sick — and nothing about
pay: no overtime hours, no rates. The roster and the mark codes are exactly
the month register's, so what the client is sent is what the site sees.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from .models import Attendance, Employee, EmployeeSiteAllocation

MAX_DAYS = 92
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CODES = {"ABSENT": "A", "SICK": "S", "LEAVE": "L", "PAID_LEAVE": "PL",
         "HALF_DAY": "½"}
LEGEND = ("P present · F rest day worked · ½ half day · A absent · "
          "L leave · PL paid leave · S sick")


def code(a, is_rest):
    """The register's own mark for a day (see views_hr.attendance_register)."""
    if a is None:
        return ""
    if a.remark == "PRESENT":
        return "F" if is_rest else "P"
    return CODES.get(a.remark, "")


def job_title(emp):
    """What the client reads against the name: the typed title, else the
    manpower category (owner 2026-09-03)."""
    if emp.job_title:
        return emp.job_title
    return emp.job_category.name if emp.job_category_id else ""


def kind(emp):
    """Staff or worker, from the category's group — the client feeds and
    houses the two differently (owner 2026-09-03)."""
    if emp.job_category_id and emp.job_category.grp == "STAFF":
        return "Staff"
    return "Worker"


def _month_blocks(start, end, work_week):
    """The range cut at month boundaries: one grid per calendar month keeps a
    92-day range readable and the columns aligned to the dates."""
    blocks, cur = [], start
    while cur <= end:
        last = (cur.replace(day=28) + timedelta(days=4)).replace(day=1) \
            - timedelta(days=1)
        stop = min(last, end)
        days = []
        d = cur
        while d <= stop:
            days.append({"date": d, "d": d.day, "dow": DOW[d.isoweekday() - 1],
                         "rest": d.isoweekday() not in work_week})
            d += timedelta(days=1)
        blocks.append({"label": cur.strftime("%B %Y"), "start": cur,
                       "end": stop, "days": days})
        cur = stop + timedelta(days=1)
    return blocks


def build(site, start, end):
    if end < start:
        raise ValueError("The end of the range is before its start.")
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"That range is longer than {MAX_DAYS} days.")
    work_week = set(site.working_days)
    blocks = _month_blocks(start, end, work_week)

    # Who was here in the RANGE, not who is here today — the register's rule
    # (owner 2026-08-14): allocations overlapping the range, plus anyone the
    # site actually marked in it.
    here = EmployeeSiteAllocation.objects.filter(
        site=site, from_date__lte=end).filter(
        Q(to_date__isnull=True) | Q(to_date__gte=start))
    marked = Attendance.objects.filter(site=site, day__gte=start,
                                       day__lte=end)
    roster = (Employee.objects
              .filter(Q(id__in=here.values_list("employee_id", flat=True))
                      | Q(id__in=marked.values_list("employee_id", flat=True)))
              .select_related("job_category").order_by("emp_no").distinct())
    att = {(a.employee_id, a.day): a for a in marked}

    KEYS = ("present", "rest_worked", "half", "absent", "leave",
            "paid_leave", "sick")
    grand = {k: 0 for k in KEYS}
    worker_totals = {}
    for block in blocks:
        rows, headcount = [], {d["d"]: 0 for d in block["days"]}
        btot = {k: 0 for k in KEYS}
        for emp in roster:
            cells, t = {}, {k: 0 for k in KEYS}
            for dd in block["days"]:
                a = att.get((emp.id, dd["date"]))
                c = code(a, dd["rest"])
                if c:
                    cells[dd["d"]] = c
                if a is None:
                    continue
                if a.remark == "PRESENT":
                    t["rest_worked" if dd["rest"] else "present"] += 1
                    headcount[dd["d"]] += 1
                elif a.remark == "HALF_DAY":
                    t["half"] += 1
                    headcount[dd["d"]] += 1
                elif a.remark == "ABSENT":
                    t["absent"] += 1
                elif a.remark == "SICK":
                    t["sick"] += 1
                elif a.remark == "LEAVE":
                    t["leave"] += 1
                elif a.remark == "PAID_LEAVE":
                    t["paid_leave"] += 1
            if not cells and not any(t.values()):
                continue                    # not on site this month at all
            t["on_site"] = t["present"] + t["rest_worked"] + t["half"]
            rows.append({"emp_no": emp.emp_no, "full_name": emp.full_name,
                         "job_title": job_title(emp), "kind": kind(emp),
                         "cells": [{"c": cells.get(dd["d"], ""),
                                    "rest": dd["rest"]}
                                   for dd in block["days"]],
                         **t})
            wt = worker_totals.setdefault(emp.id, {
                "emp_no": emp.emp_no, "full_name": emp.full_name,
                "job_title": job_title(emp), "kind": kind(emp),
                **{k: 0 for k in KEYS}, "on_site": 0})
            for k in KEYS:
                wt[k] += t[k]
                btot[k] += t[k]
                grand[k] += t[k]
            wt["on_site"] += t["on_site"]
        btot["on_site"] = btot["present"] + btot["rest_worked"] + btot["half"]
        days_with_marks = [d for d in headcount if headcount[d]]
        # Every column sized explicitly (fixed layout, border-box cells):
        # identity 80 mm, four totals 8 mm, a day 5.2 mm. A two-day month
        # is a narrow grid; a 31-day month fills the 277 mm page width.
        COLS = {"no": 16, "name": 30, "title": 23, "kind": 11, "tot": 8}
        total = sum(COLS.values()) + 3 * COLS["tot"] + 5.2 * len(block["days"])
        pct = {k: f"{v / total * 100:.2f}" for k, v in COLS.items()}
        pct["day"] = f"{5.2 / total * 100:.2f}"
        block.update({
            "rows": rows, "totals": btot, "w": pct,
            "width_pct": f"{min(100.0, total / 277 * 100):.1f}",
            "headcount": [headcount[dd["d"]] for dd in block["days"]],
            "peak": max(headcount.values()) if headcount else 0,
            "average": (Decimal(sum(headcount.values()))
                        / Decimal(len(days_with_marks))).quantize(
                            Decimal("0.1")) if days_with_marks else Decimal("0"),
        })
    grand["on_site"] = grand["present"] + grand["rest_worked"] + grand["half"]
    return {
        "site": site, "start": start, "end": end,
        "days_covered": (end - start).days + 1,
        "blocks": blocks,
        "workers": sorted(worker_totals.values(), key=lambda w: w["emp_no"]),
        "staff_count": sum(1 for w in worker_totals.values()
                           if w["kind"] == "Staff"),
        "worker_count": sum(1 for w in worker_totals.values()
                            if w["kind"] == "Worker"),
        "totals": grand, "legend": LEGEND, "prepared_on": date.today(),
    }

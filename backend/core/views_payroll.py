"""Monthly payroll runs (owner's salary sheet). MVR runs are per site; the USD
run is a single combined run across all sites. HO HR / Finance / Admin only."""
from decimal import Decimal

from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import payroll
from .audit import audit
from .models import PayrollLine, PayrollRun, Site

ROLES = ("HO_HR", "FINANCE", "ADMIN", "PA")  # PA = full HR (owner 2026-08-03)

# HR-editable inputs on a draft line
LINE_FIELDS = ("days_worked", "fridays_worked", "ot_hours", "allowance",
               "penalty", "advance", "loan", "amount_to_site",
               "amount_to_office", "remarks")


def _guard(request):
    return request.user.role in ROLES


def _can_see_run(request, run):
    """Who may open a run: HR/Finance/Admin/PA always; the Director (they
    approve every run); and a PM of the run's own site — they verify their
    site's draft salary (owner 2026-08-12)."""
    role = request.user.role
    if role in ROLES or role == "DIRECTOR":
        return True
    return bool(role == "PM" and run.site_id
                and run.site.is_current_pm(request.user))


def _line_info(line, register=None):
    m = payroll.compute_line(line)
    reg = (register or {}).get(line.employee_id,
                               {"marked": 0, "present": 0, "absent": 0,
                                "joined_after": None})
    return {
        "days_marked": reg["marked"], "days_present": reg["present"],
        "days_absent": reg["absent"],
        "joined_after": reg.get("joined_after"),
        "excluded": line.excluded, "excluded_reason": line.excluded_reason,
        "id": line.id, "emp_no": line.employee.emp_no,
        "rest_day_revoked": line.rest_day_revoked,
        "full_name": line.employee.full_name,
        "nationality": line.employee.nationality,
        "job_title": line.employee.job_category.name
        if line.employee.job_category_id else "",
        "site_code": line.site.code if line.site_id else "",
        "basic_pay": line.basic_pay, "ot_rate": line.ot_rate,
        "days_worked": line.days_worked, "fridays_worked": line.fridays_worked,
        "ot_hours": line.ot_hours, "allowance": line.allowance,
        "penalty": line.penalty, "advance": line.advance, "loan": line.loan,
        "amount_to_site": line.amount_to_site,
        "amount_to_office": line.amount_to_office, "remarks": line.remarks,
        **m,
    }


def _run_info(run, lines=True):
    data = {
        "id": run.id, "site_id": run.site_id,
        "site_code": run.site.code if run.site_id else None,
        "currency": run.currency, "year": run.year, "month": run.month,
        "working_days": run.working_days, "status": run.status,
        "locked_by": run.locked_by.full_name if run.locked_by_id else None,
        "locked_at": run.locked_at,
        "status_label": run.get_status_display(),
        "verified_by": run.verified_by.full_name if run.verified_by_id else None,
        "verified_at": run.verified_at,
        "approved_by": run.approved_by.full_name if run.approved_by_id else None,
        "approved_at": run.approved_at,
        "return_reason": run.return_reason,
        # Named in the register, but with no payable day — an August joiner
        # with a stray July mark against him. Off the run, not out of sight
        # (owner 2026-08-15).
        "marked_but_unpayable": payroll.marked_but_unpayable(
            run.site, run.currency, run.year, run.month),
    }
    if lines:
        register = payroll.register_summary(run)
        data["lines"] = [_line_info(ln, register) for ln in
                         run.lines.select_related("employee__job_category",
                                                  "site").all()]
    return data


@api_view(["GET", "POST"])
def payroll_runs(request):
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    if request.method == "POST":
        currency = request.data.get("currency", "MVR")
        try:
            year = int(request.data["year"])
            month = int(request.data["month"])
        except (KeyError, TypeError, ValueError):
            return Response({"detail": "year and month are required."},
                            status=400)
        site = None
        if currency != "USD":  # MVR runs are per site; USD is combined
            try:
                site = Site.objects.get(pk=request.data.get("site_id"))
            except Site.DoesNotExist:
                return Response({"detail": "A site is required for an MVR run."},
                                status=400)
            # Run a site on its own — but only once its attendance is locked, so
            # days/OT are final (owner 2026-08-05).
            if not payroll.attendance_locked(site, year, month):
                return Response({"detail": f"Lock {site.code}'s attendance for "
                                 "this month before running its payroll."},
                                status=400)
        else:  # combined USD run — every USD-staffed site must be locked
            pending = payroll.unlocked_sites(year, month, currency="USD")
            if pending:
                return Response({"detail": "Lock attendance first for: "
                                 + ", ".join(pending) + "."}, status=400)
        if PayrollRun.objects.filter(site=site, currency=currency, year=year,
                                     month=month).exists():
            return Response({"detail": "A run for this period already exists."},
                            status=400)
        working_days = int(request.data.get("working_days")
                           or payroll.month_days(year, month))
        run = payroll.generate_run(site=site, currency=currency, year=year,
                                   month=month, working_days=working_days,
                                   actor=request.user)
        audit("payroll_run", run.id, "PAYROLL_RUN_CREATED", actor=request.user,
              detail={"site": site.code if site else "USD",
                      "period": f"{year}-{month:02d}"})
        return Response(_run_info(run), status=201)

    year = request.GET.get("year")
    month = request.GET.get("month")
    qs = PayrollRun.objects.select_related("site", "locked_by")
    if year:
        qs = qs.filter(year=year)
    if month:
        qs = qs.filter(month=month)
    return Response([_run_info(r, lines=False) for r in qs])


@api_view(["POST"])
def payroll_generate(request):
    """Generate all runs for a month (MVR per locked site + HO, plus USD)."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        year = int(request.data["year"])
        month = int(request.data["month"])
    except (KeyError, TypeError, ValueError):
        return Response({"detail": "year and month are required."}, status=400)
    result = payroll.generate_month(year, month, request.user)
    if result.get("blocked"):
        return Response({
            "detail": "Lock attendance for every site first — still open: "
                      + ", ".join(result["unlocked"]) + ".",
            "unlocked": result["unlocked"]}, status=400)
    audit("payroll_run", 0, "PAYROLL_MONTH_GENERATED", actor=request.user,
          detail={"period": f"{year}-{month:02d}",
                  "created": len(result["created"])})
    return Response(result)


@api_view(["GET"])
def payroll_readiness(request):
    """Per-site attendance-lock status for a month, so HR sees what's ready to
    run and what still needs its month locked."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    from .models import (Employee, EmployeeSiteAllocation, TimesheetMonth)
    year = int(request.GET.get("year") or 0)
    month = int(request.GET.get("month") or 0)
    rows = []
    for site in Site.objects.filter(status=Site.Status.ACTIVE).order_by("code"):
        emp_ids = EmployeeSiteAllocation.objects.filter(
            site=site, to_date__isnull=True).values_list("employee_id",
                                                          flat=True)
        mvr = Employee.objects.payroll_eligible().filter(
            id__in=emp_ids, is_active=True, currency="MVR").count()
        if not mvr:
            continue
        rows.append({
            "site_id": site.id,
            "site_code": site.code, "is_head_office": site.is_head_office,
            "mvr_staff": mvr,
            "locked": TimesheetMonth.objects.filter(
                site=site, year=year, month=month, status="LOCKED").exists(),
            "has_run": PayrollRun.objects.filter(
                site=site, currency="MVR", year=year, month=month).exists(),
        })
    from django.db.models import Q
    return Response({
        "sites": rows,
        # the combined USD run carries full-USD workers + split-pay workers' basic
        "usd_staff": Employee.objects.payroll_eligible().filter(
            is_active=True).filter(
            Q(currency="USD")
            | Q(usd_basic_pay__gt=0, employment_type="PERMANENT")).count(),
        "usd_has_run": PayrollRun.objects.filter(
            site__isnull=True, currency="USD", year=year, month=month).exists(),
    })


def _site_roster_ids(site):
    """The payroll workers on a site — the same roster a run covers (both
    currencies), so the review matches what will be posted."""
    from .models import Employee, EmployeeSiteAllocation
    emp_ids = EmployeeSiteAllocation.objects.filter(
        site=site, to_date__isnull=True).values_list("employee_id", flat=True)
    return list(Employee.objects.payroll_eligible().filter(
        id__in=emp_ids, is_active=True).values_list("id", flat=True))


def _site_attendance_totals(site, year, month):
    """Month totals for a site from its locked attendance — days worked, OT
    hours, absences and rest-day (Friday) work — the figures that drive the
    run. Same rules as the per-worker attendance register."""
    import calendar
    from datetime import date

    from .models import Attendance
    ids = _site_roster_ids(site)
    t = {"workers": len(ids), "days_worked": 0, "ot_hours": Decimal("0"),
         "absences": 0, "rest_day_work": 0, "half_days": 0}
    if not ids:
        return t
    ndays = calendar.monthrange(year, month)[1]
    work_week = set(site.working_days)
    rest = {d for d in range(1, ndays + 1)
            if date(year, month, d).isoweekday() not in work_week}
    for a in Attendance.objects.filter(site=site, day__year=year,
                                       day__month=month, employee_id__in=ids):
        t["ot_hours"] += a.ot_approved or 0
        if a.remark == "PRESENT":
            if a.day.day in rest:
                t["rest_day_work"] += 1
            else:
                t["days_worked"] += 1
        elif a.remark in ("ABSENT", "SICK", "LEAVE"):
            t["absences"] += 1
        elif a.remark == "HALF_DAY":
            t["half_days"] += 1
    return t


@api_view(["GET"])
def payroll_attendance_summary(request):
    """A pre-run review: per-site attendance + OT totals for the month plus a
    company-wide roll-up, so HR checks the figures feeding payroll before
    generating a run (owner 2026-08-05)."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    from .models import TimesheetMonth
    year = int(request.GET.get("year") or 0)
    month = int(request.GET.get("month") or 0)
    keys = ("workers", "days_worked", "ot_hours", "absences", "rest_day_work",
            "half_days")
    rows = []
    totals = {k: (Decimal("0") if k == "ot_hours" else 0) for k in keys}
    for site in Site.objects.filter(status=Site.Status.ACTIVE).order_by("code"):
        t = _site_attendance_totals(site, year, month)
        if not t["workers"]:
            continue
        locked = TimesheetMonth.objects.filter(
            site=site, year=year, month=month, status="LOCKED").exists()
        rows.append({"site_id": site.id, "site_code": site.code,
                     "is_head_office": site.is_head_office, "locked": locked,
                     **t})
        for k in keys:
            totals[k] += t[k]
    return Response({"sites": rows, "totals": totals,
                     "all_locked": all(r["locked"] for r in rows) if rows
                     else False})


@api_view(["GET"])
def payroll_ot_breakdown(request):
    """The approved-OT detail for a month — who worked overtime, on which days,
    how many hours and who approved it — company-wide or for one site. The
    dedicated OT view HR wanted before running payroll (owner 2026-08-05)."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    from collections import OrderedDict

    from .models import Attendance
    year = int(request.GET.get("year") or 0)
    month = int(request.GET.get("month") or 0)
    qs = Attendance.objects.filter(day__year=year, day__month=month,
                                   ot_approved__gt=0)
    site_id = request.GET.get("site_id")
    if site_id:
        qs = qs.filter(site_id=site_id)
    qs = qs.select_related("employee__job_category", "site",
                           "ot_approved_by").order_by("employee__emp_no", "day")
    workers = OrderedDict()
    total = Decimal("0")
    for a in qs:
        w = workers.setdefault(a.employee_id, {
            "emp_no": a.employee.emp_no, "full_name": a.employee.full_name,
            "job_title": (a.employee.job_category.name
                          if a.employee.job_category_id else ""),
            "site_code": a.site.code, "total_ot": Decimal("0"), "days": []})
        w["days"].append({
            "day": a.day.isoformat(), "hours": a.ot_approved,
            "approved_by": (a.ot_approved_by.full_name
                            if a.ot_approved_by_id else "")})
        w["total_ot"] += a.ot_approved or 0
        total += a.ot_approved or 0
    return Response({"workers": list(workers.values()), "total_ot": total,
                     "worker_count": len(workers)})


@api_view(["GET", "POST"])
def payroll_run_detail(request, pk):
    try:
        run = PayrollRun.objects.select_related("site").get(pk=pk)
    except PayrollRun.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, run):
        return Response({"detail": "Not permitted."}, status=403)
    if request.method == "POST" and request.data.get("action") == "refresh":
        # Re-pull attendance / rates / policy into a draft run (owner
        # 2026-08-12: the Friday policy changed after a run was generated,
        # and sites are re-checking July attendance).
        summary, err = payroll.refresh_run(run, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response({**_run_info(run), "refresh": summary})
    if request.method == "POST" and request.data.get("action") in (
            "submit", "verify", "approve", "return"):
        # Draft salary verification: HR submits → site PM verifies → PD
        # approves → HR/Finance locks (owner 2026-08-12).
        action = request.data["action"]
        # a refusal on WHO may act is a permission error; a refusal on the
        # state or a missing reason is a bad request
        if not payroll.can_act(run, request.user, action):
            _, why = payroll.set_run_status(run, action, request.user,
                                            request.data.get("reason", ""))
            return Response({"detail": why}, status=403)
        _, err = payroll.set_run_status(run, action, request.user,
                                        request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(_run_info(run))
    if request.method == "POST":  # lock
        if run.status == "LOCKED":
            return Response({"detail": "Already locked."}, status=400)
        if not payroll.can_act(run, request.user, "lock"):
            return Response({"detail": "The run must be approved by the "
                                       "Director before it can be locked."},
                            status=400)
        payroll.lock_run(run, request.user)
        audit("payroll_run", run.id, "PAYROLL_RUN_LOCKED", actor=request.user)
        return Response(_run_info(run))
    return Response(_run_info(run))


def _money(v):
    return f"{Decimal(v):,.2f}"


def _pdf_response(html, filename):
    from django.conf import settings
    from django.http import HttpResponse
    from rest_framework.response import Response as R

    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=str(settings.MEDIA_ROOT)).write_pdf()
    except Exception:
        return R({"detail": "PDF engine unavailable on this server."},
                 status=503)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


def _month_name(m):
    import calendar
    return calendar.month_name[m]


@api_view(["GET"])
def payroll_report_pdf(request, pk):
    """The salary sheet for a run — grouped site-wise (a USD run spans sites)
    with a totals summary. HR / Finance / Admin, plus the PM and Director who
    verify it (owner 2026-08-12) — they need the register to check against."""
    try:
        run = PayrollRun.objects.select_related("site").get(pk=pk)
    except PayrollRun.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, run):
        return Response({"detail": "Not permitted."}, status=403)
    from collections import OrderedDict

    from django.template.loader import render_to_string

    from .pdf import company_info, logo_src

    register = payroll.register_summary(run)
    lines = [_line_info(ln, register) for ln in
             run.lines.select_related("employee__job_category", "site").all()]
    # The register has no Friday-money column, so Friday pay rides in the
    # allowance column (owner 2026-08-12) — otherwise the visible columns
    # don't add up to Gross now that a Friday pays 12h × the OT rate.
    for ln in lines:
        ln["allowance"] = (Decimal(ln["allowance"] or 0)
                           + Decimal(ln["friday_pay"] or 0))
    groups = OrderedDict()
    for ln in lines:
        groups.setdefault(ln["site_code"] or "—", []).append(ln)

    def totals(rows):
        keys = ("basic_pay", "earned_basic", "allowance", "ot_pay", "gross",
                "advance", "penalty", "loan", "net", "amount_to_site",
                "amount_to_office")
        return {k: _money(sum(Decimal(r[k] or 0) for r in rows)) for k in keys}

    group_list = []
    for site_code, rows in groups.items():
        for i, r in enumerate(rows, 1):
            r["no"] = i
            for k in ("basic_pay", "earned_basic", "allowance", "ot_pay",
                      "gross", "advance", "penalty", "loan", "net",
                      "amount_to_site", "amount_to_office"):
                r["f_" + k] = _money(r[k] or 0) if r[k] not in (None, "") else ""
        group_list.append({"site_code": site_code, "rows": rows,
                           "totals": totals(rows)})
    html = render_to_string("pdf/payroll_report.html", {
        "run": run, "currency": run.currency,
        "period": f"{_month_name(run.month)} {run.year}",
        "groups": group_list, "grand": totals(lines),
        "multi_site": run.site_id is None,
        "logo_src": logo_src(), "co": company_info(),
    })
    return _pdf_response(html, f"payroll-{run.currency}-{run.year}-"
                               f"{run.month:02d}.pdf")


@api_view(["GET"])
def payslip_pdf(request, pk):
    """One worker's salary slip for a run. HR / Finance / Admin."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        line = PayrollLine.objects.select_related(
            "run", "employee__job_category", "site").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    from django.template.loader import render_to_string

    from .pdf import company_info, logo_src

    info = _line_info(line, payroll.register_summary(line.run))
    for k in ("basic_pay", "daily_rate", "earned_basic", "friday_pay",
              "ot_pay", "allowance", "gross", "advance", "penalty", "loan",
              "deductions", "net", "amount_to_site", "amount_to_office"):
        info["f_" + k] = _money(info[k] or 0) if info.get(k) not in (None, "") \
            else "0.00"
    from .payroll import friday_ot_hours
    html = render_to_string("pdf/payslip.html", {
        "line": line, "run": line.run, "i": info, "currency": line.run.currency,
        "period": f"{_month_name(line.run.month)} {line.run.year}",
        "friday_ot_hours": friday_ot_hours().normalize(),
        "logo_src": logo_src(), "co": company_info(),
    })
    return _pdf_response(html, f"payslip-{line.employee.emp_no}-"
                               f"{line.run.year}-{line.run.month:02d}.pdf")


@api_view(["PATCH"])
def payroll_line(request, pk):
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        line = PayrollLine.objects.select_related("run", "employee").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if line.run.status == "LOCKED":
        return Response({"detail": "The run is locked."}, status=400)
    changed = []
    for f in LINE_FIELDS:
        if f in request.data:
            val = request.data[f]
            if f in ("amount_to_site", "amount_to_office") and val in ("", None):
                val = None
            elif f == "remarks":
                val = val or ""
            elif f == "fridays_worked":
                val = int(val or 0)
            else:
                try:
                    val = Decimal(str(val or 0))
                except (TypeError, ValueError):
                    return Response({"detail": f"{f} is invalid."}, status=400)
            setattr(line, f, val)
            changed.append(f)
    line.save(update_fields=changed or None)
    if changed:
        # an approval must never outlive the numbers it was given
        payroll.reset_to_draft(line.run, request.user,
                               f"line edited ({', '.join(changed)})")
    return Response(_line_info(line, payroll.register_summary(line.run)))


@api_view(["POST"])
def payroll_line_exclude(request, pk):
    """Leave a worker off the payout — the leaver already settled in cash
    (owner 2026-08-14). HR's call, like the rest of the line's money."""
    try:
        line = PayrollLine.objects.select_related(
            "run", "run__site", "employee").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, line.run):
        return Response({"detail": "Not your site's payroll."}, status=403)
    if request.user.role not in ("HO_HR", "FINANCE", "ADMIN", "PA"):
        return Response({"detail": "HR or Finance decide this."}, status=403)
    _, msg = payroll.set_excluded(line, request.data.get("excluded"),
                                  request.data.get("reason", ""), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_run_info(line.run))


@api_view(["POST"])
def payroll_line_rest_day(request, pk):
    """Site PM strikes a worker's unworked rest days (owner 2026-08-13)."""
    try:
        line = PayrollLine.objects.select_related(
            "run", "run__site", "employee").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, line.run):
        return Response({"detail": "Not your site's payroll."}, status=403)
    _, msg = payroll.set_rest_day_revoked(
        line, request.data.get("revoked"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_run_info(line.run))

"""Monthly payroll runs (owner's salary sheet). MVR runs are per site; the USD
run is a single combined run across all sites. HO HR / Finance / Admin only."""
import logging
from datetime import date
from decimal import Decimal

from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import payroll
from . import payroll_settlement as settlement
from . import thermal
from .audit import audit
from .models import PayrollLine, PayrollRun, Site

log = logging.getLogger(__name__)

ROLES = ("HO_HR", "FINANCE", "ADMIN", "PA")  # PA = full HR (owner 2026-08-03)
# Who may LOOK at payroll without running it: the signatory authorises the PYR
# that pays a run, and could not open the run behind it (owner 2026-08-16).
READ_ROLES = ROLES + ("SIGNATORY",)

# HR-editable inputs on a draft line
LINE_FIELDS = ("days_worked", "fridays_worked", "ot_hours", "allowance",
               "penalty", "advance", "loan", "amount_to_site",
               "amount_to_office", "remarks")


def _guard(request):
    return request.user.role in ROLES


def _read(request):
    return request.user.role in READ_ROLES


def _can_see_run(request, run):
    """Who may open a run: HR/Finance/Admin/PA always; the Director (they
    approve every run); and a PM of the run's own site — they verify their
    site's draft salary (owner 2026-08-12)."""
    role = request.user.role
    if role in READ_ROLES or role == "DIRECTOR":
        return True
    return bool(role == "PM" and run.site_id
                and run.site.is_current_pm(request.user))


def _line_info(line, register=None, fri_hours=None):
    # fri_hours is the run's Friday-OT policy, read once by _run_info; per
    # line it was one parameter query each — 229 of them on SJR.
    m = payroll.compute_line(line, fri_hours)
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
        "kind": run.kind,
        "last_working_day": run.last_working_day,
        "settlement_reason": run.settlement_reason,
        "locked_by": run.locked_by.full_name if run.locked_by_id else None,
        "locked_at": run.locked_at,
        "status_label": run.get_status_display(),
        "verified_by": run.verified_by.full_name if run.verified_by_id else None,
        "verified_at": run.verified_at,
        "approved_by": run.approved_by.full_name if run.approved_by_id else None,
        "approved_at": run.approved_at,
        "return_reason": run.return_reason,
        "pyr_ref": run.payment_request.ref if run.payment_request_id else None,
        "pyr_status": (run.payment_request.status
                       if run.payment_request_id else None),
        # Named in the register, but with no payable day — an August joiner
        # with a stray July mark against him. Off the run, not out of sight
        # (owner 2026-08-15).
        # Only meaningful for a monthly run: a settlement covers a named
        # batch, so "named in the register but not on the run" is everyone
        # else at the site.
        "marked_but_unpayable": (
            payroll.marked_but_unpayable(run.site, run.currency, run.year,
                                         run.month)
            if run.kind == PayrollRun.Kind.MONTHLY else []),
    }
    if lines:
        register = payroll.register_summary(run)
        fri = payroll.friday_ot_hours()
        data["lines"] = [_line_info(ln, register, fri) for ln in
                         run.lines.select_related("employee__job_category",
                                                  "site").all()]
    return data


@api_view(["GET", "POST"])
def payroll_runs(request):
    if not (_guard(request) if request.method == "POST" else _read(request)):
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
        # The USD run reads no register — a salary apportioned by the joining
        # and leaving dates — so it waits on no site's attendance lock (owner
        # 2026-09-05). Overtime for these workers is rufiyaa and is gated, as
        # ever, on its own site's run.
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


def _settlement_inputs(request):
    """(site, employees, last working day, reason) or (None, error)."""
    from .models import Employee, Site

    try:
        site = Site.objects.get(pk=request.data.get("site_id"))
    except (Site.DoesNotExist, TypeError, ValueError):
        return None, Response({"detail": "Unknown site."}, status=400)
    raw = request.data.get("last_working_day")
    try:
        lwd = date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None, Response({"detail": "A last working day is required."},
                              status=400)
    ids = request.data.get("employee_ids") or []
    people = list(Employee.objects.filter(id__in=ids))
    if len(people) != len(set(ids)):
        return None, Response({"detail": "Unknown worker on the batch."},
                              status=400)
    return (site, people, lwd, request.data.get("reason", "")), None


@api_view(["POST"])
def settlement_preview(request):
    """What a demobilised batch would be paid — writes nothing.

    Shows the days the register carries AFTER the stated last working day
    alongside the money, because those two records contradicting each other is
    exactly what a late demobilisation produces, and the PM has to settle it
    before the payment goes out, not after (owner 2026-08-30)."""
    if not (_guard(request) or request.user.role in ("PM", "DIRECTOR")):
        return Response({"detail": "HR / PM / Director only."}, status=403)
    parsed, err = _settlement_inputs(request)
    if err:
        return err
    site, people, lwd, _reason = parsed
    rows = settlement.preview(site, people, lwd)
    return Response({
        "last_working_day": lwd, "site_code": site.code, "rows": rows,
        "total_net": sum((r["net"] for r in rows), Decimal("0")),
        "conflict_count": sum(1 for r in rows if r["conflicts"]),
    })


@api_view(["POST"])
def settlement_create(request):
    """Raise the settlement run for a demobilised batch."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."},
                        status=403)
    parsed, err = _settlement_inputs(request)
    if err:
        return err
    site, people, lwd, reason = parsed
    run, msg = settlement.generate_settlement(
        site=site, employees=people, last_working_day=lwd, reason=reason,
        actor=request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    audit("payroll_run", run.id, "SETTLEMENT_CREATED", actor=request.user,
          detail={"site": site.code, "workers": len(people),
                  "last_working_day": lwd.isoformat()})
    return Response(_run_info(run), status=201)


@api_view(["GET"])
def settlement_candidates(request):
    """Workers at a site who can be settled, grouped by when they left.

    A site's full roster is useless for this: VKR has 41 men still working
    and 67 who have passed through, and the batch you want is the twenty
    demobilised together. That batch is already on record — their allocations
    were all closed on the same day — so the list is grouped by that date and
    the whole batch is one click (owner 2026-08-30: "how can i figure out
    those 20 from this settlement list").

    Still-active workers are listed too, last: a demobilisation is often
    settled before anyone records it."""
    from .models import Employee

    site_id = request.GET.get("site")
    if not site_id:
        return Response({"detail": "site is required."}, status=400)
    people = Employee.objects.filter(
        site_allocations__site_id=site_id,
        engagement_type="DIRECT").exclude(
        payroll_lines__run__kind="SETTLEMENT",
        payroll_lines__run__status="LOCKED").distinct().prefetch_related(
        "site_allocations")

    rows = []
    for e in people:
        # The day this site's roster let him go — the latest closed
        # allocation here. Open allocation = still working.
        closes = [a.to_date for a in e.site_allocations.all()
                  if str(a.site_id) == str(site_id)]
        left = None if any(c is None for c in closes) else (
            max(closes) if closes else None)
        rows.append({"id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
                     "is_active": e.is_active, "basic_pay": e.basic_pay,
                     "left_on": e.left_on, "removed_on": left})
    rows.sort(key=lambda r: (r["removed_on"] is None,
                             -(r["removed_on"].toordinal()
                               if r["removed_on"] else 0),
                             r["emp_no"] or ""))
    return Response(rows)


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
    if not _read(request):
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
        if a.remark in ("PRESENT", "PAID_LEAVE"):
            # Paid leave pays, so it counts here — otherwise the pre-run review
            # shows a hole where the payroll run will show days.
            if a.day.day in rest and a.remark == "PRESENT":
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
    if not _read(request):
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
    if not _read(request):
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
        # The signatory reads a run to see what the PYR pays for; re-pulling it
        # stays with HR / the site PM / the Director (owner 2026-08-16).
        if request.user.role == "SIGNATORY":
            return Response({"detail": "View only."}, status=403)
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
    if request.method == "POST":  # reopen a locked run
        if run.status != "LOCKED":
            return Response({"detail": "Locking is automatic — a run locks "
                                       "when the Director approves it."},
                            status=400)
        if request.user.role not in ("HO_HR", "FINANCE", "ADMIN"):
            return Response({"detail": "HR, Finance or Admin reopen a run."},
                            status=403)
        _, err = payroll.reopen_run(run, request.user)
        if err:
            return Response({"detail": err}, status=400)
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


def _signoffs(run):
    """Who prepared, verified and approved the run — the three steps the sheet
    is actually signed off by, each with the name and moment already recorded.

    The sheet carried three EMPTY boxes, one of them "CHECKED BY (FINANCE)",
    which is not a step in this flow at all: HR prepares, the site PM verifies
    the days, the Director approves (owner 2026-08-19). Finance pays the PYR
    that follows; it does not check the sheet.

    A step not yet taken returns no name, so the box prints as a blank rule and
    a draft can still be signed by hand.
    """
    return [
        {"label": "PREPARED BY (HR / PAYROLL)", "pending": "not yet prepared",
         # falls back to whoever generated it, for a run not yet submitted
         "by": run.submitted_by or run.created_by,
         "at": run.submitted_at or run.created_at},
        {"label": "VERIFIED BY (SITE PM)", "pending": "not yet verified",
         "by": run.verified_by, "at": run.verified_at},
        {"label": "APPROVED BY (DIRECTOR)", "pending": "not yet approved",
         "by": run.approved_by, "at": run.approved_at},
    ]


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
        "run": run, "currency": run.currency, "signoffs": _signoffs(run),
        "period": f"{_month_name(run.month)} {run.year}",
        "groups": group_list, "grand": totals(lines),
        "multi_site": run.site_id is None,
        "logo_src": logo_src(), "co": company_info(),
    })
    return _pdf_response(html, f"payroll-{run.currency}-{run.year}-"
                               f"{run.month:02d}.pdf")


def _slip_context(line, register=None):
    """Everything a salary slip needs, in either format. `register` is passed in
    when slipping a whole run so the summary is computed once, not per worker."""
    from django.utils import timezone

    from .pdf import company_info, logo_src
    from .payroll import friday_ot_hours

    info = _line_info(line, register if register is not None
                      else payroll.register_summary(line.run))
    for k in ("basic_pay", "daily_rate", "earned_basic", "friday_pay",
              "ot_pay", "allowance", "gross", "advance", "penalty", "loan",
              "deductions", "net", "amount_to_site", "amount_to_office"):
        info["f_" + k] = _money(info[k] or 0) if info.get(k) not in (None, "") \
            else "0.00"
    run = line.run
    return {
        "line": line, "run": run, "i": info, "currency": run.currency,
        "period": f"{_month_name(run.month)} {run.year}",
        "friday_ot_hours": friday_ot_hours().normalize(),
        "logo_src": logo_src(), "co": company_info(),
        "run_ref": (f"{run.site.code if run.site_id else 'USD'} "
                    f"{run.year}-{run.month:02d}"),
        "printed_at": timezone.localtime().strftime("%d %b %Y %H:%M"),
        "page_height": thermal.RENDER_H_MM,
    }


def _thermal_response(lines, filename):
    """Receipt-width slips, one page each so the autocut separates them."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from rest_framework.response import Response as R

    if not lines:
        return R({"detail": "No payable lines on this run."}, status=400)
    register = payroll.register_summary(lines[0].run)
    htmls = [render_to_string("pdf/payslip_thermal.html",
                              _slip_context(ln, register)) for ln in lines]
    try:
        # Flattened to images: a POS driver renders a PDF by extracting its text
        # and re-typing it, which collapses the amount column and merges
        # figures. With no text there is nothing to extract (owner 2026-08-19).
        pdf = thermal.flatten_to_images(thermal.render_slips(htmls))
    except Exception:
        log.exception("thermal slip render failed")
        return R({"detail": "PDF engine unavailable on this server."},
                 status=503)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


def _escpos_response(lines, filename):
    """Ready-to-send ESC/POS. HR and Finance print from Windows PCs, so the
    rasterising happens here rather than asking them to install PyMuPDF and
    Pillow — their end only has to open a socket (owner 2026-08-19)."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from rest_framework.response import Response as R

    if not lines:
        return R({"detail": "No payable lines on this run."}, status=400)
    register = payroll.register_summary(lines[0].run)
    htmls = [render_to_string("pdf/payslip_thermal.html",
                              _slip_context(ln, register)) for ln in lines]
    try:
        pdf = thermal.render_slips(htmls)
        job, count = thermal.escpos_bytes(pdf)
    except Exception:
        log.exception("escpos render failed")
        return R({"detail": "PDF engine unavailable on this server."},
                 status=503)
    resp = HttpResponse(job, content_type="application/octet-stream")
    # attachment, always: this is a byte stream for the printer, not something
    # a browser should try to display
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["X-Slip-Count"] = str(count)
    return resp


@api_view(["GET"])
def printer_tool_zip(request):
    """The two files an office PC needs, served from the app itself.

    Getting them onto the HR machine any other way turned into a saga — the
    owner's external drive is NTFS and macOS cannot write to it, and mail
    clients strip .cmd attachments. Downloading them from the same page as the
    slips removes the whole problem (owner 2026-08-19).
    """
    import io
    import zipfile
    from pathlib import Path

    from django.conf import settings
    from django.http import HttpResponse

    if not _read(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    folder = Path(settings.BASE_DIR).parent / "tools" / "windows"
    # One program file and one page of instructions. It was two files that had
    # to stay together, and the .cmd got copied to a Desktop without its script
    # — so the PowerShell now lives inside the .cmd (owner 2026-08-19).
    wanted = ["READ ME FIRST.txt", "Print salary slips.cmd"]
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in wanted:
            f = folder / name
            if f.exists():
                z.write(f, name)
                added += 1
    # An EMPTY zip is still 22 bytes of end-of-directory record, so the
    # buffer being non-empty proves nothing — count the files. This shipped
    # once serving a 22-byte nothing because tools/ was not in the image.
    if added == 0:
        log.error("printer tool files not found at %s", folder)
        return Response({"detail": "Printer setup files are missing on the "
                                   "server — tell whoever maintains it."},
                        status=503)
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="slip-printer-setup.zip"'
    return resp


@api_view(["GET"])
def run_slips_escpos(request, pk):
    """Every payable worker on a run, as ESC/POS for an 80mm printer."""
    try:
        run = PayrollRun.objects.select_related("site").get(pk=pk)
    except PayrollRun.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, run):
        return Response({"detail": "Not permitted."}, status=403)
    lines = list(run.lines.select_related("employee__job_category", "site",
                                          "run__site")
                 .filter(excluded=False)
                 .order_by("employee__emp_no"))
    site = run.site.code if run.site_id else "USD"
    return _escpos_response(
        lines, f"slips-{site}-{run.year}-{run.month:02d}.escpos")


@api_view(["GET"])
def payslip_escpos(request, pk):
    """One worker's slip as ESC/POS — for a reprint."""
    if not _read(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        line = PayrollLine.objects.select_related(
            "run__site", "employee__job_category", "site").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, line.run):
        return Response({"detail": "Not permitted."}, status=403)
    return _escpos_response(
        [line], f"slip-{line.employee.emp_no}-"
                f"{line.run.year}-{line.run.month:02d}.escpos")


@api_view(["GET"])
def payslip_thermal_pdf(request, pk):
    """One worker's slip at 80mm receipt width."""
    if not _read(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        line = PayrollLine.objects.select_related(
            "run__site", "employee__job_category", "site").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, line.run):
        return Response({"detail": "Not your site\'s payroll."}, status=403)
    return _thermal_response(
        [line], f"slip-{line.employee.emp_no}-"
                f"{line.run.year}-{line.run.month:02d}.pdf")


@api_view(["GET"])
def run_slips_thermal_pdf(request, pk):
    """Every payable worker on a run, one slip per page.

    Printing a run one worker at a time is not a workflow — this is the whole
    point of putting slips on a receipt printer (owner 2026-08-18). Excluded
    lines are left out: they are the leavers already settled in cash.
    """
    try:
        run = PayrollRun.objects.select_related("site").get(pk=pk)
    except PayrollRun.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_run(request, run):
        return Response({"detail": "Not permitted."}, status=403)
    lines = list(run.lines.select_related("employee__job_category", "site",
                                          "run__site")
                 .filter(excluded=False)
                 .order_by("employee__emp_no"))
    site = run.site.code if run.site_id else "USD"
    return _thermal_response(
        lines, f"slips-{site}-{run.year}-{run.month:02d}.pdf")


@api_view(["GET"])
def payslip_pdf(request, pk):
    """One worker's salary slip for a run. HR / Finance / Admin."""
    if not _read(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        line = PayrollLine.objects.select_related(
            "run", "employee__job_category", "site").get(pk=pk)
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    from django.template.loader import render_to_string

    html = render_to_string("pdf/payslip.html",
                            _slip_context(line, register=None))
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

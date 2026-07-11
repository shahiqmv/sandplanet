"""Monthly payroll runs (owner's salary sheet). MVR runs are per site; the USD
run is a single combined run across all sites. HO HR / Finance / Admin only."""
from decimal import Decimal

from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import payroll
from .audit import audit
from .models import PayrollLine, PayrollRun, Site

ROLES = ("HO_HR", "FINANCE", "ADMIN")

# HR-editable inputs on a draft line
LINE_FIELDS = ("days_worked", "fridays_worked", "ot_hours", "allowance",
               "penalty", "advance", "loan", "amount_to_site",
               "amount_to_office", "remarks")


def _guard(request):
    return request.user.role in ROLES


def _line_info(line):
    m = payroll.compute_line(line)
    return {
        "id": line.id, "emp_no": line.employee.emp_no,
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
    }
    if lines:
        data["lines"] = [_line_info(ln) for ln in
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
        mvr = Employee.objects.filter(id__in=emp_ids, is_active=True,
                                      currency="MVR").count()
        if not mvr:
            continue
        rows.append({
            "site_code": site.code, "is_head_office": site.is_head_office,
            "mvr_staff": mvr,
            "locked": TimesheetMonth.objects.filter(
                site=site, year=year, month=month, status="LOCKED").exists(),
            "has_run": PayrollRun.objects.filter(
                site=site, currency="MVR", year=year, month=month).exists(),
        })
    return Response({
        "sites": rows,
        "usd_staff": Employee.objects.filter(is_active=True,
                                             currency="USD").count(),
        "usd_has_run": PayrollRun.objects.filter(
            site__isnull=True, currency="USD", year=year, month=month).exists(),
    })


@api_view(["GET", "POST"])
def payroll_run_detail(request, pk):
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        run = PayrollRun.objects.select_related("site").get(pk=pk)
    except PayrollRun.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "POST":  # lock
        if run.status == "LOCKED":
            return Response({"detail": "Already locked."}, status=400)
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
    with a totals summary. HR / Finance / Admin."""
    if not _guard(request):
        return Response({"detail": "HO HR / Finance / Admin only."}, status=403)
    try:
        run = PayrollRun.objects.select_related("site").get(pk=pk)
    except PayrollRun.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    from collections import OrderedDict

    from django.template.loader import render_to_string

    from .pdf import company_info, logo_src

    lines = [_line_info(ln) for ln in
             run.lines.select_related("employee__job_category", "site").all()]
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

    info = _line_info(line)
    for k in ("basic_pay", "daily_rate", "earned_basic", "friday_pay",
              "ot_pay", "allowance", "gross", "advance", "penalty", "loan",
              "deductions", "net", "amount_to_site", "amount_to_office"):
        info["f_" + k] = _money(info[k] or 0) if info.get(k) not in (None, "") \
            else "0.00"
    html = render_to_string("pdf/payslip.html", {
        "line": line, "run": line.run, "i": info, "currency": line.run.currency,
        "period": f"{_month_name(line.run.month)} {line.run.year}",
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
    return Response(_line_info(line))

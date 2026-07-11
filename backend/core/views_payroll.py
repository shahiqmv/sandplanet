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

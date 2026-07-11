"""Employees & site timesheets (spec §6A). Sensitive fields (basic_pay,
passport_no) are serialized only for HO HR / Admin, never logged, and
excluded from site-level responses."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .audit import audit
from .models import (
    Attendance,
    CompanyParameter,
    Employee,
    EmployeeSiteAllocation,
    ManpowerCategory,
    OvertimeRate,
    Site,
    TimesheetMonth,
)
from .permissions import scoped_site_ids

HR_ROLES = ("HO_HR", "ADMIN")
PAYROLL_ROLES = ("HO_HR", "FINANCE", "ADMIN")  # R3 addendum
# passport/permit/contact: HR+Admin only; basic_pay also visible to Finance
SENSITIVE_FIELDS = ("passport_no", "work_permit_no", "emergency_contact")
PAY_FIELDS = ("basic_pay",)


def _is_hr(user):
    return user.role in HR_ROLES


def _sees_pay(user):
    return user.role in PAYROLL_ROLES


class IsHrOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return _is_hr(request.user)


class EmployeeSerializer(serializers.ModelSerializer):
    site_id = serializers.SerializerMethodField()
    site_code = serializers.SerializerMethodField()
    job_category_name = serializers.CharField(source="job_category.name",
                                              read_only=True, default=None)
    photo_url = serializers.SerializerMethodField()
    ot_rate = serializers.SerializerMethodField()
    ot_effective = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ["id", "emp_no", "full_name", "photo", "photo_url",
                  "date_of_birth", "passport_no", "nationality",
                  "job_category", "job_category_name", "basic_pay", "currency",
                  "ot_applies", "ot_rate", "ot_effective",
                  "work_permit_no", "work_permit_expiry", "emergency_contact",
                  "join_date", "is_active", "site_id", "site_code"]
        read_only_fields = ["emp_no", "photo_url", "ot_rate", "ot_effective"]
        extra_kwargs = {"photo": {"write_only": True, "required": False}}

    def get_photo_url(self, obj):
        return obj.photo.url if obj.photo else None

    def get_ot_rate(self, obj):
        return obj.ot_rate()

    def get_ot_effective(self, obj):
        return obj.ot_rate() > 0

    def get_site_id(self, obj):
        return obj.current_site_id()

    def get_site_code(self, obj):
        row = obj.site_allocations.filter(to_date__isnull=True) \
            .select_related("site").first()
        return row.site.code if row else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Site users see emp no, name, category only (spec §6A.1)
        if request and not _is_hr(request.user):
            for field in SENSITIVE_FIELDS:
                data.pop(field, None)
        if request and not _sees_pay(request.user):
            for field in PAY_FIELDS + ("ot_rate", "currency"):
                data.pop(field, None)
        return data


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [IsHrOrReadOnly]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Employee.objects.select_related("job_category").order_by("emp_no")
        site_ids = scoped_site_ids(self.request.user)
        if site_ids is not None:  # site roles: own roster only
            qs = qs.filter(site_allocations__site_id__in=site_ids,
                           site_allocations__to_date__isnull=True)
        if self.request.GET.get("site"):
            qs = qs.filter(site_allocations__site_id=self.request.GET["site"],
                           site_allocations__to_date__isnull=True)
        if self.request.GET.get("active") != "all":
            qs = qs.filter(is_active=True)
        return qs.distinct()

    def perform_create(self, serializer):
        from .numbering import next_ref

        with transaction.atomic():
            n = int(next_ref("EMP", None).split("-")[1])
            employee = serializer.save(emp_no=f"EMP-{n:04d}")
        audit("employee", employee.id, "EMPLOYEE_CREATED",
              actor=self.request.user, detail={"emp_no": employee.emp_no})

    def perform_update(self, serializer):
        employee = serializer.save()
        audit("employee", employee.id, "EMPLOYEE_UPDATED",
              actor=self.request.user,
              detail={"fields": sorted(
                  k for k in self.request.data
                  if k not in SENSITIVE_FIELDS + PAY_FIELDS)})

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        """Transfer to a site; history kept for payroll (spec §6A.1)."""
        employee = self.get_object()
        try:
            site = Site.objects.get(pk=request.data.get("site_id"))
        except Site.DoesNotExist:
            return Response({"detail": "Unknown site_id."}, status=400)
        today = date.today()
        employee.site_allocations.filter(to_date__isnull=True) \
            .update(to_date=today)
        EmployeeSiteAllocation.objects.create(employee=employee, site=site,
                                              from_date=today)
        audit("employee", employee.id, "EMPLOYEE_ALLOCATED",
              actor=request.user, to_state=site.code)
        return Response(self.get_serializer(employee).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = False
        employee.save(update_fields=["is_active"])
        employee.site_allocations.filter(to_date__isnull=True) \
            .update(to_date=date.today())
        audit("employee", employee.id, "EMPLOYEE_DEACTIVATED",
              actor=request.user)
        return Response(self.get_serializer(employee).data)


# ===== Attendance =====


def _month_locked(site_id, day):
    return TimesheetMonth.objects.filter(
        site_id=site_id, year=day.year, month=day.month, status="LOCKED"
    ).exists()


def _window_hours(site):
    start = datetime.combine(date.today(), site.working_hours_from)
    end = datetime.combine(date.today(), site.working_hours_to)
    return Decimal((end - start).seconds) / 3600


def _normal_hours(site, check_in, check_out, remark):
    if remark in ("ABSENT", "SICK", "LEAVE"):
        return Decimal("0")
    full = _window_hours(site)
    if remark == "HALF_DAY":
        return (full / 2).quantize(Decimal("0.01"))
    if check_in and check_out:
        start = max(check_in, site.working_hours_from)
        end = min(check_out, site.working_hours_to)
        overlap = (datetime.combine(date.today(), end) -
                   datetime.combine(date.today(), start)).total_seconds()
        return max(Decimal(str(overlap)) / 3600, Decimal("0")) \
            .quantize(Decimal("0.01"))
    return full.quantize(Decimal("0.01"))  # present, default site hours


def _site_scope_ok(request, site):
    site_ids = scoped_site_ids(request.user)
    return site_ids is None or site.id in site_ids


@api_view(["GET"])
def attendance_grid(request):
    """Whole crew on one screen (spec §6A.2): roster with existing rows."""
    try:
        site = Site.objects.get(pk=request.GET.get("site"))
        day = date.fromisoformat(request.GET.get("date"))
    except (Site.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "site and date required."}, status=400)
    if not _site_scope_ok(request, site):
        return Response({"detail": "Not found."}, status=404)

    # A rest day is any weekday outside the site's working week (usually
    # Friday). Working it is the 7th-day work paid as an extra day, so the grid
    # defaults everyone to OFF and only marks those who actually worked.
    is_rest_day = day.isoweekday() not in site.working_days
    roster = Employee.objects.filter(
        is_active=True, site_allocations__site=site,
        site_allocations__to_date__isnull=True,
    ).select_related("job_category").order_by("emp_no").distinct()
    existing = {a.employee_id: a for a in Attendance.objects.filter(
        site=site, day=day)}
    rows = []
    for employee in roster:
        att = existing.get(employee.id)
        default_remark = "OFF" if is_rest_day else "PRESENT"
        rows.append({
            "attendance_id": att.id if att else None,
            "employee_id": employee.id,
            "emp_no": employee.emp_no,
            "full_name": employee.full_name,
            "category": employee.job_category.name
            if employee.job_category else "",
            "check_in": att.check_in if att else site.working_hours_from,
            "check_out": att.check_out if att else site.working_hours_to,
            "ot_requested": att.ot_requested if att else 0,
            "ot_approved": att.ot_approved if att else None,
            "remark": att.remark if att else default_remark,
            "saved": att is not None,
        })
    return Response({
        "site": site.code, "date": day.isoformat(),
        "is_rest_day": is_rest_day,
        "locked": _month_locked(site.id, day),
        "rows": rows,
    })


@api_view(["GET"])
def attendance_register(request):
    """Whole-month attendance for a site: a per-worker day grid plus totals
    (present / absent / leave / OT hours / Fridays worked) and a site summary.
    Site team + HR/Finance/Admin. Also serves 'as of today' for the current
    month, since days beyond today simply carry no record yet."""
    import calendar

    try:
        site = Site.objects.get(pk=request.GET.get("site"))
        year = int(request.GET.get("year"))
        month = int(request.GET.get("month"))
    except (Site.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "site, year, month required."}, status=400)
    if not _site_scope_ok(request, site):
        return Response({"detail": "Not found."}, status=404)

    ndays = calendar.monthrange(year, month)[1]
    work_week = set(site.working_days)
    days = []
    for d in range(1, ndays + 1):
        wd = date(year, month, d).isoweekday()
        days.append({"day": d, "dow": ["Mon", "Tue", "Wed", "Thu", "Fri",
                     "Sat", "Sun"][wd - 1], "rest": wd not in work_week})
    today = date.today()
    today_day = today.day if (today.year == year and today.month == month) \
        else None

    roster = Employee.objects.filter(
        is_active=True, site_allocations__site=site,
        site_allocations__to_date__isnull=True).select_related(
        "job_category").order_by("emp_no").distinct()
    att = {}
    for a in Attendance.objects.filter(site=site, day__year=year,
                                       day__month=month):
        att[(a.employee_id, a.day.day)] = a

    def code(a, is_rest):
        if a is None:
            return ""
        if a.remark == "PRESENT":
            return "F" if is_rest else "P"
        return {"ABSENT": "A", "SICK": "S", "LEAVE": "L",
                "HALF_DAY": "½"}.get(a.remark, "")

    rest_days = {d["day"] for d in days if d["rest"]}
    rows, sums = [], {"present": 0, "absent": 0, "leave": 0, "sick": 0,
                      "ot_hours": Decimal("0"), "fridays": 0}
    for emp in roster:
        cells, t = {}, {"present": 0, "absent": 0, "leave": 0, "sick": 0,
                        "half": 0, "ot_hours": Decimal("0"), "fridays": 0}
        for d in range(1, ndays + 1):
            a = att.get((emp.id, d))
            c = code(a, d in rest_days)
            if c:
                cells[str(d)] = c
            if a is None:
                continue
            t["ot_hours"] += a.ot_approved or 0
            if a.remark == "PRESENT":
                if d in rest_days:
                    t["fridays"] += 1
                else:
                    t["present"] += 1
            elif a.remark == "HALF_DAY":
                t["half"] += 1
            elif a.remark == "ABSENT":
                t["absent"] += 1
            elif a.remark == "SICK":
                t["sick"] += 1
            elif a.remark == "LEAVE":
                t["leave"] += 1
        rows.append({
            "emp_no": emp.emp_no, "full_name": emp.full_name,
            "category": emp.job_category.name if emp.job_category_id else "",
            "days": cells, **t})
        for k in ("present", "absent", "leave", "sick", "ot_hours", "fridays"):
            sums[k] += t[k]
    return Response({
        "site": site.code, "year": year, "month": month,
        "days": days, "today": today_day,
        "locked": TimesheetMonth.objects.filter(
            site=site, year=year, month=month, status="LOCKED").exists(),
        "rows": rows, "totals": sums,
    })


@api_view(["PUT"])
def attendance_bulk(request):
    """Day-grid upsert by Site Admin / SE; late edits audited (spec §6A.2)."""
    if request.user.role not in ("SITE_ADMIN", "SITE_ENGINEER", "PM",
                                 "HO_HR", "ADMIN"):
        return Response({"detail": "Site team or HR records attendance."},
                        status=403)
    try:
        site = Site.objects.get(pk=request.data.get("site"))
        day = date.fromisoformat(request.data.get("date"))
    except (Site.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "site and date required."}, status=400)
    if not _site_scope_ok(request, site):
        return Response({"detail": "Not allocated to this site."}, status=403)
    if day > date.today():
        return Response({"detail": "Attendance cannot be entered for future "
                                   "days."}, status=400)
    if _month_locked(site.id, day):
        return Response({"detail": "This month is locked. Ask HO HR to "
                                   "reopen it."}, status=400)

    def parse_time(value):
        if not value:
            return None
        if isinstance(value, str):
            return datetime.strptime(value[:5], "%H:%M").time()
        return value

    late_edit = day < date.today()
    saved = 0
    for row in request.data.get("rows", []):
        try:
            employee = Employee.objects.get(pk=row.get("employee_id"),
                                            is_active=True)
        except Employee.DoesNotExist:
            continue
        remark = row.get("remark") or "PRESENT"
        if remark == "OFF":
            # Rest day, not worked — clear any existing record, create none
            Attendance.objects.filter(employee=employee, day=day).delete()
            continue
        check_in = parse_time(row.get("check_in"))
        check_out = parse_time(row.get("check_out"))
        record, _created = Attendance.objects.update_or_create(
            employee=employee, day=day,
            defaults={
                "site": site,
                "check_in": check_in, "check_out": check_out,
                "remark": remark,
                "ot_requested": Decimal(str(row.get("ot_requested") or 0)),
                "entered_by": request.user,
            },
        )
        record.normal_hours = _normal_hours(
            site, record.check_in, record.check_out, remark)
        record.save(update_fields=["normal_hours"])
        saved += 1
    audit("attendance", site.id, "ATTENDANCE_SAVED", actor=request.user,
          detail={"site": site.code, "date": day.isoformat(), "rows": saved,
                  "late_edit": late_edit})
    return Response({"saved": saved, "late_edit": late_edit})


@api_view(["POST"])
def ot_approve(request):
    """PM approves OT per day or in batch; unapproved OT can never flow
    into payroll (spec §6A.2)."""
    ids = request.data.get("ids") or []
    rows = Attendance.objects.filter(pk__in=ids).select_related("site")
    if not rows:
        return Response({"detail": "ids required."}, status=400)
    for row in rows:
        pm = row.site.current_pm()
        if not (request.user.role in ("ADMIN", "HO_HR") or
                (request.user.role == "PM" and pm and pm.id == request.user.id)):
            return Response({"detail": f"Only the site PM or HR approves OT "
                                       f"({row.site.code})."}, status=403)
        if _month_locked(row.site_id, row.day):
            return Response({"detail": "Month is locked."}, status=400)
    hours_override = request.data.get("hours")
    for row in rows:
        row.ot_approved = Decimal(str(hours_override)) \
            if hours_override is not None else row.ot_requested
        row.ot_approved_by = request.user
        row.ot_approved_at = timezone.now()
        row.save(update_fields=["ot_approved", "ot_approved_by",
                                "ot_approved_at"])
    audit("attendance", rows[0].site_id, "OT_APPROVED", actor=request.user,
          detail={"count": len(rows)})
    return Response({"approved": len(rows)})


# ===== Overtime rate master (owner: managed, not hardcoded) =====


@api_view(["GET", "POST"])
def overtime_rates(request):
    """GET: every DPR job category with its MVR/USD OT rate (if set) so the
    management page can show and fill them. POST: upsert one category+currency
    rate. HR/Admin only."""
    if request.method == "POST":
        if not _is_hr(request.user):
            return Response({"detail": "HO HR/Admin manage OT rates."},
                            status=403)
        try:
            cat = ManpowerCategory.objects.get(pk=request.data.get("category_id"))
        except ManpowerCategory.DoesNotExist:
            return Response({"detail": "Unknown category."}, status=400)
        currency = request.data.get("currency", "MVR")
        try:
            rate = Decimal(str(request.data.get("rate_per_hour") or 0))
        except (TypeError, ValueError):
            return Response({"detail": "Rate is invalid."}, status=400)
        row, _ = OvertimeRate.objects.update_or_create(
            category=cat, currency=currency,
            defaults={"rate_per_hour": rate,
                      "applies_by_default": bool(
                          request.data.get("applies_by_default", True))})
        audit("overtime_rate", row.id, "OT_RATE_SET", actor=request.user,
              detail={"category": cat.name, "currency": currency,
                      "rate": str(rate)})
        return Response(_ot_rate_info(row), status=200)

    cats = ManpowerCategory.objects.filter(
        list_type="DPR", is_active=True).order_by("grp", "sort_order")
    rates = {(r.category_id, r.currency): r
             for r in OvertimeRate.objects.all()}
    out = []
    for cat in cats:
        row = {"category_id": cat.id, "category_name": cat.name,
               "grp": cat.grp, "rates": {}}
        for cur in ("MVR", "USD"):
            r = rates.get((cat.id, cur))
            row["rates"][cur] = {
                "rate_per_hour": r.rate_per_hour if r else None,
                "applies_by_default": r.applies_by_default if r else True,
            } if r else None
        out.append(row)
    return Response(out)


def _ot_rate_info(r):
    return {"id": r.id, "category_id": r.category_id, "currency": r.currency,
            "rate_per_hour": r.rate_per_hour,
            "applies_by_default": r.applies_by_default}


# ===== Month close & payroll (spec §6A.3) =====


@api_view(["POST"])
def timesheet_lock(request, site_id, year, month):
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    pm = site.current_pm()
    # HR can sign off any month (needed for Head Office, which has no PM, and
    # for corrections); otherwise the site PM signs off (spec §6A.3).
    if not (request.user.role in ("ADMIN", "HO_HR") or
            (request.user.role == "PM" and pm and pm.id == request.user.id)):
        return Response({"detail": "The site PM or HR signs off the month."},
                        status=403)
    row, _ = TimesheetMonth.objects.get_or_create(site=site, year=year,
                                                  month=month)
    if row.status == "LOCKED":
        return Response({"detail": "Already locked."}, status=400)
    row.status = "LOCKED"
    row.signed_off_by = request.user
    row.signed_off_at = timezone.now()
    row.save()
    # Staff cost is Incurred at month lock (§6C.3.5) — one Labour & Staff
    # posting per site for the period
    from . import staff_cost

    staff_cost.post_staff_cost(site, year, month, request.user)
    audit("timesheet", row.id, "TIMESHEET_LOCKED", actor=request.user,
          detail={"site": site.code, "period": f"{year}-{month:02d}"})
    return Response({"status": "LOCKED",
                     "signed_off_by": request.user.full_name})


@api_view(["POST"])
def timesheet_reopen(request, site_id, year, month):
    """HR reopen with reason — audited (spec §6A.3)."""
    if not _is_hr(request.user):
        return Response({"detail": "HO HR/Payroll reopens months."}, status=403)
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        return Response({"detail": "A reason is required."}, status=400)
    try:
        row = TimesheetMonth.objects.get(site_id=site_id, year=year,
                                         month=month, status="LOCKED")
    except TimesheetMonth.DoesNotExist:
        return Response({"detail": "Month is not locked."}, status=400)
    row.status = "OPEN"
    row.reopened_by = request.user
    row.reopen_reason = reason
    row.save()
    # Reverse the month's staff cost so it can be recomputed at the next lock
    from . import staff_cost

    staff_cost.reverse_staff_cost(row.site, year, month, request.user)
    audit("timesheet", row.id, "TIMESHEET_REOPENED", actor=request.user,
          detail={"reason": reason, "period": f"{year}-{month:02d}"})
    return Response({"status": "OPEN"})


def _param_decimal(key, default):
    try:
        return Decimal(str(CompanyParameter.objects.get(key=key).value))
    except CompanyParameter.DoesNotExist:
        return Decimal(str(default))


@api_view(["GET"])
def payroll_export(request, year, month):
    """Per employee: days worked, absences, hours, approved OT, computed
    gross = basic + OT x hourly x multiplier. HR/Finance/Admin (R3)."""
    if not _sees_pay(request.user):
        return Response({"detail": "HO HR/Payroll or Finance only."},
                        status=403)
    multiplier = _param_decimal("ot_multiplier", 1.25)
    divisor = _param_decimal("hourly_rate_divisor", 240)

    qs = Attendance.objects.filter(day__year=year, day__month=month) \
        .select_related("employee", "site")
    if request.GET.get("site"):
        qs = qs.filter(site_id=request.GET["site"])

    by_employee = {}
    for att in qs:
        entry = by_employee.setdefault(att.employee_id, {
            "employee": att.employee, "site_codes": set(),
            "days_worked": 0, "absences": 0,
            "normal_hours": Decimal("0"), "ot_hours": Decimal("0"),
        })
        entry["site_codes"].add(att.site.code)
        if att.remark in ("ABSENT", "SICK", "LEAVE"):
            entry["absences"] += 1
        elif att.remark == "HALF_DAY":
            entry["days_worked"] += 0.5
        else:
            entry["days_worked"] += 1
        entry["normal_hours"] += att.normal_hours or 0
        entry["ot_hours"] += att.ot_approved or 0  # approved OT ONLY

    rows = []
    for entry in sorted(by_employee.values(),
                        key=lambda e: e["employee"].emp_no):
        employee = entry["employee"]
        basic = employee.basic_pay or Decimal("0")
        hourly = (basic / divisor).quantize(Decimal("0.01")) if divisor else 0
        ot_amount = (entry["ot_hours"] * hourly * multiplier) \
            .quantize(Decimal("0.01"))
        rows.append({
            "emp_no": employee.emp_no, "full_name": employee.full_name,
            "sites": "/".join(sorted(entry["site_codes"])),
            "days_worked": entry["days_worked"],
            "absences": entry["absences"],
            "normal_hours": entry["normal_hours"],
            "ot_hours_approved": entry["ot_hours"],
            "basic_pay": basic, "hourly_rate": hourly,
            "ot_amount": ot_amount, "gross": basic + ot_amount,
        })

    # NB: "format" is reserved by DRF content negotiation — use "export"
    if request.GET.get("export") == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = f"Payroll {year}-{month:02d}"
        headers = ["Emp No", "Name", "Site(s)", "Days Worked", "Absences",
                   "Normal Hours", "Approved OT (h)", "Basic Pay (MVR)",
                   "Hourly Rate", "OT Amount", "Gross (MVR)"]
        ws.append(headers)
        for row in rows:
            ws.append([row["emp_no"], row["full_name"], row["sites"],
                       row["days_worked"], row["absences"],
                       float(row["normal_hours"]),
                       float(row["ot_hours_approved"]),
                       float(row["basic_pay"]), float(row["hourly_rate"]),
                       float(row["ot_amount"]), float(row["gross"])])
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")
        response["Content-Disposition"] = \
            f'attachment; filename="payroll-{year}-{month:02d}.xlsx"'
        wb.save(response)
        return response

    return Response({
        "period": f"{year}-{month:02d}",
        "ot_multiplier": multiplier, "hourly_rate_divisor": divisor,
        "rows": rows,
    })


@api_view(["GET"])
def dashboard_hr(request):
    """HR/Payroll dashboard (spec §7.4): month-lock board, permit-expiry
    and reallocation alerts, workforce today and OT summaries."""
    if request.user.role not in PAYROLL_ROLES:
        return Response({"detail": "HR/Finance/Admin only."}, status=403)
    today = date.today()
    sites = Site.objects.exclude(is_head_office=True).order_by("code")
    locks = {
        (t.site_id): t for t in TimesheetMonth.objects.filter(
            year=today.year, month=today.month)
    }
    active_sites = [s for s in sites if s.status == "ACTIVE"]
    board = [{
        "site_id": s.id, "code": s.code, "name": s.name,
        "status": locks[s.id].status if s.id in locks else "OPEN",
        "signed_off_at": locks[s.id].signed_off_at if s.id in locks else None,
    } for s in active_sites]
    all_locked = bool(board) and all(b["status"] == "LOCKED" for b in board)

    horizon = today + timedelta(days=60)
    expiring = list(Employee.objects.filter(
        is_active=True, work_permit_expiry__isnull=False,
        work_permit_expiry__lte=horizon,
    ).order_by("work_permit_expiry").values(
        "emp_no", "full_name", "work_permit_expiry")[:30])

    closed_ids = sites.filter(status="CLOSED").values_list("id", flat=True)
    stranded = list(EmployeeSiteAllocation.objects.filter(
        to_date__isnull=True, site_id__in=closed_ids,
        employee__is_active=True,
    ).select_related("employee", "site").values(
        "employee__emp_no", "employee__full_name", "site__code")[:30])

    todays = Attendance.objects.filter(day=today)
    present = todays.exclude(remark__in=("ABSENT", "LEAVE", "SICK")).count()
    ot_pending = Attendance.objects.filter(
        ot_requested__gt=0, ot_approved__isnull=True).count()

    return Response({
        "month": f"{today.year}-{today.month:02d}",
        "lock_board": board,
        "all_locked": all_locked,
        "permit_expiries": expiring,
        "reallocation_alerts": stranded,
        "workforce_today": present,
        "ot_pending_approval": ot_pending,
        "active_employees": Employee.objects.filter(is_active=True).count(),
    })


def site_manpower_data(site, day=None):
    """Roster vs attendance per manpower category for one site (R9):
    the employee DB says who is stationed here; today's attendance says
    who actually turned up."""
    day = day or date.today()
    allocations = EmployeeSiteAllocation.objects.filter(
        site=site, to_date__isnull=True, employee__is_active=True
    ).select_related("employee__job_category")
    cats = {}

    def bucket(category):
        key = category.id if category else 0
        if key not in cats:
            cats[key] = {"id": key,
                         "name": category.name if category else "Uncategorised",
                         "grp": category.grp if category else "",
                         "roster": 0, "present": 0, "absent": 0}
        return cats[key]

    emp_ids = []
    for a in allocations:
        bucket(a.employee.job_category)["roster"] += 1
        emp_ids.append(a.employee_id)
    todays = Attendance.objects.filter(
        site=site, day=day).select_related("employee__job_category")
    for att in todays:
        b = bucket(att.employee.job_category)
        if att.remark in ("ABSENT", "SICK", "LEAVE"):
            b["absent"] += 1
        else:
            b["present"] += 1
    rows = sorted(cats.values(), key=lambda c: -c["roster"])
    return {
        "attendance_entered": todays.exists(),
        "roster_total": len(emp_ids),
        "present": sum(c["present"] for c in rows),
        "absent": sum(c["absent"] for c in rows),
        "categories": rows,
    }


@api_view(["GET"])
def site_manpower(request, site_id):
    """Full manpower breakdown for the site page (R9 'more data' view):
    every category plus the roster with today's status. Site users see
    names and categories only — never pay or passports."""
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and site.id not in site_ids:
        return Response({"detail": "Not found."}, status=404)
    today = date.today()
    data = site_manpower_data(site, today)
    status_by_emp = {
        a.employee_id: a.remark
        for a in Attendance.objects.filter(site=site, day=today)
    }
    employees = [{
        "emp_no": a.employee.emp_no,
        "full_name": a.employee.full_name,
        "category": a.employee.job_category.name
        if a.employee.job_category else "—",
        "today": status_by_emp.get(a.employee_id, "NOT RECORDED"),
    } for a in EmployeeSiteAllocation.objects.filter(
        site=site, to_date__isnull=True, employee__is_active=True,
    ).select_related("employee__job_category")
        .order_by("employee__emp_no")]
    data["employees"] = employees
    data["date"] = today
    data["site"] = site.code
    return Response(data)

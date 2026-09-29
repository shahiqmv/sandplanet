"""Worker fines API (owner 2026-09-29). Rules live in core/fines.py."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import fines as svc
from .audit import audit
from .models import (Employee, EmployeeSiteAllocation, FineOffence, Site,
                     WorkerFine)
from .permissions import scoped_site_ids

CATALOGUE_ROLES = ("HO_HR", "ADMIN", "PA")


def _row(f, user, with_history=True):
    return {
        "id": f.id, "ref": f.ref, "status": f.status,
        "status_label": f.get_status_display(),
        "employee": f.employee_id, "emp_no": f.employee.emp_no,
        "full_name": f.employee.full_name,
        "category_name": (f.employee.job_category.name
                          if f.employee.job_category_id else ""),
        "site": f.site_id, "site_code": f.site.code,
        "offence": f.offence_id, "offence_name": f.offence.name if f.offence_id else "",
        "category": f.category, "category_label": f.get_category_display(),
        "violation_date": f.violation_date, "description": f.description,
        "amount": f.amount,
        "evidence_url": f.evidence.url if f.evidence else None,
        "recorded_by": f.recorded_by.get_full_name() or f.recorded_by.username,
        "created_at": f.created_at,
        "decided_by": (f.decided_by.get_full_name() or f.decided_by.username)
        if f.decided_by_id else "",
        "decided_at": f.decided_at, "decision_note": f.decision_note,
        "deduct_period": (f"{date(f.deduct_year, f.deduct_month, 1):%b %Y}"
                          if f.deduct_year else ""),
        "deducted_on": (f.payroll_line.run.ref or "locked run")
        if f.payroll_line_id else "",
        "carried_note": f.carried_note,
        "cancel_reason": f.cancel_reason,
        "can_decide": f.status == "PENDING" and svc.can_approve(user, f),
        "can_cancel": svc.can_cancel(user, f) and not f.payroll_line_id,
        "history": ([{"ref": h.ref, "date": h.violation_date,
                      "amount": h.amount, "status": h.status,
                      "offence": h.offence.name if h.offence_id
                      else h.get_category_display()}
                     for h in svc.history(f.employee, exclude_id=f.id)
                     .select_related("offence")[:10]]
                    if with_history else None),
    }


def _scoped(user):
    qs = WorkerFine.objects.select_related(
        "employee__job_category", "site", "offence", "recorded_by",
        "decided_by", "payroll_line__run")
    if user.role in svc.OVERSIGHT_ROLES:
        return qs
    if user.role not in ("SITE_ADMIN", "SITE_ENGINEER", "PM", "QS"):
        return qs.none()
    ids = scoped_site_ids(user)
    return qs if ids is None else qs.filter(site_id__in=ids)


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def fines(request):
    user = request.user
    if request.method == "GET":
        qs = _scoped(user)
        g = request.GET
        if g.get("site"):
            qs = qs.filter(site_id=g["site"])
        if g.get("status"):
            qs = qs.filter(status=g["status"])
        if g.get("employee"):
            qs = qs.filter(employee_id=g["employee"])
        if g.get("month"):                  # YYYY-MM of the breach
            try:
                y, m = (int(x) for x in g["month"].split("-"))
                qs = qs.filter(violation_date__year=y, violation_date__month=m)
            except ValueError:
                pass
        if g.get("q"):
            t = g["q"].strip()
            qs = qs.filter(Q(employee__emp_no__icontains=t)
                           | Q(employee__full_name__icontains=t)
                           | Q(ref__icontains=t))
        rows = list(qs[:500])
        return Response({
            "results": [_row(f, user, with_history=f.status == "PENDING")
                        for f in rows],
            "can_record": user.role in svc.RECORD_ROLES,
        })

    d = request.data
    try:
        site = Site.objects.get(pk=d.get("site"))
        emp = Employee.objects.get(pk=d.get("employee"))
        day = date.fromisoformat(d.get("violation_date") or "")
    except (Site.DoesNotExist, Employee.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "Pick the site, the worker and the date."},
                        status=400)
    offence = None
    if d.get("offence"):
        offence = FineOffence.objects.filter(pk=d["offence"],
                                             is_active=True).first()
        if offence is None:
            return Response({"detail": "That offence is no longer on the "
                                       "list."}, status=400)
    try:
        amount = Decimal(str(d.get("amount") or ""))
    except (InvalidOperation, ValueError):
        return Response({"detail": "Enter the fine amount."}, status=400)
    fine, err = svc.record(user=user, employee=emp, site=site,
                           violation_date=day,
                           description=d.get("description"), amount=amount,
                           offence=offence, category=d.get("category"),
                           evidence=request.FILES.get("evidence"))
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(fine, user), status=201)


def _get(request, pk):
    return _scoped(request.user).filter(pk=pk).first()


@api_view(["GET"])
def fine_detail(request, pk):
    f = _get(request, pk)
    if f is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(_row(f, request.user))


@api_view(["POST"])
def fine_action(request, pk, action):
    f = _get(request, pk)
    if f is None:
        return Response({"detail": "Not found."}, status=404)
    note = request.data.get("note") or request.data.get("reason") or ""
    if action in ("approve", "reject"):
        err = svc.decide(f, request.user, action == "approve", note)
    elif action == "cancel":
        err = svc.cancel(f, request.user, note)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    f.refresh_from_db()
    return Response(_row(f, request.user))


@api_view(["GET"])
def fine_workers(request):
    """Who can be fined at a site on a date: direct workers allocated there."""
    try:
        site = Site.objects.get(pk=request.GET.get("site"))
    except (Site.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "Pick a site."}, status=400)
    if not svc.can_record(request.user, site):
        return Response({"detail": "Not your site."}, status=403)
    try:
        day = date.fromisoformat(request.GET.get("date") or "")
    except ValueError:
        day = date.today()
    ids = EmployeeSiteAllocation.objects.filter(
        site=site, from_date__lte=day).filter(
        Q(to_date__isnull=True) | Q(to_date__gte=day)).values_list(
        "employee_id", flat=True)
    emps = (Employee.objects.filter(id__in=ids)
            .exclude(engagement_type="SUBCONTRACT")
            .select_related("job_category").order_by("emp_no"))
    return Response([{"id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
                      "category": e.job_category.name if e.job_category_id
                      else ""} for e in emps])


def _offence_row(o):
    return {"id": o.id, "name": o.name, "category": o.category,
            "category_label": o.get_category_display(),
            "default_amount": o.default_amount, "is_active": o.is_active,
            "sort_order": o.sort_order}


@api_view(["GET", "POST"])
def offences(request):
    if request.method == "GET":
        qs = FineOffence.objects.all()
        if request.GET.get("all") != "1":
            qs = qs.filter(is_active=True)
        return Response({"results": [_offence_row(o) for o in qs],
                         "can_edit": request.user.role in CATALOGUE_ROLES})
    if request.user.role not in CATALOGUE_ROLES:
        return Response({"detail": "HR keeps the offence list."}, status=403)
    return _save_offence(request, FineOffence())


@api_view(["PATCH"])
def offence_detail(request, pk):
    if request.user.role not in CATALOGUE_ROLES:
        return Response({"detail": "HR keeps the offence list."}, status=403)
    o = FineOffence.objects.filter(pk=pk).first()
    if o is None:
        return Response({"detail": "Not found."}, status=404)
    return _save_offence(request, o)


def _save_offence(request, o):
    d = request.data
    if "name" in d:
        o.name = (d.get("name") or "").strip()[:120]
    if "category" in d:
        o.category = d["category"]
    if "default_amount" in d:
        try:
            o.default_amount = Decimal(str(d.get("default_amount") or 0))
        except InvalidOperation:
            return Response({"detail": "Enter an amount."}, status=400)
    if "is_active" in d:
        o.is_active = bool(d["is_active"])
    if "sort_order" in d:
        o.sort_order = int(d.get("sort_order") or 0)
    if not o.name:
        return Response({"detail": "Name the offence."}, status=400)
    if o.category not in FineOffence.Category.values:
        return Response({"detail": "Pick a category."}, status=400)
    if o.default_amount < 0:
        return Response({"detail": "The amount can't be negative."}, status=400)
    created = o.pk is None
    o.save()
    audit("fine_offence", o.id, "FINE_OFFENCE_" + ("ADDED" if created
                                                   else "CHANGED"),
          actor=request.user, detail={"name": o.name,
                                      "amount": str(o.default_amount),
                                      "active": o.is_active})
    return Response(_offence_row(o), status=201 if created else 200)

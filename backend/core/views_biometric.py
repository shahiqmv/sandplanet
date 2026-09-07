"""The app's own screens for the terminals: registry, health, the raw punch log
and enrolment (owner 2026-08-23). Read-only with respect to attendance — Phase 1
does not touch a day grid."""
from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import biometric as svc
from .audit import audit
from .models import AttendanceDevice, DevicePunch, Employee, Site
from .permissions import scoped_site_ids


def _scoped(request, qs, field="site_id"):
    ids = scoped_site_ids(request.user)
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


def _device_row(d, today):
    stale = None
    if d.last_seen_at:
        mins = int((svc.djtz.now() - d.last_seen_at).total_seconds() // 60)
        stale = mins
    return {
        "id": d.id, "name": d.name, "serial": d.serial, "model": d.model,
        "site_code": d.site.code, "site_id": d.site_id,
        "location_note": d.location_note, "is_active": d.is_active,
        "last_seen_at": d.last_seen_at, "last_punch_at": d.last_punch_at,
        "minutes_since_seen": stale,
        # A terminal silent for two hours in the working day is a problem
        # someone should see this morning, not at month end.
        "healthy": bool(d.last_seen_at and stale is not None and stale <= 120),
        "punches_received": d.punches_received,
        "punches_today": d.punches.filter(punched_at__date=today).count(),
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def devices(request):
    if request.method == "POST":
        if not svc.can_manage(request.user):
            return Response({"detail": "HR registers terminals."}, status=403)
        site = Site.objects.filter(pk=request.data.get("site_id")).first()
        serial = (request.data.get("serial") or "").strip()
        name = (request.data.get("name") or "").strip()
        if site is None or not serial or not name:
            return Response({"detail": "Site, name and serial are required."},
                            status=400)
        if AttendanceDevice.objects.filter(serial=serial).exists():
            return Response({"detail": f"Serial {serial} is already "
                                       "registered."}, status=400)
        d = AttendanceDevice.objects.create(
            site=site, name=name[:60], serial=serial[:40],
            model=(request.data.get("model") or "")[:60],
            location_note=(request.data.get("location_note") or "")[:120],
            registered_by=request.user)
        audit("site", site.id, "ATTENDANCE_DEVICE_REGISTERED",
              actor=request.user,
              detail={"serial": d.serial, "name": d.name})
        return Response(_device_row(d, date.today()), status=201)

    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    today = date.today()
    qs = _scoped(request, AttendanceDevice.objects.select_related("site"))
    return Response([_device_row(d, today) for d in qs])


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def device(request, pk):
    """Correct what a terminal is called.

    The registry was register-and-list only, so a name typed once was
    permanent: SJR's unit went in as "Main gate", turned out to be at the site
    office, and had to be renamed in the database by hand (owner 2026-09-07).

    The serial and the site are deliberately NOT editable. The serial is how
    ADMS identifies the device — changing it would orphan its punches and let
    a stranger's serial inherit them. And a punch takes its site from the
    terminal, so moving one would drag its whole punch history to the new
    site; that needs the punch to remember where it was recorded first.
    """
    if not svc.can_manage(request.user):
        return Response({"detail": "HR manages terminals."}, status=403)
    d = _scoped(request, AttendanceDevice.objects.select_related("site")
                ).filter(pk=pk).first()
    if d is None:
        return Response({"detail": "Terminal not found."}, status=404)
    name = (request.data.get("name", d.name) or "").strip()
    if not name:
        return Response({"detail": "A terminal needs a name."}, status=400)
    was, fields = d.name, ["name"]
    d.name = name[:60]
    if "location_note" in request.data:
        d.location_note = (request.data.get("location_note") or "")[:120]
        fields.append("location_note")
    d.save(update_fields=fields)
    if was != d.name:
        audit("site", d.site_id, "ATTENDANCE_DEVICE_RENAMED",
              actor=request.user,
              detail={"serial": d.serial, "from": was, "to": d.name})
    return Response(_device_row(d, date.today()))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def punches(request):
    """The raw log. Optional ?site= &date= &status= &q="""
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    qs = (DevicePunch.objects.select_related("device__site", "employee")
          .order_by("-punched_at", "-id"))
    ids = scoped_site_ids(request.user)
    if ids is not None:
        qs = qs.filter(device__site_id__in=ids)
    if request.GET.get("site"):
        qs = qs.filter(device__site_id=request.GET["site"])
    day = request.GET.get("date")
    if day:
        qs = qs.filter(punched_at__date=day)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    q = (request.GET.get("q") or "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(device_user_id__icontains=q)
                       | Q(employee__emp_no__icontains=q)
                       | Q(employee__full_name__icontains=q))
    rows = [{
        "id": p.id, "device": p.device.name, "site_code": p.device.site.code,
        "device_user_id": p.device_user_id, "punched_at": p.punched_at,
        "direction": p.direction, "verify_mode": p.verify_mode,
        "status": p.status, "status_label": p.get_status_display(),
        "emp_no": p.employee.emp_no if p.employee_id else None,
        "full_name": p.employee.full_name if p.employee_id else None,
        "raw": p.raw,
    } for p in qs[:400]]
    return Response({"punches": rows, "count": len(rows)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def enrolment(request):
    """Who is enrolled on a site, and who is still missing."""
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    site = Site.objects.filter(pk=request.GET.get("site")).first()
    if site is None:
        return Response({"detail": "Choose a site."}, status=400)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return Response({"detail": "Not one of your sites."}, status=403)
    from .models import BiometricEnrolment
    rows = (BiometricEnrolment.objects
            .filter(is_active=True, employee__site_allocations__site=site,
                    employee__site_allocations__to_date__isnull=True)
            .select_related("employee", "enrolled_by").distinct())
    return Response({
        "enrolled": [{
            "employee_id": r.employee_id, "emp_no": r.employee.emp_no,
            "full_name": r.employee.full_name,
            "device_user_id": r.device_user_id,
            "finger_count": r.finger_count, "face_enrolled": r.face_enrolled,
            "card_enrolled": r.card_enrolled, "enrolled_on": r.enrolled_on,
            "enrolled_by": (r.enrolled_by.full_name
                            if r.enrolled_by_id else ""),
        } for r in rows],
        "missing": svc.enrolment_gaps(site),
    })


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def employee_enrolment(request, pk):
    if not svc.can_manage(request.user):
        return Response({"detail": "HR records enrolment."}, status=403)
    emp = Employee.objects.filter(pk=pk, is_active=True).first()
    if emp is None:
        return Response({"detail": "Unknown worker."}, status=404)
    if request.method == "DELETE":
        msg = svc.remove_enrolment(emp, request.user,
                                  request.data.get("reason") or "")
        if msg:
            return Response({"detail": msg}, status=400)
        return Response({"removed": True})
    row, msg = svc.enrol(emp, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"employee_id": emp.id, "emp_no": emp.emp_no,
                     "device_user_id": row.device_user_id,
                     "finger_count": row.finger_count,
                     "face_enrolled": row.face_enrolled}, status=201)

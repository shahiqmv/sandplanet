"""Endpoints for staff requests — the ask, the Director's decision, and the
hand-off to HR or Finance."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import staff_requests as sr
from .models import Document, StaffRequest


def _row(req, me=None):
    return {
        "id": req.id, "kind": req.kind,
        "kind_label": req.get_kind_display(),
        "status": req.status, "status_label": req.get_status_display(),
        "employee": {"emp_no": req.employee.emp_no,
                     "full_name": req.employee.full_name,
                     "id": req.employee_id},
        "raised_by": req.raised_by.full_name if req.raised_by_id else "",
        "amount": req.amount, "currency": req.employee.currency,
        "from_date": req.from_date, "to_date": req.to_date,
        "days": req.days, "reason": req.reason,
        "decided_by": req.decided_by.full_name if req.decided_by_id else "",
        "decided_at": req.decided_at, "decision_note": req.decision_note,
        "done_at": req.done_at,
        "pyr_ref": (req.payment_request.ref if req.payment_request_id
                    else None),
        "leave_id": req.worker_leave_id,
        "mine": bool(me and req.raised_by_id == me.id),
        "can_cancel": bool(me and req.raised_by_id == me.id
                           and req.status == StaffRequest.Status.SUBMITTED),
    }


def _get(pk):
    return StaffRequest.objects.select_related(
        "employee", "raised_by", "decided_by", "payment_request").filter(
        pk=pk).first()


@api_view(["GET", "POST"])
def my_requests(request):
    """Your own requests, and the way to raise one."""
    if request.method == "POST":
        req, err = sr.create(request.user, request.data)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_row(req, request.user), status=201)

    emp = getattr(request.user, "employee", None)
    rows = (StaffRequest.objects.select_related(
        "employee", "raised_by", "decided_by", "payment_request")
        .filter(employee=emp) if emp else StaffRequest.objects.none())
    return Response({
        "linked": emp is not None,
        "is_staff": bool(emp and sr.is_staff(emp)),
        "requests": [_row(r, request.user) for r in rows],
    })


@api_view(["GET"])
def request_queue(request):
    """What the signed-in role has to act on."""
    rows = sr.queue_for(request.user)
    return Response([_row(r, request.user) for r in rows])


@api_view(["POST"])
def decide_request(request, pk):
    req = _get(pk)
    if req is None:
        return Response({"detail": "Not found."}, status=404)
    err = sr.decide(req, request.user,
                    approve=bool(request.data.get("approve")),
                    note=request.data.get("note", ""))
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(req, request.user))


@api_view(["POST"])
def cancel_request(request, pk):
    req = _get(pk)
    if req is None:
        return Response({"detail": "Not found."}, status=404)
    err = sr.cancel(req, request.user)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(req, request.user))


@api_view(["POST"])
def grant_request_leave(request, pk):
    """HR turns an approved leave request into leave — paid or unpaid."""
    req = _get(pk)
    if req is None:
        return Response({"detail": "Not found."}, status=404)
    lv, err = sr.grant_leave(req, request.user,
                             kind=request.data.get("kind"),
                             note=request.data.get("note", ""))
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(req, request.user))


@api_view(["POST"])
def link_request_payment(request, pk):
    """Finance ties the PYR it raised back to the request."""
    req = _get(pk)
    if req is None:
        return Response({"detail": "Not found."}, status=404)
    doc = Document.objects.filter(ref=request.data.get("ref")).first()
    if doc is None:
        return Response({"detail": "Unknown payment request."}, status=400)
    err = sr.link_payment(req, doc, request.user)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(req, request.user))

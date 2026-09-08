"""The tenders & offers register — its screens.

Read is wider than write: QS, the Director and Admin run it, a signatory reads
it as they read everything, and a site PM sees the enquiries for their own
site (owner 2026-09-08).
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import tenders as svc


def _rev(r):
    return {"id": r.id, "rev_label": r.rev_label,
            "issued_at": r.issued_at, "created_at": r.created_at,
            "created_by": r.created_by.full_name if r.created_by_id else None,
            "note": (r.payload or {}).get("note", ""),
            "value": (r.payload or {}).get("value"),
            # The distinction the register exists for.
            "issued": r.issued_at is not None}


def _row(t, full=False):
    doc = t.document
    out = {
        "id": t.id, "ref": doc.ref, "status": doc.status,
        "site_id": doc.site_id, "site_code": doc.site.code,
        "client_name": t.client_name, "title": t.title,
        "enquiry_date": t.enquiry_date, "due_date": t.due_date,
        "our_format": t.our_format, "currency": t.currency,
        "value_submitted": t.value_submitted,
        "value_awarded": t.value_awarded,
        "submitted_at": t.submitted_at,
        "outcome_date": t.outcome_date, "outcome_ref": t.outcome_ref,
        "lost_reason": t.lost_reason, "lost_to": t.lost_to,
        "rev_label": doc.current_revision.rev_label
        if doc.current_revision_id else None,
        "awarded_project": (t.awarded_project.code
                            if t.awarded_project_id else None),
    }
    if full:
        out.update({
            "client_contact": t.client_contact, "scope": t.scope,
            "revisions": [_rev(r) for r in
                          doc.revisions.select_related("created_by")
                          .order_by("id")],
            "attachments": [{"id": a.id, "kind": a.kind,
                             "caption": a.caption,
                             "url": a.file.url if a.file else None}
                            for a in doc.attachments.all()],
        })
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tender_list(request):
    if request.method == "POST":
        if not svc.can_manage(request.user):
            return Response({"detail": "QS, the Director or Admin open a "
                                       "tender."}, status=403)
        t, err = svc.create_tender(request.data, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_row(t, full=True), status=201)

    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    qs = svc.visible_to(request.user)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("open") == "1":
        qs = qs.filter(document__status__in=svc.OPEN_STATUSES)
    return Response([_row(t) for t in qs])


def _get(request, pk):
    t = svc.visible_to(request.user).filter(pk=pk).first()
    if t is None:
        return None, Response({"detail": "Tender not found."}, status=404)
    return t, None


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def tender_detail(request, pk):
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    t, err = _get(request, pk)
    if err:
        return err
    if request.method == "PATCH":
        if not svc.can_manage(request.user):
            return Response({"detail": "QS, the Director or Admin edit a "
                                       "tender."}, status=403)
        msg = svc.edit_tender(t, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        t.refresh_from_db()
    return Response(_row(t, full=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def tender_action(request, pk, action):
    if not svc.can_manage(request.user):
        return Response({"detail": "QS, the Director or Admin run a tender."},
                        status=403)
    t, err = _get(request, pk)
    if err:
        return err
    if action == "revision":
        _rv, msg = svc.add_revision(t, request.data, request.user)
    elif action == "issue":
        msg = svc.issue_revision(t, request.data, request.user)
    elif action in ("awarded", "lost", "withdrawn"):
        msg = svc.record_outcome(t, action.upper(), request.data,
                                 request.user)
    else:
        return Response({"detail": f"Unknown action '{action}'."}, status=400)
    if msg:
        return Response({"detail": msg}, status=400)
    t.refresh_from_db()
    return Response(_row(t, full=True))

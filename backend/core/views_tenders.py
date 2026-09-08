"""The tenders & offers register — its screens.

Read is wider than write: QS, the Director and Admin run it, a signatory reads
it as they read everything, and a site PM sees the enquiries for their own
site (owner 2026-09-08).
"""
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, MultiPartParser
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
        "submit_our_format": t.submit_our_format, "currency": t.currency,
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
            "visits": [{"id": v.id, "visited_on": v.visited_on,
                        "attendees": v.attendees, "notes": v.notes}
                       for v in t.visits.all()],
            "rfis": [{"id": r.id, "number": r.number,
                      "question": r.question, "raised_on": r.raised_on,
                      "answer": r.answer, "answered_on": r.answered_on,
                      "answered": r.is_answered}
                     for r in t.rfis.all()],
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
    elif action == "visit":
        _v, msg = svc.add_visit(t, request.data, request.user)
    elif action == "rfi":
        _r, msg = svc.raise_rfi(t, request.data, request.user)
    elif action == "rfi-answer":
        _r, msg = svc.answer_rfi(t, request.data.get("rfi_id"), request.data,
                                 request.user)
    elif action in ("awarded", "lost", "withdrawn"):
        msg = svc.record_outcome(t, action.upper(), request.data,
                                 request.user)
    else:
        return Response({"detail": f"Unknown action '{action}'."}, status=400)
    if msg:
        return Response({"detail": msg}, status=400)
    t.refresh_from_db()
    return Response(_row(t, full=True))


# ---- the offer's priced bill ------------------------------------------
#
# The same BOQ the project will have. A tender's bill is captured in full
# whichever format is submitted — that is what lets the register compare what
# we offered with what was awarded — and on an award it is handed to the new
# project rather than copied (owner 2026-09-08).

def _boq_target(request, pk, writing):
    t = svc.visible_to(request.user).filter(pk=pk).first()
    if t is None:
        return None, Response({"detail": "Tender not found."}, status=404)
    if writing:
        if not svc.can_manage(request.user):
            return None, Response(
                {"detail": "QS, the Director or Admin price a tender."},
                status=403)
        if t.document.status not in svc.OPEN_STATUSES:
            return None, Response(
                {"detail": "This tender is closed — its bill cannot be "
                           "changed."}, status=400)
    return t, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tender_boq(request, pk):
    from .views_commercial import _boq_payload
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    t, err = _boq_target(request, pk, writing=False)
    if err:
        return err
    return Response(_boq_payload(t))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def tender_boq_save(request, pk):
    from . import commercial
    from .views_commercial import _boq_payload
    t, err = _boq_target(request, pk, writing=True)
    if err:
        return err
    _boq, msg = commercial.set_boq_items(t, request.data.get("rows") or [],
                                         request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    t.refresh_from_db()
    return Response(_boq_payload(t))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def tender_boq_capture(request, pk):
    """Read a bill out of the client's PDF or Excel into a reviewable draft."""
    from . import boq_extract
    t, err = _boq_target(request, pk, writing=True)
    if err:
        return err
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "Attach the bill to read."}, status=400)
    try:
        imp, msg = boq_extract.run_import(t, upload, request.user)
    except boq_extract.ExtractionError as e:
        return Response({"detail": str(e)}, status=400)
    except Exception as e:               # surface the reason, never a bare 500
        import logging
        logging.getLogger("boq").exception("Tender BOQ capture failed")
        return Response({"detail": f"Capture failed: {e}"}, status=400)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(boq_extract.import_payload(imp))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tender_boq_draft(request, pk):
    """The capture still waiting to be reviewed, if there is one."""
    from . import boq_extract
    from .models import BoqImport
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    t, err = _boq_target(request, pk, writing=False)
    if err:
        return err
    imp = (BoqImport.objects.filter(tender=t, status="DRAFT")
           .order_by("-created_at").first())
    return Response(boq_extract.import_payload(imp) if imp else None)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tender_submission_pdf(request, pk):
    """The pack that goes to the client: covering letter, priced summary, and
    the bill where we submit on our own form.

    Available before issue too — the QS needs to read the letter before
    sending it — but the reference and revision on it are the real ones.
    """
    from .views_commercial import pdf_bytes
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    t, err = _boq_target(request, pk, writing=False)
    if err:
        return err
    if t.document.current_revision is None:
        return Response({"detail": "There is nothing to submit yet."},
                        status=400)
    ctx = svc.submission_context(t)
    from django.http import HttpResponse
    try:
        pdf = pdf_bytes("pdf/tender_submission.html", ctx)
    except Exception as e:                       # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"},
                        status=500)
    rev = t.document.current_revision.rev_label
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'inline; filename="{t.document.ref}-{rev}-submission.pdf"')
    return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tender_boq_template(request, pk):
    """The same blank pricing sheet a project hands out."""
    from django.http import HttpResponse

    from . import commercial
    if not svc.can_view(request.user):
        return Response({"detail": "Not permitted."}, status=403)
    t, err = _boq_target(request, pk, writing=False)
    if err:
        return err
    wb = commercial.template_workbook()
    resp = HttpResponse(content_type="application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="boq-template.xlsx"'
    wb.save(resp)
    return resp


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def tender_boq_import(request, pk):
    """Load a filled pricing sheet onto the offer."""
    from . import commercial
    from .views_commercial import _boq_payload
    t, err = _boq_target(request, pk, writing=True)
    if err:
        return err
    upload = request.FILES.get("file")
    if not upload:
        return Response({"detail": "Attach the filled BOQ Excel (.xlsx)."},
                        status=400)
    rows, msg = commercial.rows_from_xlsx(upload)
    if msg:
        return Response({"detail": msg}, status=400)
    _boq, msg = commercial.import_boq_rows(t, rows, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    t.refresh_from_db()
    return Response(_boq_payload(t))

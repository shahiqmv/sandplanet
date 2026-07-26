"""Onboarding case API (expat recruitment / visa / mobilisation).

Case documents (passport, CV, address) are personal data: visible to HR, the
Director (PD), and the destination-site PM only. PM/HR raise, the Director is
the single approval gate.
"""
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import onboarding as ob
from .models import Attachment, Document, OnboardingCase, Site
from .permissions import scoped_site_ids

VIEW_ROLES = ("HO_HR", "DIRECTOR", "ADMIN")      # see all cases
DOC_KINDS = {k for k, _ in ob.REQUIRED_DOCS}


def _can_see(user, doc):
    if user.role in VIEW_ROLES:
        return True
    if user.role == "PM":
        ids = scoped_site_ids(user)
        return ids is None or doc.site_id in ids
    return False


def _get_case(request, pk):
    try:
        case = OnboardingCase.objects.select_related(
            "document__site", "document__created_by").get(pk=pk)
    except OnboardingCase.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_see(request.user, case.document):
        return None, Response({"detail": "Not found."}, status=404)
    return case, None


def _site_for(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except (Site.DoesNotExist, TypeError, ValueError):
        return None, Response({"detail": "Unknown site."}, status=400)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return None, Response({"detail": "Not one of your sites."}, status=403)
    return site, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def onboarding_cases(request):
    if request.user.role not in (*VIEW_ROLES, "PM"):
        return Response({"detail": "Not permitted."}, status=403)
    qs = OnboardingCase.objects.select_related(
        "document__site", "document__created_by").order_by("-document__doc_date")
    if request.user.role == "PM":
        ids = scoped_site_ids(request.user)
        if ids is not None:
            qs = qs.filter(document__site_id__in=ids)
    if request.GET.get("site_id"):
        qs = qs.filter(document__site_id=request.GET["site_id"])
    if request.GET.get("open") == "1":
        qs = qs.filter(document__status__in=ob.OPEN)
    if request.GET.get("mine") == "1":
        qs = qs.filter(document__created_by=request.user)
    return Response([ob.case_dict(c) for c in qs[:200]])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_create(request, site_id):
    site, err = _site_for(request, site_id)
    if err:
        return err
    case, msg = ob.create_case(site, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ob.case_dict(case), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def onboarding_detail(request, pk):
    case, err = _get_case(request, pk)
    if err:
        return err
    if request.method == "PATCH":
        if request.user.role not in ob.RAISE_ROLES:
            return Response({"detail": "Not permitted."}, status=403)
        msg = ob.update_case(case, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        case.refresh_from_db()
    return Response(ob.case_dict(case))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_submit(request, pk):
    case, err = _get_case(request, pk)
    if err:
        return err
    msg = ob.submit_case(case, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    case.refresh_from_db()
    return Response(ob.case_dict(case))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_action(request, pk):
    case, err = _get_case(request, pk)
    if err:
        return err
    msg = ob.decide_case(case, request.data.get("action"), request.user,
                         request.data.get("note", ""))
    if msg:
        return Response({"detail": msg}, status=400)
    case.refresh_from_db()
    return Response(ob.case_dict(case))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def onboarding_document(request, pk):
    """Attach (or replace) a checklist document while the case is editable."""
    case, err = _get_case(request, pk)
    if err:
        return err
    if request.user.role not in ob.RAISE_ROLES:
        return Response({"detail": "Not permitted."}, status=403)
    doc = case.document
    if doc.status not in ("DRAFT", "RETURNED"):
        return Response({"detail": "Documents are locked once submitted."},
                        status=400)
    kind = request.data.get("kind")
    if kind not in DOC_KINDS:
        return Response({"detail": "Unknown document type."}, status=400)
    up = request.FILES.get("file")
    if up is None:
        return Response({"detail": "Attach a file."}, status=400)
    doc.attachments.filter(kind=kind).delete()       # one per checklist slot
    Attachment.objects.create(
        document=doc, revision=doc.current_revision, kind=kind, file=up,
        file_name=up.name, content_type=up.content_type or "",
        size_bytes=up.size, uploaded_by=request.user)
    case.refresh_from_db()
    return Response(ob.case_dict(case), status=201)

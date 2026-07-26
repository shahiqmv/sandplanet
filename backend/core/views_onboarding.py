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
    if request.GET.get("open") == "1":   # active = anything not yet closed
        qs = qs.exclude(document__status__in=ob.TERMINAL)
    if request.GET.get("mine") == "1":
        qs = qs.filter(document__created_by=request.user)
    return Response([ob.case_dict(c) for c in qs[:200]])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def onboarding_passport_scan(request):
    """Read candidate details off an uploaded passport page to prefill the
    new-case form (HR reviews before saving)."""
    if request.user.role not in ob.RAISE_ROLES:
        return Response({"detail": "Not permitted."}, status=403)
    up = request.FILES.get("file")
    if up is None:
        return Response({"detail": "Attach the passport image."}, status=400)
    from . import passport_extract
    try:
        fields = passport_extract.scan(up)
    except passport_extract.ScanError as e:
        return Response({"detail": str(e)}, status=400)
    return Response({"fields": fields})


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
def onboarding_stage(request, pk):
    """HR advances the case one stage along its visa/permit track."""
    case, err = _get_case(request, pk)
    if err:
        return err
    msg = ob.advance_stage(case, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    case.refresh_from_db()
    return Response(ob.case_dict(case))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_fee(request, pk):
    """HR raises the fee PYR for the current payment stage."""
    case, err = _get_case(request, pk)
    if err:
        return err
    pyr, msg = ob.raise_fee(case, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    case.refresh_from_db()
    return Response(ob.case_dict(case), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def onboarding_stage_doc(request, pk):
    """HR uploads a stage document — deposit receipt, air ticket, entry pass,
    business-visa certificate, insurance policy, etc."""
    case, err = _get_case(request, pk)
    if err:
        return err
    att, msg = ob.upload_document(case, request.data.get("slot"),
                                  request.FILES.get("file"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    case.refresh_from_db()
    return Response(ob.case_dict(case), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def onboarding_attachment(request, pk, att_id):
    """Stream a case document — an OBR attachment or a fee PYR's payment slip
    (same access gate as the case)."""
    case, err = _get_case(request, pk)
    if err:
        return err
    att = ob.case_attachment(case, att_id)
    if att is None:
        return Response({"detail": "Not found."}, status=404)
    from django.http import FileResponse
    return FileResponse(
        att.file.open("rb"),
        content_type=att.content_type or "application/octet-stream",
        filename=att.file_name or f"attachment-{att.id}")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_letter(request, pk):
    """HR generates an official letter (LOA / SPL) for the case."""
    case, err = _get_case(request, pk)
    if err:
        return err
    letter, msg = ob.generate_letter(case, request.data.get("kind"),
                                     request.data.get("fields") or {},
                                     request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    case.refresh_from_db()
    return Response(ob.case_dict(case), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def onboarding_letter_download(request, pk, letter_id):
    """Stream a generated letter PDF (same access gate as the case docs)."""
    case, err = _get_case(request, pk)
    if err:
        return err
    letter = case.letters.filter(pk=letter_id).select_related(
        "attachment").first()
    if letter is None or not letter.attachment_id or not letter.attachment.file:
        return Response({"detail": "Not found."}, status=404)
    from django.http import FileResponse
    return FileResponse(letter.attachment.file.open("rb"),
                        content_type="application/pdf",
                        filename=f"{letter.ref}.pdf")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_stage_data(request, pk):
    """HR mirrors the portal status / records the medical result."""
    case, err = _get_case(request, pk)
    if err:
        return err
    msg = ob.set_stage_data(case, request.data, request.user)
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

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .audit import audit
from .models import (
    Approval,
    Attachment,
    Document,
    DocumentRevision,
    Holiday,
    Site,
    User,
)
from .numbering import next_ref
from .pdf import generate_pdf
from .permissions import scoped_site_ids
from .serializers_documents import AttachmentSerializer, DocumentSerializer

CREATE_ROLES = {  # spec §3 "can create"
    "DPR": {"SITE_ENGINEER", "SITE_ADMIN", "PM"},
    "TWS": {"SITE_ENGINEER", "PM"},
}
ISSUE_ROLES = CREATE_ROLES
MIN_DPR_PHOTOS = 4  # decision 8 — hard block


def _get_scoped_document(request, ref):
    try:
        doc = Document.objects.select_related("site", "current_revision").get(ref=ref)
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and doc.site_id not in site_ids:
        return None, Response({"detail": "Not found."}, status=404)
    return doc, None


def _is_site_pm(user, site):
    pm = site.current_pm()
    return user.role == User.Role.PM and pm is not None and pm.id == user.id


@api_view(["POST"])
def document_create(request):
    doc_type = request.data.get("doc_type")
    if doc_type not in Document.TRANSITIONS:
        return Response({"detail": f"Unsupported doc_type '{doc_type}'."}, status=400)
    try:
        site = Site.objects.get(pk=request.data.get("site_id"))
    except Site.DoesNotExist:
        return Response({"detail": "Unknown site_id."}, status=400)

    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and site.id not in site_ids:
        return Response({"detail": "Not allocated to this site."}, status=403)
    if request.user.role not in CREATE_ROLES[doc_type] and request.user.role != "ADMIN":
        return Response({"detail": "Role cannot create this document."}, status=403)
    # Lifecycle rules (spec §2.2)
    if site.status == Site.Status.CLOSED:
        return Response({"detail": "Site is closed — no new documents."}, status=400)
    if site.status == Site.Status.ON_HOLD and request.user.role not in ("PM", "ADMIN"):
        return Response(
            {"detail": "Site on hold — only PM/HO can create documents."}, status=403
        )

    doc_date = request.data.get("doc_date") or date.today().isoformat()
    if doc_type == "DPR":  # one per site per working day (spec §5.1)
        clash = Document.objects.filter(
            doc_type="DPR", site=site, doc_date=doc_date, is_void=False
        ).first()
        if clash:
            return Response(
                {"detail": f"{clash.ref} already exists for {doc_date}."}, status=400
            )

    payload = request.data.get("payload") or {}
    with transaction.atomic():
        ref = next_ref(doc_type, site)  # locks counter until commit — gap-free
        doc = Document.objects.create(
            doc_type=doc_type, ref=ref, site=site, doc_date=doc_date,
            status="DRAFT", created_by=request.user,
        )
        revision = DocumentRevision.objects.create(
            document=doc, rev_label="R0", payload=payload, created_by=request.user
        )
        doc.current_revision = revision
        doc.save(update_fields=["current_revision"])
    audit("document", doc.id, "DOC_CREATED", actor=request.user,
          to_state="DRAFT", detail={"ref": ref})
    return Response(DocumentSerializer(doc, context={"request": request}).data,
                    status=201)


@api_view(["GET", "PATCH"])
def document_detail(request, ref):
    doc, err = _get_scoped_document(request, ref)
    if err:
        return err
    if request.method == "GET":
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    # PATCH — draft revisions only (issued revisions immutable, spec §7.2)
    revision = doc.current_revision
    if doc.is_void or doc.status != "DRAFT" or revision.issued_at is not None:
        return Response({"detail": "Only draft documents can be edited."}, status=400)
    if request.user.role not in CREATE_ROLES.get(doc.doc_type, set()) \
            and request.user.role != "ADMIN":
        return Response({"detail": "Role cannot edit this document."}, status=403)
    if "payload" in request.data:
        revision.payload = request.data["payload"]
        revision.save(update_fields=["payload"])
    if "doc_date" in request.data and doc.doc_type == "DPR":
        clash = Document.objects.filter(
            doc_type="DPR", site=doc.site, doc_date=request.data["doc_date"],
            is_void=False,
        ).exclude(pk=doc.pk).first()
        if clash:
            return Response(
                {"detail": f"{clash.ref} already exists for that date."}, status=400
            )
        doc.doc_date = request.data["doc_date"]
        doc.save(update_fields=["doc_date"])
    return Response(DocumentSerializer(doc, context={"request": request}).data)


@api_view(["POST"])
def document_action(request, ref, action_name):
    doc, err = _get_scoped_document(request, ref)
    if err:
        return err
    if doc.is_void:
        return Response({"detail": "Document is void."}, status=400)
    handler = {"issue": _do_issue, "verify": _do_verify, "void": _do_void}.get(
        action_name
    )
    if handler is None:
        return Response({"detail": f"Unknown action '{action_name}'."}, status=400)
    return handler(request, doc)


def _transition(doc, new_status):
    allowed = Document.TRANSITIONS[doc.doc_type].get(doc.status, set())
    return new_status in allowed


def _record(doc, action, request, comment=""):
    Approval.objects.create(
        document=doc, revision=doc.current_revision, action=action,
        actor=request.user, actor_role=request.user.role, comment=comment,
    )


def _do_issue(request, doc):
    if request.user.role not in ISSUE_ROLES.get(doc.doc_type, set()) \
            and request.user.role != "ADMIN":
        return Response({"detail": "Role cannot issue this document."}, status=403)
    if not _transition(doc, "ISSUED"):
        return Response({"detail": f"Cannot issue from {doc.status}."}, status=400)
    if doc.doc_type == "DPR":
        captioned = doc.attachments.filter(kind="PHOTO").exclude(caption="").count()
        if captioned < MIN_DPR_PHOTOS:
            return Response(
                {"detail": f"DPR needs at least {MIN_DPR_PHOTOS} captioned photos "
                           f"to issue ({captioned} attached)."},
                status=400,
            )
    old = doc.status
    revision = doc.current_revision
    with transaction.atomic():
        revision.issued_at = timezone.now()  # locks the revision
        revision.save(update_fields=["issued_at"])
        doc.status = "ISSUED"
        doc.save(update_fields=["status", "updated_at"])
        _record(doc, "ISSUE", request)
    audit("document", doc.id, "DOC_ISSUED", actor=request.user,
          from_state=old, to_state="ISSUED", detail={"ref": doc.ref})
    generate_pdf(doc, revision, "issue")
    return Response(DocumentSerializer(doc, context={"request": request}).data)


def _do_verify(request, doc):
    if not _is_site_pm(request.user, doc.site) and request.user.role != "ADMIN":
        return Response({"detail": "Only the site's PM can verify."}, status=403)
    if not _transition(doc, "VERIFIED"):
        return Response({"detail": f"Cannot verify from {doc.status}."}, status=400)
    old = doc.status
    with transaction.atomic():
        doc.status = "VERIFIED"
        doc.save(update_fields=["status", "updated_at"])
        _record(doc, "VERIFY", request, comment=request.data.get("comment", ""))
    audit("document", doc.id, "DOC_VERIFIED", actor=request.user,
          from_state=old, to_state="VERIFIED", detail={"ref": doc.ref})
    generate_pdf(doc, doc.current_revision, "verified")
    return Response(DocumentSerializer(doc, context={"request": request}).data)


def _do_void(request, doc):
    """Void + reissue path (spec §7.2): admin-visible, reason required,
    number kept — the register row remains."""
    if not (request.user.role == "ADMIN" or _is_site_pm(request.user, doc.site)):
        return Response({"detail": "Only PM or Admin can void."}, status=403)
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        return Response({"detail": "A reason is required to void."}, status=400)
    doc.is_void = True
    doc.void_reason = reason
    doc.voided_by = request.user
    doc.voided_at = timezone.now()
    doc.save(update_fields=["is_void", "void_reason", "voided_by", "voided_at"])
    _record(doc, "VOID", request, comment=reason)
    audit("document", doc.id, "DOC_VOIDED", actor=request.user,
          from_state=doc.status, to_state="VOID", detail={"reason": reason})
    return Response(DocumentSerializer(doc, context={"request": request}).data)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def document_attachments(request, ref):
    doc, err = _get_scoped_document(request, ref)
    if err:
        return err
    if doc.is_void or doc.status != "DRAFT":
        return Response({"detail": "Attachments only on drafts."}, status=400)
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "file is required."}, status=400)
    attachment = Attachment.objects.create(
        document=doc, revision=doc.current_revision,
        kind=request.data.get("kind", "PHOTO"),
        file=upload, file_name=upload.name,
        content_type=upload.content_type or "",
        size_bytes=upload.size, caption=request.data.get("caption", ""),
        uploaded_by=request.user,
    )
    return Response(AttachmentSerializer(attachment,
                                         context={"request": request}).data,
                    status=201)


@api_view(["GET"])
def documents_list(request):
    qs = Document.objects.select_related("site").order_by("-doc_date", "-id")
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    if request.GET.get("site"):
        qs = qs.filter(site_id=request.GET["site"])
    if request.GET.get("doc_type"):
        qs = qs.filter(doc_type=request.GET["doc_type"])
    return Response(
        DocumentSerializer(qs[:200], many=True, context={"request": request}).data
    )


# ===== DPR/TWS register with gap detection (spec §6) =====


@api_view(["GET"])
def register_dpr_tws(request):
    try:
        site = Site.objects.get(pk=request.GET.get("site"))
    except (Site.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "site parameter required."}, status=400)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and site.id not in site_ids:
        return Response({"detail": "Not found."}, status=404)

    today = date.today()
    default_from = today - timedelta(days=13)
    date_from = date.fromisoformat(request.GET.get("from", default_from.isoformat()))
    date_to = min(date.fromisoformat(request.GET.get("to", today.isoformat())), today)

    holidays = set(
        Holiday.objects.filter(site__isnull=True).values_list("day", flat=True)
    ) | set(Holiday.objects.filter(site=site).values_list("day", flat=True))

    docs = {}
    for d in Document.objects.filter(
        site=site, doc_type__in=["DPR", "TWS"],
        doc_date__gte=date_from, doc_date__lte=date_to,
    ).order_by("id"):
        key = (d.doc_type, d.doc_date)
        # Voided rows remain visible (spec §4.1) but never satisfy the day
        if key not in docs or docs[key].is_void:
            docs[key] = d
    # Gap-flagging runs only for ACTIVE sites from the start date (spec §2.2)
    gaps_active = site.status == Site.Status.ACTIVE
    rows = []
    day = date_from
    while day <= date_to:
        working = day.isoweekday() in (site.working_days or []) and day not in holidays
        if working:
            dpr = docs.get(("DPR", day))
            tws = docs.get(("TWS", day))
            dpr_missing = dpr is None or dpr.is_void
            in_gap_window = (
                gaps_active and site.start_date is not None
                and day >= site.start_date
            )
            rows.append({
                "date": day.isoformat(),
                "day": day.strftime("%A"),
                "dpr_ref": dpr.ref if dpr else None,
                "dpr_status": "VOID" if dpr and dpr.is_void else
                              (dpr.status if dpr else None),
                "tws_ref": tws.ref if tws and not tws.is_void else None,
                "gap": in_gap_window and dpr_missing and day < today,
                "due_today": day == today and dpr_missing and in_gap_window,
            })
        day += timedelta(days=1)
    return Response({"site": site.code, "rows": rows})


@api_view(["GET"])
def dashboard_site(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and site.id not in site_ids:
        return Response({"detail": "Not found."}, status=404)

    today = date.today()
    dpr_today = Document.objects.filter(
        doc_type="DPR", site=site, doc_date=today, is_void=False
    ).first()
    unverified = Document.objects.filter(
        doc_type="DPR", site=site, status="ISSUED", is_void=False
    ).count()
    drafts = Document.objects.filter(
        site=site, status="DRAFT", is_void=False
    ).count()
    return Response({
        "site": site.code,
        "dpr_today": {"ref": dpr_today.ref, "status": dpr_today.status}
        if dpr_today else None,
        "unverified_dprs": unverified,
        "open_drafts": drafts,
    })

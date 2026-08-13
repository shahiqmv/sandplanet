"""Subcontractor register + site-level team management API (subcontractor
module, Phase 2). The SA/SE manage their own site's subcontractors and workers;
PM / Director / Signatory / Finance / QS see the whole register (§7)."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import subcontract
from .models import Document, Employee, Site, Subcontractor
from .permissions import scoped_site_ids

VIEW_ALL = ("PM", "DIRECTOR", "SIGNATORY", "FINANCE", "QS", "ADMIN")


def _can_see_all(user):
    return user.role in VIEW_ALL


def _visible_subs(user):
    qs = Subcontractor.objects.select_related("site", "created_by")
    if _can_see_all(user):
        return qs
    return qs.filter(site_id__in=(scoped_site_ids(user) or []))


def _get_visible(request, pk):
    return _visible_subs(request.user).filter(pk=pk).first()


def _worker_json(emp):
    state = ("PENDING" if emp.sub_pending
             else "ACTIVE" if emp.is_active else "REMOVED")
    return {
        "id": emp.id, "emp_no": emp.emp_no, "full_name": emp.full_name,
        "nationality": emp.nationality,
        "job_title": emp.job_category.name if emp.job_category_id else "",
        "job_category_id": emp.job_category_id, "join_date": emp.join_date,
        "state": state,
    }


def _sub_json(sub, workers=False):
    data = {
        "id": sub.id, "name": sub.name, "site_id": sub.site_id,
        "site_code": sub.site.code, "registration_no": sub.registration_no,
        "address": sub.address,
        "contact_person": sub.contact_person, "phone": sub.phone,
        "signatory_name": sub.signatory_name,
        "signatory_title": sub.signatory_title,
        "bank_details": sub.bank_details, "notes": sub.notes,
        "status": sub.status, "status_label": sub.get_status_display(),
        "can_raise_sca": sub.can_raise_sca,
        "created_by": sub.created_by.full_name if sub.created_by_id else "",
        "created_at": sub.created_at,
        "worker_count": sub.workers.filter(is_active=True).count(),
        "pending_count": sub.workers.filter(sub_pending=True).count(),
    }
    if workers:
        data["workers"] = [_worker_json(w) for w in sub.workers
                           .select_related("job_category").order_by("full_name")]
    return data


@api_view(["GET", "POST"])
def subcontractors(request):
    if request.method == "POST":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES:
            return Response({"detail": "Site Admin / Engineer only."},
                            status=403)
        try:
            site = Site.objects.get(pk=request.data.get("site_id"))
        except (Site.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "A site is required."}, status=400)
        scoped = scoped_site_ids(request.user)
        if scoped is not None and site.id not in scoped:
            return Response({"detail": "Not one of your sites."}, status=403)
        sub, err = subcontract.create_subcontractor(site, request.data,
                                                    request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_sub_json(sub), status=201)

    qs = _visible_subs(request.user)
    if request.GET.get("site_id"):
        qs = qs.filter(site_id=request.GET["site_id"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return Response([_sub_json(s) for s in qs])


@api_view(["GET", "PATCH"])
def subcontractor_detail(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES:
            return Response({"detail": "Site Admin / Engineer only."},
                            status=403)
        err = subcontract.update_subcontractor(sub, request.data, request.user)
        if err:
            return Response({"detail": err}, status=400)
    return Response(_sub_json(sub, workers=True))


@api_view(["POST"])
def subcontractor_action(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    action = request.data.get("action")
    if action == "approve":
        err = subcontract.approve_subcontractor(sub, request.user)
    elif action == "return":
        err = subcontract.return_subcontractor(
            sub, request.user, request.data.get("reason", ""))
    elif action in ("suspend", "close", "reactivate"):
        target = {"suspend": Subcontractor.Status.SUSPENDED,
                  "close": Subcontractor.Status.CLOSED,
                  "reactivate": Subcontractor.Status.APPROVED}[action]
        err = subcontract.set_subcontractor_status(sub, target, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_sub_json(sub, workers=True))


@api_view(["POST"])
def subcontractor_workers(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in subcontract.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    emp, err = subcontract.add_worker(sub, request.data, request.user)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_worker_json(emp), status=201)


@api_view(["POST"])
def subcontract_worker_action(request, emp_id):
    try:
        emp = Employee.objects.select_related("subcontractor__site").get(
            pk=emp_id, engagement_type=Employee.Engagement.SUBCONTRACT)
    except Employee.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    sub = emp.subcontractor
    scoped = scoped_site_ids(request.user)
    if (sub and not _can_see_all(request.user)
            and scoped is not None and sub.site_id not in scoped):
        return Response({"detail": "Not one of your sites."}, status=403)
    action = request.data.get("action")
    if action == "approve":
        if request.user.role not in ("PM", "ADMIN"):
            return Response({"detail": "PM approval required."}, status=403)
        err = subcontract.approve_worker(emp, request.user)
    elif action == "remove":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES + ("PM",):
            return Response({"detail": "Site team only."}, status=403)
        err = subcontract.remove_worker(emp, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_worker_json(emp))


# ---- Subcontract Agreements (SCA) --------------------------------------------
# Create + draft-edit live here; view/submit/approve/return reuse the generic
# document endpoints (/documents/<ref> and /documents/<ref>/actions/<action>).

def _agreement_row(doc):
    a = doc.subcontract_agreement
    return {"ref": doc.ref, "status": doc.status, "title": a.title,
            "value": a.value, "currency": a.currency, "doc_date": doc.doc_date,
            "project_code": doc.project.code if doc.project_id else None,
            "item_count": a.items.count()}


@api_view(["GET", "POST"])
def subcontractor_agreements(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "POST":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES + ("PM",):
            return Response({"detail": "Site Admin / Engineer / PM only."},
                            status=403)
        doc, err = subcontract.create_sca(sub, request.data, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_agreement_row(doc), status=201)
    rows = [_agreement_row(d) for d in Document.objects.filter(
        doc_type="SCA", is_void=False,
        subcontract_agreement__subcontractor=sub)
        .select_related("project", "subcontract_agreement")
        .order_by("-id")]
    return Response(rows)


@api_view(["PATCH"])
def subcontract_agreement_edit(request, ref):
    try:
        doc = Document.objects.select_related(
            "site", "subcontract_agreement__subcontractor").get(
                ref=ref, doc_type="SCA")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    scoped = scoped_site_ids(request.user)
    if scoped is not None and doc.site_id not in scoped:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in subcontract.SITE_MANAGE_ROLES + ("PM",):
        return Response({"detail": "Site Admin / Engineer / PM only."},
                        status=403)
    doc, err = subcontract.update_sca(doc, request.data, request.user)
    if err:
        return Response({"detail": err}, status=400)
    from .serializers_documents import DocumentSerializer
    return Response(DocumentSerializer(doc, context={"request": request}).data)


@api_view(["GET"])
def subcontract_agreement_pdf(request, ref):
    """Render the formal Subcontract Agreement PDF. Carries rates, so it's for
    PM and above (no Site Admin / Engineer export), same as the rate view."""
    try:
        doc = Document.objects.select_related(
            "site", "project",
            "subcontract_agreement__subcontractor").get(ref=ref, doc_type="SCA")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    scoped = scoped_site_ids(request.user)
    if scoped is not None and doc.site_id not in scoped:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_all(request.user):
        return Response({"detail": "The agreement PDF is for PM and above."},
                        status=403)
    from .views_commercial import _render_pdf
    return _render_pdf("pdf/subcontract_agreement.html",
                       subcontract.sca_pdf_context(doc),
                       f"{doc.ref}-Subcontract-Agreement")


# ---- SVC: subcontract valuations -----------------------------------------

def _get_svc(request, ref):
    try:
        doc = Document.objects.select_related(
            "site", "subcontract_valuation__agreement__document",
            "subcontract_valuation__agreement__subcontractor").get(
                ref=ref, doc_type="SVC")
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    scoped = scoped_site_ids(request.user)
    if scoped is not None and doc.site_id not in scoped:
        return None, Response({"detail": "Not found."}, status=404)
    return doc, None


@api_view(["GET", "POST"])
def agreement_valuations(request, ref):
    """List (GET) or open (POST) valuations against an approved agreement."""
    from .models import SubcontractValuation
    try:
        sca = Document.objects.select_related(
            "subcontract_agreement__subcontractor").get(ref=ref, doc_type="SCA")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    scoped = scoped_site_ids(request.user)
    if scoped is not None and sca.site_id not in scoped:
        return Response({"detail": "Not found."}, status=404)
    agreement = sca.subcontract_agreement
    if request.method == "POST":
        doc, err = subcontract.create_svc(agreement, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(subcontract.svc_payload(doc.subcontract_valuation),
                        status=201)
    vals = (SubcontractValuation.objects.filter(agreement=agreement)
            .select_related("document").order_by("seq"))
    return Response([
        {"id": v.id, "ref": v.document.ref, "seq": v.seq,
         "status": v.document.status,
         "now_due": str(subcontract.svc_valuation(v)["now_due"])}
        for v in vals])


@api_view(["GET", "PATCH"])
def valuation_detail(request, ref):
    doc, err = _get_svc(request, ref)
    if err:
        return err
    v = doc.subcontract_valuation
    if request.method == "PATCH":
        _, msg = subcontract.value_svc(v, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
    return Response(subcontract.svc_payload(v))


@api_view(["GET"])
def valuation_certificate_pdf(request, ref):
    """The printable Subcontract Valuation Certificate. Carries rates, so PM
    and above only (same gate as the agreement PDF). Draft valuations can't
    print — the quantities aren't even submitted yet."""
    doc, err = _get_svc(request, ref)
    if err:
        return err
    if not _can_see_all(request.user):
        return Response({"detail": "The certificate PDF is for PM and above."},
                        status=403)
    if doc.status == "DRAFT":
        return Response({"detail": "Submit the valuation before printing the "
                                   "certificate."}, status=400)
    from .views_commercial import _render_pdf
    return _render_pdf("pdf/svc_certificate.html",
                       subcontract.svc_pdf_context(doc),
                       f"{doc.ref}-Valuation-Certificate")


@api_view(["POST"])
def valuation_action(request, ref):
    doc, err = _get_svc(request, ref)
    if err:
        return err
    msg = subcontract.svc_action(
        doc.subcontract_valuation, request.data.get("action", ""),
        request.user, request.data.get("note", ""))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(subcontract.svc_payload(doc.subcontract_valuation))


@api_view(["GET"])
def site_agreements(request):
    """Approved subcontract agreements a payment can be raised against.

    A PYR links to one so that whatever is paid — advance, part payment —
    nets off that subcontractor's next valuation (owner 2026-08-13).
    """
    from .models import SubcontractAgreement
    from .subcontract import paid_to_date
    site_id = request.GET.get("site")
    qs = SubcontractAgreement.objects.filter(
        document__status="APPROVED", document__is_void=False,
    ).select_related("document", "subcontractor", "document__site")
    ids = scoped_site_ids(request.user)
    if ids is not None:
        qs = qs.filter(document__site_id__in=ids)
    if site_id:
        qs = qs.filter(document__site_id=site_id)
    return Response([{
        "id": a.id, "ref": a.document.ref, "title": a.title,
        "site_code": a.document.site.code,
        "subcontractor": a.subcontractor.name,
        "value": a.value, "currency": a.currency,
        "paid_to_date": paid_to_date(a),
    } for a in qs.order_by("subcontractor__name")])

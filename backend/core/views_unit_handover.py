"""Unit-by-unit handover — API. Rules live in core/unit_handover.py."""
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import handover
from . import unit_handover as svc
from .models import ProjectUnit
from .permissions import scoped_site_ids


def _unit(request, pk):
    unit = (ProjectUnit.objects.select_related("project__site", "handover")
            .prefetch_related("snags").filter(pk=pk).first())
    if unit is None:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and unit.project.site_id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return unit, None


def _fresh(request, pk):
    unit, _ = _unit(request, pk)
    return Response(svc.detail(unit, request.user))


@api_view(["GET"])
def unit_handover(request, pk):
    unit, err = _unit(request, pk)
    if err:
        return err
    return Response(svc.detail(unit, request.user))


@api_view(["POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def unit_handover_action(request, pk, action):
    unit, err = _unit(request, pk)
    if err:
        return err
    role = request.user.role
    if action == "step-back":
        if role not in svc.UNDO_ROLES:
            return Response({"detail": "A PM, QS or Director takes a "
                                       "handover step back."}, status=403)
        _, msg = svc.step_back(unit, request.data.get("reason"), request.user)
    elif role not in svc.RECORD_ROLES:
        return Response({"detail": "The site team records handovers."},
                        status=403)
    elif action == "offer":
        _, msg = svc.offer(unit, request.data, request.user)
    elif action == "inspect":
        _, msg = svc.record_inspection(unit, request.data, request.user)
    elif action == "hand-over":
        _, msg = svc.hand_over(unit, request.data, request.user,
                               signed_copy=request.FILES.get("signed_copy"))
    elif action == "signed-copy":
        _, msg = svc.attach_signed_copy(
            unit, request.FILES.get("signed_copy"), request.user)
    else:
        return Response({"detail": "Unknown action."}, status=404)
    if msg:
        return Response({"detail": msg}, status=400)
    return _fresh(request, pk)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def unit_snags(request, pk):
    """Raise a snag against this unit. It is a snag of the project's handover
    dossier like any other, tagged with the unit — the dossier is opened if
    the project has none yet."""
    unit, err = _unit(request, pk)
    if err:
        return err
    if request.user.role not in handover.RECORDER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    dossier = getattr(unit.project, "handover", None)
    if dossier is None:
        dossier, _ = handover.open_dossier(unit.project, request.user)
    _, msg = handover.raise_snag(dossier, request.data, request.user,
                                 photo=request.FILES.get("photo"), unit=unit)
    if msg:
        return Response({"detail": msg}, status=400)
    return _fresh(request, pk)


@api_view(["GET"])
def unit_handover_certificate(request, pk):
    """The certificate the client signs: the unit, the inspection, what is
    still open, and the defects period it starts."""
    unit, err = _unit(request, pk)
    if err:
        return err
    h = getattr(unit, "handover", None)
    if h is None or h.status == "OFFERED":
        return Response({"detail": "The certificate is issued once the "
                                   "joint inspection is recorded."},
                        status=400)
    from django.template.loader import render_to_string

    from . import pdf as pdf_mod
    from .views_payroll import _pdf_response
    project = unit.project
    snags = [s for s in unit.snags.select_related("owner").order_by("id")
             if s.is_open]
    html = render_to_string("pdf/unit_handover_certificate.html", {
        "h": h, "unit": unit, "project": project, "site": project.site,
        "snags": snags, "dlp_ends": h.defects_liability_ends(),
        "dlp_months": project.defects_liability_months,
        "subline": f"{project.site.code} · {project.code} · {unit.ref}",
        "logo_src": pdf_mod.logo_src(), "co": pdf_mod.company_info(),
        "printed_at": timezone.localtime()})
    return _pdf_response(html, f"{h.certificate_no}-{unit.ref}.pdf")

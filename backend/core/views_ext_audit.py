"""External audits — API (`/api/v1/audits/*`). Rules live in core/ext_audit.py."""
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import ext_audit
from .models import ExternalAudit, ExternalAuditFile


def _read(request):
    if request.user.role not in ext_audit.VIEW_ROLES:
        return Response({"detail": "Audits are open to Finance, the "
                                   "Director and the signatory."}, status=403)
    return None


def _write(request):
    if request.user.role not in ext_audit.EDIT_ROLES:
        return Response({"detail": "Finance keeps the audit register."},
                        status=403)
    return None


def _find(ident):
    qs = ExternalAudit.objects.prefetch_related("files__uploaded_by")
    if str(ident).upper().startswith("AUD-"):
        return qs.filter(ref__iexact=ident).first()
    return qs.filter(pk=ident).first() if str(ident).isdigit() else None


@api_view(["GET", "POST"])
def audits(request):
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        a, msg = ext_audit.save(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(ext_audit.audit_dict(a, detail=True), status=201)
    rows = [ext_audit.audit_dict(a) for a in
            ExternalAudit.objects.prefetch_related("files")]
    return Response({"audits": rows, "meta": ext_audit.meta(),
                     "can_edit": request.user.role in ext_audit.EDIT_ROLES})


@api_view(["GET", "PATCH"])
def audit_detail(request, ident):
    if (bad := _read(request)):
        return bad
    a = _find(ident)
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if (bad := _write(request)):
            return bad
        a, msg = ext_audit.save(request.data, request.user, rec=a)
        if msg:
            return Response({"detail": msg}, status=400)
        a = _find(a.id)
    out = ext_audit.audit_dict(a, detail=True)
    out["meta"] = ext_audit.meta()
    out["can_edit"] = request.user.role in ext_audit.EDIT_ROLES
    return Response(out)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def audit_files(request, ident):
    if (bad := _read(request) or _write(request)):
        return bad
    a = _find(ident)
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    f, msg = ext_audit.add_file(a, request.FILES.get("file"),
                                request.data.get("kind"),
                                request.data.get("label"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ext_audit.audit_dict(_find(a.id), detail=True),
                    status=201)


@api_view(["DELETE"])
def audit_file(request, ident, pk):
    if (bad := _read(request) or _write(request)):
        return bad
    a = _find(ident)
    f = ExternalAuditFile.objects.filter(pk=pk, audit=a).first() if a else None
    if f is None:
        return Response({"detail": "Not found."}, status=404)
    ext_audit.remove_file(f, request.user)
    return Response(ext_audit.audit_dict(_find(a.id), detail=True))

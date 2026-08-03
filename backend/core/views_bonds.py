"""Project bonds & insurance endpoints (owner 2026-08-03). Same access as the
project commercial module: scoped to the project's site; mutations by the
QS / PM / Director / Admin."""
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import bonds as bs
from .models import Project, ProjectBond
from .permissions import scoped_site_ids


def _project(request, pid):
    p = Project.objects.filter(pk=pid).select_related("site").first()
    if not p:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and p.site_id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return p, None


def _bond(request, pk):
    b = (ProjectBond.objects.filter(pk=pk)
         .select_related("project__site", "pyr").first())
    if not b:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and b.project.site_id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return b, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def project_bonds(request, pid):
    project, err = _project(request, pid)
    if err:
        return err
    if request.method == "POST":
        bond, msg = bs.add_bond(project, request.data, request.FILES,
                                request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(bs.bond_dict(bond, request), status=201)
    return Response({"bonds": bs.project_bonds(project, request),
                     "can_edit": request.user.role in bs.EDIT_ROLES,
                     "gaps": bs.required_gaps(project)})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def bond_detail(request, pk):
    bond, err = _bond(request, pk)
    if err:
        return err
    if request.method == "DELETE":
        msg = bs.delete_bond(bond, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(status=204)
    msg = bs.update_bond(bond, request.data, request.FILES, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(bs.bond_dict(bond, request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bond_raise_pyr(request, pk):
    bond, err = _bond(request, pk)
    if err:
        return err
    msg = bs.raise_bond_pyr(bond, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(bs.bond_dict(bond, request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def bond_issue(request, pk):
    bond, err = _bond(request, pk)
    if err:
        return err
    msg = bs.issue_bond(bond, request.data, request.FILES, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(bs.bond_dict(bond, request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bond_cancel(request, pk):
    bond, err = _bond(request, pk)
    if err:
        return err
    msg = bs.cancel_bond(bond, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(bs.bond_dict(bond, request))

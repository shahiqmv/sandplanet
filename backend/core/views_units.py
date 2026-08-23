"""Unit progress board — the API behind the Units tab and the client portal."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import units as svc
from .models import BoqCategory, Project, ProjectUnit, UnitStage
from .permissions import scoped_site_ids


def _get_project(request, pk):
    """The project, scoped to what this user may see (404 outside their
    sites — the same rule the rest of the project API uses)."""
    project = Project.objects.select_related("site", "boq").filter(
        pk=pk).first()
    if project is None:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and project.site_id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return project, None


def _payload(project, user):
    """The board plus everything the panel needs to render itself.

    EVERY endpoint returns this, not a bare board: the panel replaces its
    whole state with the response, so a partial payload made it forget the
    project was unit-based and fall back to the "not a unit BOQ" message
    right after generating units.
    """
    data = svc.board(project)
    # Progress tracking is a MONITORING concern: any project may use it, even
    # one priced flat with a locked BOQ (owner 2026-08-23, VKR's 17 pools).
    # `unit_priced` only says whether units can be generated from BOQ category
    # quantities; `tracks_units` says whether this project is using the board.
    data["is_unit_project"] = True
    data["unit_priced"] = svc.is_unit_priced(project)
    data["tracks_units"] = svc.tracks_units(project)
    data["can_manage"] = svc.can_manage(user)
    data["project_stages"] = [
        {"id": st.id, "name": st.name, "weight": st.weight}
        for st in svc.project_stages(project)]
    data["ladders"] = [
        {"category_id": c.id, "ref": c.ref, "name": c.name, "qty": c.qty,
         "is_lump": c.is_lump, "units": c.units.count(),
         "stages": [{"id": s.id, "name": s.name, "weight": s.weight}
                    for s in c.stages.all()]}
        for c in getattr(project, "boq", None).categories.all()
    ] if svc.is_unit_priced(project) else []
    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def project_units(request, pk):
    """The board, plus the stage ladder per category so the tab can edit it."""
    project, err = _get_project(request, pk)
    if err:
        return err
    return Response(_payload(project, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def category_stages(request, pk):
    """Set a category's stage ladder (PM / QS / Director)."""
    cat = BoqCategory.objects.filter(pk=pk).select_related(
        "boq__project__site").first()
    if cat is None:
        return Response({"detail": "Not found."}, status=404)
    _, err = _get_project(request, cat.boq.project_id)
    if err:
        return err
    if not svc.can_manage(request.user):
        return Response({"detail": "The PM or QS sets the stages."},
                        status=403)
    msg = svc.set_stages(cat, request.data.get("stages") or [], request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_payload(cat.boq.project, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def category_generate_units(request, pk):
    """Create the category's units from its quantity (D-01…D-11)."""
    cat = BoqCategory.objects.filter(pk=pk).select_related(
        "boq__project__site").first()
    if cat is None:
        return Response({"detail": "Not found."}, status=404)
    _, err = _get_project(request, cat.boq.project_id)
    if err:
        return err
    if not svc.can_manage(request.user):
        return Response({"detail": "The PM or QS sets up units."}, status=403)
    made, msg = svc.generate_units(cat, request.user,
                                   prefix=request.data.get("prefix"))
    if msg:
        return Response({"detail": msg}, status=400)
    data = _payload(cat.boq.project, request.user)
    data["created"] = made
    return Response(data, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def project_stages(request, pk):
    """Set the stage ladder for a project whose units are not tied to BOQ
    categories — a flat-priced job monitored unit by unit."""
    project, err = _get_project(request, pk)
    if err:
        return err
    if not svc.can_manage(request.user):
        return Response({"detail": "The PM or QS sets the stages."},
                        status=403)
    msg = svc.set_project_stages(project, request.data.get("stages") or [],
                                 request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_payload(project, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def project_create_units(request, pk):
    """Create units on a project: a count with a prefix, or explicit refs
    (the real villa / pool numbers)."""
    project, err = _get_project(request, pk)
    if err:
        return err
    if not svc.can_manage(request.user):
        return Response({"detail": "The PM or QS sets up units."}, status=403)
    made, msg = svc.generate_project_units(
        project, request.user, count=request.data.get("count"),
        refs=request.data.get("refs"),
        prefix=request.data.get("prefix") or "UNIT")
    if msg:
        return Response({"detail": msg}, status=400)
    data = _payload(project, request.user)
    data["created"] = made
    return Response(data, status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def unit_detail(request, pk):
    """Rename a unit, record its size / scope / target, put it on hold."""
    unit = ProjectUnit.objects.filter(pk=pk).select_related(
        "project__site", "category").first()
    if unit is None:
        return Response({"detail": "Not found."}, status=404)
    _, err = _get_project(request, unit.project_id)
    if err:
        return err
    if not svc.can_manage(request.user):
        return Response({"detail": "The PM or QS edits a unit."}, status=403)
    if request.method == "DELETE":
        if unit.stage_progress.exists():
            return Response({"detail": "Progress has been reported against "
                                       "this unit — put it on hold instead."},
                            status=400)
        project = unit.project
        unit.delete()
        return Response(_payload(project, request.user))
    for f in ("ref", "name", "size", "scope", "location", "hold_reason"):
        if f in request.data:
            setattr(unit, f, (request.data.get(f) or "").strip())
    if "target_date" in request.data:
        unit.target_date = request.data.get("target_date") or None
    if request.data.get("status") in dict(ProjectUnit.Status.choices):
        unit.status = request.data["status"]
    if not unit.ref:
        return Response({"detail": "A unit needs a reference."}, status=400)
    if ProjectUnit.objects.filter(project=unit.project, ref=unit.ref).exclude(
            pk=unit.pk).exists():
        return Response({"detail": f"{unit.ref} is already used on this "
                                   "project."}, status=400)
    unit.save()
    if unit.status != ProjectUnit.Status.ON_HOLD:
        svc.recalc(unit)
    return Response(_payload(unit.project, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def unit_progress(request, pk):
    """Report a stage figure by hand (the DPR is the usual route)."""
    unit = ProjectUnit.objects.filter(pk=pk).select_related(
        "project__site", "category").first()
    if unit is None:
        return Response({"detail": "Not found."}, status=404)
    _, err = _get_project(request, unit.project_id)
    if err:
        return err
    if request.user.role not in svc.REPORT_ROLES:
        return Response({"detail": "Not permitted."}, status=403)
    stage = UnitStage.objects.filter(pk=request.data.get("stage_id"),
                                     category_id=unit.category_id).first()
    if stage is None:
        return Response({"detail": "Choose a stage of this unit."}, status=400)
    from datetime import date
    msg = svc.report_progress(unit, stage, request.data.get("percent"),
                              on=date.today(), actor=request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_payload(unit.project, request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def site_units(request, pk):
    """Units across a site's unit-based projects — the picker the DPR uses."""
    out = []
    for project in Project.objects.filter(site_id=pk).select_related(
            "boq").prefetch_related("unit_stages"):
        for u in project.units.select_related("category").prefetch_related(
                "category__stages"):
            out.append({
                "id": u.id, "ref": u.ref, "name": u.name,
                "project_id": project.id, "project_code": project.code,
                "percent": u.percent, "status": u.status,
                "stages": [{"id": s.id, "name": s.name}
                           for s in svc.stages_for(u)]})
    return Response(out)

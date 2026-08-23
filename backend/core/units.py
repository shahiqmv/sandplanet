"""Unit progress tracking for unit-based (per-unit BOQ) projects.

Owner 2026-08-23: on a villa/pool project everyone needs to know, at any
moment, where each unit has got to — the client, the site team and
management — and reading it off the programme is guesswork. Each BOQ category
defines its stages once, with weights; units are generated from the category's
quantity and renamed to whatever the client calls them; the site reports a
stage percentage on the DPR work-done row it is already filling in.

The DPR stays the record: every figure on the board carries the DPR it came
from and the day it was reported.
"""
from decimal import Decimal

from django.db import transaction

from .audit import audit
from .models import (Boq, BoqCategory, ProjectUnit, UnitStage,
                     UnitStageProgress)

ZERO = Decimal("0")
MANAGE_ROLES = ("PM", "QS", "DIRECTOR", "ADMIN")
REPORT_ROLES = MANAGE_ROLES + ("SITE_ENGINEER", "SITE_ADMIN")

# A sensible starting point so a PM is never faced with a blank page; every
# name and weight is editable per category.
DEFAULT_STAGES = [("Mobilisation", 5), ("Strip-out / demolition", 10),
                  ("Civil works", 25), ("MEP first fix", 15),
                  ("Finishes", 25), ("MEP second fix", 10),
                  ("Snagging", 5), ("Handover", 5)]


def can_manage(user):
    return user.role in MANAGE_ROLES


def is_unit_priced(project):
    """Does the BOQ price this project per unit? Only decides whether units
    can be GENERATED from BOQ category quantities — never whether progress can
    be tracked."""
    boq = getattr(project, "boq", None)
    return bool(boq and boq.mode == Boq.Mode.UNIT)


# Kept for callers that only ask "does this project track units".
def is_unit_project(project):
    return is_unit_priced(project) or project.units.exists()


def tracks_units(project):
    return project.units.exists() or project.unit_stages.exists()


def stages_for(unit):
    """A unit's ladder: its BOQ category's, or the project's own."""
    if unit.category_id:
        return list(unit.category.stages.all())
    return list(unit.project.unit_stages.all())


def project_stages(project):
    return list(project.unit_stages.all())


def set_project_stages(project, rows, actor):
    """The ladder for a project whose units are not tied to BOQ categories —
    a flat-priced project monitored per unit (owner 2026-08-23)."""
    return _set_stages(rows, actor, project=project,
                       existing=project.unit_stages.all(),
                       units=project.units.filter(category__isnull=True),
                       label=project.code, project_id=project.id)


def ensure_project_stages(project, names=None):
    """Seed a project ladder the first time — the caller's stage names, or the
    default ladder."""
    if project.unit_stages.exists():
        return project_stages(project)
    rows = ([(n, w) for n, w in names] if names else DEFAULT_STAGES)
    UnitStage.objects.bulk_create([
        UnitStage(project=project, sort_order=i, name=n, weight=w)
        for i, (n, w) in enumerate(rows, 1)])
    return project_stages(project)


def generate_project_units(project, actor, count=None, refs=None,
                           prefix="UNIT"):
    """Create units directly on a project — for a flat-priced job that still
    has to be monitored unit by unit. `refs` names them explicitly (the real
    villa numbers); otherwise `count` makes PREFIX-01…"""
    ensure_project_stages(project)
    have = set(project.units.values_list("ref", flat=True))
    last = project.units.order_by("-sort_order").first()
    order = last.sort_order if last else 0
    wanted = [r.strip() for r in (refs or []) if r and r.strip()]
    if not wanted:
        try:
            n = int(count or 0)
        except (TypeError, ValueError):
            return 0, "How many units?"
        if n <= 0:
            return 0, "How many units?"
        base = "".join(ch for ch in (prefix or "UNIT").strip().upper()
                       if ch.isalnum() or ch in "-_") or "UNIT"
        wanted, i = [], 1
        while len(wanted) < n:
            ref = f"{base}-{i:02d}"
            i += 1
            if ref not in have:
                wanted.append(ref)
    made = []
    for ref in wanted:
        if ref in have:
            continue
        have.add(ref)
        order += 1
        made.append(ProjectUnit(project=project, category=None,
                                sort_order=order, ref=ref[:30]))
    if not made:
        return 0, None
    ProjectUnit.objects.bulk_create(made)
    audit("project", project.id, "UNITS_GENERATED", actor=actor,
          detail={"count": len(made), "refs": [u.ref for u in made][:20]})
    return len(made), None


def ensure_stages(category):
    """The category's stages, seeding the default ladder the first time."""
    stages = list(category.stages.all())
    if stages:
        return stages
    UnitStage.objects.bulk_create([
        UnitStage(category=category, sort_order=i, name=n, weight=w)
        for i, (n, w) in enumerate(DEFAULT_STAGES, 1)])
    return list(category.stages.all())


def set_stages(category, rows, actor):
    """Replace a category's stage ladder. Progress already reported against a
    stage that survives (matched by name) is kept."""
    return _set_stages(rows, actor, category=category,
                       existing=category.stages.all(),
                       units=category.units.all(), label=category.name[:80],
                       project_id=category.boq.project_id)


def _set_stages(rows, actor, existing, units, label, project_id,
                category=None, project=None):
    cleaned = []
    for i, r in enumerate(rows or [], 1):
        name = (r.get("name") or "").strip()
        if not name:
            return "Every stage needs a name."
        try:
            weight = Decimal(str(r.get("weight") or 0))
        except Exception:
            return f"{name}: the weight must be a number."
        if weight < ZERO:
            return f"{name}: the weight cannot be negative."
        cleaned.append((i, name, weight))
    if not cleaned:
        return "Give the unit at least one stage."
    if sum(w for _, _, w in cleaned) <= ZERO:
        return "The weights cannot all be zero."
    with transaction.atomic():
        keep = {}
        for old in existing:
            keep[old.name.strip().lower()] = old
        seen = []
        for order, name, weight in cleaned:
            existing = keep.pop(name.strip().lower(), None)
            if existing:
                existing.sort_order, existing.weight = order, weight
                existing.save(update_fields=["sort_order", "weight"])
                seen.append(existing)
            else:
                seen.append(UnitStage.objects.create(
                    category=category, project=project, sort_order=order,
                    name=name, weight=weight))
        for dropped in keep.values():          # removed stages take their
            dropped.delete()                   # progress rows with them
        for unit in units:
            recalc(unit)
    audit("project", project_id, "UNIT_STAGES_SET", actor=actor,
          detail={"for": label, "stages": [n for _, n, _ in cleaned]})
    return None


def generate_units(category, actor, prefix=None, start=1):
    """Create the category's units from its quantity — D-01…D-11 — skipping
    refs that already exist, so it is safe to re-run after the quantity grows.
    """
    project = category.boq.project
    if category.is_lump:
        return 0, "A lump-sum bill has no units to track."
    want = int(category.qty or 0)
    if want <= 0:
        return 0, "This category has no quantity to generate units from."
    base = (prefix or category.ref or category.name[:3]).strip().upper()
    base = "".join(ch for ch in base if ch.isalnum() or ch in "-_") or "U"
    ensure_stages(category)
    have = set(project.units.values_list("ref", flat=True))
    made = []
    n = int(start)
    last = category.units.order_by("-sort_order").first()
    order = (last.sort_order if last else 0)
    while len(made) < want - category.units.count():
        ref = f"{base}-{n:02d}"
        n += 1
        if ref in have:
            continue
        order += 1
        made.append(ProjectUnit(project=project, category=category,
                                sort_order=order, ref=ref,
                                name=category.name[:120]))
    if not made:
        return 0, None
    ProjectUnit.objects.bulk_create(made)
    audit("project", project.id, "UNITS_GENERATED", actor=actor,
          detail={"category": category.name[:80], "count": len(made)})
    return len(made), None


def recalc(unit):
    """The unit's weighted percentage, and the status that follows from it."""
    stages = stages_for(unit)
    total_w = sum((s.weight for s in stages), ZERO)
    done = {p.stage_id: p.percent for p in unit.stage_progress.all()}
    if total_w > ZERO:
        pct = sum(((done.get(s.id, ZERO) * s.weight) for s in stages),
                  ZERO) / total_w
    else:
        pct = ZERO
    pct = pct.quantize(Decimal("0.01"))
    fields = ["percent"]
    unit.percent = pct
    if unit.status != ProjectUnit.Status.ON_HOLD:
        if pct >= Decimal("100"):
            unit.status = ProjectUnit.Status.COMPLETE
        elif pct > ZERO:
            unit.status = ProjectUnit.Status.IN_PROGRESS
        else:
            unit.status = ProjectUnit.Status.NOT_STARTED
        fields.append("status")
    unit.save(update_fields=fields)
    return pct


def report_progress(unit, stage, percent, document=None, on=None, actor=None):
    """Record a stage figure — from a DPR, or by hand on the units board."""
    try:
        pct = Decimal(str(percent))
    except Exception:
        return "The progress must be a number."
    pct = max(ZERO, min(Decimal("100"), pct))
    row, _ = UnitStageProgress.objects.get_or_create(unit=unit, stage=stage)
    row.percent = pct
    row.updated_from = document
    row.updated_on = on
    row.save(update_fields=["percent", "updated_from", "updated_on"])
    if pct > ZERO and unit.started_on is None:
        unit.started_on = on
        unit.save(update_fields=["started_on"])
    recalc(unit)
    unit.refresh_from_db()
    if unit.status == ProjectUnit.Status.COMPLETE and unit.completed_on is None:
        unit.completed_on = on
        unit.save(update_fields=["completed_on"])
    elif unit.status != ProjectUnit.Status.COMPLETE and unit.completed_on:
        unit.completed_on = None
        unit.save(update_fields=["completed_on"])
    return None


def apply_dpr(doc, actor):
    """An issued DPR's work-done rows carry unit + stage + % to date. Applied
    per row; rows without a unit are the ordinary programme rows and are left
    exactly as they were, so nothing about the DPR is lost or displaced."""
    applied = 0
    for row in (doc.current_revision.payload or {}).get("work_done", []):
        unit_id, stage_id = row.get("unit_id"), row.get("stage_id")
        todate = row.get("progress_todate")
        if not unit_id or not stage_id or todate in (None, ""):
            continue
        unit = ProjectUnit.objects.filter(
            pk=unit_id, project__site_id=doc.site_id).select_related(
            "category").first()
        stage = UnitStage.objects.filter(pk=stage_id).first()
        if unit is None or stage is None:
            continue
        if stage.category_id != unit.category_id or (
                stage.category_id is None
                and stage.project_id != unit.project_id):
            continue
        if report_progress(unit, stage, todate, document=doc,
                           on=doc.doc_date, actor=actor) is None:
            applied += 1
    if applied:
        audit("document", doc.id, "DPR_UNIT_PROGRESS", actor=actor,
              detail={"rows": applied})
    return applied


def board(project):
    """The unit board: every unit with its stage line, for the team, for
    management and for the client portal."""
    units = (project.units.select_related("category")
             .prefetch_related("stage_progress__stage",
                               "category__stages",
                               "project__unit_stages")
             .order_by("sort_order", "id"))
    cats, rows = {}, []
    for u in units:
        stages = stages_for(u)
        done = {p.stage_id: p for p in u.stage_progress.all()}
        current = ""
        for st in stages:
            pc = done.get(st.id)
            if pc is None or pc.percent < Decimal("100"):
                current = st.name
                break
        else:
            current = "Complete" if stages else ""
        last = max((p.updated_on for p in u.stage_progress.all()
                    if p.updated_on), default=None)
        last_doc = None
        for p in sorted(u.stage_progress.all(),
                        key=lambda x: (x.updated_on or  # newest reported
                                       __import__("datetime").date.min),
                        reverse=True):
            if p.updated_from_id:
                last_doc = p.updated_from.ref
                break
        rows.append({
            "id": u.id, "ref": u.ref, "name": u.name, "size": u.size,
            "scope": u.scope, "location": u.location,
            "category": u.category.name if u.category_id else "",
            "category_id": u.category_id,
            "status": u.status, "status_label": u.get_status_display(),
            "percent": u.percent, "current_stage": current,
            "started_on": u.started_on, "completed_on": u.completed_on,
            "target_date": u.target_date, "hold_reason": u.hold_reason,
            "last_reported_on": last, "last_dpr": last_doc,
            "stages": [{"id": st.id, "name": st.name, "weight": st.weight,
                        "percent": (done[st.id].percent if st.id in done
                                    else ZERO),
                        "dpr": (done[st.id].updated_from.ref
                                if st.id in done and done[st.id].updated_from_id
                                else None),
                        "on": done[st.id].updated_on if st.id in done else None}
                       for st in stages],
        })
        key = u.category_id or 0
        if True:
            c = cats.setdefault(key, {
                "id": u.category_id,
                "name": u.category.name if u.category_id else "All units",
                "ref": u.category.ref if u.category_id else "",
                "units": 0, "complete": 0,
                "in_progress": 0, "not_started": 0, "on_hold": 0,
                "percent": ZERO})
            c["units"] += 1
            c["percent"] += u.percent
            c[{"COMPLETE": "complete", "IN_PROGRESS": "in_progress",
               "NOT_STARTED": "not_started", "ON_HOLD": "on_hold"}[u.status]] += 1
    for c in cats.values():
        c["percent"] = (c["percent"] / c["units"]).quantize(Decimal("0.01"))
    overall = (sum((r["percent"] for r in rows), ZERO) / len(rows)
               ).quantize(Decimal("0.01")) if rows else ZERO
    return {"units": rows, "categories": list(cats.values()),
            "overall_percent": overall, "unit_count": len(rows),
            "complete": sum(1 for r in rows if r["status"] == "COMPLETE")}

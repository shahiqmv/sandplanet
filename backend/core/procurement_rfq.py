"""Request for quotation from the procurement schedule (owner 2026-10-12).

The PM and the QS ask suppliers for prices while the plan is being built.
They pick lines (a whole section, or item by item) and the app prints a
plain running list — photo, description, make, unit, quantity — addressed to
the supplier under an RFQ reference. Nothing else goes on it: no project,
section or trade, no dates, no terms, no estimate, no other supplier.
"""
from .audit import audit
from .models import AuditLog, ScheduleLine

RFQ_ROLES = ("QS", "PM", "SITE_ENGINEER", "SITE_ADMIN", "DIRECTOR",
             "HO_PURCHASING", "ADMIN")


def _image_src(line):
    """The line's reference photo, else its catalogue item's photo."""
    f = line.reference_image or (line.item.photo if line.item_id and
                                 getattr(line.item, "photo", None) else None)
    if not f:
        return None
    try:
        return f"file:///{f.path}"        # filesystem storage
    except NotImplementedError:
        return f.url                      # Spaces: fetched by URL


def _next_ref(site):
    n = AuditLog.objects.filter(event="PSC_RFQ",
                                detail__site=site.code).count() + 1
    return f"RFQ-{site.code}-{n:03d}"


def build(sched, line_ids, data, actor):
    """The RFQ's context, or (None, error)."""
    if actor.role not in RFQ_ROLES:
        return None, "The PM, QS, site team or Purchasing raises an RFQ."
    try:
        ids = [int(x) for x in (line_ids or [])]
    except (TypeError, ValueError):
        return None, "Choose the items to ask for."
    lines = list(ScheduleLine.objects.filter(schedule=sched, pk__in=ids)
                 .exclude(state="CANCELLED")
                 .select_related("section", "project", "item"))
    if not lines:
        return None, "Choose at least one item to ask a price for."
    if len(lines) != len(set(ids)):
        return None, "Some of those items are not on this schedule."
    site = sched.site or sched.document.site
    # one running list in the plan's own order — no project, section or
    # trade on it (owner 2026-10-12)
    from .procurement_schedule import order_projects
    projects = order_projects(sched, list({ln.project_id: ln.project
                                           for ln in lines
                                           if ln.project_id}.values()))
    rank = {p.id: i for i, p in enumerate(projects)}
    lines.sort(key=lambda ln: (
        rank.get(ln.project_id, len(rank)),
        ln.section.sort_order if ln.section_id else 9999,
        ln.section_id or 0, ln.s_no or 0, ln.id))
    rows = [{"no": i, "description": ln.description,
             "make": ln.make_brand, "spec": ln.specification,
             "qty": ln.quantity, "uom": ln.uom, "image": _image_src(ln)}
            for i, ln in enumerate(lines, start=1)]
    ref = _next_ref(site)
    ctx = {"ref": ref, "supplier": (data.get("supplier") or "").strip(),
           "rows": rows, "has_images": any(r["image"] for r in rows)}
    audit("document", sched.document_id, "PSC_RFQ", actor=actor,
          detail={"ref": ref, "site": site.code, "lines": len(lines),
                  "supplier": ctx["supplier"][:120]})
    return ctx, None

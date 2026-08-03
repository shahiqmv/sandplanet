"""Client-safe report data for the portal (owner 2026-08-02 redesign).

The portal renders DPR / DMA / TWS / LM reports as web-native pages, not as the
print PDF in a frame. Each builder returns plain JSON primitives through an
explicit allowlist — no Django objects, no file:// paths, no commercial or
engagement data. The print PDF stays available for download via pdf.py.
"""
from .models import Document, ManpowerCategory


def _pct(v):
    """A percentage cell → float, or None when blank/non-numeric."""
    try:
        s = str(v).strip().rstrip("%").strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def client_project_progress(project):
    """What the client sees for a project's overall progress: the PM's
    published override if set, else the programme's duration-weighted %, else
    None. Carries the PM's status note (shown whenever set)."""
    from .views_projects import programme_overall_progress
    if project.progress_override is not None:
        pct, source = float(project.progress_override), "published"
    else:
        pct = programme_overall_progress(project)
        source = "programme" if pct is not None else None
    return {
        "percent": None if pct is None else round(pct),
        "note": project.progress_note or "",
        "source": source,
        "updated_at": (project.progress_updated_at.isoformat()
                       if project.progress_updated_at else None),
    }


def project_programme(project):
    """Client-safe programme for a project: the Gantt rows (name, dates,
    milestone flag, dependencies, % complete) + the weighted overall %.
    Programme carries no commercial data, so every field is client-safe."""
    from .views_projects import programme_overall_progress
    acts = [{
        "id": a.id, "sort_order": a.sort_order, "indent": a.indent,
        "name": a.name,
        "start": a.start.isoformat() if a.start else None,
        "finish": a.finish.isoformat() if a.finish else None,
        "duration_days": a.duration_days,
        "is_milestone": a.is_milestone,
        "predecessors": a.predecessors or "",
        "progress": float(a.progress),
    } for a in project.activities.all()]
    return {"activities": acts, "overall": programme_overall_progress(project),
            "start_date": (project.start_date.isoformat()
                           if project.start_date else None),
            "target_date": (project.planned_completion.isoformat()
                            if project.planned_completion else None)}


def project_progress(site, code=None):
    """Interim overall progress for a project (or the whole site when code is
    None): the average of the to-date % across the most recent DPR that carries
    activity rows for it. Returns an int 0–100 or None. This is the placeholder
    engine until site-level progress is designed properly (owner)."""
    dprs = (Document.objects.filter(
        site=site, doc_type="DPR", is_void=False,
        status__in=("ISSUED", "VERIFIED"), current_revision__isnull=False)
        .select_related("current_revision").order_by("-doc_date")[:30])
    for d in dprs:
        rows = (d.current_revision.payload or {}).get("work_done", [])
        vals = [_pct(r.get("progress_todate") or r.get("progress_pct"))
                for r in rows
                if not code or (r.get("project") or "").strip() == code]
        vals = [v for v in vals if v is not None]
        if vals:
            return round(sum(vals) / len(vals))
    return None


def site_workforce(site):
    """The site's current workforce summary for the portal — by trade + grand
    total. Sourced from the most recent DPR's reported manpower, which is the
    real site strength and already folds in subcontract labour (never labelled
    as such). Falls back to the HR roster if no DPR exists yet."""
    dprs = (Document.objects.filter(
        site=site, doc_type="DPR", is_void=False,
        status__in=("ISSUED", "VERIFIED"), current_revision__isnull=False)
        .select_related("current_revision").order_by("-doc_date")[:10])
    for d in dprs:
        mp = _dpr_manpower(d.current_revision.payload or {})
        if mp["total"] <= 0:
            continue      # skip empty reports; use the latest with a headcount
        by_trade = sorted(
            [{"trade": n, "count": c} for n, c in (mp["staff"] + mp["labour"])],
            key=lambda x: -x["count"])
        return {"grand_total": mp["total"], "by_trade": by_trade,
                "as_of": d.doc_date.isoformat(), "source": "report"}
    from .views_hr import site_manpower_data
    m = site_manpower_data(site)
    entered = m["attendance_entered"]
    by_trade = sorted(
        [{"trade": c["name"], "count": c["present"] if entered else c["roster"]}
         for c in m["categories"]
         if (c["present"] if entered else c["roster"]) > 0],
        key=lambda x: -x["count"])
    return {"grand_total": m["present"] if entered else m["roster_total"],
            "by_trade": by_trade, "as_of": None, "source": "roster"}


def _dpr_manpower(payload):
    cats = {c.id: c for c in ManpowerCategory.objects.filter(list_type="DPR")}
    counts = payload.get("manpower", {}) or {}
    staff, labour, total = [], [], 0
    for cat in sorted(cats.values(), key=lambda c: (c.grp, c.sort_order)):
        n = int(counts.get(str(cat.id), 0) or 0)
        if n <= 0:
            continue
        total += n
        (staff if cat.grp == "STAFF" else labour).append([cat.name, n])
    return {"staff": staff, "labour": labour, "total": total}


def _dpr_json(doc, rev):
    payload = rev.payload or {}
    site = doc.site
    titles = {p.code: p.title for p in site.projects.all()}
    grouped, order = {}, []
    for row in payload.get("work_done", []):
        key = (row.get("project") or "").strip()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    order.sort(key=lambda k: k == "")            # General Works last
    work_groups, n = [], 0
    for key in order:
        rows = []
        for row in grouped[key]:
            n += 1
            rows.append({
                "no": n,
                "activity": row.get("activity", ""),
                "trade": row.get("trade", ""),
                "location": row.get("location", ""),
                "today": row.get("progress_today", ""),
                "todate": row.get("progress_todate", "")
                or row.get("progress_pct", ""),
                "remarks": row.get("remarks", ""),
                "off_programme": bool((row.get("project") or "").strip())
                and not row.get("activity_id"),
            })
        label = f"{key} — {titles[key]}" if key in titles \
            else (key or "General Works")
        work_groups.append({"label": label, "rows": rows})

    def rows(keys, src):
        return [{k: r.get(k, "") for k in keys} for r in payload.get(src, [])]

    photos = []
    for p in doc.attachments.filter(kind="PHOTO").order_by("id"):
        try:
            photos.append({"url": p.file.url, "caption": p.caption})
        except Exception:
            pass
    return {
        "type": "DPR", "title": "Daily Progress Report", "doc_no": doc.ref,
        "date": doc.doc_date.isoformat(),
        "day": doc.doc_date.strftime("%A"),
        "working_hours": payload.get("working_hours", ""),
        "weather_am": payload.get("weather_am", ""),
        "weather_pm": payload.get("weather_pm", ""),
        "site": site.name,
        "work_groups": work_groups,
        "manpower": _dpr_manpower(payload),
        "machinery": rows(("item", "nos", "remarks"), "machinery"),
        "materials": rows(("material", "unit", "opening", "received",
                           "consumed", "balance", "remarks"), "materials"),
        "photos": photos,
    }


def _dma_json(doc, rev):
    payload = rev.payload or {}
    tasks = payload.get("tasks", [])
    totals, total = {}, 0
    for t in tasks:
        try:
            w = int(t.get("workers") or 0)
        except (TypeError, ValueError):
            w = 0
        if w:
            key = (t.get("category") or "Unassigned").strip() or "Unassigned"
            totals[key] = totals.get(key, 0) + w
            total += w
    return {
        "type": "DMA", "title": "Daily Manpower Allocation", "doc_no": doc.ref,
        "date": doc.doc_date.isoformat(),
        "working_hours": payload.get("working_hours", ""),
        "based_on_tws": ", ".join(payload.get("tws_refs") or []),
        "tasks": [{"no": i + 1, "task": t.get("task", ""),
                   "project": t.get("project", "") or "General",
                   "location": t.get("location", ""),
                   "category": t.get("category", ""),
                   "workers": t.get("workers", ""),
                   "remarks": t.get("remarks", "")}
                  for i, t in enumerate(tasks)],
        "totals": sorted(totals.items()), "total": total,
        "notes": payload.get("notes", ""),
    }


def _tws_json(doc, rev):
    payload = rev.payload or {}
    cats = {c.id: c for c in ManpowerCategory.objects.filter(list_type="DPR")}
    counts = payload.get("manpower", {}) or {}
    manpower, total = [], 0
    for cat in sorted(cats.values(), key=lambda c: (c.grp, c.sort_order)):
        n = int(counts.get(str(cat.id), 0) or 0)
        if n:
            manpower.append([cat.name, n])
            total += n
    return {
        "type": "TWS", "title": "Tomorrow Work Schedule", "doc_no": doc.ref,
        "date": doc.doc_date.isoformat(),
        "working_hours": payload.get("working_hours", ""),
        "activities": [{"no": i + 1, "activity": a.get("activity", ""),
                        "project": a.get("project", "") or "General",
                        "location": a.get("location", ""),
                        "trade": a.get("trade", ""),
                        "remarks": a.get("remarks", "")}
                       for i, a in enumerate(payload.get("activities", []))],
        "manpower": manpower, "total": total,
        "access_support": payload.get("access_support", "") or "None.",
    }


def _lm_json(doc, rev):
    payload = rev.payload or {}
    items = []
    for i, line in enumerate(rev.lines.all()):
        items.append({
            "no": i + 1,
            "description": line.description or "",
            "unit": getattr(line, "unit", "") or "",
            "qty_loaded": _cell(getattr(line, "qty_loaded", None)),
            "qty_pending": _cell(getattr(line, "qty_pending", None)),
            "remarks": getattr(line, "remarks", "") or "",
        })
    return {
        "type": "LM", "title": "Loading Manifest", "doc_no": doc.ref,
        "date": doc.doc_date.isoformat(),
        "vessel": payload.get("vessel", ""),
        "departure": payload.get("departure_point", ""),
        "arrival": payload.get("expected_arrival", ""),
        "trip": payload.get("trip_no", ""),
        "items": items,
    }


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) or hasattr(v, "is_integer"):
        f = float(v)
        return f"{f:,.2f}".rstrip("0").rstrip(".")
    return str(v)


_BUILDERS = {"DPR": _dpr_json, "DMA": _dma_json, "TWS": _tws_json,
             "LM": _lm_json}


def report_json(doc, rev):
    """Client-safe structured content for a report, or None for a type the
    portal doesn't render."""
    builder = _BUILDERS.get(doc.doc_type)
    return builder(doc, rev) if builder else None

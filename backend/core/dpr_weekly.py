"""Site report over a date range, rolled up from the daily ones.

Any range, not only a week: a client asks for the week, but a monthly
summary, a fortnight, or the stretch since the last site meeting are the same
document over different dates (owner 2026-08-31). The default is still the
current Saturday-to-Friday week, so the button means what it always did.

The client asks for it every week and the sites have been typing it out by
hand from their own DPRs — a week's worth of figures already sitting in the
system, re-keyed into a document (owner 2026-08-31).

Nothing here is a new fact. Every number is read from the issued DPRs of the
week, so the weekly and the dailies cannot disagree: if a figure looks wrong
the DPR behind it is named, and that is the record to correct.

Days with no DPR are reported as missing rather than skipped. A week that
quietly averages five days as though it were seven flatters the site, and the
client is the one person certain to notice the gap.
"""
import logging
from collections import OrderedDict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Document, ManpowerCategory

log = logging.getLogger(__name__)

# Issued or verified: a draft is the site's working copy, not a report.
REPORTED = ("ISSUED", "VERIFIED")

WEATHER_ORDER = ["Sunny", "Cloudy", "Rainy", "Stormy"]


def week_window(on=None):
    """Saturday to Friday — the Maldivian working week, the same window the
    unit-progress report uses."""
    today = timezone.localdate()
    day = on or today
    start = day - timedelta(days=(day.isoweekday() - 6) % 7)
    end = min(start + timedelta(days=6), today if day >= today else
              start + timedelta(days=6))
    return start, end


def _num(v):
    try:
        return float(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(v):
    return int(round(_num(v)))


def dprs_for(site, start, end, project=None):
    docs = (Document.objects.filter(doc_type="DPR", site=site,
                                    doc_date__gte=start, doc_date__lte=end,
                                    status__in=REPORTED, is_void=False)
            .select_related("current_revision").order_by("doc_date"))
    if project is not None:
        # NOT project__in=[project, None]: that renders as IN (1, NULL), and
        # SQL never matches NULL by equality — so every site-wide DPR, which
        # is most of them, silently vanished from the week.
        docs = docs.filter(Q(project=project) | Q(project__isnull=True))
    return list(docs)


def _payload(doc):
    return (doc.current_revision.payload or {}) if doc.current_revision_id \
        else {}


def coverage(docs, start, end):
    """Which days of the week were reported, and which were not."""
    have = {d.doc_date: d for d in docs}
    days = []
    day = start
    while day <= end:
        d = have.get(day)
        days.append({"date": day, "weekday": day.strftime("%a"),
                     "ref": d.ref if d else "", "missing": d is None})
        day += timedelta(days=1)
    return days


def manpower(docs, project=None):
    """Daily headcount by category, plus the week's man-days.

    The DPR keys manpower by category id, so the names are resolved here and
    only the categories that actually appeared are shown."""
    cats = {c.id: c for c in ManpowerCategory.objects.filter(list_type="DPR")}
    by_cat, per_day = OrderedDict(), []
    for doc in docs:
        counts = _payload(doc).get("manpower") or {}
        total = 0
        for raw, n in counts.items():
            try:
                cat = cats.get(int(raw))
            except (TypeError, ValueError):
                cat = None
            if cat is None:
                continue
            v = _int(n)
            if v <= 0:
                continue
            by_cat.setdefault(cat.id, {"name": cat.name, "grp": cat.grp,
                                       "sort": cat.sort_order, "days": {},
                                       "total": 0})
            by_cat[cat.id]["days"][doc.doc_date] = v
            by_cat[cat.id]["total"] += v
            total += v
        per_day.append({"date": doc.doc_date, "ref": doc.ref, "total": total})
    rows = sorted(by_cat.values(), key=lambda r: (r["grp"], r["sort"]))
    totals = [d["total"] for d in per_day]
    return {
        "rows": rows, "per_day": per_day,
        "man_days": sum(totals),
        "peak": max(totals) if totals else 0,
        "peak_on": (per_day[totals.index(max(totals))]["date"]
                    if totals else None),
        "low": min(totals) if totals else 0,
        "average": round(sum(totals) / len(totals), 1) if totals else 0,
    }


def work_done(docs, project=None):
    """The range's activities, per unit, with the days each ran and where it
    got to.

    The team's own report is a table per villa — activity, start, finish,
    percent — and that is what a client reads: not what the trades were busy
    with, but where each pool has got to. Units are the spine; anything the
    DPR records without a unit falls to a "General" block at the end so it is
    not lost (owner 2026-08-31)."""
    from .models import ProjectUnit, UnitStage

    ids = {r.get("unit_id") for d in docs
           for r in (_payload(d).get("work_done") or []) if r.get("unit_id")}
    units = {str(u.id): u for u in ProjectUnit.objects.filter(
        id__in=[i for i in ids if str(i).isdigit()]).select_related("project")}
    stages = {str(st.id): st for st in UnitStage.objects.all()}

    blocks = OrderedDict()
    for doc in docs:
        for row in _payload(doc).get("work_done") or []:
            if project is not None and row.get("project") not in (
                    None, "", project.code):
                continue
            act = (row.get("activity") or "").strip()
            stage = stages.get(str(row.get("stage_id") or ""))
            label = act or (stage.name if stage else "")
            if not label:
                continue
            unit = units.get(str(row.get("unit_id") or ""))
            key = unit.ref if unit else "General"
            block = blocks.setdefault(key, {"unit": unit, "ref": key,
                                            "items": OrderedDict()})
            ik = (label.lower(), (row.get("location") or "").strip().lower())
            item = block["items"].setdefault(ik, {
                "activity": label, "stage": stage.name if stage else "",
                "location": (row.get("location") or "").strip(),
                "trade": (row.get("trade") or "").strip(),
                "days": [], "percent": None})
            item["days"].append(doc.doc_date)
            pct = row.get("progress_todate")
            if pct not in (None, ""):
                item["percent"] = _num(pct)      # the latest reported

    out = []
    for key, b in blocks.items():
        items = [{**i, "day_count": len(i["days"]),
                  "first": min(i["days"]), "last": max(i["days"])}
                 for i in b["items"].values()]
        out.append({"ref": key, "unit": b["unit"],
                    "name": b["unit"].name if b["unit"] else "",
                    "percent": (float(b["unit"].percent or 0)
                                if b["unit"] else None),
                    "items": items})
    # Units first, in reference order; anything unassigned last.
    out.sort(key=lambda b: (b["ref"] == "General", b["ref"]))
    return out


def weather(docs):
    """How the week went overhead, and the hours of rain."""
    tally, rain_hours, rain_days = OrderedDict(), 0.0, 0
    for doc in docs:
        p = _payload(doc)
        for slot in ("weather_am", "weather_pm"):
            w = (p.get(slot) or "").strip()
            if w:
                tally[w] = tally.get(w, 0) + 1
        hrs = _rain_hours(p.get("rain_from"), p.get("rain_to"))
        if hrs:
            rain_hours += hrs
            rain_days += 1
    order = {w: i for i, w in enumerate(WEATHER_ORDER)}
    rows = sorted(tally.items(), key=lambda kv: (order.get(kv[0], 99), kv[0]))
    return {"halves": rows, "rain_hours": round(rain_hours, 1),
            "rain_days": rain_days}


def _rain_hours(a, b):
    """Hours between two HH:MM stamps. A window that ends before it starts
    ran past midnight."""
    def mins(v):
        try:
            h, m = str(v).split(":")[:2]
            return int(h) * 60 + int(m)
        except (TypeError, ValueError):
            return None
    x, y = mins(a), mins(b)
    if x is None or y is None:
        return 0.0
    span = y - x
    if span < 0:
        span += 24 * 60
    return round(span / 60.0, 2)


def man_hours(docs):
    """Attendance × the day's working hours, and the period's total.

    The team's own weekly report carries this table and computes it by hand
    from the same dailies (owner 2026-08-31). Working hours are read from the
    DPR's own "07:00 – 22:00" line, so if a figure looks wrong the report
    behind it is the one to correct."""
    rows, total = [], 0.0
    for doc in docs:
        p = _payload(doc)
        counts = (p.get("manpower") or {}).values()
        heads = sum(_int(v) for v in counts)
        hrs = _span_hours(p.get("working_hours"))
        mh = round(heads * hrs, 1)
        total += mh
        rows.append({"date": doc.doc_date, "ref": doc.ref, "heads": heads,
                     "hours": hrs, "man_hours": mh,
                     "window": (p.get("working_hours") or "").strip()})
    return {"rows": rows, "total": round(total, 1)}


def _span_hours(window):
    """Hours in a "07:00 – 22:00" working window. Any dash will do, and a
    window that ends before it starts ran past midnight."""
    if not window:
        return 0.0
    text = str(window)
    for dash in ("–", "—", "-", "to"):
        if dash in text:
            a, _, b = text.partition(dash)
            return _rain_hours(a.strip(), b.strip())
    return 0.0


def time_lost(docs):
    rows = []
    for doc in docs:
        p = _payload(doc)
        hrs = _num(p.get("work_time_lost"))
        cause = (p.get("time_lost_cause") or "").strip()
        reason = (p.get("time_lost_reason") or "").strip()
        if hrs or cause or reason:
            rows.append({"date": doc.doc_date, "ref": doc.ref, "hours": hrs,
                         "cause": cause, "reason": reason})
    return {"rows": rows, "hours": round(sum(r["hours"] for r in rows), 1)}


def safety(docs):
    rows = []
    for doc in docs:
        s = _payload(doc).get("safety") or {}
        if s.get("incident"):
            rows.append({"date": doc.doc_date, "ref": doc.ref,
                         "details": (s.get("details") or "").strip()})
    return rows


def notes(docs):
    """Matters affecting progress, and anything the client's team instructed
    on site — the two the client reads first."""
    out = []
    for doc in docs:
        p = _payload(doc)
        for key, label in (("matters_affecting", "Matters affecting progress"),
                           ("visitors_instructions", "Visitors / instructions")):
            text = (p.get(key) or "").strip()
            if text:
                out.append({"date": doc.doc_date, "ref": doc.ref,
                            "label": label, "text": text})
    return out


MAX_PHOTOS = 24


def resolve_range(start=None, end=None, on=None):
    """The range to report on, and whether it is a plain week.

    Given explicit dates, they win. Given nothing, the current Saturday-to-
    Friday week — so the weekly button keeps its meaning."""
    if start or end:
        a = start or end
        b = end or start
        if b < a:
            a, b = b, a
        return a, b
    return week_window(on)


def photos(docs, limit=MAX_PHOTOS):
    """Progress photos from the range's daily reports.

    Capped: a fortnight at a busy site runs to a hundred, and a client report
    that takes a minute to open is one nobody opens. The count of what was
    left out is shown rather than quietly dropped."""
    from .models import Attachment

    rows = (Attachment.objects.filter(document__in=docs, kind="PHOTO")
            .select_related("document").order_by("document__doc_date", "id"))
    total = rows.count()
    out = []
    for a in rows[:limit]:
        try:
            src = f"file:///{a.file.path}"      # filesystem storage
        except (NotImplementedError, ValueError):
            src = a.file.url                    # S3: the engine fetches it
        out.append({"src": src, "caption": a.caption,
                    "date": a.document.doc_date, "ref": a.document.ref})
    return {"items": out, "total": total,
            "omitted": max(total - len(out), 0)}


def programme(project, end):
    """The planned programme, summarised — the top of the WBS with its dates
    and where each part has got to.

    The team's report opens with this, and it is the frame a client reads the
    rest against: not "what happened", but "what was meant to happen by now".
    Only the top two outline levels; the detail is the programme itself."""
    if project is None:
        return []
    from .models import ProgrammeActivity

    rows = []
    for a in (ProgrammeActivity.objects.filter(project=project, indent__lte=1)
              .order_by("sort_order")):
        pct = float(a.progress or 0)
        late = bool(a.finish and a.finish < end and pct < 100)
        due = bool(a.start and a.start <= end and pct <= 0)
        rows.append({
            "name": a.name, "indent": a.indent,
            "milestone": a.is_milestone,
            "start": a.start, "finish": a.finish,
            "percent": pct,
            "state": ("Complete" if pct >= 100
                      else "Overdue" if late
                      else "Not started" if due
                      else "In progress" if pct > 0
                      else "Upcoming"),
        })
    return rows


def build(site, on=None, project=None, start=None, end=None,
          with_photos=True):
    start, end = resolve_range(start, end, on)
    docs = dprs_for(site, start, end, project=project)
    days = coverage(docs, start, end)
    mp = manpower(docs, project=project)
    # Lay each category's week out as a list aligned to `days`, so the
    # template walks two lists in step instead of reaching into a dict by
    # date — which Django templates cannot do without a custom tag.
    for row in mp["rows"]:
        row["cells"] = [row["days"].get(d["date"]) for d in days]
    return {
        "site": site, "project": project,
        "start": start, "end": end,
        "days": days,
        "reported": len(docs), "expected": len(days),
        "missing": [d for d in days if d["missing"]],
        "manpower": mp,
        "work_done": work_done(docs, project=project),
        "programme": programme(project, end),
        "weather": weather(docs),
        "time_lost": time_lost(docs),
        "safety": safety(docs),
        "notes": notes(docs),
        "manpower_chart": manpower_chart(mp),
        "designation_chart": designation_chart(mp, days),
        "man_hours": man_hours(docs),
        "photos": photos(docs) if with_photos else {"items": [], "total": 0,
                                                    "omitted": 0},
        "days_covered": (end - start).days + 1,
        "is_week": (end - start).days == 6 and start.isoweekday() == 6,
    }


# ---- chart (inline SVG; WeasyPrint runs no JavaScript) -------------------

NAVY = "#10344F"
SKY = "#1685CC"
LINE = "#D8E3EC"
GREY = "#8A94A0"


def manpower_chart(mp, width=740, height=175):
    """Men on site each day, with the week's average as a rule across it."""
    days = mp["per_day"]
    if not days:
        return ""
    # Headroom above the tallest bar so the value labels and the average
    # rule are not printed on top of each other. The baseline stays at zero:
    # a headcount chart that starts anywhere else exaggerates the variation.
    peak = max(max(d["total"] for d in days), 1)
    top = peak * 1.18
    left, bottom = 36, 26
    right = 52                      # room for the average label, off the plot
    plot_w = width - left - right
    plot_h = height - bottom - 16
    step = plot_w / len(days)
    bar_w = min(step * 0.52, 40)
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Helvetica, Arial, sans-serif">']
    for g in (0, 0.5, 1):
        y = 16 + plot_h * (1 - g * peak / top)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" '
                   f'y2="{y:.1f}" stroke="{LINE}" stroke-width="0.6"/>')
        out.append(f'<text x="{left - 6}" y="{y + 3.5:.1f}" font-size="8" '
                   f'fill="{GREY}" text-anchor="end">{int(peak * g)}</text>')
    for i, d in enumerate(days):
        h = plot_h * d["total"] / top
        x = left + i * step + (step - bar_w) / 2
        y = 16 + plot_h - h
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                   f'height="{h:.1f}" fill="{SKY}" rx="2"/>')
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 4:.1f}" '
                   f'font-size="8.5" font-weight="bold" fill="{NAVY}" '
                   f'text-anchor="middle">{d["total"]}</text>')
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 10}" '
                   f'font-size="8" fill="{GREY}" text-anchor="middle">'
                   f'{d["date"].strftime("%a %-d")}</text>')
    avg = mp["average"]
    if avg:
        y = 16 + plot_h * (1 - avg / top)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" '
                   f'y2="{y:.1f}" stroke="{NAVY}" stroke-width="0.9" '
                   f'stroke-dasharray="4 3"/>')
        # In the right margin, clear of the bars and their value labels.
        out.append(f'<text x="{left + plot_w + 6}" y="{y + 3:.1f}" '
                   f'font-size="8" fill="{NAVY}">avg {avg}</text>')
    out.append("</svg>")
    return "".join(out)


# A dozen distinguishable hues. The team's own report colours every
# designation separately, and a client reads the shape of the crew from it.
SERIES = ["#1685CC", "#1A7F37", "#E8703A", "#E8B93A", "#8A63D2", "#E86AA6",
          "#2FA8B8", "#7A8B99", "#B02418", "#4C6EF5", "#12897A", "#C77DFF"]


def designation_chart(mp, days, width=740, height=225):
    """Men per day, split by designation — the shape of the crew.

    Grouped bars rather than a stack: a client comparing Tuesday's masons to
    Wednesday's wants two bars side by side, not two segments at different
    heights up a column."""
    rows = [r for r in mp["rows"] if r["total"]]
    if not rows or not days:
        return ""
    top = max((max(r["cells"] or [0], key=lambda v: v or 0) or 0)
              for r in rows) or 1
    left, bottom = 34, 62
    plot_w = width - left - 10
    plot_h = height - bottom - 12
    group = plot_w / len(days)
    # Fill the group rather than leaving hairlines: with a handful of trades
    # the bars should read as bars.
    bar = max(min((group - 8) / len(rows), 16), 2.5)

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Helvetica, Arial, sans-serif">']
    for g in (0, 0.5, 1):
        y = 10 + plot_h * (1 - g)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - 8}" '
                   f'y2="{y:.1f}" stroke="{LINE}" stroke-width="0.6" '
                   f'stroke-dasharray="3 3"/>')
        out.append(f'<text x="{left - 5}" y="{y + 3.5:.1f}" font-size="8" '
                   f'fill="{GREY}" text-anchor="end">{int(top * g)}</text>')
    for di, day in enumerate(days):
        x0 = left + di * group
        span = bar * len(rows)
        for ri, r in enumerate(rows):
            v = r["cells"][di] or 0
            if not v:
                continue
            h = plot_h * v / top
            x = x0 + (group - span) / 2 + ri * bar
            out.append(f'<rect x="{x:.1f}" y="{10 + plot_h - h:.1f}" '
                       f'width="{bar - 0.8:.1f}" height="{h:.1f}" '
                       f'fill="{SERIES[ri % len(SERIES)]}" rx="1"/>')
        out.append(f'<text x="{x0 + group / 2:.1f}" y="{10 + plot_h + 13:.1f}" '
                   f'font-size="8" fill="{GREY}" text-anchor="middle">'
                   f'{day["date"].strftime("%-d %b")}</text>')
    # Legend, wrapped across the foot.
    lx, ly = left, 10 + plot_h + 31
    for ri, r in enumerate(rows):
        label = r["name"][:24]
        w = 12 + len(label) * 4.6 + 14
        if lx + w > width - 4:
            lx, ly = left, ly + 13
        out.append(f'<rect x="{lx:.1f}" y="{ly - 6.5:.1f}" width="7" '
                   f'height="7" rx="1.5" '
                   f'fill="{SERIES[ri % len(SERIES)]}"/>')
        out.append(f'<text x="{lx + 11:.1f}" y="{ly:.1f}" font-size="8" '
                   f'fill="{NAVY}">{_esc(label)}</text>')
        lx += w
    out.append("</svg>")
    return "".join(out)


def _esc(v):
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))

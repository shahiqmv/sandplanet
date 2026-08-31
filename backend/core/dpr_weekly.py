"""Weekly site report, rolled up from the daily ones.

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
    """The week's activities, grouped by trade, each with the days it ran.

    An activity repeated all week is one line saying so, not seven — a client
    reading a weekly report wants the shape of the week, and the dailies are
    there for the detail."""
    trades = OrderedDict()
    for doc in docs:
        for row in _payload(doc).get("work_done") or []:
            if project is not None and row.get("project") not in (
                    None, "", project.code):
                continue
            trade = (row.get("trade") or "General").strip() or "General"
            act = (row.get("activity") or "").strip()
            if not act:
                continue
            loc = (row.get("location") or "").strip()
            key = (act.lower(), loc.lower())
            block = trades.setdefault(trade, OrderedDict())
            item = block.setdefault(key, {"activity": act, "location": loc,
                                          "days": [], "refs": []})
            item["days"].append(doc.doc_date)
            item["refs"].append(doc.ref)
    return [{"trade": t,
             "items": [{**i, "day_count": len(i["days"]),
                        "first": min(i["days"]), "last": max(i["days"])}
                       for i in items.values()]}
            for t, items in trades.items()]


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


def machinery(docs):
    """Plant on site — the most any day carried, since the daily return is a
    count of what stood on site, not a delivery."""
    seen = OrderedDict()
    for doc in docs:
        for row in _payload(doc).get("machinery") or []:
            item = (row.get("item") or "").strip()
            if not item:
                continue
            n = _int(row.get("nos"))
            cur = seen.setdefault(item, {"item": item, "nos": 0,
                                         "remarks": ""})
            cur["nos"] = max(cur["nos"], n)
            note = (row.get("remarks") or "").strip()
            if note and note not in cur["remarks"]:
                cur["remarks"] = (cur["remarks"] + "; " + note).strip("; ")
    return list(seen.values())


def materials(docs):
    """Opening at the start of the week, what came in, what was used, and the
    closing balance — the movement, not seven snapshots."""
    rows = OrderedDict()
    for doc in docs:
        for r in _payload(doc).get("materials") or []:
            name = (r.get("material") or "").strip()
            if not name:
                continue
            cur = rows.get(name)
            if cur is None:
                cur = rows[name] = {"material": name,
                                    "unit": (r.get("unit") or "").strip(),
                                    "opening": _num(r.get("opening")),
                                    "received": 0.0, "consumed": 0.0,
                                    "balance": _num(r.get("balance"))}
            cur["received"] += _num(r.get("received"))
            cur["consumed"] += _num(r.get("consumed"))
            cur["balance"] = _num(r.get("balance"))   # the latest day's
    return [r for r in rows.values()
            if r["received"] or r["consumed"] or r["opening"] or r["balance"]]


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


def build(site, on=None, project=None):
    start, end = week_window(on)
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
        "weather": weather(docs),
        "machinery": machinery(docs),
        "materials": materials(docs),
        "time_lost": time_lost(docs),
        "safety": safety(docs),
        "notes": notes(docs),
        "manpower_chart": manpower_chart(mp),
    }


# ---- chart (inline SVG; WeasyPrint runs no JavaScript) -------------------

NAVY = "#10344F"
SKY = "#1685CC"
LINE = "#D8E3EC"
GREY = "#8A94A0"


def manpower_chart(mp, width=740, height=150):
    """Men on site each day, with the week's average as a rule across it."""
    days = mp["per_day"]
    if not days:
        return ""
    top = max(max(d["total"] for d in days), 1)
    left, bottom = 34, 22
    plot_w = width - left - 8
    plot_h = height - bottom - 12
    step = plot_w / len(days)
    bar_w = min(step * 0.6, 46)
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Helvetica, Arial, sans-serif">']
    for g in (0, 0.5, 1):
        y = 12 + plot_h * (1 - g)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - 8}" '
                   f'y2="{y:.1f}" stroke="{LINE}" stroke-width="0.6"/>')
        out.append(f'<text x="{left - 5}" y="{y + 3:.1f}" font-size="7" '
                   f'fill="{GREY}" text-anchor="end">{int(top * g)}</text>')
    for i, d in enumerate(days):
        h = plot_h * d["total"] / top
        x = left + i * step + (step - bar_w) / 2
        y = 12 + plot_h - h
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                   f'height="{h:.1f}" fill="{SKY}" rx="2"/>')
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 3:.1f}" '
                   f'font-size="7.5" fill="{NAVY}" text-anchor="middle">'
                   f'{d["total"]}</text>')
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" '
                   f'font-size="7.5" fill="{GREY}" text-anchor="middle">'
                   f'{d["date"].strftime("%a")}</text>')
    avg = mp["average"]
    if avg:
        y = 12 + plot_h * (1 - avg / top)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - 8}" '
                   f'y2="{y:.1f}" stroke="{NAVY}" stroke-width="0.9" '
                   f'stroke-dasharray="4 3"/>')
        out.append(f'<text x="{width - 10}" y="{y - 3:.1f}" font-size="7" '
                   f'fill="{NAVY}" text-anchor="end">avg {avg}</text>')
    out.append("</svg>")
    return "".join(out)

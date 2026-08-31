"""Weekly unit-progress report — the one clients ask for.

The board answers "where is V211 now". A client asks "what moved this week",
which is a different question and needs history: UnitProgressEvent, written
as each figure is reported.

Charts are inline SVG built here rather than drawn in the browser, because
WeasyPrint renders HTML and CSS but runs no JavaScript — a chart library
would produce an empty box in the PDF. SVG also scales cleanly at print
resolution, which a canvas bitmap does not.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import UnitProgressEvent

log = logging.getLogger(__name__)

ZERO = Decimal("0")

# House colours, matching the letterhead rules.
NAVY = "#10344F"
SKY = "#1685CC"
LINE = "#D8E3EC"
GREY = "#8A94A0"
GREEN = "#1A7F37"
BAND = "#EEF4F9"


def week_window(week_ending=None):
    """The seven days ending on `week_ending` (default: today)."""
    end = week_ending or timezone.localdate()
    return end - timedelta(days=6), end


def _pct(v):
    return float(v or 0)


def unit_rows(project, start, end):
    """Every unit, where it is now and where it was before the week began."""
    units = list(project.units.select_related("category")
                 .prefetch_related("stage_progress__stage").order_by("ref"))
    # One query for the whole project's history, then bucketed in memory —
    # a per-unit query would be 17 round trips for 17 pools.
    events = list(UnitProgressEvent.objects.filter(
        unit__project=project, on__lte=end).select_related("stage")
        .order_by("on", "id"))
    before, during = {}, {}
    for e in events:
        key = (e.unit_id, e.stage_id)
        if e.on < start:
            before[key] = e.percent
        else:
            during.setdefault(key, e.previous)   # first move of the week

    rows = []
    for u in units:
        stages = list(u.stage_progress.all())
        now = _unit_percent(u, {s.stage_id: s.percent for s in stages})
        was_map = {}
        for s in stages:
            key = (u.id, s.stage_id)
            if key in during:
                was_map[s.stage_id] = during[key]
            elif key in before:
                was_map[s.stage_id] = before[key]
            else:
                # No history at all: assume it stood where it stands now, so
                # the week shows no movement rather than inventing a jump
                # from zero on the day history started.
                was_map[s.stage_id] = s.percent
        was = _unit_percent(u, was_map)
        rows.append({
            "ref": u.ref, "unit": u,
            "milestone": _milestone(u, stages),
            "now": now, "was": was, "moved": round(now - was, 1),
            "status": u.status,
            "started_on": u.started_on, "completed_on": u.completed_on,
            "last_reported": max((s.updated_on for s in stages
                                  if s.updated_on), default=None),
        })
    return rows


def _unit_percent(unit, by_stage):
    """A unit's overall percent from its stage figures, weighted as the board
    weights them."""
    stages = list(unit.project.unit_stages.all()) or []
    if unit.category_id:
        cat_stages = [s for s in stages if s.category_id == unit.category_id]
        if cat_stages:
            stages = cat_stages
    if not stages:
        return 0.0
    total_w = sum(float(s.weight or 1) for s in stages) or 1.0
    got = sum(float(s.weight or 1) * _pct(by_stage.get(s.id, ZERO)) / 100.0
              for s in stages)
    return round(got / total_w * 100.0, 1)


def _milestone(unit, stages):
    """The stage the unit is working on now — the furthest one started but
    not finished, else the last one finished."""
    done = [s for s in stages if _pct(s.percent) >= 100]
    live = [s for s in stages if 0 < _pct(s.percent) < 100]
    if live:
        return sorted(live, key=lambda s: s.stage.sort_order)[-1].stage.name
    if done:
        return sorted(done, key=lambda s: s.stage.sort_order)[-1].stage.name
    return "Not started"


def summary(project, rows, start, end):
    total = len(rows)
    complete = sum(1 for r in rows if r["status"] == "COMPLETE")
    now = round(sum(r["now"] for r in rows) / total, 1) if total else 0.0
    was = round(sum(r["was"] for r in rows) / total, 1) if total else 0.0
    moved_rows = [r for r in rows if r["moved"] > 0]
    return {
        "units": total, "complete": complete,
        "overall_now": now, "overall_was": was,
        "overall_moved": round(now - was, 1),
        "moved_count": len(moved_rows),
        "still_count": total - len(moved_rows),
        "started_this_week": sum(
            1 for r in rows
            if r["started_on"] and start <= r["started_on"] <= end),
        "completed_this_week": sum(
            1 for r in rows
            if r["completed_on"] and start <= r["completed_on"] <= end),
        "best": sorted(rows, key=lambda r: -r["moved"])[:3],
    }


# ---- charts (inline SVG; WeasyPrint runs no JavaScript) ------------------

def bar_chart(rows, width=760, row_h=17):
    """One horizontal bar per unit: where it stands, with the week's movement
    shown as a lighter segment on the end, so a client sees position and
    progress in the same glance."""
    if not rows:
        return ""
    h = len(rows) * row_h + 26
    label_w, right = 54, 46
    plot = width - label_w - right
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" '
           f'xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Helvetica, Arial, sans-serif">']
    # Grid every 25%, drawn behind the bars.
    for g in range(0, 101, 25):
        x = label_w + plot * g / 100
        out.append(f'<line x1="{x:.1f}" y1="16" x2="{x:.1f}" y2="{h - 10}" '
                   f'stroke="{LINE}" stroke-width="0.6"/>')
        out.append(f'<text x="{x:.1f}" y="11" font-size="7" fill="{GREY}" '
                   f'text-anchor="middle">{g}%</text>')
    for i, r in enumerate(rows):
        y = 22 + i * row_h
        was_w = plot * max(r["was"], 0) / 100
        now_w = plot * max(r["now"], 0) / 100
        out.append(f'<text x="0" y="{y + 8}" font-size="8" fill="{NAVY}" '
                   f'font-weight="bold">{r["ref"]}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{plot:.1f}" '
                   f'height="10" fill="{BAND}" rx="2"/>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{was_w:.1f}" '
                   f'height="10" fill="{NAVY}" rx="2"/>')
        if now_w > was_w:
            out.append(f'<rect x="{label_w + was_w:.1f}" y="{y}" '
                       f'width="{now_w - was_w:.1f}" height="10" '
                       f'fill="{SKY}" rx="2"/>')
        out.append(f'<text x="{width - right + 4}" y="{y + 8}" font-size="8" '
                   f'fill="{NAVY}">{r["now"]:.0f}%</text>')
        if r["moved"] > 0:
            out.append(f'<text x="{width - 6}" y="{y + 8}" font-size="7" '
                       f'fill="{GREEN}" text-anchor="end">'
                       f'+{r["moved"]:.0f}</text>')
    out.append("</svg>")
    return "".join(out)


def milestone_chart(rows, width=760, bar_h=26):
    """How many units sit at each milestone — where the work is bunched."""
    counts = {}
    for r in rows:
        counts[r["milestone"]] = counts.get(r["milestone"], 0) + 1
    if not counts:
        return ""
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    h = len(items) * bar_h + 10
    label_w = 200
    plot = width - label_w - 30
    top = max(c for _, c in items) or 1
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" '
           f'xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Helvetica, Arial, sans-serif">']
    for i, (name, n) in enumerate(items):
        y = i * bar_h + 4
        w = plot * n / top
        out.append(f'<text x="0" y="{y + 13}" font-size="8.5" fill="{NAVY}">'
                   f'{_esc(name)[:38]}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 3}" width="{w:.1f}" '
                   f'height="14" fill="{SKY}" rx="2"/>')
        out.append(f'<text x="{label_w + w + 5:.1f}" y="{y + 14}" '
                   f'font-size="8.5" fill="{NAVY}" font-weight="bold">'
                   f'{n}</text>')
    out.append("</svg>")
    return "".join(out)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def build(project, week_ending=None):
    start, end = week_window(week_ending)
    rows = unit_rows(project, start, end)
    return {
        "project": project, "site": project.site,
        "start": start, "end": end,
        "rows": rows,
        "summary": summary(project, rows, start, end),
        "bar_chart": bar_chart(rows),
        "milestone_chart": milestone_chart(rows),
    }

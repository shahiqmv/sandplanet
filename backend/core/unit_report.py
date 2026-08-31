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


def week_window(on=None):
    """The Maldivian working week containing `on`: Saturday to Friday.

    The site working week is Saturday to Thursday with Friday the rest day,
    so a week anchored anywhere else splits every site's week in two. This
    was a rolling seven days ending today — anchored to no weekday at all,
    so a report run on a Monday covered Tuesday to Monday and straddled two
    weeks (owner 2026-08-31).

    Clipped to today: a report never covers days that have not happened."""
    today = timezone.localdate()
    day = on or today
    # isoweekday: Mon=1 … Sat=6, Sun=7. Days back to this week's Saturday.
    start = day - timedelta(days=(day.isoweekday() - 6) % 7)
    end = min(start + timedelta(days=6), max(day, start))
    if end > today:
        end = today
    return start, end


def week_is_complete(start, end):
    """Whether the week has run its course — a client should be told when a
    figure is a week to date rather than a full week."""
    return (end - start).days >= 6


def _pct(v):
    return float(v or 0)


def unit_rows(project, start, end):
    """Every unit, where it is now and where it was before the week began."""
    units = list(project.units.select_related("category")
                 .prefetch_related("stage_progress__stage").order_by("ref"))
    # One query for the whole project's history, then bucketed in memory —
    # a per-unit query would be 17 round trips for 17 pools.
    events = list(UnitProgressEvent.objects.filter(
        unit__project=project, on__lte=end).select_related("stage", "source")
        .order_by("on", "id"))
    before, during = {}, {}
    # Where this week's movement came from. The teams report through the DPR
    # where a programme activity maps onto a unit stage, and edit the board
    # by hand where it does not — so a client-facing figure should say which
    # of the two moved it, and a PM should be able to see at a glance how
    # much of a week was adjusted rather than reported (owner 2026-08-31).
    moved_by = {}
    for e in events:
        key = (e.unit_id, e.stage_id)
        if e.on < start:
            before[key] = e.percent
        else:
            during.setdefault(key, e.previous)   # first move of the week
            if e.percent != e.previous:          # an opening balance is not
                m = moved_by.setdefault(e.unit_id,                # a movement
                                        {"dprs": set(), "manual": 0})
                if e.source_id:
                    m["dprs"].add(e.source.ref)
                else:
                    m["manual"] += 1

    rows = []
    for u in units:
        stages = list(u.stage_progress.all())
        # The board's stored figure, not a recomputation of it: the client
        # sees this number on the portal and must see the same one here.
        now = round(float(u.percent or 0), 1)
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
        src = moved_by.get(u.id)
        rows.append({
            "ref": u.ref, "unit": u,
            "moved_by_dprs": sorted(src["dprs"]) if src else [],
            "moved_by_manual": src["manual"] if src else 0,
            "source_label": _source_label(src),
            "milestone": _milestone(u, stages),
            "now": now, "was": was, "moved": round(now - was, 1),
            "status": u.status,
            "started_on": u.started_on, "completed_on": u.completed_on,
            "last_reported": max((s.updated_on for s in stages
                                  if s.updated_on), default=None),
        })
    return rows


def _source_label(src):
    """Plain words for who moved a unit this week."""
    if not src:
        return ""
    bits = []
    if src["dprs"]:
        bits.append(", ".join(sorted(src["dprs"])))
    if src["manual"]:
        bits.append(f"{src['manual']} manual "
                    f"adjustment{'' if src['manual'] == 1 else 's'}")
    return " · ".join(bits)


def _unit_percent(unit, by_stage):
    """A unit's overall percent from a set of stage figures.

    Deliberately the same arithmetic as units.recalc — weight-averaged over
    the unit's own stages — because this figure sits next to the board's in a
    client's hands. Two ways of averaging the same numbers is how a PDF ends
    up saying 30% while the portal says 28% (owner 2026-08-31)."""
    from .units import stages_for

    stages = stages_for(unit)
    total_w = sum(float(s.weight or 0) for s in stages)
    if total_w <= 0:
        return 0.0
    got = sum(_pct(by_stage.get(s.id, ZERO)) * float(s.weight or 0)
              for s in stages)
    return round(got / total_w, 1)


def _milestone(unit, stages):
    """What the unit is working on: the first stage not yet finished.

    The board's own rule — "what has to be done next" — not "the furthest
    thing touched". They disagree whenever a later stage starts before an
    earlier one finishes, which on a pool is most of the time."""
    from .units import stages_for

    done = {s.stage_id: s.percent for s in stages}
    for st in stages_for(unit):
        pc = done.get(st.id)
        if pc is None or _pct(pc) < 100:
            return st.name
    return "Complete" if stages else "Not started"


def summary(project, rows, start, end):
    total = len(rows)
    complete = sum(1 for r in rows if r["status"] == "COMPLETE")
    now = round(sum(r["now"] for r in rows) / total, 1) if total else 0.0
    was = round(sum(r["was"] for r in rows) / total, 1) if total else 0.0
    moved_rows = [r for r in rows if r["moved"] > 0]
    by_dpr = sum(1 for r in moved_rows if r["moved_by_dprs"])
    by_hand = sum(1 for r in moved_rows
                  if r["moved_by_manual"] and not r["moved_by_dprs"])
    return {
        "moved_by_dpr": by_dpr, "moved_by_hand": by_hand,
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
        "complete_week": week_is_complete(start, end),
        "days_covered": (end - start).days + 1,
        "rows": rows,
        "summary": summary(project, rows, start, end),
        "bar_chart": bar_chart(rows),
        "milestone_chart": milestone_chart(rows),
    }

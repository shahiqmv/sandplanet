"""Site progress analysis: where each project stands against its programme
(owner 2026-11-07).

Progress is the programme's own measure (programme_overall_progress, or the
PM's override where one is set), and the rating is the one the portfolio
dashboard already uses: on track within 10 points of the time elapsed, watch
within 25, attention beyond. Progress is as reported now; time elapsed is
measured at the end of the period.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count

from .models import Attendance, Document, ExtensionOfTime, Project
from .reports import col, kpi, section
from .views_projects import programme_overall_progress

RATING = {"on_track": "On track", "watch": "Watch", "attention": "Attention",
          "info": "—"}
LIVE = ("AWARDED", "ACTIVE", "ON_HOLD")


def _progress(p):
    if p.progress_override is not None:
        return float(p.progress_override)
    return programme_overall_progress(p)


def _rating(p, progress, elapsed):
    if p.status != "ACTIVE" or elapsed is None or progress is None:
        return "info"
    if progress >= elapsed - 10:
        return "on_track"
    if progress >= elapsed - 25:
        return "watch"
    return "attention"


def build(ctx):
    on = ctx.end
    projects = (Project.objects.filter(site_id__in=ctx.site_ids,
                                       status__in=LIVE)
                .select_related("site", "pm")
                .prefetch_related("activities").order_by("site__code", "code"))
    rows, milestones = [], []
    counts = {"on_track": 0, "watch": 0, "attention": 0, "info": 0}
    for p in projects:
        progress = _progress(p)
        elapsed = None
        if p.start_date and p.planned_completion \
                and p.planned_completion > p.start_date:
            elapsed = 100 * (on - p.start_date).days / (
                p.planned_completion - p.start_date).days
            elapsed = round(max(min(elapsed, 100), 0), 1)
        eot = (ExtensionOfTime.objects.filter(
            project=p, revised_completion__isnull=False,
            decided_on__isnull=False, days_awarded__gt=0)
            .order_by("-decided_on", "-id").first())
        completion = eot.revised_completion if eot else p.planned_completion
        rating = _rating(p, progress, elapsed)
        counts[rating] += 1
        missed = 0
        for a in p.activities.all():
            if not a.is_milestone or not a.finish:
                continue
            done = a.progress >= 100
            late = not done and a.finish < on
            due_now = ctx.start <= a.finish <= on
            soon = not done and on < a.finish <= on + timedelta(days=30)
            if late:
                missed += 1
            if late or due_now or soon:
                milestones.append({
                    "site": p.site.code, "project": p.code, "milestone": a.name,
                    "due": a.finish,
                    "state": ("Achieved" if done else "Missed" if late
                              else "Due in the next 30 days"),
                    "achieved": a.actual_finish,
                })
        rows.append({
            "site": p.site.code, "project": f"{p.code} — {p.title}",
            "status": p.get_status_display(),
            "pm": p.pm.full_name if p.pm else "",
            "start": p.start_date, "planned": p.planned_completion,
            "current": completion,
            "elapsed": elapsed, "progress": progress,
            "variance": (round(progress - elapsed, 1)
                         if progress is not None and elapsed is not None
                         else None),
            "rating": RATING[rating], "missed": missed,
            "dprs": Document.objects.filter(
                project=p, doc_type="DPR", is_void=False,
                doc_date__gte=ctx.start, doc_date__lte=on).count(),
        })

    milestones.sort(key=lambda m: ({"Missed": 0, "Due in the next 30 days": 1,
                                    "Achieved": 2}[m["state"]], m["due"]))
    manpower = _manpower(ctx)
    shown = [r["progress"] for r in rows if r["progress"] is not None]
    n_missed = sum(1 for m in milestones if m["state"] == "Missed")
    return {
        "kpis": [
            kpi("Live projects", len(rows), "int"),
            kpi("On track", counts["on_track"], "int",
                sub="within 10 points of time elapsed"),
            kpi("Watch", counts["watch"], "int", sub="10–25 points behind"),
            kpi("Attention", counts["attention"], "int",
                sub="more than 25 points behind"),
            kpi("Average progress", sum(shown) / len(shown) if shown else None,
                "pct"),
            kpi("Milestones missed", n_missed, "int",
                sub="past due, not complete"),
        ],
        "sections": [
            section("Projects", [
                col("site", "Site"), col("project", "Project", wide=True),
                col("status", "Status"), col("pm", "PM"),
                col("start", "Start", "date"),
                col("planned", "Contract completion", "date"),
                col("current", "Current completion", "date"),
                col("elapsed", "Time elapsed", "pct"),
                col("progress", "Progress", "pct"),
                col("variance", "Ahead (+) / behind (−)", "num"),
                col("rating", "Rating"), col("missed", "Milestones missed",
                                             "int"),
                col("dprs", "DPRs in period", "int"),
            ], rows, note="Current completion is the contract date, or the "
                          "date of the latest extension of time awarded."),
            section("Milestones", [
                col("site", "Site"), col("project", "Project", wide=True),
                col("milestone", "Milestone", wide=True), col("due", "Due", "date"),
                col("state", "Where it stands"),
                col("achieved", "Achieved on", "date"),
            ], milestones),
            manpower,
        ],
        "notes": [
            "Progress is as reported now; time elapsed is measured at "
            f"{on:%d %b %Y}.",
        ],
    }


def _manpower(ctx):
    """People present on site per day, from the attendance registers."""
    marks = (Attendance.objects.filter(
        site_id__in=ctx.site_ids, day__gte=ctx.start, day__lte=ctx.end,
        remark__in=("PRESENT", "HALF_DAY"))
        .values("site__code", "site__name", "day").annotate(n=Count("id")))
    by_site = {}
    for m in marks:
        s = by_site.setdefault(m["site__code"], {
            "site": f"{m['site__code']} — {m['site__name']}",
            "days": 0, "man_days": 0, "peak": 0})
        s["days"] += 1
        s["man_days"] += m["n"]
        s["peak"] = max(s["peak"], m["n"])
    rows = []
    for code in sorted(by_site):
        s = by_site[code]
        s["average"] = Decimal(s["man_days"]) / s["days"] if s["days"] else None
        rows.append(s)
    return section("People on site", [
        col("site", "Site"), col("days", "Days with a register", "int"),
        col("average", "Average present per day", "num"),
        col("peak", "Peak day", "int"),
        col("man_days", "Man-days marked present", "int"),
    ], rows, note="Own and subcontract workers marked present or half day.")

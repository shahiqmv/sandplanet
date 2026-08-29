"""Programme baseline, actuals and slippage.

`ProgrammeActivity.start/finish` are the CURRENT plan and are overwritten every
time a revision is imported. That was the whole programme until now, so a
revision destroyed the plan the company had committed to, and there was no
record of when work actually happened (conformance audit 2026-08-28).

Three things live here:
  * capturing an immutable baseline (and re-baselining when an EOT is awarded),
  * carrying actuals and progress across a re-import,
  * comparing the live programme against the baseline to say what slipped.

Matching between a baseline and a re-imported programme is by NAME, not by the
MS Project ID column: those renumber the moment a row is inserted, so they look
stable and are not.
"""
import re

from django.db import transaction
from django.utils import timezone

from .models import BaselineActivity, ProgrammeActivity, ProgrammeBaseline

_PUNCT = re.compile(r"[^a-z0-9]+")


def match_key(name):
    """A name reduced to what survives re-typing: case, punctuation and
    whitespace differences are not real differences between revisions."""
    return _PUNCT.sub(" ", (name or "").lower()).strip()[:200]


def current_baseline(project):
    return project.baselines.filter(superseded_at__isnull=True).first()


@transaction.atomic
def capture_baseline(project, user, label="", reason=""):
    """Freeze the programme as it stands. Supersedes any previous baseline —
    which is kept, so what we were working to last month is still answerable."""
    live = list(project.activities.order_by("sort_order"))
    if not live:
        return None, "There is no programme to baseline yet."
    previous = current_baseline(project)
    if previous is not None:
        previous.superseded_at = timezone.now()
        previous.save(update_fields=["superseded_at"])
    rev_no = (project.baselines.order_by("-rev_no")
              .values_list("rev_no", flat=True).first())
    rev_no = 0 if rev_no is None else rev_no + 1
    baseline = ProgrammeBaseline.objects.create(
        project=project, rev_no=rev_no, captured_by=user,
        label=label or ("Contract programme" if rev_no == 0
                        else f"Revision {rev_no}"),
        reason=reason)
    BaselineActivity.objects.bulk_create([
        BaselineActivity(
            baseline=baseline, sort_order=a.sort_order, indent=a.indent,
            name=a.name, match_key=match_key(a.name),
            duration_days=a.duration_days, start=a.start, finish=a.finish,
            is_milestone=a.is_milestone)
        for a in live])
    return baseline, None


def carry_forward(project):
    """What must survive a re-import, keyed by name: the dates work actually
    happened and the progress reported against it. Read BEFORE the old
    activities are deleted, applied to the new ones after."""
    out = {}
    for a in project.activities.all():
        k = match_key(a.name)
        if k and k not in out:
            out[k] = {"actual_start": a.actual_start,
                      "actual_finish": a.actual_finish,
                      "progress": a.progress,
                      "progress_updated_from_id": a.progress_updated_from_id}
    return out


def apply_carried(activity, carried):
    """Restore an activity's history after a re-import. Returns True if
    anything was carried, so the caller can report how much survived."""
    prior = carried.get(match_key(activity.name))
    if not prior:
        return False
    for field, value in prior.items():
        setattr(activity, field, value)
    activity.save(update_fields=list(prior.keys()))
    return True


def _days(a, b):
    return (a - b).days if (a and b) else None


def comparison(project, as_of=None):
    """Live programme against its baseline, activity by activity.

    Slippage is measured on FINISH, and against the actual finish where the
    work is done — an activity that finished late is late by a fact, not by a
    forecast."""
    as_of = as_of or timezone.localdate()
    base = current_baseline(project)
    base_rows = {}
    if base is not None:
        for b in base.activities.all():
            base_rows.setdefault(b.match_key, b)

    rows, slipped, unbaselined = [], 0, 0
    for a in project.activities.order_by("sort_order"):
        b = base_rows.get(match_key(a.name))
        if b is None:
            unbaselined += 1
        planned_finish = a.actual_finish or a.finish
        drift = _days(planned_finish, b.finish) if b else None
        if drift and drift > 0:
            slipped += 1
        started_late = _days(a.actual_start, b.start) if b else None
        rows.append({
            "id": a.id, "name": a.name, "indent": a.indent,
            "is_milestone": a.is_milestone,
            "baseline_start": b.start if b else None,
            "baseline_finish": b.finish if b else None,
            "planned_start": a.start, "planned_finish": a.finish,
            "actual_start": a.actual_start, "actual_finish": a.actual_finish,
            "progress": a.progress,
            "in_baseline": b is not None,
            "days_late": drift,
            "started_late_by": started_late,
            # Work that should have finished by now and has not.
            "overdue": bool(b and b.finish and b.finish < as_of
                            and not a.actual_finish),
        })
    return {
        "baseline": None if base is None else {
            "id": base.id, "rev_no": base.rev_no, "label": base.label,
            "captured_at": base.captured_at, "reason": base.reason,
            "activity_count": len(base_rows),
        },
        "as_of": as_of,
        "rows": rows,
        "summary": {
            "activities": len(rows), "slipped": slipped,
            "not_in_baseline": unbaselined,
            "overdue": sum(1 for r in rows if r["overdue"]),
            "complete": sum(1 for r in rows if r["actual_finish"]),
        },
    }

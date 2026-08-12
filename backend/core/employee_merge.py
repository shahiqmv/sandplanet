"""Merge a duplicate employee record into the one that survives.

HR sometimes re-creates a worker instead of reactivating them, leaving the
month's attendance stranded on a record payroll will never see (payroll filters
is_active). Merging moves every dependent row onto the surviving record and
deletes the duplicate, so the work — and the pay — follows the person
(owner 2026-08-12).
"""
from django.db import transaction

from .audit import audit

# Every FK that points at Employee, and how a merge treats it.
MOVE = ("attendance", "payroll_lines", "salary_advances", "change_items",
        "salary_revisions", "permit_renewals", "site_allocations")


def preview(source, target):
    """What a merge would do — counts per relation plus attendance-day clashes
    (Attendance is unique per employee+day, so overlapping days can't both
    move)."""
    from .models import Attendance
    src_days = set(Attendance.objects.filter(employee=source)
                   .values_list("day", flat=True))
    tgt_days = set(Attendance.objects.filter(employee=target)
                   .values_list("day", flat=True))
    clashes = sorted(src_days & tgt_days)
    return {
        "source": source.emp_no, "target": target.emp_no,
        "moves": {rel: getattr(source, rel).count() for rel in MOVE},
        "attendance_clashes": clashes,
        "warnings": _warnings(source, target),
    }


def _norm(v):
    return "".join(ch for ch in (v or "").upper() if ch.isalnum())


def _warnings(source, target):
    out = []
    if not target.is_active:
        out.append("the surviving record is inactive")
    if source.engagement_type != target.engagement_type:
        out.append(f"engagement differs ({source.engagement_type} → "
                   f"{target.engagement_type})")
    if (_norm(source.passport_no) and _norm(target.passport_no)
            and _norm(source.passport_no) != _norm(target.passport_no)):
        out.append("passport numbers differ")
    return out


@transaction.atomic
def merge(source, target, actor, clash="keep_target"):
    """Move source's history onto target, then delete source.

    `clash` decides an attendance day both records hold:
      keep_higher — the row with the greater normal hours wins (RECOMMENDED,
        owner 2026-08-12: a re-created record often carries 0-hour placeholder
        days while the real 11-hour marking sits on the duplicate; blindly
        keeping the survivor destroyed 154 h of FAYSAL AHAMMED's July);
      keep_target — the surviving record's row wins;
      keep_source — the duplicate's row wins.
    Ties keep the survivor's row (identical hours, so nothing is lost)."""
    from .models import Attendance
    if source.pk == target.pk:
        return None, "A record can't be merged into itself."
    if clash not in ("keep_target", "keep_source", "keep_higher"):
        return None, "Unknown clash rule."

    tgt_rows = {a.day: a for a in Attendance.objects.filter(employee=target)}
    tgt_days = dict((d, a.id) for d, a in tgt_rows.items())
    moved = {}
    dropped = []
    hours_rescued = 0
    for src_row in list(Attendance.objects.filter(employee=source)):
        day, att_id = src_row.day, src_row.id
        if day in tgt_days:
            take_source = clash == "keep_source"
            if clash == "keep_higher":
                s_h = src_row.normal_hours or 0
                t_h = tgt_rows[day].normal_hours or 0
                take_source = s_h > t_h
                if take_source:
                    hours_rescued += float(s_h - t_h)
            if take_source:
                Attendance.objects.filter(pk=tgt_days[day]).delete()
                Attendance.objects.filter(pk=att_id).update(employee=target)
            else:
                Attendance.objects.filter(pk=att_id).delete()
            dropped.append(str(day))
        else:
            Attendance.objects.filter(pk=att_id).update(employee=target)
    moved["attendance"] = (Attendance.objects.filter(employee=target).count()
                           - len(tgt_days))

    for rel in MOVE:
        if rel == "attendance":
            continue
        mgr = getattr(source, rel)
        moved[rel] = mgr.count()
        mgr.update(employee=target)

    # an onboarding case points at the employee with related_name="+"
    from .models import OnboardingCase
    moved["onboarding_cases"] = OnboardingCase.objects.filter(
        employee=source).update(employee=target)

    detail = {"merged": source.emp_no, "into": target.emp_no,
              "name": source.full_name, "passport": source.passport_no or "",
              "moved": moved, "clash_rule": clash,
              "clashing_days_resolved": dropped,
              "hours_rescued": round(hours_rescued, 2)}
    src_id = source.id
    source.delete()
    audit("employee", target.id, "EMPLOYEE_MERGED", actor=actor, detail=detail)
    audit("employee", src_id, "EMPLOYEE_MERGED_AWAY", actor=actor,
          detail=detail)
    return detail, None

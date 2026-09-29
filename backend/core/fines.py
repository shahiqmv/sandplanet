"""Worker fines (owner 2026-09-29): recorded by the site team, approved by the
site PM, deducted on that month's payroll.

The fine is the only way money reaches PayrollLine.penalty now. That keeps one
route to the deduction: HR cannot type a penalty that has no fine behind it,
and a fine cannot be approved without landing on a run.

Which run. An approved fine comes off the payroll of the site it was recorded
at, in its deduction month — the month of the breach, or, if that month's run
has already left HR's hands (with the PM, the Director, approved or locked),
the first month after it whose run is still open. So a PM's approval never
changes figures someone else has already signed. A USD-salaried man's fine
comes off the combined USD run instead, converted at the company rate, the
same as his rufiyaa advances. A settlement run takes every fine the leaver
still owes, from any site and month.

When a run locks, the fines on it are tied to their lines and are spent. A
fine whose man has no line on that run — he moved site before payroll — is
carried to the next month at his current site, and says so.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .audit import audit
from .models import PayrollRun, Site, WorkerFine

RECORD_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "ADMIN")
# Who sees every site's fines (the site team sees its own)
OVERSIGHT_ROLES = ("HO_HR", "FINANCE", "DIRECTOR", "ADMIN", "PA", "SIGNATORY")
OPEN_RUN = ("DRAFT", "RETURNED")          # still HR's to change
ZERO = Decimal("0")


def usd_salaried(emp):
    from .payroll import is_split_pay
    return (emp.currency or "MVR") == "USD" and not is_split_pay(emp)


def _next(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def monthly_run(emp, site, y, m):
    """The monthly run this man's fine for (y, m) would come off."""
    if usd_salaried(emp):
        return PayrollRun.objects.filter(site__isnull=True, currency="USD",
                                         kind="MONTHLY", year=y,
                                         month=m).first()
    return PayrollRun.objects.filter(site=site, currency="MVR",
                                     kind="MONTHLY", year=y, month=m).first()


def target_period(emp, site, y, m):
    """First month from (y, m) whose run does not exist yet or is still
    HR's to change."""
    for _ in range(24):
        run = monthly_run(emp, site, y, m)
        if run is None or run.status in OPEN_RUN:
            return y, m
        y, m = _next(y, m)
    return y, m


# ---- permissions -----------------------------------------------------------

def site_ok(user, site):
    from .permissions import scoped_site_ids
    ids = scoped_site_ids(user)
    return ids is None or site.id in ids


def can_record(user, site):
    return user.role in RECORD_ROLES and site_ok(user, site)


def can_approve(user, fine):
    """The site's PM (any co-PM); the Director where a site has no PM, and for
    head office. Never the person who recorded it."""
    if user.id == fine.recorded_by_id:
        return False
    site = fine.site
    if user.role == "ADMIN":
        return True
    if user.role == "PM":
        return site.is_current_pm(user)
    if user.role == "DIRECTOR":
        return site.is_head_office or not site.current_pms()
    return False


def can_view(user, site):
    return user.role in OVERSIGHT_ROLES or (
        user.role in ("SITE_ADMIN", "SITE_ENGINEER", "PM", "QS")
        and site_ok(user, site))


# ---- payroll ---------------------------------------------------------------

def fines_for_line(line):
    run, emp = line.run, line.employee
    base = WorkerFine.objects.filter(employee=emp, status="APPROVED").filter(
        Q(payroll_line__isnull=True) | Q(payroll_line=line))
    if run.kind == "SETTLEMENT":
        return base                          # everything he still owes
    if run.site_id is None:                  # the combined USD run
        if not usd_salaried(emp):
            return base.none()
        return base.filter(deduct_year=run.year, deduct_month=run.month)
    if usd_salaried(emp):
        return base.none()                   # his fines are on the USD run
    return base.filter(site_id=run.site_id, deduct_year=run.year,
                       deduct_month=run.month)


def line_penalty(line):
    total = fines_for_line(line).aggregate(t=Sum("amount"))["t"] or ZERO
    if total and line.run.currency == "USD":
        from . import fx
        from .payroll import q
        return q(total / fx.usd_rate())
    return total


def apply_fines(run, employee_ids=None):
    """Set every line's penalty from its approved fines. Returns the emp nos
    whose penalty changed."""
    if run.status == "LOCKED":
        return []
    changed = []
    lines = run.lines.select_related("employee", "run")
    if employee_ids is not None:
        lines = lines.filter(employee_id__in=employee_ids)
    for line in lines:
        pen = line_penalty(line)
        if pen != line.penalty:
            line.penalty = pen
            line.save(update_fields=["penalty"])
            changed.append(line.employee.emp_no)
    return changed


def _refresh_open_runs(fine):
    """A fine just approved or cancelled: put it on (or take it off) any run
    still open to HR that carries it."""
    runs = PayrollRun.objects.filter(status__in=OPEN_RUN,
                                     lines__employee=fine.employee).distinct()
    for run in runs:
        apply_fines(run, employee_ids=[fine.employee_id])


def settle_on_lock(run):
    """Tie the fines on this run to their lines; carry the ones whose man is
    not on it to next month at his current site. Called inside lock_run."""
    lines = list(run.lines.select_related("employee", "run"))
    for line in lines:
        fines_for_line(line).update(payroll_line=line)
    if run.kind != "MONTHLY":
        return
    on_run = {ln.employee_id for ln in lines}
    stray = WorkerFine.objects.filter(
        status="APPROVED", payroll_line__isnull=True,
        deduct_year=run.year, deduct_month=run.month).select_related(
        "employee", "site")
    stray = stray.filter(employee__currency="USD") if run.site_id is None \
        else stray.filter(site_id=run.site_id)
    for f in stray:
        if f.employee_id in on_run:
            continue
        if (run.site_id is not None) == usd_salaried(f.employee):
            continue                         # it belongs to the other run
        y, m = _next(run.year, run.month)
        sid = f.employee.current_site_id() or f.site_id
        site = Site.objects.get(pk=sid)
        ny, nm = target_period(f.employee, site, y, m)
        note = (f"Not on {run.ref or 'the run'} — carried to "
                f"{ny}-{nm:02d}" + (f" at {site.code}" if sid != f.site_id else ""))
        f.site_id, f.deduct_year, f.deduct_month = sid, ny, nm
        f.carried_note = note[:200]
        f.save(update_fields=["site", "deduct_year", "deduct_month",
                              "carried_note"])


def release_on_reopen(run):
    WorkerFine.objects.filter(payroll_line__run=run).update(payroll_line=None)


# ---- the workflow ----------------------------------------------------------

def record(*, user, employee, site, violation_date, description, amount,
           offence=None, category=None, evidence=None):
    if not can_record(user, site):
        return None, "You can record fines only for your own site."
    if employee.engagement_type == "SUBCONTRACT":
        return None, ("A subcontract worker is not on our payroll — raise it "
                      "with his subcontractor.")
    if violation_date > timezone.localdate():
        return None, "The date of the breach can't be in the future."
    from .models import EmployeeSiteAllocation
    here = EmployeeSiteAllocation.objects.filter(
        employee=employee, site=site, from_date__lte=violation_date).filter(
        Q(to_date__isnull=True) | Q(to_date__gte=violation_date)).exists()
    if not here:
        return None, (f"{employee.emp_no} was not allocated to {site.code} on "
                      f"{violation_date:%d %b %Y}.")
    try:
        amount = Decimal(str(amount))
    except Exception:
        return None, "Enter the fine amount."
    if amount <= 0:
        return None, "The fine must be more than zero."
    description = (description or "").strip()
    if not description:
        return None, "Say what happened."
    if offence is not None:
        category = offence.category
    if category not in dict(WorkerFine._meta.get_field("category").choices):
        return None, "Pick the kind of breach."
    from .numbering import next_ref
    with transaction.atomic():
        fine = WorkerFine(employee=employee, site=site, offence=offence,
                          category=category, violation_date=violation_date,
                          description=description, amount=amount,
                          recorded_by=user)
        fine.ref = next_ref("FIN", site)
        if evidence is not None:
            fine.evidence = evidence
        fine.save()
    audit("worker_fine", fine.id, "FINE_RECORDED", actor=user,
          detail={"ref": fine.ref, "emp": employee.emp_no, "site": site.code,
                  "amount": str(amount), "category": category})
    _notify_approvers(fine)
    return fine, None


def decide(fine, user, approve, note=""):
    if fine.status != "PENDING":
        return f"{fine.ref} is already {fine.get_status_display().lower()}."
    if not can_approve(user, fine):
        return ("Only the site's PM can decide this fine — and never the "
                "person who recorded it.")
    note = (note or "").strip()
    if not approve and not note:
        return "Give the reason for rejecting it."
    with transaction.atomic():
        fine.status = "APPROVED" if approve else "REJECTED"
        fine.decided_by, fine.decided_at = user, timezone.now()
        fine.decision_note = note[:300]
        if approve:
            v = fine.violation_date
            fine.deduct_year, fine.deduct_month = target_period(
                fine.employee, fine.site, v.year, v.month)
        fine.save()
        if approve:
            _refresh_open_runs(fine)
    audit("worker_fine", fine.id,
          "FINE_APPROVED" if approve else "FINE_REJECTED", actor=user,
          detail={"ref": fine.ref, "note": note[:120],
                  "deduct": f"{fine.deduct_year}-{fine.deduct_month:02d}"
                  if approve else None})
    _notify_recorder(fine, user)
    return None


def can_cancel(user, fine):
    if fine.status == "PENDING":
        return user.id == fine.recorded_by_id or can_approve(user, fine) \
            or user.role in ("HO_HR", "ADMIN")
    if fine.status == "APPROVED":
        # An approved fine is withdrawn by whoever could approve it (the PM
        # who did, a co-PM) or by HR — never by the site team alone.
        return (can_approve(user, fine) or user.role in ("HO_HR", "ADMIN")
                or (user.role == "PM" and fine.site.is_current_pm(user)))
    return False


def cancel(fine, user, reason):
    if not can_cancel(user, fine):
        return "You can't cancel this fine."
    reason = (reason or "").strip()
    if not reason:
        return "Give the reason for cancelling it."
    if fine.payroll_line_id:
        return (f"{fine.ref} has already been deducted on "
                f"{fine.payroll_line.run.ref or 'a locked run'}.")
    if fine.status == "APPROVED":
        run = monthly_run(fine.employee, fine.site, fine.deduct_year,
                          fine.deduct_month)
        if run is not None and run.status not in OPEN_RUN:
            return (f"The {fine.deduct_year}-{fine.deduct_month:02d} payroll "
                    "is with the PM/Director now — have it returned to HR "
                    "first.")
    with transaction.atomic():
        was = fine.status
        fine.status = "CANCELLED"
        fine.cancelled_by, fine.cancelled_at = user, timezone.now()
        fine.cancel_reason = reason[:300]
        fine.save()
        if was == "APPROVED":
            _refresh_open_runs(fine)
    audit("worker_fine", fine.id, "FINE_CANCELLED", actor=user,
          detail={"ref": fine.ref, "reason": reason[:120]})
    return None


def history(employee, days=180, exclude_id=None):
    """His other fines — repeat breaches are what a PM needs to see."""
    since = timezone.localdate() - timedelta(days=days)
    qs = WorkerFine.objects.filter(employee=employee, violation_date__gte=since,
                                   status__in=("PENDING", "APPROVED"))
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs


def _notify_approvers(fine):
    from .notify import _role_users, notify_user
    who = fine.site.current_pms()
    if not who or fine.site.is_head_office:
        who = list(_role_users("DIRECTOR"))
    body = (f"{fine.site.code} · {fine.employee.emp_no} "
            f"{fine.employee.full_name} · MVR {fine.amount:,.2f}")
    for u in who:
        if u.id != fine.recorded_by_id:
            notify_user(u, f"Fine to approve — {fine.ref}", body=body,
                        category="approval")


def _notify_recorder(fine, actor):
    from .notify import notify_user
    verb = "approved" if fine.status == "APPROVED" else "rejected"
    body = f"{fine.employee.emp_no} · MVR {fine.amount:,.2f}"
    if fine.status == "APPROVED":
        body += f" · deducted {date(fine.deduct_year, fine.deduct_month, 1):%b %Y}"
    elif fine.decision_note:
        body += f" · {fine.decision_note}"
    notify_user(fine.recorded_by, f"{fine.ref} {verb}", body=body)


def pending_for(user):
    qs = WorkerFine.objects.filter(status="PENDING").select_related(
        "site", "employee", "recorded_by", "offence")
    return [f for f in qs if can_approve(user, f)]

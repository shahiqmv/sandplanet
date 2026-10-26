"""Safety induction sessions, SP-HSE-F01 (owner 2026-10-26, HSE forms brief
C.1).

Induction is per site — each resort has its own rules — so a man needs one
for the site he is on now: a new hire, a transfer in, an approved
subcontract worker, or a bring-back whose last induction there is over
twelve months old. The session picks its men from those not yet inducted on
the site, prints the form with them on it, and the signed copy uploaded
gives each man his induction record. The PM verifies the session.

The control is a FLAG, never a block (brief C.1, owner decision pending):
attendance is the only record of days paid and of the manpower at work, and
a block would push men off it. A man marked Present on a site where he has
no induction carries "Not inducted" — except on the day of a session he is
on, so day-one work is normal; a session left without its signed copy for
48 hours stops covering him.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import hse_induction_content as content
from .audit import audit
from .models import (Employee, EmployeeSiteAllocation, InductionAttendee,
                     InductionSession, SafetyInduction)

RECORD_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                "HO_HR", "PA")
SITE_TEAM = ("SITE_ADMIN", "SITE_ENGINEER", "PM")
OVERSIGHT_ROLES = ("HO_HR", "DIRECTOR", "ADMIN", "PA", "SIGNATORY")
REINDUCT_DAYS = 365        # a bring-back after a year is inducted again
UNSIGNED_HOURS = 48


# ---- permissions -----------------------------------------------------------

def _site_ok(user, site):
    from .permissions import scoped_site_ids
    ids = scoped_site_ids(user)
    return ids is None or site.id in ids


def can_record(user, site):
    return user.role in RECORD_ROLES and _site_ok(user, site)


def can_verify(user, s):
    """The site's PM (any co-PM); the Director where there is no PM, and
    for head office; Admin."""
    if user.role == "ADMIN":
        return True
    if user.role == "PM":
        return s.site.is_current_pm(user)
    if user.role == "DIRECTOR":
        return s.site.is_head_office or not s.site.current_pms()
    return False


def scoped(user):
    qs = InductionSession.objects.select_related(
        "site", "created_by", "uploaded_by", "verified_by")
    if user.role in OVERSIGHT_ROLES:
        return qs
    if user.role not in SITE_TEAM:
        return qs.none()
    from .permissions import scoped_site_ids
    ids = scoped_site_ids(user)
    return qs if ids is None else qs.filter(site_id__in=ids)


# ---- who is inducted -------------------------------------------------------

def _stint_start(employee_id, site, day):
    a = (EmployeeSiteAllocation.objects
         .filter(employee_id=employee_id, site=site, from_date__lte=day)
         .filter(Q(to_date__isnull=True) | Q(to_date__gte=day))
         .order_by("-from_date").first())
    return a.from_date if a else day


def inducted_ids(site, day, employee_ids):
    """The men among these covered on `site` on `day`: an induction on this
    site that holds for his current stint (taken within a year before it
    began, or since), or a live session that day he is on."""
    employee_ids = list(employee_ids)
    if not employee_ids:
        return set()
    covered = set()
    latest = {}
    for emp_id, on in (SafetyInduction.objects
                       .filter(site=site, employee_id__in=employee_ids,
                               inducted_on__lte=day)
                       .values_list("employee_id", "inducted_on")):
        if on > latest.get(emp_id, on.replace(year=1900)):
            latest[emp_id] = on
    for emp_id, on in latest.items():
        start = _stint_start(emp_id, site, day)
        if on >= start - timedelta(days=REINDUCT_DAYS):
            covered.add(emp_id)
    # day-one cover: a session on this day (or not yet 48h old unsigned)
    cut = timezone.now() - timedelta(hours=UNSIGNED_HOURS)
    live = (InductionAttendee.objects
            .filter(session__site=site, session__held_on=day,
                    employee_id__in=employee_ids, attended=True)
            .exclude(session__status="CANCELLED")
            .filter(Q(session__status__in=("SIGNED", "VERIFIED"))
                    | Q(session__created_at__gte=cut)))
    covered |= set(live.values_list("employee_id", flat=True))
    return covered


def not_inducted_ids(site, day, employee_ids):
    employee_ids = list(employee_ids)
    return set(employee_ids) - inducted_ids(site, day, employee_ids)


def candidates(site, day):
    """Who a session on this site and day can take: everyone on the site
    then — direct and subcontract — not yet inducted for this stint, and not
    already on another live session."""
    ids = list(EmployeeSiteAllocation.objects.filter(
        site=site, from_date__lte=day).filter(
        Q(to_date__isnull=True) | Q(to_date__gte=day)).values_list(
        "employee_id", flat=True))
    need = not_inducted_ids(site, day, ids)
    pending = set(InductionAttendee.objects.filter(
        session__site=site, employee_id__in=need,
        session__status__in=("DRAFT", "PRINTED")).values_list(
        "employee_id", flat=True))
    return (Employee.objects.filter(id__in=need - pending)
            .filter(Q(is_active=True) | Q(sub_pending=True))
            .select_related("job_category", "subcontractor")
            .order_by("engagement_type", "emp_no"))


# ---- the session -----------------------------------------------------------

def create(*, user, site, held_on, language, trainer_name, employee_ids,
           notes=""):
    if not can_record(user, site):
        return None, "You can run inductions only on your own site."
    if held_on > timezone.localdate() + timedelta(days=14):
        return None, "Plan a session at most two weeks ahead."
    trainer_name = (trainer_name or "").strip()[:120]
    if not trainer_name:
        return None, "Name the trainer — anyone, including the resort's " \
                     "safety officer."
    ids = [int(i) for i in (employee_ids or []) if str(i).strip()]
    if not ids:
        return None, "Pick the men for the session."
    allowed = {e.id for e in candidates(site, held_on)}
    bad = [i for i in ids if i not in allowed]
    if bad:
        names = ", ".join(Employee.objects.filter(id__in=bad)
                          .values_list("emp_no", flat=True))
        return None, (f"{names}: not on {site.code} that day, already "
                      "inducted, or on another session.")
    from .numbering import next_ref
    with transaction.atomic():
        s = InductionSession(site=site, held_on=held_on,
                             language=(language or "")[:2].upper(),
                             trainer_name=trainer_name, created_by=user,
                             form_rev=content.FORM_REV,
                             notes=(notes or "").strip())
        s.ref = next_ref("IND", site)
        s.save()
        InductionAttendee.objects.bulk_create(
            [InductionAttendee(session=s, employee_id=i) for i in ids])
    audit("induction_session", s.id, "INDUCTION_PLANNED", actor=user,
          detail={"ref": s.ref, "site": site.code, "men": len(ids)})
    return s, None


def edit_attendees(s, user, add=(), remove=()):
    if s.status not in ("DRAFT", "PRINTED"):
        return "The signed copy is in — the attendance is what it shows."
    if not can_record(user, s.site):
        return "You can run inductions only on your own site."
    allowed = {e.id for e in candidates(s.site, s.held_on)}
    for i in add or ():
        if int(i) not in allowed:
            return "One of those men cannot be added to this session."
        InductionAttendee.objects.get_or_create(session=s, employee_id=int(i))
    if remove:
        s.attendees.filter(employee_id__in=[int(i) for i in remove]).delete()
    if not s.attendees.exists():
        return "A session needs at least one man."
    if s.status == "PRINTED":       # the printed sheet no longer matches
        s.status, s.printed_at = "DRAFT", None
        s.save(update_fields=["status", "printed_at"])
    return None


def mark_printed(s):
    if s.status == "DRAFT":
        s.status, s.printed_at = "PRINTED", timezone.now()
        s.save(update_fields=["status", "printed_at"])


def upload_signed(s, user, files, absent_ids=(), topics_na=()):
    """The signed sheet completes the session: each man who signed gets his
    induction on this site. Men who did not sign are left off."""
    from . import signed_sheets
    if s.status not in ("PRINTED", "DRAFT"):
        return "The signed copy is already in."
    if not can_record(user, s.site):
        return "You can run inductions only on your own site."
    if s.status == "DRAFT":
        return "Print the sheet first — the signed copy is that sheet."
    pdf, err = signed_sheets.join(files)
    if err:
        return err
    absent = {int(i) for i in (absent_ids or ())}
    na = [t for t in (topics_na or ()) if t in content.TOPIC_NOS]
    with transaction.atomic():
        s.signed_copy.save(f"{s.ref}-signed.pdf", pdf, save=False)
        s.uploaded_by, s.uploaded_at = user, timezone.now()
        s.topics_na = na
        s.status = "SIGNED"
        s.save()
        s.attendees.filter(employee_id__in=absent).update(attended=False)
        topics = ", ".join(f"{no} {en}" for no, en, _b in content.TOPICS
                           if no not in na)
        for a in s.attendees.filter(attended=True):
            SafetyInduction.objects.create(
                employee_id=a.employee_id, site=s.site, inducted_on=s.held_on,
                inducted_by=user, topics=topics, session=s,
                notes=f"{s.ref} · trained by {s.trainer_name}")
    audit("induction_session", s.id, "INDUCTION_SIGNED", actor=user,
          detail={"ref": s.ref, "inducted": s.attendees.filter(
              attended=True).count(), "absent": len(absent)})
    _notify_verifier(s)
    return None


def verify(s, user):
    if s.status != "SIGNED":
        return "Only a session with its signed copy is verified."
    if not can_verify(user, s):
        return "The site PM verifies the induction."
    s.status = "VERIFIED"
    s.verified_by, s.verified_at = user, timezone.now()
    s.save(update_fields=["status", "verified_by", "verified_at"])
    audit("induction_session", s.id, "INDUCTION_VERIFIED", actor=user,
          detail={"ref": s.ref})
    return None


def cancel(s, user, reason):
    if s.status in ("SIGNED", "VERIFIED", "CANCELLED"):
        return "A signed session stands — it is the men's record."
    if not can_record(user, s.site):
        return "You can run inductions only on your own site."
    s.status = "CANCELLED"
    s.notes = (s.notes + f"\nCancelled: {(reason or '').strip()}").strip()
    s.save(update_fields=["status", "notes"])
    audit("induction_session", s.id, "INDUCTION_CANCELLED", actor=user,
          detail={"ref": s.ref})
    return None


# ---- queues and counts -----------------------------------------------------

def _notify_verifier(s):
    from .notify import _role_users, notify_user
    who = s.site.current_pms()
    if not who or s.site.is_head_office:
        who = list(_role_users("DIRECTOR"))
    for u in who:
        notify_user(u, f"Induction to verify — {s.ref}",
                    body=f"{s.site.code} · {s.held_on:%d %b} · "
                         f"{s.attendees.filter(attended=True).count()} men",
                    category="approval")


def to_verify(user):
    return [s for s in InductionSession.objects.filter(status="SIGNED")
            .select_related("site") if can_verify(user, s)]


def unsigned_for(user):
    """Sheets printed more than 48 hours ago with no signed copy — the
    site team's to chase."""
    if user.role not in RECORD_ROLES:
        return []
    cut = timezone.now() - timedelta(hours=UNSIGNED_HOURS)
    return [s for s in scoped(user).filter(status="PRINTED",
                                           printed_at__lte=cut)
            if _site_ok(user, s.site)]


def present_not_inducted(site, day):
    """How many men marked Present on the site today have no induction
    there — the daily summary's line."""
    from .models import Attendance
    ids = list(Attendance.objects.filter(
        site=site, day=day, remark__in=("PRESENT", "HALF_DAY")).values_list(
        "employee_id", flat=True))
    return len(not_inducted_ids(site, day, ids))

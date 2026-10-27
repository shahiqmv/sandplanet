"""Employee warning notices, SP-HSE-F02 (owner 2026-10-26, HSE forms brief
C.2).

The site team raises a warning for a direct or subcontract worker who was on
the site that day; the site PM approves it (the Director where there is no
PM, and for head office) and never the person who raised it — the fines rule.
Planet suggests the level from his active warnings: none → verbal, verbal →
first written, first → final written, final → removal from site; changing
it needs a reason. The approved form is printed, served, and the signed copy
uploaded — that makes the warning ACTIVE. It counts toward the next level
for twelve months and stays on file for good.

No money, and no link to fines either way (owner 2026-09-29): if a site
wants both for one event it records both, separately. A removal uses the
existing flows — a Remove batch for a direct worker, which the PM approves
as usual; a subcontract worker comes off the site at once.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .audit import audit
from .form_i18n import TRANSLATED, english  # noqa: F401  (TRANSLATED re-exported)
from .models import Employee, EmployeeSiteAllocation, WarningNotice

FORM_REV = "F02 Rev 0"
RECORD_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "ADMIN")
SITE_TEAM = ("SITE_ADMIN", "SITE_ENGINEER", "PM")
# Head office sees every site's warnings; the Signatory reads, as everywhere.
OVERSIGHT_ROLES = ("HO_HR", "DIRECTOR", "ADMIN", "PA", "SIGNATORY")
LEVEL_ORDER = ["VERBAL", "FIRST", "FINAL", "REMOVAL"]
ACTIVE_MONTHS_KEY = "hse_warning_active_months"
DEFAULT_ACTIVE_MONTHS = 12

# The form's offences in the form's order; the words in each language are
# "off_<code>" in core/form_i18n.
OFFENCES = [(code, group, english()[f"off_{code}"]) for code, group in (
    ("PPE", "SAFETY"), ("HEIGHT", "SAFETY"), ("TOOLS", "SAFETY"),
    ("GUARDS", "SAFETY"), ("SMOKING", "SAFETY"), ("ALCOHOL", "SAFETY"),
    ("FIGHT", "CONDUCT"), ("THEFT", "CONDUCT"), ("LATE", "CONDUCT"),
    ("ABSENT", "CONDUCT"), ("SUBSTANDARD", "CONDUCT"))]
OFFENCE_CODES = {o[0] for o in OFFENCES}

# Languages a worker's forms can be in (brief C.5). Those in TRANSLATED
# print beside English (owner 2026-10-26); the rest print English and the
# form says to explain it verbally.
LANGUAGES = [("BN", "Bengali"), ("HI", "Hindi"), ("SI", "Sinhala"),
             ("TA", "Tamil"), ("NE", "Nepali"), ("DV", "Dhivehi"),
             ("EN", "English")]


# ---- permissions -----------------------------------------------------------

def _site_ok(user, site):
    from .permissions import scoped_site_ids
    ids = scoped_site_ids(user)
    return ids is None or site.id in ids


def can_record(user, site):
    return user.role in RECORD_ROLES and _site_ok(user, site)


def can_approve(user, w):
    """The site's PM (any co-PM) — his own warnings included: on many sites
    the PM does the safety and admin work himself and prepares the warning
    as well as approving it (owner 2026-10-27). The Director where a site
    has no PM, and for head office; Admin. Anyone else never approves what
    they raised."""
    if user.role == "PM":
        return w.site.is_current_pm(user)
    if user.id == w.raised_by_id:
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "DIRECTOR":
        return w.site.is_head_office or not w.site.current_pms()
    return False


def can_view(user, site):
    return user.role in OVERSIGHT_ROLES or (
        user.role in SITE_TEAM and _site_ok(user, site))


def scoped(user):
    qs = WarningNotice.objects.select_related(
        "employee__job_category", "employee__subcontractor", "site",
        "raised_by", "decided_by", "uploaded_by", "incident__document")
    if user.role in OVERSIGHT_ROLES:
        return qs
    if user.role not in SITE_TEAM:
        return qs.none()
    from .permissions import scoped_site_ids
    ids = scoped_site_ids(user)
    return qs if ids is None else qs.filter(site_id__in=ids)


# ---- the level ladder ------------------------------------------------------

def active_months():
    from .models import CompanyParameter
    row = CompanyParameter.objects.filter(key=ACTIVE_MONTHS_KEY).first()
    try:
        return int(row.value) if row else DEFAULT_ACTIVE_MONTHS
    except (TypeError, ValueError):
        return DEFAULT_ACTIVE_MONTHS


def active_warnings(employee, as_of=None, exclude_id=None):
    as_of = as_of or timezone.localdate()
    qs = WarningNotice.objects.filter(employee=employee, status="ACTIVE",
                                      active_until__gte=as_of)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs


def suggest_level(employee, as_of=None, exclude_id=None):
    """The next step up from his highest active warning."""
    held = [LEVEL_ORDER.index(w.level) for w in
            active_warnings(employee, as_of, exclude_id)]
    if not held:
        return "VERBAL"
    return LEVEL_ORDER[min(max(held) + 1, len(LEVEL_ORDER) - 1)]


def history(employee, exclude_id=None):
    """Every warning on file, newest first — what a PM weighs."""
    qs = WarningNotice.objects.filter(employee=employee).exclude(
        status="CANCELLED")
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.select_related("site").order_by("-event_date", "-id")


def on_site(employee, site, day):
    return EmployeeSiteAllocation.objects.filter(
        employee=employee, site=site, from_date__lte=day).filter(
        Q(to_date__isnull=True) | Q(to_date__gte=day)).exists()


# ---- raising and deciding --------------------------------------------------

def _clean(data, employee, event_date, exclude_id=None):
    """(fields, error) for a warning's content."""
    offences = [o for o in (data.get("offences") or []) if o in OFFENCE_CODES]
    other = (data.get("other_offence") or "").strip()[:200]
    if not offences and not other:
        return None, "Tick the offence, or describe it under Other."
    what = (data.get("what_happened") or "").strip()
    if not what:
        return None, "Say what happened — date, time and place."
    suggested = suggest_level(employee, event_date, exclude_id)
    level = data.get("level") or suggested
    if level not in LEVEL_ORDER:
        return None, "Pick the warning level."
    reason = (data.get("level_reason") or "").strip()[:300]
    if level != suggested and not reason:
        return None, (f"Planet suggests a "
                      f"{dict(WarningNotice.Level.choices)[suggested].lower()}"
                      " from his active warnings — give the reason for a "
                      "different level.")
    lang = {}
    if "language" in data:      # the language the form prints in
        code = (data.get("language") or "").upper()
        if code and code not in dict(LANGUAGES):
            return None, "Pick a language from the list."
        lang = {"language": "" if code == "EN" else code}
    return {**lang, "offences": offences, "other_offence": other,
            "what_happened": what,
            "corrective_action": (data.get("corrective_action")
                                  or "").strip(),
            "supervisor": (data.get("supervisor") or "").strip()[:120],
            "level": level, "suggested_level": suggested,
            "level_reason": reason if level != suggested else ""}, None


def raise_warning(*, user, employee, site, event_date, data, incident=None):
    if not can_record(user, site):
        return None, "You can raise warnings only for your own site."
    if event_date > timezone.localdate():
        return None, "The date can't be in the future."
    if not on_site(employee, site, event_date):
        return None, (f"{employee.emp_no} was not on {site.code} on "
                      f"{event_date:%d %b %Y}.")
    fields, err = _clean(data, employee, event_date)
    if err:
        return None, err
    from .numbering import next_ref
    with transaction.atomic():
        fields.setdefault("language", employee.preferred_language or "")
        w = WarningNotice(employee=employee, site=site, incident=incident,
                          event_date=event_date, raised_by=user,
                          form_rev=FORM_REV, **fields)
        w.ref = next_ref("WN", site)
        w.save()
    audit("warning_notice", w.id, "WARNING_RAISED", actor=user,
          detail={"ref": w.ref, "emp": employee.emp_no, "site": site.code,
                  "level": w.level, "suggested": w.suggested_level})
    _notify_approvers(w)
    return w, None


def edit(w, user, data):
    """The person who raised it corrects a warning before approval, or after
    the PM returned it — a return goes back to the PM."""
    if w.status not in ("PENDING", "RETURNED"):
        return "Only a warning not yet approved can be changed."
    if user.id != w.raised_by_id and user.role not in ("HO_HR", "ADMIN"):
        return "Only the person who raised it can change it."
    fields, err = _clean(data, w.employee, w.event_date, exclude_id=w.id)
    if err:
        return err
    for k, v in fields.items():
        setattr(w, k, v)
    was = w.status
    w.status = "PENDING"
    w.save()
    audit("warning_notice", w.id, "WARNING_EDITED", actor=user,
          detail={"ref": w.ref, "level": w.level})
    if was == "RETURNED":
        _notify_approvers(w)
    return None


def decide(w, user, approve, note=""):
    if w.status != "PENDING":
        return f"{w.ref} is {w.get_status_display().lower()}."
    if not can_approve(user, w):
        return ("Only the site's PM approves a warning — anyone else "
                "never the one they raised.")
    note = (note or "").strip()
    if not approve and not note:
        return "Say why it is going back to the site."
    w.status = "APPROVED" if approve else "RETURNED"
    w.decided_by, w.decided_at = user, timezone.now()
    w.decision_note = note[:300]
    w.save(update_fields=["status", "decided_by", "decided_at",
                          "decision_note"])
    audit("warning_notice", w.id,
          "WARNING_APPROVED" if approve else "WARNING_RETURNED", actor=user,
          detail={"ref": w.ref, "note": note[:120],
                  "own": user.id == w.raised_by_id})
    if user.id != w.raised_by_id:
        _notify_raiser(w, user)
    return None


def mark_printed(w):
    if w.status == "APPROVED" and w.printed_at is None:
        w.printed_at = timezone.now()
        w.save(update_fields=["printed_at"])


def serve(w, user, files, served_on, refused=False, witness=""):
    """Upload the signed copy: the warning becomes ACTIVE. If the man
    refused to sign, a witness signs instead — the warning stands either way.
    """
    from . import signed_sheets
    if w.status != "APPROVED":
        return "Only an approved warning is served."
    if not (user.role in RECORD_ROLES and _site_ok(user, w.site)):
        return "The site team serves the warning."
    if served_on is None or served_on > timezone.localdate():
        return "Give the date it was served."
    if served_on < w.event_date:
        return "It can't be served before the offence."
    witness = (witness or "").strip()[:120]
    if refused and not witness:
        return "He refused to sign — name the witness who signed instead."
    pdf, err = signed_sheets.join(files)
    if err:
        return err
    with transaction.atomic():
        w.signed_copy.save(f"{w.ref}-signed.pdf", pdf, save=False)
        w.served_on = served_on
        w.refused_to_sign = bool(refused)
        w.witness_name = witness
        w.uploaded_by, w.uploaded_at = user, timezone.now()
        w.status = "ACTIVE"
        w.active_until = _add_months(served_on, active_months())
        w.save()
        if w.level == "REMOVAL":
            _remove_from_site(w, user)
    audit("warning_notice", w.id, "WARNING_SERVED", actor=user,
          detail={"ref": w.ref, "served": str(served_on),
                  "refused": bool(refused)})
    if w.level in ("FINAL", "REMOVAL"):
        _notify_hr(w)
    return None


def cancel(w, user, reason):
    reason = (reason or "").strip()
    if not reason:
        return "Give the reason for cancelling it."
    if w.status == "CANCELLED":
        return f"{w.ref} is already cancelled."
    if w.status == "ACTIVE":
        if user.role not in ("HO_HR", "ADMIN"):
            return "A served warning is withdrawn only by HR."
    elif not (user.id == w.raised_by_id or can_approve(user, w)
              or user.role in ("HO_HR", "ADMIN")):
        return "You can't cancel this warning."
    w.status = "CANCELLED"
    w.cancelled_by, w.cancelled_at = user, timezone.now()
    w.cancel_reason = reason[:300]
    w.save(update_fields=["status", "cancelled_by", "cancelled_at",
                          "cancel_reason"])
    audit("warning_notice", w.id, "WARNING_CANCELLED", actor=user,
          detail={"ref": w.ref, "reason": reason[:120]})
    return None


# ---- removal from site -----------------------------------------------------

def _remove_from_site(w, user):
    """A direct worker: open the existing Remove batch for the PM to approve.
    A subcontract worker: off the site's subcontract workers at once."""
    emp = w.employee
    if emp.is_subcontract:
        from . import subcontract
        subcontract.remove_worker(emp, user)
        return
    from . import worker_mgmt
    batch, err = worker_mgmt.create_remove_batch(
        w.site, [emp.id], user, reason=f"Removal from site — warning {w.ref}")
    if batch is not None:
        w.removal_batch = batch
        w.save(update_fields=["removal_batch"])


def _add_months(day, months):
    import calendar
    m = day.month - 1 + months
    y, m = day.year + m // 12, m % 12 + 1
    return day.replace(year=y, month=m,
                       day=min(day.day, calendar.monthrange(y, m)[1]))


# ---- notifications and queues ----------------------------------------------

def _approvers(w):
    from .notify import _role_users
    who = w.site.current_pms()
    if not who or w.site.is_head_office:
        who = [u for u in _role_users("DIRECTOR") if u.id != w.raised_by_id]
    return who


def approver_names(w):
    """Who the warning waits for, for the screen."""
    return ", ".join((u.get_full_name() or u.username) for u in _approvers(w))


def _notify_approvers(w):
    from .notify import notify_user
    body = (f"{w.site.code} · {w.employee.emp_no} {w.employee.full_name} · "
            f"{w.get_level_display()}")
    for u in _approvers(w):
        if u.id == w.raised_by_id:
            continue            # a PM's own warning: he approves it himself
        notify_user(u, f"Warning to approve — {w.ref}", body=body,
                    category="approval")


def _notify_raiser(w, actor):
    from .notify import notify_user
    if w.status == "APPROVED":
        notify_user(w.raised_by, f"{w.ref} approved — print and serve it",
                    body=f"{w.employee.emp_no} {w.employee.full_name} · "
                         f"{w.get_level_display()}")
    else:
        notify_user(w.raised_by, f"{w.ref} returned",
                    body=w.decision_note)


def _notify_hr(w):
    from .notify import _role_users, notify_user
    title = (f"Removal from site — {w.ref}" if w.level == "REMOVAL"
             else f"Final warning served — {w.ref}")
    body = f"{w.site.code} · {w.employee.emp_no} {w.employee.full_name}"
    if w.level == "REMOVAL":
        body += (" · subcontract worker taken off the site — tell his "
                 "subcontractor" if w.employee.is_subcontract
                 else " · Remove batch opened for the PM")
    for u in _role_users("HO_HR"):
        notify_user(u, title, body=body)
    if w.level == "REMOVAL":
        for u in w.site.current_pms():
            notify_user(u, title, body=body)


def pending_for(user):
    qs = WarningNotice.objects.filter(status="PENDING").select_related(
        "site", "employee", "raised_by")
    return [w for w in qs if can_approve(user, w)]


def unserved_for(user, hours=None):
    """Approved warnings not served within 48 hours of approval or printing —
    the site team's to chase."""
    from .signed_sheets import OVERDUE_HOURS
    if user.role not in RECORD_ROLES:
        return []
    cut = timezone.now() - timedelta(hours=hours or OVERDUE_HOURS)
    qs = scoped(user).filter(status="APPROVED").filter(
        Q(printed_at__lte=cut) | Q(printed_at__isnull=True,
                                   decided_at__lte=cut))
    return [w for w in qs if _site_ok(user, w.site)]


def eligible_workers(site, day):
    """Who can be warned at a site on a date: everyone on it that day,
    direct and subcontract alike."""
    ids = EmployeeSiteAllocation.objects.filter(
        site=site, from_date__lte=day).filter(
        Q(to_date__isnull=True) | Q(to_date__gte=day)).values_list(
        "employee_id", flat=True)
    return (Employee.objects.filter(id__in=ids)
            .select_related("job_category", "subcontractor")
            .order_by("engagement_type", "emp_no"))

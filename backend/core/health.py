"""Worker health log (SOP-HR-04, owner 2026-10-10).

Sites are on islands with limited or no medical facilities, so delay can cost
a life. The log exists so that no complaint is lost, every one is attended to
the same day, the referral ladder is followed, and the people who fall sick
again and again are seen before something unfortunate happens.

The ladder, from the SOP:
  first complaint      → first aid on site, checked again evening and morning
  2nd of the same in 7 days, sick over 2 days, or fever
                       → resort doctor / nearest island health centre, today
  3rd, no improvement, or the doctor refers on
                       → Malé within 24 hours
  any red-flag sign    → emergency evacuation now, no approval needed
A worker returns only with a doctor's clearance after a referral or fever,
and is checked on at day 3 and day 7 after return.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .audit import audit
from .models import (Attendance, CompanyParameter, Employee, HealthAlert,
                     HealthCase, HealthEvent, Site, User)
from .notify import notify_user

# Anyone who marks attendance records health (owner 2026-10-10): the site
# team, its PM, HR, the Director, Admin and the PA.
RECORDER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "DIRECTOR",
                  "ADMIN", "PA"}
# The medical profile (blood group, conditions, allergies, medication) is
# head-office business plus the PM who has the man on his site.
PROFILE_HO_ROLES = {"HO_HR", "DIRECTOR", "ADMIN"}
HO_READ_ROLES = {"HO_HR", "DIRECTOR", "ADMIN", "PA", "SIGNATORY", "FINANCE"}

DEFAULTS = {"health_repeat_cases": 3, "health_repeat_days": 90,
            "health_outbreak_cases": 5, "health_outbreak_days": 7,
            "health_outbreak_quiet_days": 14}
# Any suspected dengue is treated as a possible outbreak (SOP §E.32).
DENGUE_CLUSTER = 1
SAME_COMPLAINT_DAYS = 7      # "2nd complaint of the same problem in 7 days"
SICK_DAYS_TO_REFER = 2       # "sick for more than 2 days"
ATTEND_WITHIN_HOURS = 24     # "no case left without follow-up for 24 hours"
FOLLOW_UP_DAYS = (3, 7)      # checks after return


def param(key):
    try:
        v = CompanyParameter.objects.get(key=key).value
        return int(str(v).strip())
    except (CompanyParameter.DoesNotExist, ValueError, TypeError):
        return DEFAULTS[key]


def can_record(user):
    return user.role in RECORDER_ROLES


def sees_profile(user, employee):
    if user.role in PROFILE_HO_ROLES:
        return True
    if user.role != "PM":
        return False
    site_id = employee.current_site_id()
    if not site_id:
        return False
    site = Site.objects.filter(pk=site_id).first()
    return bool(site and site.is_current_pm(user))


def _next_ref(site):
    n = HealthCase.objects.filter(site=site).count() + 1
    while True:
        ref = f"HLT-{site.code}-{n:03d}"
        if not HealthCase.objects.filter(ref=ref).exists():
            return ref
        n += 1


# ---- cases ----------------------------------------------------------------------

@transaction.atomic
def open_case(*, employee, site, user, reported_on=None, complaint="UNKNOWN",
              symptoms="", started_on=None, temperature=None, red_flag=False,
              source="REPORT", incident=None):
    """Open a case, or return the man's case that is already open.

    A man marked sick three mornings running is one illness, not three; the
    attendance hook and the site both land on the same case. A later report
    that names the complaint fills in a case opened as "not yet recorded".
    Returns (case, created)."""
    reported_on = reported_on or timezone.localdate()
    existing = (HealthCase.objects.filter(employee=employee, status="OPEN")
                .order_by("-reported_on").first())
    if existing is not None:
        changed = []
        if existing.complaint == "UNKNOWN" and complaint != "UNKNOWN":
            existing.complaint = complaint
            changed.append("complaint")
        if symptoms and not existing.symptoms:
            existing.symptoms = symptoms
            changed.append("symptoms")
        if temperature is not None and existing.temperature is None:
            existing.temperature = temperature
            changed.append("temperature")
        if red_flag and not existing.red_flag:
            existing.red_flag = True
            changed.append("red_flag")
        # a sick mark on an earlier day than the case was logged: the
        # illness began then, and the sick days count from then
        if reported_on < existing.reported_on:
            existing.reported_on = reported_on
            changed.append("reported_on")
        if changed:
            existing.save(update_fields=changed)
            _check_cluster(existing)
            if "red_flag" in changed:
                _notify_red_flag(existing, user)
        return existing, False
    case = HealthCase.objects.create(
        ref=_next_ref(site), employee=employee, site=site,
        reported_on=reported_on, reported_by=user, complaint=complaint,
        symptoms=(symptoms or "").strip(), started_on=started_on,
        temperature=temperature, red_flag=bool(red_flag), source=source,
        incident=incident)
    # The complaint is a category, never the symptoms — those are medical
    # detail and stay off the audit trail.
    audit("health", case.id, "HEALTH_CASE_OPENED", actor=user,
          detail={"ref": case.ref, "emp": employee.emp_no, "site": site.code,
                  "complaint": complaint, "source": source,
                  "red_flag": bool(red_flag)})
    _check_cluster(case)
    if red_flag:
        _notify_red_flag(case, user)
    return case, True


def case_from_attendance(record, user):
    """A SICK mark on the register opens the man's case (source ATTENDANCE),
    or joins the one already open. Returns the case if one was opened."""
    if record.remark != "SICK":
        return None
    case, created = open_case(employee=record.employee, site=record.site,
                              user=user, reported_on=record.day,
                              source="ATTENDANCE")
    return case if created else None


def case_from_incident(incident, person, user):
    """An injured employee on an HSE incident gets a health case, so the
    treatment and the return to work are followed in one place (SOP §2)."""
    if person.involvement != "INJURED" or not person.employee_id:
        return None
    doc = incident.document
    detail = ", ".join(x for x in (person.injury, person.body_part) if x)
    case, _ = open_case(employee=person.employee, site=doc.site, user=user,
                        reported_on=incident.occurred_at.date(),
                        complaint="INJURY", symptoms=detail,
                        source="INCIDENT", incident=incident)
    return case


def _site_people(site, roles=()):
    seen, out = set(), []
    for u in list(site.current_pms()) + list(User.objects.filter(
            role__in=roles, is_active=True)):
        if u.is_active and u.id not in seen:
            seen.add(u.id)
            out.append(u)
    return out


def _tell(people, title, body, actor=None):
    for u in people:
        if actor is not None and u.id == actor.id:
            continue
        notify_user(u, title, body, category="alert")


def _notify_red_flag(case, actor):
    _tell(_site_people(case.site, ("DIRECTOR", "ADMIN")),
          f"RED FLAG — {case.employee.full_name} at {case.site.code}",
          "Emergency evacuation now, by the fastest means. No approval is "
          "needed to start it. Inform the MD and Director by phone.", actor)


@transaction.atomic
def add_event(case, *, kind, user, at=None, detail="", facility="",
              escort="", fit_on=None, light_duties=False):
    """Record a step. Returns (event, error)."""
    if case.status == "CLOSED" and kind not in ("FOLLOW_UP", "NOTE",
                                                "REPORT"):
        return None, "This case is closed — reopen it to add treatment steps."
    if kind not in HealthEvent.Kind.values:
        return None, "Unknown step."
    at = at or timezone.now()
    if kind in HealthEvent.REFERRALS and not escort.strip() \
            and kind != "DOCTOR":
        # A sick, weak or non-local-speaking worker never travels alone to
        # Malé or in an evacuation (SOP §C.23).
        return None, "Name the escort who travels with him."
    ev = HealthEvent.objects.create(
        case=case, kind=kind, at=at, detail=(detail or "").strip(),
        facility=(facility or "").strip()[:160],
        escort=(escort or "").strip()[:120], by=user)
    fields = []
    if kind == "CLEARED":
        case.fit_on = fit_on or at.date()
        case.light_duties = bool(light_duties)
        case.status = "CLOSED"
        case.closed_at = timezone.now()
        case.closed_by = user
        fields += ["fit_on", "light_duties", "status", "closed_at",
                   "closed_by"]
    if kind == "EVACUATED" and not case.red_flag:
        case.red_flag = True
        fields.append("red_flag")
    if fields:
        case.save(update_fields=fields)
    audit("health", case.id, "HEALTH_STEP", actor=user,
          detail={"ref": case.ref, "emp": case.employee.emp_no,
                  "kind": kind})
    if kind == "EVACUATED":
        _tell(_site_people(case.site, ("DIRECTOR", "ADMIN", "HO_HR")),
              f"Evacuation — {case.employee.full_name}, {case.site.code}",
              (facility or detail or "Emergency evacuation under way.")[:200],
              user)
    elif kind == "MALE":
        _tell(_site_people(case.site, ("DIRECTOR", "HO_HR")),
              f"Referred to Malé — {case.employee.full_name}, "
              f"{case.site.code}",
              f"{case.get_complaint_display()}. Escort: {escort or '—'}. "
              f"{facility}"[:200], user)
    elif kind == "DOCTOR":
        _tell(_site_people(case.site),
              f"Seen a doctor — {case.employee.full_name}, {case.site.code}",
              f"{case.get_complaint_display()}. {facility}"[:200], user)
    return ev, None


def needs_clearance(case):
    """A doctor decides when a referred or feverish man works again
    (SOP §F.40)."""
    if case.red_flag or case.complaint in ("FEVER", "DENGUE"):
        return True
    return case.events.filter(kind__in=("DOCTOR", "MALE", "EVACUATED",
                                        "ADMITTED")).exists()


@transaction.atomic
def close_case(case, user, note=""):
    """Close a minor case that never went to a doctor. Returns an error
    string when the ladder says a doctor must clear him first."""
    if case.status == "CLOSED":
        return "Already closed."
    if needs_clearance(case):
        return ("He saw a doctor, or had a fever: record the doctor's "
                "clearance (Cleared by doctor) instead of closing by hand.")
    if not case.events.filter(kind__in=HealthEvent.ATTENDED).exists():
        return "Record what was done for him before closing the case."
    case.status = "CLOSED"
    case.closed_at = timezone.now()
    case.closed_by = user
    case.fit_on = case.fit_on or timezone.localdate()
    case.save(update_fields=["status", "closed_at", "closed_by", "fit_on"])
    if note:
        HealthEvent.objects.create(case=case, kind="NOTE", at=timezone.now(),
                                   detail=note.strip(), by=user)
    audit("health", case.id, "HEALTH_CASE_CLOSED", actor=user,
          detail={"ref": case.ref, "emp": case.employee.emp_no})
    return None


@transaction.atomic
def reopen_case(case, user, reason=""):
    if case.status != "CLOSED":
        return "Not closed."
    case.status = "OPEN"
    case.closed_at = None
    case.closed_by = None
    case.save(update_fields=["status", "closed_at", "closed_by"])
    HealthEvent.objects.create(case=case, kind="NOTE", at=timezone.now(),
                               detail=f"Reopened. {reason}".strip(), by=user)
    audit("health", case.id, "HEALTH_CASE_REOPENED", actor=user,
          detail={"ref": case.ref, "emp": case.employee.emp_no})
    return None


# ---- what the log knows -------------------------------------------------------

def days_sick(case):
    """Sick marks on the register from the report to the clearance."""
    end = case.fit_on or timezone.localdate()
    return Attendance.objects.filter(
        employee_id=case.employee_id, remark="SICK",
        day__gte=case.reported_on, day__lte=end).count()


def earlier_same(case):
    """Earlier cases of the same complaint within the SOP's 7-day window."""
    if case.complaint == "UNKNOWN":
        return 0
    return HealthCase.objects.filter(
        employee_id=case.employee_id, complaint=case.complaint,
        reported_on__gte=case.reported_on - timedelta(days=SAME_COMPLAINT_DAYS),
        reported_on__lte=case.reported_on).exclude(pk=case.pk).count()


def cases_in_window(employee_id, on=None, days=None):
    on = on or timezone.localdate()
    days = days or param("health_repeat_days")
    return HealthCase.objects.filter(
        employee_id=employee_id, reported_on__gt=on - timedelta(days=days),
        reported_on__lte=on).count()


def is_repeat(employee_id, on=None):
    return cases_in_window(employee_id, on) >= param("health_repeat_cases")


def due(case, kinds=None):
    """What the ladder says is due on this case now: (level, text).

    Level 3 is urgent (evacuate / Malé), 2 is today, 1 is housekeeping,
    0 nothing. Computed, so a Focal Point reading the list is told rather
    than left to remember the SOP."""
    kinds = kinds if kinds is not None else set(
        case.events.values_list("kind", flat=True))
    if case.status == "CLOSED":
        if case.fit_on:
            done = sum(1 for k in kinds if k == "FOLLOW_UP")
            today = timezone.localdate()
            for i, d in enumerate(FOLLOW_UP_DAYS):
                if done <= i and today >= case.fit_on + timedelta(days=d):
                    return 1, f"Day-{d} check after return is due"
        return 0, ""
    if case.red_flag and "EVACUATED" not in kinds:
        return 3, "RED FLAG — emergency evacuation now, day or night"
    if not kinds & HealthEvent.ATTENDED:
        age = timezone.now() - case.created_at
        if age.total_seconds() > ATTEND_WITHIN_HOURS * 3600:
            return 3, "Not attended for over 24 hours — act now"
        return 2, "Not yet attended — first aid, check and record today"
    referred = bool(kinds & {"DOCTOR", "MALE", "EVACUATED", "ADMITTED"})
    same = earlier_same(case)
    sick = days_sick(case)
    if "MALE" not in kinds and "EVACUATED" not in kinds:
        if same >= 2 or ("DOCTOR" in kinds and sick > SICK_DAYS_TO_REFER + 2):
            return 3, ("3rd complaint in 7 days / no improvement — "
                       "send to Malé within 24 hours")
    if not referred and (same >= 1 or sick > SICK_DAYS_TO_REFER
                         or case.complaint in ("FEVER", "DENGUE")
                         or case.temperature and case.temperature >= 38):
        why = ("2nd complaint in 7 days" if same >= 1
               else f"sick {sick} days" if sick > SICK_DAYS_TO_REFER
               else "fever")
        return 2, f"{why} — resort doctor / nearest health centre today"
    if referred and "REPORT" not in kinds:
        return 1, "File the doctor's report / certificate"
    if needs_clearance(case):
        return 1, "Returns to work only with the doctor's clearance"
    return 0, ""


# ---- clusters ---------------------------------------------------------------------

def _check_cluster(case):
    """Five of the same complaint at one site in seven days (owner), or any
    suspected dengue (SOP), and the PM, HR and the Director are told —
    once per cluster."""
    if case.complaint in ("UNKNOWN", "INJURY", "PAIN", "OTHER"):
        return None
    days = param("health_outbreak_days")
    threshold = (DENGUE_CLUSTER if case.complaint == "DENGUE"
                 else param("health_outbreak_cases"))
    start = case.reported_on - timedelta(days=days - 1)
    n = HealthCase.objects.filter(site_id=case.site_id,
                                  complaint=case.complaint,
                                  reported_on__gte=start,
                                  reported_on__lte=case.reported_on).count()
    if n < threshold:
        return None
    quiet = param("health_outbreak_quiet_days")
    live = HealthAlert.objects.filter(
        site_id=case.site_id, complaint=case.complaint, closed_on__isnull=True,
        window_end__gte=case.reported_on - timedelta(days=quiet)).first()
    if live is not None:
        live.window_end = max(live.window_end, case.reported_on)
        live.count = HealthCase.objects.filter(
            site_id=case.site_id, complaint=case.complaint,
            reported_on__gte=live.window_start,
            reported_on__lte=live.window_end).count()
        live.save(update_fields=["window_end", "count"])
        return None
    alert = HealthAlert.objects.create(
        site_id=case.site_id, complaint=case.complaint, window_start=start,
        window_end=case.reported_on, count=n)
    label = case.get_complaint_display()
    audit("site", case.site_id, "HEALTH_OUTBREAK_ALERT", actor=None,
          detail={"site": case.site.code, "complaint": case.complaint,
                  "count": n, "days": days})
    _tell(_site_people(case.site, ("HO_HR", "DIRECTOR", "ADMIN")),
          f"Possible outbreak at {case.site.code}: {label}",
          (f"{n} case{'s' if n != 1 else ''} in {days} days. Separate the "
           "sick in the sick bay, every one sees a doctor, inform the "
           "client's representative and the resort today (SOP-HR-04 §E)."))
    return alert


def sweep_alerts(today=None):
    """An outbreak is over when no new case has appeared for the quiet
    period (14 days). Run daily."""
    today = today or timezone.localdate()
    quiet = param("health_outbreak_quiet_days")
    closed = 0
    for a in HealthAlert.objects.filter(closed_on__isnull=True):
        last = HealthCase.objects.filter(
            site_id=a.site_id, complaint=a.complaint).order_by(
            "-reported_on").values_list("reported_on", flat=True).first()
        if last and today - last >= timedelta(days=quiet):
            a.closed_on = today
            a.save(update_fields=["closed_on"])
            closed += 1
    return closed


def active_alerts(site_ids=None):
    qs = HealthAlert.objects.filter(closed_on__isnull=True).select_related(
        "site").order_by("-window_end")
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    return qs


# ---- lists -------------------------------------------------------------------------

def _scoped(qs, site_ids):
    return qs if site_ids is None else qs.filter(site_id__in=site_ids)


def unattended(site_ids=None):
    """Open cases nobody has done anything about yet."""
    qs = HealthCase.objects.filter(status="OPEN").exclude(
        events__kind__in=HealthEvent.ATTENDED)
    return _scoped(qs, site_ids).select_related("employee", "site").distinct()


def to_attend_items(user):
    """My Tasks: the site's own sickness reports waiting to be attended."""
    if user.role not in RECORDER_ROLES:
        return []
    from .permissions import scoped_site_ids
    out = []
    for c in unattended(scoped_site_ids(user)).order_by("reported_on")[:50]:
        level, text = due(c)
        out.append({"ref": c.ref, "doc_type": "HLT", "site_code": c.site.code,
                    "project_code": None, "doc_date": c.reported_on,
                    "status": c.status, "case_id": c.id,
                    "hint": f"{c.employee.full_name} — {text}"})
    return out


def repeat_list(site_ids=None, on=None):
    """Men with three or more cases in 90 days (owner's thresholds): the
    ones to see properly before an unfortunate incident."""
    on = on or timezone.localdate()
    days, floor = param("health_repeat_days"), param("health_repeat_cases")
    qs = _scoped(HealthCase.objects.filter(
        reported_on__gt=on - timedelta(days=days), reported_on__lte=on),
        site_ids)
    rows = (qs.values("employee_id").annotate(n=Count("id"))
            .filter(n__gte=floor).order_by("-n"))
    emp_ids = [r["employee_id"] for r in rows]
    emps = {e.id: e for e in Employee.objects.filter(pk__in=emp_ids)}
    out = []
    for r in rows:
        e = emps.get(r["employee_id"])
        if e is None:
            continue
        cases = list(HealthCase.objects.filter(
            employee=e, reported_on__gt=on - timedelta(days=days))
            .select_related("site").order_by("-reported_on"))
        out.append({
            "employee_id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
            "site_code": cases[0].site.code if cases else "",
            "cases": r["n"], "days": days,
            "last_on": cases[0].reported_on if cases else None,
            "open": any(c.status == "OPEN" for c in cases),
            "complaints": sorted({c.get_complaint_display() for c in cases}),
        })
    return out


def repeat_flags(employee_ids, on=None):
    """{employee_id: cases in the repeat window} for those at or over the
    floor — a chip on the register and the pickers."""
    on = on or timezone.localdate()
    days, floor = param("health_repeat_days"), param("health_repeat_cases")
    rows = (HealthCase.objects.filter(
        employee_id__in=list(employee_ids),
        reported_on__gt=on - timedelta(days=days), reported_on__lte=on)
        .values("employee_id").annotate(n=Count("id")).filter(n__gte=floor))
    return {r["employee_id"]: r["n"] for r in rows}


def follow_ups_due(site_ids=None):
    """Closed cases whose day-3 / day-7 check after return is due."""
    today = timezone.localdate()
    qs = _scoped(HealthCase.objects.filter(
        status="CLOSED", fit_on__isnull=False,
        fit_on__gte=today - timedelta(days=FOLLOW_UP_DAYS[-1] + 14),
        fit_on__lte=today - timedelta(days=FOLLOW_UP_DAYS[0])), site_ids)
    out = []
    for c in qs.select_related("employee", "site"):
        level, text = due(c)
        if level:
            out.append((c, text))
    return out


def summary(site_ids=None, days=30):
    today = timezone.localdate()
    since = today - timedelta(days=days)
    open_qs = _scoped(HealthCase.objects.filter(status="OPEN"), site_ids)
    unatt = unattended(site_ids)
    overdue = sum(1 for c in unatt
                  if (timezone.now() - c.created_at).total_seconds()
                  > ATTEND_WITHIN_HOURS * 3600)
    referred = open_qs.filter(events__kind__in=("DOCTOR", "MALE", "EVACUATED",
                                                "ADMITTED")).distinct().count()
    recent = _scoped(HealthCase.objects.filter(reported_on__gte=since),
                     site_ids)
    by_complaint = [{"complaint": r["complaint"],
                     "label": HealthCase.Complaint(r["complaint"]).label,
                     "n": r["n"]}
                    for r in recent.values("complaint").annotate(n=Count("id"))
                    .order_by("-n")]
    return {
        "open": open_qs.count(), "unattended": unatt.count(),
        "overdue": overdue, "referred_out": referred,
        "new_today": recent.filter(reported_on=today).count(),
        "last_days": days, "cases_last_days": recent.count(),
        "by_complaint": by_complaint,
        "repeat": len(repeat_list(site_ids)),
        "follow_ups_due": len(follow_ups_due(site_ids)),
        "alerts": [{"id": a.id, "site_code": a.site.code,
                    "complaint": a.complaint,
                    "label": HealthCase.Complaint(a.complaint).label,
                    "count": a.count, "since": a.window_start,
                    "last": a.window_end}
                   for a in active_alerts(site_ids)],
    }


def daily_summary(today=None):
    """SOP §B.17: the daily health summary goes to the Site PM and the
    Director every day, even when there are no cases. One line per site to
    its PMs; one consolidated note to the Director and HR."""
    today = today or timezone.localdate()
    lines, sent = [], 0
    for site in Site.objects.filter(status=Site.Status.ACTIVE).order_by("code"):
        s = summary([site.id])
        if not (s["open"] or s["cases_last_days"] or s["alerts"]
                or site.employee_allocations.filter(
                    to_date__isnull=True).exists()):
            continue
        text = (f"{site.code}: {s['new_today']} new, {s['open']} open, "
                f"{s['unattended']} not yet attended"
                + (f", {s['overdue']} over 24h" if s["overdue"] else "")
                + (f", {s['referred_out']} with a doctor" if s["referred_out"]
                   else "")
                + (f", OUTBREAK: {', '.join(a['label'] for a in s['alerts'])}"
                   if s["alerts"] else ""))
        lines.append(text)
        for pm in site.current_pms():
            if pm.is_active:
                notify_user(pm, f"Health today — {site.code}", text,
                            category="alert")
                sent += 1
    body = "; ".join(lines) if lines else "No cases on any site."
    for u in User.objects.filter(role__in=("DIRECTOR", "HO_HR"),
                                 is_active=True):
        notify_user(u, f"Daily health summary — {today:%d %b}", body[:300],
                    category="alert")
        sent += 1
    return sent

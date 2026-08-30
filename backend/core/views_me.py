"""What a person may see about themselves.

Every other HR and payroll endpoint answers "who is allowed to look at this
employee?". These answer a narrower question — "what is MY record?" — and the
narrowness is the security model: nothing here takes an employee id, from a
URL, a query string or a body. The record is always
`request.user.employee`, so there is no parameter to tamper with and no way
to walk from your own payslip to somebody else's (owner 2026-08-30, once
logins were linked to employee records).

Two rules beyond that:

  * only LOCKED payroll runs. A draft figure is a working number that the PM
    and the Director have not signed, and showing a man a number that later
    moves is worse than showing him nothing.
  * salary is his own, so it is his to see. The staff-pay privacy rule that
    hides MANAGEMENT pay from site roles is about looking at OTHER people;
    it has never meant a man cannot see his own wage.
"""
import logging
import re
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import PayrollLine, SalaryAdvance, WorkerLeave
from .payroll import RECOVERABLE_ADVANCE_STATUSES, compute_line, q
from .payroll_settlement import outstanding_balance

log = logging.getLogger(__name__)

NOT_LINKED = {
    "detail": "Your login isn't linked to an employee record yet. "
              "Ask HR to link it and this page will fill in.",
    "linked": False,
}


def _me(request):
    return getattr(request.user, "employee", None)


# How long a PIN keeps the pay visible. Short on purpose: the screen is meant
# to be opened, read and closed, and a window long enough to forget about is
# a window that outlives the person looking at it.
UNLOCK_SECONDS = 180
SESSION_KEY = "salary_unlocked_until"
FAILS_KEY = "salary_pin_fails"
MAX_FAILS = 5
LOCKOUT_MINUTES = 15
LOCKOUT_KEY = "salary_pin_locked_until"


def _now():
    return timezone.now()


def _unlocked_until(request):
    """When the current unlock expires, or None. The clock is the server's —
    a client that keeps its own countdown is a client that can be told to
    stop counting."""
    raw = request.session.get(SESSION_KEY)
    if not raw:
        return None
    try:
        when = timezone.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return when if when > _now() else None


def _has_pin(request):
    return bool(request.user.salary_pin)


def _locked_out(request):
    raw = request.session.get(LOCKOUT_KEY)
    if not raw:
        return None
    try:
        when = timezone.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return when if when > _now() else None


def _money_gate(request):
    """None if the pay may be shown, else the response explaining why not.

    Pay is hidden by DEFAULT, not on request (owner 2026-08-30). An opt-in
    screen protects the people who think to switch it on, which is not the
    person carrying a shared site tablet. Setting a PIN — which costs the
    account password — is what opens it the first time."""
    has = _has_pin(request)
    # An open window is only good while the PIN behind it still exists: if
    # the PIN is cleared or reset out from under a session, that session's
    # remaining minutes should not keep the pay on screen.
    if has and _unlocked_until(request):
        return None
    return Response({
        "detail": ("Enter your PIN to see your pay." if has
                   else "Your pay is hidden. Create a PIN to see it."),
        "pin_required": True, "has_pin": has, "linked": True}, status=403)


def _weak(pin):
    if not re.fullmatch(r"\d{4,6}", pin or ""):
        return "A PIN is 4 to 6 digits."
    if len(set(pin)) == 1:
        return "That PIN is all one digit — pick another."
    runs = "01234567890" 
    if pin in runs or pin in runs[::-1]:
        return "That PIN is a run of digits — pick another."
    return None


@api_view(["GET"])
def my_profile(request):
    """The signed-in person's own employment record."""
    e = _me(request)
    if e is None:
        return Response(NOT_LINKED, status=200)

    site = None
    alloc = e.site_allocations.filter(to_date__isnull=True).select_related(
        "site").first()
    if alloc:
        site = {"code": alloc.site.code, "name": alloc.site.name,
                "since": alloc.from_date}

    return Response({
        "linked": True,
        "employment": {
            "emp_no": e.emp_no, "full_name": e.full_name,
            "photo": e.photo.url if e.photo else None,
            "job_category": e.job_category.name if e.job_category_id else "",
            "employment_type": e.employment_type,
            "engagement_type": e.engagement_type,
            "join_date": e.join_date, "is_active": e.is_active,
            "left_on": e.left_on, "site": site,
            "nationality": e.nationality,
        },
        # The dates that decide whether he can legally keep working. Showing
        # them to the man himself is the cheapest expiry reminder there is.
        "documents": {
            "passport_no": e.passport_no,
            "passport_expiry": e.passport_expiry,
            "work_permit_no": e.work_permit_no,
            "work_permit_expiry": e.work_permit_expiry,
            "visa_number": e.work_visa_number,
            "medical_expiry": e.medical_expiry,
            "insurance_expiry": e.insurance_expiry,
        },
        # Pay is the part worth hiding, so it is withheld on its own — the
        # employment and document sections stay readable behind the PIN,
        # which is what makes the gate tolerable to live with.
        "pay_locked": _money_gate(request) is not None,
        "pay": None if _money_gate(request) is not None else {
            "basic_pay": e.basic_pay, "currency": e.currency,
            "usd_basic_pay": e.usd_basic_pay,
            "ot_rate": e.ot_rate(), "ot_applies": e.ot_applies,
        },
    })


@api_view(["GET"])
def my_pin(request):
    """Whether a PIN is set, and how long the pay is currently visible."""
    until = _unlocked_until(request)
    return Response({
        "has_pin": _has_pin(request),
        "unlocked_until": until,
        "seconds_left": int((until - _now()).total_seconds()) if until else 0,
        "window_seconds": UNLOCK_SECONDS,
        "locked_out_until": _locked_out(request),
    })


@api_view(["POST"])
def set_my_pin(request):
    """Set or change the PIN on your own pay.

    Always costs the account password, even when only changing it: a session
    left open on a site tablet is exactly what the PIN defends against, so
    that session must not be able to quietly rewrite it. Requiring the
    password is also the forgotten-PIN path — there is no separate reset, and
    no way to switch the gate off, because the pay is hidden by default."""
    password = request.data.get("password") or ""
    if not request.user.check_password(password):
        return Response({"detail": "That password is not right."}, status=400)

    pin = (request.data.get("pin") or "").strip()
    bad = _weak(pin)
    if bad:
        return Response({"detail": bad}, status=400)
    request.user.salary_pin = make_password(pin)
    request.user.salary_pin_set_at = _now()
    request.user.save(update_fields=["salary_pin", "salary_pin_set_at"])
    request.session.pop(FAILS_KEY, None)
    request.session.pop(LOCKOUT_KEY, None)
    # Setting a PIN leaves the pay visible for the usual window, so the person
    # is not immediately locked out of the screen they were just on.
    request.session[SESSION_KEY] = (
        _now() + timedelta(seconds=UNLOCK_SECONDS)).isoformat()
    return Response({"has_pin": True, "window_seconds": UNLOCK_SECONDS})


@api_view(["POST"])
def unlock_my_pay(request):
    """Open the pay for one short window."""
    if not _has_pin(request):
        return Response({"detail": "No PIN is set yet — create one to see "
                                   "your pay."}, status=400)
    out = _locked_out(request)
    if out:
        return Response({"detail": "Too many wrong PINs. Try again later.",
                         "locked_out_until": out}, status=429)

    pin = (request.data.get("pin") or "").strip()
    if not check_password(pin, request.user.salary_pin):
        fails = int(request.session.get(FAILS_KEY, 0)) + 1
        request.session[FAILS_KEY] = fails
        if fails >= MAX_FAILS:
            request.session[LOCKOUT_KEY] = (
                _now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            request.session[FAILS_KEY] = 0
            return Response({"detail": "Too many wrong PINs. Try again in "
                                       f"{LOCKOUT_MINUTES} minutes."},
                            status=429)
        return Response({"detail": "Wrong PIN.",
                         "attempts_left": MAX_FAILS - fails}, status=400)

    request.session[FAILS_KEY] = 0
    until = _now() + timedelta(seconds=UNLOCK_SECONDS)
    request.session[SESSION_KEY] = until.isoformat()
    return Response({"unlocked_until": until,
                     "seconds_left": UNLOCK_SECONDS,
                     "window_seconds": UNLOCK_SECONDS})


@api_view(["POST"])
def lock_my_pay(request):
    """Close it now, without waiting for the timer."""
    request.session.pop(SESSION_KEY, None)
    return Response({"unlocked_until": None, "seconds_left": 0})


@api_view(["GET"])
def my_payslips(request):
    """Every locked run this person has been paid on, newest first."""
    e = _me(request)
    if e is None:
        return Response(NOT_LINKED, status=200)
    gate = _money_gate(request)
    if gate is not None:
        return gate

    rows = []
    for line in PayrollLine.objects.filter(
            employee=e, run__status="LOCKED").select_related(
            "run", "site").order_by("-run__year", "-run__month", "-id"):
        money = compute_line(line)
        rows.append({
            "line_id": line.id, "year": line.run.year,
            "month": line.run.month, "currency": line.run.currency,
            "kind": line.run.kind, "site": line.site.code if line.site_id else "",
            "days_worked": line.days_worked, "ot_hours": line.ot_hours,
            "fridays_worked": line.fridays_worked,
            "excluded": line.excluded,
            "excluded_reason": line.excluded_reason,
            "gross": money["gross"], "deductions": money["deductions"],
            "net": money["net"],
        })
    return Response({"linked": True, "payslips": rows})


@api_view(["GET"])
def my_payslip_pdf(request, pk):
    """One of this person's own payslips.

    Scoped by employee AND by locked status in the same query, so a guessed
    id returns 404 rather than somebody else's wage."""
    e = _me(request)
    if e is None:
        return Response({"detail": NOT_LINKED["detail"]}, status=403)
    gate = _money_gate(request)
    if gate is not None:
        return gate
    try:
        line = PayrollLine.objects.select_related(
            "run", "employee__job_category", "site").get(
            pk=pk, employee=e, run__status="LOCKED")
    except PayrollLine.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)

    from django.template.loader import render_to_string

    from .views_payroll import _pdf_response, _slip_context

    html = render_to_string("pdf/payslip.html",
                            _slip_context(line, register=None))
    return _pdf_response(html, f"payslip-{line.employee.emp_no}-"
                               f"{line.run.year}-{line.run.month:02d}.pdf")


@api_view(["GET"])
def my_money(request):
    """Advances and loans: what was taken, and what is still owed."""
    e = _me(request)
    if e is None:
        return Response(NOT_LINKED, status=200)
    gate = _money_gate(request)
    if gate is not None:
        return gate

    rows = []
    for a in SalaryAdvance.objects.filter(
            employee=e,
            document__status__in=RECOVERABLE_ADVANCE_STATUSES).select_related(
            "document").order_by("-period_year", "-period_month"):
        n = max(a.months, 1)
        rows.append({"ref": a.document.ref, "kind": a.kind,
                     "amount": a.amount, "months": n,
                     "installment": q(a.amount / n),
                     "from_period": f"{a.period_year}-{a.period_month:02d}"})
    return Response({"linked": True, "advances": rows,
                     "outstanding": outstanding_balance(e)})


@api_view(["GET"])
def my_leave(request):
    e = _me(request)
    if e is None:
        return Response(NOT_LINKED, status=200)
    rows = [{"kind": lv.kind, "from_date": lv.from_date,
             "to_date": lv.to_date, "returned_on": lv.returned_on,
             "reason": lv.reason}
            for lv in WorkerLeave.objects.filter(employee=e)
            .order_by("-from_date")[:24]]
    return Response({"linked": True, "leave": rows})

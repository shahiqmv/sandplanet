"""Subcontractor lifecycle + site-level team management (subcontractor module,
Phase 2). Site-managed: the SA/SE create and staff subcontractors; PM→Director
activate; HR/HO have no management role. A subcontract worker is an Employee
(engagement_type SUBCONTRACT), kept out of payroll structurally (Phase 1)."""
import logging
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .audit import audit
from .models import Employee, EmployeeSiteAllocation, Subcontractor
from .numbering import next_ref

log = logging.getLogger(__name__)

SITE_MANAGE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN")
_FIELDS = ("name", "registration_no", "address", "contact_person", "phone",
           "signatory_name", "signatory_title", "bank_details", "notes")


def create_subcontractor(site, data, actor):
    if not (data.get("name") or "").strip():
        return None, "A subcontractor name is required."
    sub = Subcontractor.objects.create(
        site=site, created_by=actor,
        **{f: (data.get(f) or "") for f in _FIELDS})
    audit("subcontractor", sub.id, "SUB_CREATED", actor=actor,
          detail={"name": sub.name, "site": site.code})
    return sub, None


def update_subcontractor(sub, data, actor):
    if sub.status != Subcontractor.Status.DRAFT:
        return "Only a draft subcontractor can be edited."
    for f in _FIELDS:
        if f in data:
            setattr(sub, f, data.get(f) or "")
    sub.save()
    return None


def approve_subcontractor(sub, actor):
    """PM approves a Draft → PM_APPROVED; Director activates that → Approved."""
    S = Subcontractor.Status
    role = actor.role
    if sub.status == S.DRAFT:
        if role not in ("PM", "ADMIN"):
            return "A draft subcontractor is approved by the site PM."
        sub.status = S.PM_APPROVED
    elif sub.status == S.PM_APPROVED:
        if role not in ("DIRECTOR", "ADMIN"):
            return "A PM-approved subcontractor is activated by a Director."
        sub.status = S.APPROVED
    else:
        return f"Cannot approve a {sub.get_status_display()} subcontractor."
    sub.save(update_fields=["status", "updated_at"])
    audit("subcontractor", sub.id, "SUB_APPROVED", actor=actor,
          to_state=sub.status, detail={"name": sub.name})
    from . import notify
    notify.notify_subcontractor(sub, actor)
    return None


def return_subcontractor(sub, actor, reason=""):
    if sub.status not in (Subcontractor.Status.PM_APPROVED,
                          Subcontractor.Status.DRAFT):
        return "Only a pending subcontractor can be returned."
    sub.status = Subcontractor.Status.DRAFT
    sub.save(update_fields=["status", "updated_at"])
    audit("subcontractor", sub.id, "SUB_RETURNED", actor=actor,
          detail={"reason": reason})
    return None


def set_subcontractor_status(sub, status, actor):
    """Suspend / close / reactivate — a PM+ control (per §3.1)."""
    S = Subcontractor.Status
    if status not in (S.SUSPENDED, S.CLOSED, S.ACTIVE, S.APPROVED):
        return "Invalid status."
    if actor.role not in ("PM", "DIRECTOR", "ADMIN"):
        return "Suspend / close requires PM approval."
    # Re-opening a CLOSED group is an admin-level correction (owner
    # 2026-08-11) — closure ends the engagement; only an administrator
    # reverses a mistaken close.
    if sub.status == S.CLOSED and actor.role != "ADMIN":
        return "Only an administrator can re-open a closed subcontractor."
    sub.status = status
    sub.save(update_fields=["status", "updated_at"])
    audit("subcontractor", sub.id, "SUB_STATUS", actor=actor, to_state=status)
    return None


# ---- team management ---------------------------------------------------------

def add_worker(sub, data, actor):
    """SA/SE adds a worker under an Approved subcontractor. The worker starts
    inactive + pending, so it stays out of every attendance roster + manpower
    count until the PM approves it."""
    if not sub.can_raise_sca:
        return None, "Workers can only be added under an approved subcontractor."
    if not (data.get("full_name") or "").strip():
        return None, "The worker's name is required."
    from .models import passport_holder
    held = passport_holder(data.get("passport_no"))
    if held is not None:
        return None, (f"Passport {data.get('passport_no').strip()} is already "
                      f"on {held.emp_no} {held.full_name}.")
    with transaction.atomic():
        n = int(next_ref("EMP", None).split("-")[1])
        emp = Employee.objects.create(
            emp_no=f"EMP-{n:04d}", full_name=data["full_name"].strip(),
            passport_no=data.get("passport_no", ""),
            nationality=data.get("nationality", ""),
            job_category_id=data.get("job_category_id") or None,
            emergency_contact=data.get("emergency_contact", ""),
            engagement_type=Employee.Engagement.SUBCONTRACT, subcontractor=sub,
            is_active=False, sub_pending=True)
        EmployeeSiteAllocation.objects.create(
            employee=emp, site=sub.site, from_date=date.today())
    audit("employee", emp.id, "SUB_WORKER_ADDED", actor=actor,
          detail={"sub": sub.name, "name": emp.full_name})
    return emp, None


def take_on_directly(emp, data, actor):
    """Take a subcontractor's man onto our own payroll.

    It happens the other way round from how the record was made: a man comes
    in on a subcontractor's business visa, works a few days, and is good
    enough that we hire him ourselves (owner 2026-09-10, EMP-0809). Until now
    `engagement_type` was written once at creation and never again, so the
    only way through was editing the row by hand — no record of who decided
    it, or when he stopped being someone else's man.

    A subcontract worker deliberately carries no pay and is structurally
    barred from payroll, so becoming DIRECT is not a flag flip: he needs a
    salary and a category before he is a payable employee at all, and this
    refuses to make a half-built one.

    `join_date` is when OUR employment starts, which is not always when he
    arrived — a man who worked six months for the subcontractor first joins
    us today. Left out, the date already on the record stands.
    """
    from decimal import Decimal, InvalidOperation

    from .models import Employee

    if emp.engagement_type != Employee.Engagement.SUBCONTRACT:
        return "This worker is already a direct employee."
    if emp.sub_pending:
        return ("This worker is still awaiting the PM's approval as a "
                "subcontract worker. Approve or remove him first.")
    try:
        pay = Decimal(str(data.get("basic_pay") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return "Enter the basic pay as a number."
    if pay <= 0:
        return ("A direct employee needs a basic pay — a subcontract worker "
                "carries none, and without one his payroll line is zero.")
    category_id = data.get("job_category_id") or emp.job_category_id
    if not category_id:
        return ("Pick the worker category. It is what the manpower reports "
                "count him under and what his overtime rate comes from.")
    employment = data.get("employment_type") or Employee.EmploymentType.CONTRACT
    if employment not in dict(Employee.EmploymentType.choices):
        return "Unknown employment type."
    join = data.get("join_date") or None

    was = emp.subcontractor.name if emp.subcontractor_id else ""
    fields = ["engagement_type", "subcontractor", "basic_pay", "job_category",
              "employment_type", "currency", "updated_at"]
    with transaction.atomic():
        emp.engagement_type = Employee.Engagement.DIRECT
        emp.subcontractor = None
        emp.basic_pay = pay
        emp.job_category_id = category_id
        emp.employment_type = employment
        emp.currency = data.get("currency") or emp.currency or "MVR"
        if join:
            emp.join_date = join
            fields.append("join_date")
        emp.save(update_fields=fields)
        # The onboarding case that brought him in said he was somebody else's
        # worker. Leaving it saying so would have the visa file and the
        # employee record disagreeing about who he works for.
        from .models import OnboardingCase
        # `employee` is related_name="+" — there is no reverse accessor, so
        # this has to be queried or it silently does nothing.
        for case in OnboardingCase.objects.filter(employee=emp,
                                                  bv_purpose="SUBCONTRACT"):
            # A subcontract business visa ENDS on arrival; a recruitment one
            # carries the in-country BV→WP conversion tail (`sequence()`). So
            # this is not bookkeeping — it is what lets HR go on and apply for
            # his work permit (owner 2026-09-10).
            case.bv_purpose = "RECRUITMENT"
            case.subcontractor = None
            # A recruitment case must carry the proposed salary — it goes on
            # the appointment letter — and it is the same figure we just put
            # on his record. Leaving it empty would make the case invalid the
            # moment anyone touched it.
            case.proposed_salary = pay
            case.currency = emp.currency
            if not case.job_category_id:
                case.job_category_id = category_id
            case.save(update_fields=["bv_purpose", "subcontractor",
                                     "proposed_salary", "currency",
                                     "job_category", "updated_at"])
    # No pay in the detail (spec §7.2) — that it changed is the record.
    audit("employee", emp.id, "TAKEN_ON_DIRECTLY", actor=actor,
          detail={"emp_no": emp.emp_no, "from_subcontractor": was,
                  "employment_type": employment,
                  "join_date": str(emp.join_date or ""),
                  "why": "engaged through a subcontractor, hired directly"})
    return None


def approve_worker(emp, actor):
    """PM approval activates a pending subcontract worker — it now appears in
    the site attendance register + manpower count."""
    if not emp.sub_pending:
        return "This worker is not pending approval."
    emp.sub_pending = False
    emp.is_active = True
    emp.save(update_fields=["sub_pending", "is_active", "updated_at"])
    audit("employee", emp.id, "SUB_WORKER_APPROVED", actor=actor)
    return None


def remove_worker(emp, actor):
    """Immediate deactivation with an audit entry (no approval needed)."""
    emp.is_active = False
    emp.sub_pending = False
    emp.save(update_fields=["is_active", "sub_pending", "updated_at"])
    audit("employee", emp.id, "SUB_WORKER_REMOVED", actor=actor)
    return None


# ---- Subcontract Agreements (SCA) --------------------------------------------
# An SCA is a Document subtype (doc_type SCA) headed by SubcontractAgreement,
# exactly the way an IPR is headed by ImportOrder. Lifecycle DRAFT→SUBMITTED→
# PM_APPROVED→APPROVED runs on the generic Document approval engine
# (views_documents._do_submit/_do_approve/_do_return); this module owns only
# creation + draft editing of the header and its priced scope.

def _dec(v):
    from decimal import Decimal, InvalidOperation
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _scope_items(agreement, rows):
    """(unsaved) SubcontractScopeItem instances from cleaned dict rows. A row
    with no qty, rate or unit is a heading."""
    from .models import SubcontractScopeItem
    out = []
    for i, r in enumerate(rows):
        desc = str(r.get("description") or "").strip()
        section = str(r.get("section") or "").strip()
        code = str(r.get("item_code") or "").strip()
        unit = str(r.get("unit") or "").strip()
        if not (desc or section or code):
            continue
        qty, rate = _dec(r.get("qty")), _dec(r.get("rate"))
        is_heading = bool(r.get("is_heading")) or (
            qty is None and rate is None and not unit)
        out.append(SubcontractScopeItem(
            agreement=agreement, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate=rate,
            is_heading=is_heading))
    return out


def _set_scope(agreement, rows):
    from .models import SubcontractScopeItem
    items = _scope_items(agreement, rows)
    agreement.items.all().delete()
    SubcontractScopeItem.objects.bulk_create(items)
    return len(items)


def create_sca(sub, data, actor):
    """Draft a Subcontract Agreement under an approved subcontractor."""
    from datetime import date

    from .models import (Document, DocumentRevision, Project,
                         SubcontractAgreement)
    from .numbering import next_ref
    if not sub.can_raise_sca:
        return None, "Only an approved subcontractor can hold an agreement."
    if not (data.get("title") or "").strip():
        return None, "Give the agreement a title."
    project = None
    if data.get("project_id"):
        project = Project.objects.filter(pk=data["project_id"],
                                         site=sub.site).first()
    with transaction.atomic():
        doc = Document.objects.create(
            doc_type="SCA", ref=next_ref("SCA", sub.site), site=sub.site,
            project=project, doc_date=data.get("doc_date") or date.today(),
            status="DRAFT", created_by=actor)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        payload={}, created_by=actor)
        doc.current_revision = doc.revisions.first()
        doc.save(update_fields=["current_revision"])
        agreement = SubcontractAgreement.objects.create(
            document=doc, subcontractor=sub, project=project,
            title=data["title"].strip())
        _apply_sca_terms(agreement, data)
        agreement.save()
        _set_scope(agreement, data.get("rows") or [])
    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "sub": sub.name})
    return doc, None


def _apply_sca_terms(agreement, data):
    """Set the SCA header + commercial terms from the form (draft-edit safe)."""
    from decimal import Decimal
    if "title" in data and (data.get("title") or "").strip():
        agreement.title = data["title"].strip()
    if "currency" in data:
        agreement.currency = (data.get("currency")
                              or agreement.currency)[:3].upper()
    for f in ("start_date", "end_date"):
        if f in data:
            setattr(agreement, f, data.get(f) or None)
    for f in ("scope_of_work", "contractor_signatory_name",
              "contractor_signatory_title", "notes"):
        if f in data:
            setattr(agreement, f, data.get(f) or "")
    if "basis" in data and data.get("basis") in ("MEASURED", "DAYWORK"):
        agreement.basis = data["basis"]
    for f in ("advance_percent", "retention_percent", "gst_percent",
              "markup_percent"):
        # non-null, default 0
        if f in data:
            setattr(agreement, f, _dec(data.get(f)) or Decimal("0"))
    for f in ("ld_amount", "ld_cap_percent"):            # optional
        if f in data:
            setattr(agreement, f, _dec(data.get(f)))
    if "payment_days" in data:
        v = data.get("payment_days")
        try:
            agreement.payment_days = int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            pass


def _pct(v):
    """Trim a percentage for display: 10.00 -> '10', 7.50 -> '7.5'."""
    return "" if v is None else ("%g" % float(v))


# ---- SVC: subcontract valuations (Phase 4) -------------------------------

from decimal import Decimal   # noqa: E402

# The doc statuses at which an SVC is still open (blocks a second in-flight one).
_SVC_OPEN = ("DRAFT", "SUBMITTED", "PM_VERIFIED", "DIRECTOR_APPROVED")
_SVC_CERTIFIED = ("AUTHORISED", "PAID")


# ---- day work: labour hired by the man-day -------------------------------

DAY_MARK_VALUE = {"PRESENT": Decimal("1"), "HALF_DAY": Decimal("0.5")}


def is_daywork(agreement):
    return agreement.basis == "DAYWORK"


def set_day_rates(agreement, rows, actor):
    """Replace the agreed category rates on a day-work agreement.

    Replaced wholesale rather than patched: the screen edits them as one
    table, and a half-applied rate card is a wrong certificate. Rates already
    written onto a valuation's lines are untouched — that is the point of
    storing them there.
    """
    from .models import SubcontractDayRate
    if agreement.document.status != "DRAFT":
        return "Rates can only be set while the agreement is a draft."
    seen, clean = set(), []
    for r in rows or []:
        cid = r.get("job_category_id")
        if not cid:
            continue
        if cid in seen:
            return "The same category is listed twice."
        seen.add(cid)
        day = _dec(r.get("rate_per_day")) or Decimal("0")
        ot = _dec(r.get("ot_rate_per_hour")) or Decimal("0")
        if day < 0 or ot < 0:
            return "A rate cannot be negative."
        clean.append(SubcontractDayRate(agreement=agreement,
                                        job_category_id=cid,
                                        rate_per_day=day,
                                        ot_rate_per_hour=ot))
    with transaction.atomic():
        agreement.day_rates.all().delete()
        SubcontractDayRate.objects.bulk_create(clean)
    audit("document", agreement.document_id, "SCA_DAY_RATES_SET", actor=actor,
          detail={"ref": agreement.document.ref, "categories": len(clean)})
    return None


def _certified_periods(agreement, exclude_id=None):
    """Periods already certified on this agreement — a man-day is charged
    once, so a new valuation may not reach back into one of them."""
    from .models import SubcontractValuation
    qs = SubcontractValuation.objects.filter(
        agreement=agreement, document__is_void=False,
        period_from__isnull=False).exclude(
        document__status__in=("DRAFT", "RETURNED"))
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return [(v.period_from, v.period_to, v.document.ref)
            for v in qs.select_related("document")]


def period_clash(agreement, start, end, exclude_id=None):
    for a, b, ref in _certified_periods(agreement, exclude_id):
        if start <= b and a <= end:
            return (f"{a:%d %b} to {b:%d %b %Y} is already certified on "
                    f"{ref}. A man-day is charged once.")
    return None


def read_worker_days(agreement, start, end):
    """What the register says the gang worked, between two dates.

    Only days actually worked are charged: PRESENT is a day, HALF_DAY is
    half, and everything else — absent, sick, leave — is nothing. A
    subcontractor's man is hired by the day, so a day he did not work is not
    ours to pay for; that is a matter between him and his employer.
    """
    from .models import Attendance
    rates = {r.job_category_id: r for r in agreement.day_rates.all()}
    rows = {}
    marks = Attendance.objects.filter(
        employee__subcontractor_id=agreement.subcontractor_id,
        employee__engagement_type="SUBCONTRACT",
        day__gte=start, day__lte=end).select_related(
        "employee__job_category")
    for m in marks:
        emp = m.employee
        row = rows.setdefault(emp.id, {
            "employee": emp, "job_category": emp.job_category,
            "days": Decimal("0"), "ot_hours": Decimal("0")})
        row["days"] += DAY_MARK_VALUE.get(m.remark, Decimal("0"))
        row["ot_hours"] += m.sub_extra_hours or Decimal("0")
    out = []
    for row in rows.values():
        rate = rates.get(row["job_category"].id if row["job_category"]
                         else None)
        row["rate_per_day"] = rate.rate_per_day if rate else Decimal("0")
        row["ot_rate_per_hour"] = (rate.ot_rate_per_hour if rate
                                   else Decimal("0"))
        out.append(row)
    return out


def fill_worker_days(v, actor=None):
    """(Re-)read the register into this valuation's lines.

    Only ever onto a draft: attendance moves — a late edit is audited but it
    still moves — and a certificate that quietly followed it would not be a
    certificate. Refreshing is a deliberate act on a document nobody has
    signed yet.
    """
    from .models import SubcontractWorkerDay
    if v.document.status not in ("DRAFT", "RETURNED"):
        return "Only a draft valuation reads the register again."
    if not v.period_from or not v.period_to:
        return "This valuation has no period to read."
    rows = read_worker_days(v.agreement, v.period_from, v.period_to)
    with transaction.atomic():
        v.worker_days.all().delete()
        SubcontractWorkerDay.objects.bulk_create([
            SubcontractWorkerDay(
                valuation=v, employee=r["employee"],
                job_category=r["job_category"], days=r["days"],
                ot_hours=r["ot_hours"], rate_per_day=r["rate_per_day"],
                ot_rate_per_hour=r["ot_rate_per_hour"])
            for r in rows])
    if actor is not None:
        audit("document", v.document_id, "SVC_DAYS_READ", actor=actor,
              detail={"ref": v.document.ref, "workers": len(rows),
                      "period": f"{v.period_from} to {v.period_to}"})
    return None


def daywork_period_value(v):
    """What this period's labour is worth: the men, then the markup.

    The markup is on the DAY RATES only — overtime is passed through at the
    rate the worker is actually paid, so it is a reimbursement and not
    something to take a fee on (owner 2026-09-10).
    """
    days_total = ot_total = Decimal("0")
    for w in v.worker_days.all():
        days_total += w.day_value
        ot_total += w.ot_value
    pct = v.markup_percent or Decimal("0")
    markup = (days_total * pct / Decimal("100")).quantize(Decimal("0.01"))
    return {"days_value": days_total, "ot_value": ot_total,
            "markup_percent": pct, "markup": markup,
            "period_gross": days_total + ot_total + markup}


def unpriced_workers(v):
    """Men on the valuation whose category carries no agreed rate."""
    return [w for w in v.worker_days.select_related("employee",
                                                    "job_category")
            if not w.priced]


def _svc_gross_cumulative(v):
    """Certified-to-date, gross, whichever way the work is valued.

    Measured work carries its own cumulative quantities, so the total is
    simply Σ (cumulative qty × rate). Day work values a PERIOD, so the
    cumulative is the chain: what was certified before, plus this period's
    labour. Everything downstream — retention, advance recovery, deductions,
    what has been paid, the payable and the cost posting — reads this one
    figure and so needs no idea which basis produced it (owner 2026-09-10).
    """
    if v is None:
        return Decimal("0")
    if is_daywork(v.agreement):
        return (_svc_gross_cumulative(v.previous)
                + daywork_period_value(v)["period_gross"])
    total = Decimal("0")
    for it in v.items.select_related("scope_item"):
        total += (it.cumulative_qty or Decimal("0")) * \
                 (it.scope_item.rate or Decimal("0"))
    return total


def net_of_gst(agreement, amount):
    """Strip the GST out of money that went out gross.

    A certificate is built in net terms — the work is valued, the advance is
    recovered, and GST is charged on what is left. Money already paid comes
    back off that stack, so it has to come off NET: subtracting a gross
    payment charges the tax twice, once against what is due and again as tax
    on the remainder, and the subcontractor is short by the GST on every
    certificate after the first (owner 2026-09-09).

    On an agreement carrying no GST this is the amount itself, so nothing
    that predates GST moves by a cent.
    """
    pct = agreement.gst_percent or Decimal("0")
    amount = Decimal(amount or 0)
    if pct <= 0 or not amount:
        return amount
    return (amount / (1 + pct / Decimal("100"))).quantize(Decimal("0.01"))


def paid_to_date(agreement):
    """Everything actually paid to this subcontractor under this agreement.

    On-account payments and settled valuations both count. The contractual
    ADVANCE does not: it is recovered against each certificate instead (see
    `advance_recovered`), which is how a construction advance actually works
    — the subcontractor is paid a share of every certificate while repaying
    it, rather than receiving nothing until the certified value overtakes the
    advance (owner 2026-09-09).

    Netting the advance here was the earlier approach (2026-08-13). It was
    right to insist that nothing be clawed back that was never paid, and that
    still holds: recovery is capped at what has actually been advanced. But
    netting it in one lump left a 30% advance paying the gang nothing for the
    first third of the job.
    """
    from .models import Payable, PaymentRequest

    pyrs = PaymentRequest.objects.filter(
        subcontract_agreement=agreement,
        document__status__in=("PAID", "CLOSED"),
        document__is_void=False,
    ).exclude(payment_type="ADVANCE").aggregate(
        t=Sum("amount_paid"))["t"] or Decimal("0")
    # A settled valuation reaches the agreement through its SVC document.
    settled = Payable.objects.filter(
        document__subcontract_valuation__agreement=agreement,
        status="SETTLED",
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    return net_of_gst(agreement, Decimal(pyrs) + Decimal(settled))


@transaction.atomic
def raise_advance(agreement, actor, data=None):
    """Raise the payment request for the contractual advance.

    The percentage could be set on an agreement and there was no way to
    actually pay it — so it sat as a number on a PDF while the money was
    arranged off the system, and nothing was ever recovered against it
    (owner 2026-09-09).

    It goes out as an ADVANCE payment request against the agreement, which is
    what `advance_recovered` later claws back from each certificate.
    """
    from .models import Document, DocumentRevision, PaymentRequest
    from .payments import create_payment_request

    doc0 = agreement.document
    if doc0.status != "APPROVED":
        return None, "The agreement must be approved before its advance."
    pct = agreement.advance_percent or Decimal("0")
    if pct <= 0:
        return None, "This agreement carries no advance."
    if PaymentRequest.objects.filter(
            subcontract_agreement=agreement, payment_type="ADVANCE"
    ).exclude(document__is_void=True).exists():
        return None, "The advance has already been raised."
    net = ((agreement.value or Decimal("0")) * pct / Decimal("100")).quantize(
        Decimal("0.01"))
    if net <= 0:
        return None, "The agreement has no value to advance against."
    gst_pct = agreement.gst_percent or Decimal("0")
    gst = (net * gst_pct / Decimal("100")).quantize(Decimal("0.01"))
    ref = next_ref("PYR", doc0.site)
    doc = Document.objects.create(
        doc_type="PYR", ref=ref, site=doc0.site, project=agreement.project,
        doc_date=date.today(), status="DRAFT", created_by=actor)
    purpose = (f"{pct:g}% advance on {doc0.ref} — {agreement.title}"
               [:300])
    rev = DocumentRevision.objects.create(
        document=doc, rev_label="R0", created_by=actor,
        payload={"purpose": purpose, "kind": "subcontract_advance",
                 "sca_ref": doc0.ref})
    doc.current_revision = rev
    doc.save(update_fields=["current_revision"])
    pr, err = create_payment_request(doc, {
        "amount_requested": str(net + gst),
        "cost_head_id": _subcontract_head().id,
        "payee": agreement.subcontractor.name,
        "currency": agreement.currency,
        "payment_method": "BANK",
        "payment_type": "ADVANCE",
        "purpose": purpose,
        "subcontract_agreement_id": agreement.id,
        "has_supporting_doc": True,
    }, actor)
    if err:
        transaction.set_rollback(True)
        return None, err
    # One route, whoever clicks. Left to the raiser's role, a QS's advance
    # would clear straight to a voucher while a PM's went round the PM and
    # the Director first — the same money on two different roads (owner
    # 2026-09-09).
    #
    # It takes the shorter one deliberately: the advance percentage was
    # approved by the PM and the Director when the agreement was activated,
    # so paying it executes a term already sanctioned. The signatory still
    # signs the money out on the voucher.
    pr.origin = "CENTRAL"
    pr.save(update_fields=["origin"])
    audit("subcontract", agreement.id, "SCA_ADVANCE_RAISED", actor=actor,
          detail={"sca": doc0.ref, "pyr": doc.ref, "percent": str(pct)})
    return doc, None


def advance_paid(agreement):
    """The contractual advance actually paid out, if any — net of its GST,
    because it is recovered against net certified values."""
    from .models import PaymentRequest

    return net_of_gst(agreement, PaymentRequest.objects.filter(
        subcontract_agreement=agreement, payment_type="ADVANCE",
        document__status__in=("PAID", "CLOSED"),
        document__is_void=False,
    ).aggregate(t=Sum("amount_paid"))["t"] or 0)


def is_advance_prepayment(pr):
    """True for a subcontract advance: money out of the door that is not a
    cost. The certificates carry the cost, and the advance is recovered from
    them — so it is committed and incurred nowhere (owner 2026-09-09)."""
    return bool(pr.payment_type == "ADVANCE" and pr.subcontract_agreement_id)


def on_advance_paid(document, pr, actor):
    """A subcontract advance leaves the cost ledger alone.

    It is a prepayment recouped from the certificates, and every certificate
    already posts the work it certifies. Posting the advance too charged the
    project for the same money twice — a 240,000 subcontract with a 30%
    advance landed as 317,760 of cost (owner 2026-09-09). The same reasoning
    already keeps salary advances and capitalized import charges out of the
    ledger.

    Its GST is a different matter: that tax was genuinely paid and is
    recoverable, so it posts to the input-tax pool exactly as a certificate's
    GST does. The certificates only charge GST on what is left after the
    advance is recovered, so without this the input tax would be short.
    """
    from . import costing
    from .procurement import _ho_site

    a = pr.subcontract_agreement
    if a is None:
        return
    gross = Decimal(pr.amount_paid or 0)
    gst = gross - net_of_gst(a, gross)
    if gst <= 0:
        return
    head = costing.by_code(costing.INPUT_GST)
    if head is None:
        return
    for state in ("COMMITTED", "INCURRED"):
        costing.post(site=_ho_site(), cost_head=head, state=state,
                     source="SUBCONTRACT", amount=gst, document=document,
                     is_stock_pool=True, actor=actor, currency=a.currency)


def advance_recovered(agreement, gross_cumulative):
    """How much of the advance the certified work has repaid so far.

    Recovered at the contract's advance percentage of the gross certified —
    the standard mechanism — and CAPPED at what was actually advanced, so a
    percentage on paper can never claw back money that never moved.
    """
    paid = advance_paid(agreement)
    if paid <= 0:
        return Decimal("0")
    pct = agreement.advance_percent or Decimal("0")
    if pct <= 0:
        # An advance paid against an agreement that stipulates none is an
        # on-account payment by another name: it comes off in full, which is
        # what netting always did (owner 2026-08-13). Without this it would
        # be neither recovered nor netted, and the money would vanish from
        # the certificate.
        return paid
    due = (Decimal(gross_cumulative) * pct / Decimal("100")).quantize(
        Decimal("0.01"))
    return min(due, paid)


def _svc_net_cumulative(v):
    """Net certified-to-date = gross − retention − deductions + adjustment.

    The advance is not in here: it comes off afterwards, at the contract
    percentage and capped at what was actually advanced, so this figure stays
    what the work is worth (owner 2026-09-09)."""
    if v is None:
        return Decimal("0")
    gross = _svc_gross_cumulative(v)
    ret_pct = v.retention_percent or Decimal("0")
    retention = ret_pct / 100 * gross
    return (gross - retention
            - (v.deductions or Decimal("0")) + (v.adjustment or Decimal("0")))


def svc_valuation(v):
    """Full valuation breakdown for display + the amount now payable."""
    a = v.agreement
    prev = v.previous
    if is_daywork(a):
        return _daywork_valuation(v)
    prev_items = ({i.scope_item_id: (i.cumulative_qty or Decimal("0"))
                   for i in prev.items.all()} if prev else {})
    lines, gross_cum = [], Decimal("0")
    for it in v.items.select_related("scope_item"):
        si = it.scope_item
        rate = si.rate or Decimal("0")
        contract_qty = si.qty or Decimal("0")
        cum_qty = it.cumulative_qty or Decimal("0")
        prev_qty = prev_items.get(si.id, Decimal("0"))
        cum_val = cum_qty * rate
        gross_cum += cum_val
        lines.append({
            "id": it.id, "scope_item_id": si.id, "item_code": si.item_code,
            "description": si.description, "unit": si.unit, "rate": rate,
            "contract_qty": contract_qty, "previous_qty": prev_qty,
            "cumulative_qty": cum_qty, "this_qty": cum_qty - prev_qty,
            "this_value": (cum_qty - prev_qty) * rate, "cumulative_value": cum_val,
            "over": bool(contract_qty and cum_qty > contract_qty),
        })
    out = _certification_waterfall(v, gross_cum)
    out.update({"basis": "MEASURED", "lines": lines,
                "over_warning": any(ln["over"] for ln in lines)})
    return out


def _daywork_valuation(v):
    """The same certificate, arrived at from the register instead of a scope.

    One line per man — days, extra hours, the agreed rates — then the markup
    on the day rates. That total is this period's work; the waterfall below it
    is the one every valuation uses, which is the point: retention, the
    advance, what has been paid and the GST behave identically whichever way
    the work was measured.
    """
    period = daywork_period_value(v)
    lines = [{
        "id": w.id, "employee_id": w.employee_id,
        "emp_no": w.employee.emp_no, "name": w.employee.full_name,
        "category": (w.job_category.name if w.job_category_id else ""),
        "days": w.days, "ot_hours": w.ot_hours,
        "rate_per_day": w.rate_per_day,
        "ot_rate_per_hour": w.ot_rate_per_hour,
        "day_value": w.day_value, "ot_value": w.ot_value,
        "amount": w.amount, "priced": w.priced,
    } for w in v.worker_days.select_related("employee", "job_category")]
    gross_cum = (_svc_gross_cumulative(v.previous)
                 + period["period_gross"])
    out = _certification_waterfall(v, gross_cum)
    unpriced = [ln for ln in lines if not ln["priced"]]
    out.update({
        "basis": "DAYWORK", "lines": lines,
        "period_from": v.period_from, "period_to": v.period_to,
        "days_value": period["days_value"], "ot_value": period["ot_value"],
        "markup_percent": period["markup_percent"],
        "markup": period["markup"],
        "period_gross": period["period_gross"],
        "worker_count": len(lines),
        "unpriced": [f'{ln["emp_no"]} {ln["name"]}' for ln in unpriced],
        "over_warning": False,
    })
    return out


def _certification_waterfall(v, gross_cum):
    """Gross certified to date → what is payable now.

    Written once and shared, because the difference between a measured
    valuation and a day-work one ends at the gross figure. Retention, the
    advance recovery, what has already been paid and the GST are contract
    terms, not measurement methods, and two copies of them would drift.
    """
    a = v.agreement
    prev = v.previous
    prev_gross = _svc_gross_cumulative(prev) if prev else Decimal("0")
    ret_pct = v.retention_percent or Decimal("0")
    retention = ret_pct / 100 * gross_cum
    net_cum = (gross_cum - retention
               - (v.deductions or Decimal("0")) + (v.adjustment or Decimal("0")))
    prev_net = _svc_net_cumulative(prev) if prev else Decimal("0")
    # What is due is what has been certified less what has genuinely been
    # paid — advances, on-account payments and earlier settled valuations
    # alike. A certificate approved but not yet paid therefore rolls forward
    # instead of being dropped and chased separately (owner 2026-08-13).
    paid = paid_to_date(a)
    # The advance comes off each certificate at the contract percentage,
    # capped at what was actually advanced (owner 2026-09-09).
    adv_paid = advance_paid(a)
    adv_rec = advance_recovered(a, gross_cum)
    prev_adv_rec = (advance_recovered(a, prev_gross) if prev
                    else Decimal("0"))
    after_advance = net_cum - adv_rec
    now_due = after_advance - paid
    # GST is charged by a registered subcontractor on the work certified this
    # period, and is recoverable input tax to us — the same treatment a local
    # purchase gets. It rides on the money changing hands, not on the
    # cumulative certificate.
    gst_pct = a.gst_percent or Decimal("0")
    gst = ((now_due * gst_pct / Decimal("100")).quantize(Decimal("0.01"))
           if now_due > 0 and gst_pct > 0 else Decimal("0"))
    return {
        "currency": a.currency, "contract_value": a.value,
        "gross_cumulative": gross_cum, "previous_gross": prev_gross,
        "this_gross": gross_cum - prev_gross,
        "retention_pct": ret_pct, "retention_held": retention,
        "deductions": v.deductions or Decimal("0"),
        "adjustment": v.adjustment or Decimal("0"),
        "net_cumulative": net_cum, "previous_net": prev_net,
        "advance_percent": a.advance_percent or Decimal("0"),
        "advance_paid": adv_paid,
        "advance_recovered": adv_rec,
        "advance_recovered_this": adv_rec - prev_adv_rec,
        "advance_outstanding": adv_paid - adv_rec,
        "after_advance": after_advance,
        "paid_to_date": paid,
        "now_due": now_due,
        "gst_percent": gst_pct, "gst": gst,
        "total_payable": now_due + gst,
    }


def _period_dates(data):
    """The period a day-work valuation covers.

    Given a year and month it is that whole calendar month, which is how the
    register is kept and how these are settled; explicit dates are accepted
    for a part month (a gang that demobilised mid-month).
    """
    import calendar
    from datetime import date as _date

    if data.get("period_from") and data.get("period_to"):
        try:
            a = _date.fromisoformat(str(data["period_from"]))
            b = _date.fromisoformat(str(data["period_to"]))
            return a, b
        except (TypeError, ValueError):
            return None, None
    try:
        y, m = int(data["year"]), int(data["month"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if not 1 <= m <= 12:
        return None, None
    return _date(y, m, 1), _date(y, m, calendar.monthrange(y, m)[1])


def create_svc(agreement, actor, data=None):
    """Open a new valuation against an APPROVED agreement.

    Measured work gets one line per priced scope item, seeded at the
    previously-certified cumulative. Day work gets a PERIOD — a month, usually
    — and its lines are read off the site attendance register: one man, his
    days, his extra hours, at the rates the agreement agreed.

    Terms are snapshotted from the SCA either way, so a certified valuation
    never shifts. Only one valuation may be in flight per agreement.
    """
    from datetime import date

    from .models import (Document, DocumentRevision, SubcontractValuation,
                         SubcontractValuationItem)
    from .numbering import next_ref
    doc0 = agreement.document
    if doc0.status != "APPROVED":
        return None, "Value work only against an approved agreement."
    if actor.role not in SITE_MANAGE_ROLES:
        return None, "Only the site team can raise a valuation."
    if SubcontractValuation.objects.filter(
            agreement=agreement,
            document__status__in=_SVC_OPEN, document__is_void=False).exists():
        return None, "A valuation is already in progress for this agreement."
    prev = (SubcontractValuation.objects.filter(
        agreement=agreement, document__status__in=_SVC_CERTIFIED,
        document__is_void=False).order_by("-seq").first())
    prev_items = ({i.scope_item_id: i.cumulative_qty for i in prev.items.all()}
                  if prev else {})
    data = data or {}
    start = end = None
    if is_daywork(agreement):
        start, end = _period_dates(data)
        if start is None:
            return None, ("Give the period this valuation covers — day work "
                          "is valued a month at a time.")
        if end < start:
            return None, "The period ends before it starts."
        clash = period_clash(agreement, start, end)
        if clash:
            return None, clash
        if not agreement.day_rates.exists():
            return None, ("Set the agreed day rates on the agreement before "
                          "valuing labour against it.")
    site = doc0.site
    with transaction.atomic():
        doc = Document.objects.create(
            doc_type="SVC", ref=next_ref("SVC", site), site=site,
            project=agreement.project or doc0.project,
            doc_date=date.today(), status="DRAFT", created_by=actor)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        payload={}, created_by=actor)
        doc.current_revision = doc.revisions.first()
        doc.save(update_fields=["current_revision"])
        v = SubcontractValuation.objects.create(
            document=doc, agreement=agreement, seq=(prev.seq + 1) if prev else 1,
            previous=prev, advance_percent=agreement.advance_percent or 0,
            retention_percent=agreement.retention_percent or 0,
            markup_percent=agreement.markup_percent or 0,
            period_from=start, period_to=end, created_by=actor)
        if is_daywork(agreement):
            fill_worker_days(v, actor)
        else:
            for si in agreement.items.filter(is_heading=False):
                SubcontractValuationItem.objects.create(
                    valuation=v, scope_item=si,
                    cumulative_qty=prev_items.get(si.id, Decimal("0")))
    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "sca": agreement.document.ref})
    return doc, None


def value_svc(v, data, actor):
    """Enter cumulative quantities per line + header figures on a draft SVC.
    A line's cumulative can't fall below the previously-certified quantity."""
    if v.document.status != "DRAFT":
        return None, "Only a draft valuation can be edited."
    if actor.role not in SITE_MANAGE_ROLES:
        return None, "Only the site team can value this."
    if is_daywork(v.agreement) and (data.get("rows") or []):
        return None, ("Day work is not valued by hand — it comes off the "
                      "attendance register. Refresh it instead.")
    prev_items = ({i.scope_item_id: (i.cumulative_qty or Decimal("0"))
                   for i in v.previous.items.all()} if v.previous_id else {})
    by_id = {it.id: it for it in v.items.select_related("scope_item")}
    for row in (data.get("rows") or []):
        it = by_id.get(row.get("id"))
        if it is None:
            continue
        q = _dec(row.get("cumulative_qty"))
        if q is None:
            continue
        floor = prev_items.get(it.scope_item_id, Decimal("0"))
        if q < floor:
            return None, (f"Line {it.scope_item.item_code or it.scope_item_id}: "
                          f"cumulative quantity can't fall below the previously "
                          f"certified ({floor}).")
        it.cumulative_qty = q
        it.save(update_fields=["cumulative_qty"])
    for f in ("deductions", "adjustment"):
        if f in data:
            setattr(v, f, _dec(data.get(f)) or Decimal("0"))
    if "work_done_upto" in data:
        v.work_done_upto = data.get("work_done_upto") or None
    if "note" in data:
        v.note = data.get("note") or ""
    v.save()
    audit("document", v.document_id, "SVC_VALUED", actor=actor)
    return v, None


_SVC_APPROVAL_ACTION = {"SUBMITTED": "SUBMIT", "PM_VERIFIED": "VERIFY",
                        "DIRECTOR_APPROVED": "APPROVE",
                        "AUTHORISED": "AUTHORISE", "DRAFT": "RETURN"}


def _svc_set_status(doc, new, actor, comment=""):
    from .models import Approval
    doc.status = new
    doc.save(update_fields=["status", "updated_at"])
    # The immutable trail — also what the certificate PDF prints as the
    # digital signature blocks.
    Approval.objects.create(
        document=doc, revision=doc.current_revision,
        action=_SVC_APPROVAL_ACTION.get(new, new), actor=actor,
        actor_role=actor.role, comment=comment)
    audit("document", doc.id, f"SVC_{new}", actor=actor, to_state=new,
          detail={"note": comment} if comment else None)
    try:
        from .notify import notify_document
        notify_document(doc, actor)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_document(SVC) failed")


def _subcontract_head():
    from .models import CostHead
    head, _ = CostHead.objects.get_or_create(
        code="SUBCONTRACT",
        defaults={"name": "Subcontract", "sort_order": 60,
                  "is_system": True})
    return head


def _svc_authorise(v, actor):
    """At signatory authorisation: post this period's certified work as
    COMMITTED + INCURRED cost under the 'Subcontract' head (the value of work
    done — before advance recovery/retention, which are cash-flow, not cost),
    and raise a Payable for the net amount now due so Finance can settle it on
    a payment voucher (owner D-1)."""
    from . import costing
    from .models import Payable
    head = _subcontract_head()
    doc, a = v.document, v.agreement
    val = svc_valuation(v)
    this_gross = val["this_gross"]
    if this_gross:
        for state in ("COMMITTED", "INCURRED"):
            costing.post(site=doc.site, cost_head=head, state=state,
                         source="SUBCONTRACT",
                         amount=this_gross.quantize(Decimal("0.01")),
                         document=doc, actor=actor, currency=a.currency)
    # GST is recoverable input tax, not a project cost — posted to the Input
    # GST account at head office, exactly as a local purchase does (owner
    # 2026-09-09).
    gst = val["gst"]
    if gst > 0:
        from .procurement import _ho_site
        gst_head = costing.by_code(costing.INPUT_GST)
        if gst_head is not None:
            for state in ("COMMITTED", "INCURRED"):
                costing.post(site=_ho_site(), cost_head=gst_head, state=state,
                             source="SUBCONTRACT", amount=gst, document=doc,
                             is_stock_pool=True, actor=actor,
                             currency=a.currency)
    # What we owe is the certificate plus the GST on it.
    payable = val["total_payable"]
    if payable > 0:
        days = a.payment_days if a.payment_days is not None else 30
        Payable.objects.create(
            document=doc, site=doc.site, vendor=a.subcontractor.name,
            terms=(f"{days} days" if a.payment_days is not None else ""),
            amount=payable.quantize(Decimal("0.01")),
            due_date=date.today() + timedelta(days=days))


def settle_svc_payable(payable, actor, ref):
    """Finance pays a voucher-approved SVC payable: post the PAID cost leg,
    mark the payable settled and the valuation PAID."""
    from . import costing
    doc = payable.document
    costing.post(site=doc.site, cost_head=_subcontract_head(), state="PAID",
                 source="SUBCONTRACT", amount=payable.amount, document=doc,
                 actor=actor)
    payable.status = "SETTLED"
    payable.settled_on = date.today()
    payable.settled_ref = ref or ""
    payable.save(update_fields=["status", "settled_on", "settled_ref"])
    if doc.status == "AUTHORISED":
        doc.status = "PAID"
        doc.save(update_fields=["status", "updated_at"])
        audit("document", doc.id, "SVC_PAID", actor=actor, to_state="PAID")


# The chain: SE submits → PM verifies qty → Director approves → Signatory
# authorises (commits cost). Any approver at the current step returns to draft.
_SVC_STEPS = {
    "submit": (("DRAFT", "SUBMITTED"), SITE_MANAGE_ROLES,
               "Only the site team can submit a valuation."),
    "verify": (("SUBMITTED", "PM_VERIFIED"), ("PM", "ADMIN"),
               "The PM verifies the quantities."),
    "approve": (("PM_VERIFIED", "DIRECTOR_APPROVED"), ("DIRECTOR", "ADMIN"),
                "The Director approves the valuation."),
    "authorise": (("DIRECTOR_APPROVED", "AUTHORISED"), ("SIGNATORY", "ADMIN"),
                  "A signatory authorises the valuation."),
}


def svc_action(v, action, actor, note=""):
    """Advance an SVC through its approval chain (or return it to draft)."""
    from .models import Document
    doc = v.document
    if action == "return":
        if not (note or "").strip():
            return "Give a reason for returning it."
        if doc.status not in ("SUBMITTED", "PM_VERIFIED", "DIRECTOR_APPROVED"):
            return f"Can't return a {doc.status.lower()} valuation."
        _svc_set_status(doc, "DRAFT", actor, comment=note)
        return None
    step = _SVC_STEPS.get(action)
    if not step:
        return "Unknown action."
    (frm, to), roles, denied = step
    if actor.role not in roles:
        return denied
    if doc.status != frm or to not in Document.TRANSITIONS["SVC"].get(frm, set()):
        return f"Cannot {action} a {doc.status.lower()} valuation."
    if action == "submit":
        if is_daywork(v.agreement):
            if not v.worker_days.exists():
                return ("Nobody was marked on the register for this period, "
                        "so there is nothing to value.")
            # A man valued at nothing because his trade has no agreed rate is
            # how a gang goes unpaid for a month. Say so before it is signed,
            # not after (owner 2026-09-10).
            missing = unpriced_workers(v)
            if missing:
                who = ", ".join(f"{w.employee.emp_no} "
                                f"({w.job_category.name if w.job_category_id else 'no category'})"
                                for w in missing[:4])
                more = f" and {len(missing) - 4} more" if len(missing) > 4 else ""
                return (f"No agreed day rate for {who}{more}. Set the rate on "
                        f"the agreement, or take them off the register.")
        elif not v.items.exists():
            return "There's nothing to value on this certificate."
    if action == "authorise":
        _svc_authorise(v, actor)
        v.authorised_at = timezone.now()
        v.save(update_fields=["authorised_at"])
    _svc_set_status(doc, to, actor)
    return None


def svc_payload(v, request=None):
    """Header + full valuation breakdown for the API."""
    a = v.agreement
    d = {
        "id": v.id, "ref": v.document.ref, "status": v.document.status,
        "seq": v.seq, "agreement_ref": a.document.ref,
        "agreement_title": a.title,
        "subcontractor": a.subcontractor.name,
        "work_done_upto": v.work_done_upto, "note": v.note,
        "basis": a.basis,
        "period_from": v.period_from, "period_to": v.period_to,
        "created_by": v.created_by.full_name if v.created_by_id else "",
        "created_at": v.created_at,
        "valuation": _jsonify(svc_valuation(v)),
    }
    return d


def _jsonify(val):
    """Decimals → strings so the breakdown serialises cleanly."""
    def conv(x):
        if isinstance(x, Decimal):
            return str(x)
        if isinstance(x, list):
            return [conv(i) for i in x]
        if isinstance(x, dict):
            return {k: conv(i) for k, i in x.items()}
        return x
    return conv(val)


def sca_pdf_context(doc):
    """Merge-field context for the Subcontract Agreement PDF (owner template)."""
    from decimal import Decimal

    from .commercial import amount_in_words
    from .pdf import _font_dir, company_info, mark_src
    a = doc.subcontract_agreement
    sub = a.subcontractor
    value = a.value or Decimal("0")
    retention = a.retention_percent or Decimal("0")

    def fdate(d):
        return d.strftime("%d %b %Y") if d else ""

    project = a.project or doc.project
    return {
        "mark_src": mark_src(), "font_dir": _font_dir(),
        "co": company_info(), "ref": doc.ref, "issue_date": fdate(doc.doc_date),
        "a": a, "sub": sub, "items": list(a.items.all()),
        "currency": a.currency, "price_fmt": f"{value:,.2f}",
        "value_words": amount_in_words(value, a.currency),
        "scope_of_work": a.scope_of_work,
        "scope_lines": [ln.strip().lstrip("-•*–—").strip()
                        for ln in (a.scope_of_work or "").splitlines()
                        if ln.strip()],
        "project_title": project.title if project else "",
        "site_name": doc.site.name if doc.site_id else "",
        "agreement_date": fdate(doc.doc_date),
        "start_date": fdate(a.start_date) or "____________",
        "completion_date": fdate(a.end_date) or "____________",
        "advance_percent": _pct(a.advance_percent),
        "has_advance": bool(a.advance_percent and a.advance_percent > 0),
        "retention_percent": _pct(retention),
        "show_retention": bool(retention and retention > 0),
        "payment_days": a.payment_days or "",
        "ld_amount": f"{a.ld_amount:,.2f}" if a.ld_amount is not None else "",
        "ld_cap_percent": _pct(a.ld_cap_percent),
        "contractor_signatory_name": (a.contractor_signatory_name
                                      or "Muditha Samanthilaka"),
        "contractor_signatory_title": (a.contractor_signatory_title
                                       or "Director, Projects"),
    }


def svc_pdf_context(doc):
    """Merge-field context for the Subcontract Valuation Certificate PDF."""
    from .commercial import amount_in_words
    from .pdf import _font_dir, company_info, logo_src
    v = doc.subcontract_valuation
    a = v.agreement
    val = svc_valuation(v)
    # Money renders pre-formatted with thousand separators (owner 2026-08-09)
    def q2(x):
        return f"{(x or Decimal('0')).quantize(Decimal('0.01')):,}"
    # Digital signature blocks: the latest approval per action (a RETURN wipes
    # the run, so only actions after the last return count).
    approvals = list(doc.approvals.select_related("actor"))
    last_return = max((i for i, ap in enumerate(approvals)
                       if ap.action == "RETURN"), default=-1)
    by_action = {}
    for ap in approvals[last_return + 1:]:
        by_action[ap.action] = ap
    def sig(action):
        ap = by_action.get(action)
        return {"name": ap.actor.full_name, "role": ap.actor_role,
                "at": ap.acted_at} if ap else None
    def nonzero(x):
        return bool(x and x != Decimal("0"))
    now_due = (val["now_due"] or Decimal("0")).quantize(Decimal("0.01"))
    return {
        "logo_src": logo_src(), "font_dir": _font_dir(),
        "co": company_info(), "doc_title": "Subcontract Valuation Certificate",
        "doc_no_label": "Certificate No", "doc_ref": doc.ref,
        "subline": f"Valuation No. {v.seq} · {a.title}",
        "ref": doc.ref, "seq": v.seq, "status": doc.status,
        "is_authorised": doc.status in ("AUTHORISED", "PAID"),
        "issue_date": doc.doc_date, "work_done_upto": v.work_done_upto,
        "sub": a.subcontractor, "a": a, "sca_ref": a.document.ref,
        "site_name": doc.site.name if doc.site_id else "",
        "project_title": (a.project or doc.project).title
                         if (a.project or doc.project) else "",
        "currency": val["currency"], "contract_value": q2(val["contract_value"]),
        # The body of the certificate is the one thing the two bases do not
        # share: measured work lists items and quantities, day work lists men
        # and days. Everything under "Certification" is identical.
        "basis": val["basis"],
        "lines": ([{**ln, "rate_per_day": q2(ln["rate_per_day"]),
                    "ot_rate_per_hour": q2(ln["ot_rate_per_hour"]),
                    "day_value": q2(ln["day_value"]),
                    "ot_value": q2(ln["ot_value"]),
                    "amount": q2(ln["amount"])}
                   for ln in val["lines"]]
                  if val["basis"] == "DAYWORK" else
                  [{**ln, "rate": q2(ln["rate"]),
                    "this_value": q2(ln["this_value"]),
                    "cumulative_value": q2(ln["cumulative_value"])}
                   for ln in val["lines"]]),
        "period_from": val.get("period_from"),
        "period_to": val.get("period_to"),
        "days_value": q2(val.get("days_value")),
        "ot_value": q2(val.get("ot_value")),
        "markup_percent": val.get("markup_percent") or Decimal("0"),
        "markup": q2(val.get("markup")),
        "period_gross": q2(val.get("period_gross")),
        "gross_cumulative": q2(val["gross_cumulative"]),
        "retention_pct": _pct(val["retention_pct"]),
        "retention_held": q2(val["retention_held"]),
        "show_retention": nonzero(val["retention_held"]),
        "deductions": q2(val["deductions"]),
        "show_deductions": nonzero(val["deductions"]),
        "adjustment": q2(val["adjustment"]),
        "show_adjustment": nonzero(val["adjustment"]),
        "net_cumulative": q2(val["net_cumulative"]),
        "previous_net": q2(val["previous_net"]),
        "paid_to_date": q2(val["paid_to_date"]), "now_due": q2(now_due),
        "amount_words": amount_in_words(now_due, val["currency"]),
        "over_warning": val["over_warning"],
        "sig_prepared": sig("SUBMIT"), "sig_verified": sig("VERIFY"),
        "sig_approved": sig("APPROVE"), "sig_authorised": sig("AUTHORISE"),
        "note": v.note,
    }


def update_sca(doc, data, actor):
    """Edit a draft SCA in place — header, terms + scope."""
    if doc.status != "DRAFT":
        return None, "Only a draft agreement can be edited."
    agreement = doc.subcontract_agreement
    _apply_sca_terms(agreement, data)
    agreement.save()
    if "rows" in data:
        _set_scope(agreement, data.get("rows") or [])
    if "day_rates" in data:
        err = set_day_rates(agreement, data.get("day_rates") or [], actor)
        if err:
            return None, err
    audit("document", doc.id, "SCA_EDITED", actor=actor,
          detail={"ref": doc.ref})
    return doc, None

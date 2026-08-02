"""Subcontractor lifecycle + site-level team management (subcontractor module,
Phase 2). Site-managed: the SA/SE create and staff subcontractors; PM→Director
activate; HR/HO have no management role. A subcontract worker is an Employee
(engagement_type SUBCONTRACT), kept out of payroll structurally (Phase 1)."""
import logging
from datetime import date, timedelta

from django.db import transaction
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
    for f in ("advance_percent", "retention_percent"):   # non-null, default 0
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


def _svc_gross_cumulative(v):
    """Σ (cumulative qty × scope rate) across a valuation's lines."""
    if v is None:
        return Decimal("0")
    total = Decimal("0")
    for it in v.items.select_related("scope_item"):
        total += (it.cumulative_qty or Decimal("0")) * \
                 (it.scope_item.rate or Decimal("0"))
    return total


def _svc_net_cumulative(v):
    """Net certified-to-date = gross − advance recovery − retention − deductions
    + adjustment. Advance recovers pro-rata (recovery % = advance %), capped at
    the advance paid; retention is optional (0 = none)."""
    if v is None:
        return Decimal("0")
    gross = _svc_gross_cumulative(v)
    adv_pct = v.advance_percent or Decimal("0")
    ret_pct = v.retention_percent or Decimal("0")
    adv_total = adv_pct / 100 * (v.agreement.value or Decimal("0"))
    recovery = min(adv_pct / 100 * gross, adv_total)
    retention = ret_pct / 100 * gross
    return (gross - recovery - retention
            - (v.deductions or Decimal("0")) + (v.adjustment or Decimal("0")))


def svc_valuation(v):
    """Full valuation breakdown for display + the amount now payable."""
    a = v.agreement
    prev = v.previous
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
    prev_gross = _svc_gross_cumulative(prev) if prev else Decimal("0")
    adv_pct = v.advance_percent or Decimal("0")
    ret_pct = v.retention_percent or Decimal("0")
    adv_total = adv_pct / 100 * (a.value or Decimal("0"))
    recovery = min(adv_pct / 100 * gross_cum, adv_total)
    retention = ret_pct / 100 * gross_cum
    net_cum = (gross_cum - recovery - retention
               - (v.deductions or Decimal("0")) + (v.adjustment or Decimal("0")))
    prev_net = _svc_net_cumulative(prev) if prev else Decimal("0")
    return {
        "currency": a.currency, "contract_value": a.value,
        "lines": lines,
        "gross_cumulative": gross_cum, "previous_gross": prev_gross,
        "this_gross": gross_cum - prev_gross,
        "advance_total": adv_total, "advance_recovered": recovery,
        "retention_pct": ret_pct, "retention_held": retention,
        "deductions": v.deductions or Decimal("0"),
        "adjustment": v.adjustment or Decimal("0"),
        "net_cumulative": net_cum, "previous_net": prev_net,
        "now_due": net_cum - prev_net,
        "over_warning": any(ln["over"] for ln in lines),
    }


def create_svc(agreement, actor):
    """Open a new valuation against an APPROVED agreement — one line per priced
    scope item, seeded at the previously-certified cumulative, terms snapshotted
    from the SCA. Only one valuation may be in flight per agreement."""
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
            retention_percent=agreement.retention_percent or 0, created_by=actor)
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


def _svc_set_status(doc, new, actor, comment=""):
    doc.status = new
    doc.save(update_fields=["status", "updated_at"])
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
        name="Subcontract", defaults={"sort_order": 60})
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
    now_due = val["now_due"]
    if now_due > 0:
        days = a.payment_days if a.payment_days is not None else 30
        Payable.objects.create(
            document=doc, site=doc.site, vendor=a.subcontractor.name,
            terms=(f"{days} days" if a.payment_days is not None else ""),
            amount=now_due.quantize(Decimal("0.01")),
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
    if action == "submit" and not v.items.exists():
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


def update_sca(doc, data, actor):
    """Edit a draft SCA in place — header, terms + scope."""
    if doc.status != "DRAFT":
        return None, "Only a draft agreement can be edited."
    agreement = doc.subcontract_agreement
    _apply_sca_terms(agreement, data)
    agreement.save()
    if "rows" in data:
        _set_scope(agreement, data.get("rows") or [])
    audit("document", doc.id, "SCA_EDITED", actor=actor,
          detail={"ref": doc.ref})
    return doc, None

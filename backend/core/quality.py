"""QA / QC — inspection & test plans, non-conformance, supplier evaluation.

The audit found real submittal and inspection workflows but no non-conformance
register and no supplier evaluation (conformance audit 2026-08-28): a quality
failure had nowhere to live, and a supplier who kept causing them was never
rated.

Corrective actions deliberately reuse the register the safety module already
uses. A company's open-actions list has to be one list — an NCR action and an
incident action are the same kind of promise.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .audit import audit
from .hse import open_actions_for, raise_action
from .models import (Document, DocumentRevision, InspectionTestPlan, ItpItem,
                     ItpRecord, NonConformance, SupplierEvaluation)
from .notify import notify_user
from .numbering import next_ref

RAISER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                "QS", "HO_PURCHASING", "PA"}
# Who may decide what happens to non-conforming work. Deliberately narrower
# than who may raise it: anyone should be able to say "this is wrong", but
# "use it anyway" is an engineering decision (owner 2026-08-29).
DISPOSITION_ROLES = {"PM", "DIRECTOR", "ADMIN", "QS"}


def _new_document(doc_type, site, user, doc_date, status, project=None):
    ref = next_ref(doc_type, site)
    doc = Document.objects.create(
        doc_type=doc_type, ref=ref, site=site, project=project,
        doc_date=doc_date, status=status, created_by=user)
    revision = DocumentRevision.objects.create(
        document=doc, rev_label="R0", payload={}, created_by=user)
    doc.current_revision = revision
    doc.save(update_fields=["current_revision"])
    return doc


def _as_date(value):
    if isinstance(value, str) and value:
        return parse_date(value)
    return value or None


# ---- inspection & test plans -------------------------------------------

@transaction.atomic
def create_itp(*, site, data, user, project=None):
    title = (data.get("title") or "").strip()
    if not title:
        return None, "What is this plan for?"
    items = data.get("items") or []
    if not items:
        return None, "A plan with no inspection points is not a plan."
    prepared_on = _as_date(data.get("prepared_on")) or timezone.localdate()

    doc = _new_document("ITP", site, user, prepared_on, "RECORDED", project)
    supersedes = None
    if data.get("supersedes_id"):
        supersedes = InspectionTestPlan.objects.filter(
            pk=data["supersedes_id"], document__site=site).first()
    plan = InspectionTestPlan.objects.create(
        document=doc, title=title,
        discipline=(data.get("discipline") or "")[:60],
        prepared_by=user, prepared_on=prepared_on,
        notes=(data.get("notes") or "").strip(),
        supersedes=supersedes)
    for i, row in enumerate(items):
        ItpItem.objects.create(
            plan=plan, sort_order=i,
            activity=(row.get("activity") or "").strip(),
            reference=(row.get("reference") or "").strip(),
            acceptance_criteria=(row.get("acceptance_criteria") or "").strip(),
            point_type=row.get("point_type") or "REVIEW",
            responsible=row.get("responsible") or "US",
            frequency=(row.get("frequency") or "")[:80],
            record_required=(row.get("record_required") or "").strip())
    if supersedes is not None:
        old = supersedes.document
        old.status = "SUPERSEDED"
        old.save(update_fields=["status"])
    audit("document", doc.id, "ITP_RECORDED", actor=user, to_state="RECORDED",
          detail={"ref": doc.ref, "title": title[:80], "items": len(items),
                  "hold_points": sum(1 for r in items
                                     if r.get("point_type") == "HOLD")})
    return plan, None


@transaction.atomic
def record_itp_result(*, item, data, user):
    result = data.get("result")
    if result not in dict(ItpRecord.Result.choices):
        return None, "Did it pass or fail?"
    record = ItpRecord.objects.create(
        item=item, location=(data.get("location") or "").strip(),
        inspected_on=_as_date(data.get("inspected_on"))
        or timezone.localdate(),
        inspected_by=user,
        inspector_name=(data.get("inspector_name") or "").strip(),
        result=result, note=(data.get("note") or "").strip())
    audit("document", item.plan.document_id, "ITP_POINT_RECORDED", actor=user,
          detail={"activity": item.activity[:60], "result": result,
                  "location": record.location[:60]})
    return record, None


def itp_progress(plan):
    """How much of the plan has actually been signed off, and whether any
    HOLD point is still outstanding — the one that stops work."""
    items = list(plan.items.prefetch_related("records"))
    done = holds_open = failed = 0
    for item in items:
        records = list(item.records.all())
        passed = any(r.result == "PASS" for r in records)
        if any(r.result == "FAIL" for r in records) and not passed:
            failed += 1
        if records:
            done += 1
        if item.point_type == "HOLD" and not passed:
            holds_open += 1
    return {"items": len(items), "recorded": done, "failed": failed,
            "holds_outstanding": holds_open}


# ---- non-conformance ----------------------------------------------------

@transaction.atomic
def raise_ncr(*, site, data, user, project=None):
    category = data.get("category")
    if category not in dict(NonConformance.Category.choices):
        return None, "What kind of non-conformance is it?"
    if not (data.get("description") or "").strip():
        return None, "Describe what is wrong."
    # An NCR that does not say what it breaches is an opinion, not a finding.
    if not (data.get("requirement") or "").strip():
        return None, ("Say what this fails to meet — the clause, drawing or "
                      "standard. Without it there is nothing to argue from.")
    raised_on = _as_date(data.get("raised_on")) or timezone.localdate()

    doc = _new_document("NCR", site, user, raised_on, "OPEN", project)
    ncr = NonConformance.objects.create(
        document=doc, category=category,
        severity=data.get("severity") or "MINOR",
        raised_by=user, raised_on=raised_on,
        location=(data.get("location") or "").strip(),
        description=data["description"].strip(),
        requirement=data["requirement"].strip(),
        supplier_id=data.get("supplier_id") or None)
    audit("document", doc.id, "NCR_RAISED", actor=user, to_state="OPEN",
          detail={"ref": doc.ref, "category": category,
                  "severity": ncr.severity,
                  "supplier": ncr.supplier.name if ncr.supplier_id else ""})
    for pm in (site.current_pms() if site else []):
        if pm.is_active and pm.id != user.id:
            notify_user(pm, f"Non-conformance raised — {doc.ref}",
                        ncr.description[:160], doc=doc, category="approval")
    return ncr, None


@transaction.atomic
def set_disposition(ncr, data, user):
    """What happens to the non-conforming work. Narrower than raising one:
    anyone can say this is wrong, but 'use it anyway' is an engineering
    decision that has to carry a name."""
    disposition = data.get("disposition")
    if disposition not in dict(NonConformance.Disposition.choices):
        return "Choose what happens to the work."
    if ncr.document.status == "CLOSED":
        return "This non-conformance is closed."
    if disposition == "USE_AS_IS" and not (data.get("disposition_note")
                                           or "").strip():
        return ("Accepting work that does not meet its requirement needs a "
                "reason on the record.")
    ncr.disposition = disposition
    ncr.disposition_note = (data.get("disposition_note") or "").strip()
    ncr.disposition_by = user
    ncr.disposition_at = timezone.now()
    ncr.save(update_fields=["disposition", "disposition_note",
                            "disposition_by", "disposition_at"])
    if ncr.document.status == "OPEN":
        ncr.document.status = "IN_PROGRESS"
        ncr.document.save(update_fields=["status"])
    audit("document", ncr.document_id, "NCR_DISPOSITION", actor=user,
          to_state="IN_PROGRESS",
          detail={"disposition": disposition,
                  "note": ncr.disposition_note[:200]})
    return None


@transaction.atomic
def close_ncr(ncr, user, note=""):
    doc = ncr.document
    if doc.status == "CLOSED":
        return "Already closed."
    if not ncr.disposition:
        return ("Decide what happens to the work before closing this — "
                "rework, repair, use as is, re-grade or reject.")
    still_open = open_actions_for(doc).count()
    if still_open:
        return (f"{still_open} corrective action(s) raised by this NCR are "
                f"still open.")
    ncr.closed_at = timezone.now()
    ncr.closed_by = user
    ncr.verification_note = (note or "").strip()
    ncr.save(update_fields=["closed_at", "closed_by", "verification_note"])
    was = doc.status
    doc.status = "CLOSED"
    doc.save(update_fields=["status"])
    audit("document", doc.id, "NCR_CLOSED", actor=user, from_state=was,
          to_state="CLOSED", detail={"note": ncr.verification_note[:200]})
    return None


def raise_ncr_action(ncr, data, user):
    """Same register the safety module writes to."""
    return raise_action(source_document=ncr.document, data=data, user=user)


# ---- supplier evaluation ------------------------------------------------

SCORE_FIELDS = ["quality", "delivery", "price", "responsiveness",
                "documentation"]


def _clamp(value):
    try:
        return max(1, min(int(value), 5))
    except (TypeError, ValueError):
        return 3


@transaction.atomic
def evaluate_supplier(*, supplier, data, user):
    period_start = _as_date(data.get("period_start"))
    period_end = _as_date(data.get("period_end"))
    if not period_start or not period_end:
        return None, "Which period is being rated?"
    if period_end < period_start:
        return None, "The period must end after it starts."

    scores = {f: _clamp(data.get(f, 3)) for f in SCORE_FIELDS}
    average = Decimal(sum(scores.values())) / Decimal(len(SCORE_FIELDS))
    average = average.quantize(Decimal("0.01"))
    # The count is evidence beside the opinion: a supplier rated highly while
    # carrying six non-conformances is a conversation worth having.
    ncr_count = NonConformance.objects.filter(
        supplier=supplier, raised_on__gte=period_start,
        raised_on__lte=period_end).count()

    evaluation, created = SupplierEvaluation.objects.update_or_create(
        supplier=supplier, period_start=period_start, period_end=period_end,
        defaults={**scores, "score": average,
                  "band": SupplierEvaluation.band_for(float(average)),
                  "ncr_count": ncr_count,
                  "notes": (data.get("notes") or "").strip(),
                  "evaluated_by": user})
    audit("supplier", supplier.id, "SUPPLIER_EVALUATED", actor=user,
          detail={"period": f"{period_start}..{period_end}",
                  "score": str(average), "band": evaluation.band,
                  "ncrs": ncr_count, "replaced": not created})
    return evaluation, None


def supplier_scorecard(supplier):
    """Latest rating plus the non-conformance history, so the register shows
    performance rather than only a name and a bank account."""
    latest = supplier.evaluations.first()
    year_ago = timezone.localdate() - timedelta(days=365)
    return {
        "supplier_id": supplier.id,
        "name": supplier.name,
        "latest_score": str(latest.score) if latest else None,
        "band": latest.band if latest else None,
        "evaluated_on": latest.period_end if latest else None,
        "ncrs_12m": NonConformance.objects.filter(
            supplier=supplier, raised_on__gte=year_ago).count(),
        "ncrs_open": NonConformance.objects.filter(
            supplier=supplier).exclude(document__status="CLOSED").count(),
    }

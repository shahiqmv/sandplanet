"""Materials & site testing — test requests and the results that come back.

Cube tests, compaction, pressure tests and the rest were recorded nowhere. The
reports existed as paper and only reached the app when somebody uploaded them
into the handover pack at the end, which is both late and lossy: nobody could
answer "is every pour on this villa covered by a passing 28-day result?"
without a folder and an afternoon (owner 2026-08-29).

Recording them here means handover PULLS them like any other document, and a
failed result has somewhere to go — straight into the non-conformance
register rather than into a conversation.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

import logging

from .audit import audit
from .models import Document, DocumentRevision, MaterialTest, TestResult
from .notify import notify_user
from .numbering import next_ref

log = logging.getLogger(__name__)

REQUESTER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                   "QS", "PA"}


def _as_date(value):
    if isinstance(value, str) and value:
        return parse_date(value)
    return value or None


def _as_decimal(value):
    """JSON gives us strings. A figure typed as "34.5 N/mm2" or left blank
    must not take the whole result down — it just means no number."""
    if value in ("", None):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


@transaction.atomic
def request_test(*, site, data, user, project=None):
    """Raise the request. It is issued BEFORE the sample is taken so the lab
    or the consultant can attend — that is what makes it a request rather
    than a note of something that already happened. Supplying the sampling
    date up front opens it already sampled, which keeps retrospective entry
    to one step (owner 2026-08-29)."""
    kind = data.get("kind")
    if kind not in dict(MaterialTest.Kind.choices):
        return None, "What kind of test is this?"
    if not (data.get("element") or "").strip():
        return None, "What is to be sampled? Name the element."
    requested_on = _as_date(data.get("requested_on")) or timezone.localdate()
    sampled_on = _as_date(data.get("sampled_on"))
    if sampled_on and sampled_on > timezone.localdate():
        return None, "A sample cannot have been taken in the future."

    ref = next_ref("TR", site)
    doc = Document.objects.create(
        doc_type="TR", ref=ref, site=site, project=project,
        doc_date=requested_on,
        status="SAMPLED" if sampled_on else "REQUESTED", created_by=user)
    revision = DocumentRevision.objects.create(
        document=doc, rev_label="R0", payload={}, created_by=user)
    doc.current_revision = revision
    doc.save(update_fields=["current_revision"])

    test = MaterialTest.objects.create(
        document=doc, kind=kind, element=data["element"].strip(),
        location=(data.get("location") or "").strip(),
        pour_ref=(data.get("pour_ref") or "")[:60],
        grade=(data.get("grade") or "")[:40],
        quantity=(data.get("quantity") or "")[:60],
        spec_reference=(data.get("spec_reference") or "").strip(),
        acceptance_criteria=(data.get("acceptance_criteria") or "").strip(),
        required_value=_as_decimal(data.get("required_value")),
        unit=(data.get("unit") or "")[:20],
        requested_on=requested_on,
        required_by=_as_date(data.get("required_by")),
        sampled_on=sampled_on,
        lab_name=(data.get("lab_name") or "").strip(),
        witnessed_by=(data.get("witnessed_by") or "").strip(),
        itp_item_id=data.get("itp_item_id") or None,
        notes=(data.get("notes") or "").strip(),
        requested_by=user)
    audit("document", doc.id,
          "TEST_SAMPLED" if sampled_on else "TEST_REQUESTED", actor=user,
          to_state=doc.status,
          detail={"ref": ref, "kind": kind,
                  "element": test.element[:80],
                  "required_by": str(test.required_by or ""),
                  "due": str(test.result_due_on() or "")})
    _render(test, "requested" if not sampled_on else "sampled")
    return test, None


def _render(test, milestone):
    """Archive the request/report sheet. This is the paper the lab is sent
    and the sheet that ends up in the handover pack — the same document
    throughout, re-rendered as results land."""
    from .pdf import generate_pdf

    doc = test.document
    try:
        return generate_pdf(doc, doc.current_revision, milestone)
    except Exception:                       # pragma: no cover - defensive
        log.exception("could not render the test sheet for %s", doc.ref)
        return None


@transaction.atomic
def confirm_sampling(*, test, data, user):
    """The sample has been taken. Until this, the request is something the
    lab is being asked for; after it, the result clock is running."""
    doc = test.document
    if doc.status != "REQUESTED":
        return "This request has already been sampled."
    sampled_on = _as_date(data.get("sampled_on")) or timezone.localdate()
    if sampled_on > timezone.localdate():
        return "A sample cannot have been taken in the future."
    test.sampled_on = sampled_on
    test.sampled_note = (data.get("sampled_note") or "").strip()
    if data.get("witnessed_by"):
        test.witnessed_by = data["witnessed_by"].strip()
    test.save(update_fields=["sampled_on", "sampled_note", "witnessed_by"])
    doc.status = "SAMPLED"
    doc.save(update_fields=["status"])
    audit("document", doc.id, "TEST_SAMPLED", actor=user,
          from_state="REQUESTED", to_state="SAMPLED",
          detail={"on": str(sampled_on),
                  "due": str(test.result_due_on() or "")})
    _render(test, "sampled")
    return None


def _grade(test, value):
    """Pass or fail against the acceptance figure, where one was set. With no
    figure recorded the outcome is whatever the person entering it says —
    the software does not invent a criterion it was never given."""
    if test.required_value is None or value is None:
        return None
    return "PASS" if value >= test.required_value else "FAIL"


@transaction.atomic
def record_result(*, test, data, user, certificate=None):
    if test.document.status == "REQUESTED":
        return None, ("Confirm the sample was taken before recording a "
                      "result against it.")
    value = _as_decimal(data.get("value"))
    outcome = data.get("outcome")
    graded = _grade(test, value)
    if outcome not in dict(TestResult.Outcome.choices):
        outcome = graded or "PENDING"

    result = TestResult.objects.create(
        test=test, report_ref=(data.get("report_ref") or "")[:80],
        specimen_ref=(data.get("specimen_ref") or "")[:60],
        age_days=data.get("age_days") or None,
        tested_on=_as_date(data.get("tested_on")) or timezone.localdate(),
        value=value, unit=(data.get("unit") or test.unit)[:20],
        outcome=outcome, certificate=certificate,
        remarks=(data.get("remarks") or "").strip(),
        recorded_by=user)
    _settle(test, user)
    audit("document", test.document_id, "TEST_RESULT_RECORDED", actor=user,
          to_state=test.document.status,
          detail={"age_days": result.age_days, "outcome": outcome,
                  "value": str(value or ""),
                  "required": str(test.required_value or ""),
                  "graded_automatically": graded is not None})
    _render(test, "result")
    if outcome == "FAIL":
        _alert_failure(test, result, user)
    return result, None


def _settle(test, user):
    """Move the request on as results land. A failure at any age fails the
    lot — a cube that broke low at 7 days is not rescued by the 28-day one
    being fine, it is a question that has to be answered."""
    # Query, do not use test.results.all(): the caller fetched the test with
    # prefetch_related("results"), so the related manager hands back the list
    # as it was BEFORE this result was written and the request never settles.
    results = list(TestResult.objects.filter(test=test))
    doc = test.document
    if not results:
        return
    if any(r.outcome == "FAIL" for r in results):
        status = "FAILED"
    elif all(r.outcome == "PASS" for r in results) and _is_complete(test,
                                                                   results):
        status = "PASSED"
    else:
        status = "PARTIAL"
    if doc.status != status:
        doc.status = status
        doc.save(update_fields=["status"])


def _is_complete(test, results):
    """Has the defining result arrived? For a cube that is the 28-day break;
    for anything with no defined age, one result is the whole test."""
    age = test.final_age_days()
    if not age:
        return True
    return any((r.age_days or 0) >= age for r in results)


def _alert_failure(test, result, actor):
    doc = test.document
    for pm in (doc.site.current_pms() if doc.site_id else []):
        if pm.is_active and pm.id != actor.id:
            notify_user(pm, f"Test failed — {doc.ref}",
                        f"{test.get_kind_display()} on {test.element[:80]}: "
                        f"{result.value} {result.unit or ''} against "
                        f"{test.required_value or '—'}.",
                        doc=doc, category="approval")


@transaction.atomic
def raise_ncr_for(test, data, user):
    """A failed test straight into the non-conformance register, carrying its
    own reference as the requirement it breached."""
    from . import quality

    if test.ncr_id:
        return None, f"{test.ncr.ref} already covers this test."
    if test.document.status != "FAILED":
        return None, "Only a failed test raises a non-conformance."
    worst = test.results.filter(outcome="FAIL").order_by("value").first()
    payload = {
        "category": "MATERIAL",
        "severity": data.get("severity") or "MAJOR",
        "location": test.location or test.element,
        "description": data.get("description") or (
            f"{test.get_kind_display()} failed on {test.element}. "
            f"{test.document.ref}: result {worst.value if worst else '—'} "
            f"{test.unit} against {test.required_value} {test.unit}."),
        "requirement": (test.acceptance_criteria or test.spec_reference
                        or f"Specified {test.required_value} {test.unit}"),
    }
    ncr, problem = quality.raise_ncr(site=test.document.site, data=payload,
                                     user=user,
                                     project=test.document.project)
    if problem:
        return None, problem
    test.ncr = ncr.document
    test.save(update_fields=["ncr"])
    audit("document", test.document_id, "TEST_NCR_RAISED", actor=user,
          detail={"ncr": ncr.document.ref})
    return ncr, None


def overdue(site_ids=None, as_of=None):
    """Samples whose defining result never came back."""
    as_of = as_of or timezone.localdate()
    qs = MaterialTest.objects.filter(
        sampled_on__isnull=False).exclude(
        document__status__in=["PASSED", "FAILED", "CANCELLED"]).select_related(
        "document", "document__site")
    if site_ids is not None:
        qs = qs.filter(document__site_id__in=site_ids)
    return [t for t in qs if t.is_overdue(as_of)]


def statistics(site_ids=None):
    qs = MaterialTest.objects.select_related("document")
    if site_ids is not None:
        qs = qs.filter(document__site_id__in=site_ids)
    rows = list(qs)
    return {
        "total": len(rows),
        "requested": sum(1 for t in rows
                         if t.document.status == "REQUESTED"),
        "passed": sum(1 for t in rows if t.document.status == "PASSED"),
        "failed": sum(1 for t in rows if t.document.status == "FAILED"),
        "awaiting": sum(1 for t in rows
                        if t.document.status in ("SAMPLED", "PARTIAL")),
        "overdue": sum(1 for t in rows if t.is_overdue()),
    }

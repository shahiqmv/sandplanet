"""The cost-posting service (Technical Design §4A) — the ONLY writer to
cost_postings. Every project cost figure flows through here as one of the
three states (COMMITTED / INCURRED / PAID). Postings are append-only; a
correction is a reversal row (negative amount, reversal_of set), never an
edit or delete.

Segregation of duties (build brief, non-negotiable): a FINANCE user may
never authorise a document whose amount is at or above signatory_threshold
— authorisation belongs to SIGNATORY. Enforced in can_authorise().
"""
from datetime import date
from decimal import Decimal

from .models import CostHead, CostPosting, User


def signatory_threshold():
    """The amount below which Finance may authorise-and-pay in one step
    (decision 24). Default DISABLED — None means everything needs a
    signatory. Stored as company parameter `signatory_threshold`."""
    from .models import CompanyParameter

    try:
        value = CompanyParameter.objects.get(key="signatory_threshold").value
    except CompanyParameter.DoesNotExist:
        return None
    if value in (None, "", "disabled"):
        return None
    return Decimal(str(value))


def can_authorise(user, amount):
    """Who may authorise a PR/PYR of `amount` (build brief; §6C.2 SoD).
    SIGNATORY and ADMIN always may. FINANCE may only below the threshold;
    at or above it — or when the threshold is disabled — Finance is
    blocked (403 at the endpoint)."""
    if user.role in (User.Role.SIGNATORY, User.Role.ADMIN):
        return True
    if user.role == User.Role.FINANCE:
        threshold = signatory_threshold()
        return threshold is not None and Decimal(str(amount)) < threshold
    return False


def post(*, site, cost_head, state, source, amount, posted_on=None,
         document=None, document_line=None, petty_cash_entry=None,
         ipr_line=None, is_stock_pool=False, staff_year=None, staff_month=None,
         work_package="", reversal_of=None, actor=None, currency="MVR"):
    """Append one cost posting. The single low-level writer — callers are
    the typed trigger functions below, never views directly."""
    return CostPosting.objects.create(
        site=site, cost_head=cost_head, state=state, source=source,
        amount=Decimal(str(amount)), currency=currency,
        posted_on=posted_on or date.today(),
        document=document, document_line=document_line,
        petty_cash_entry=petty_cash_entry, ipr_line=ipr_line,
        is_stock_pool=is_stock_pool, staff_year=staff_year,
        staff_month=staff_month, work_package=work_package,
        reversal_of=reversal_of, created_by=actor,
    )


def reverse_petty_cash_entry(entry, actor=None):
    """Reverse the INCURRED posting of an approved petty-cash entry that is
    voided before reimbursement (§4A: negative mirror, never a delete)."""
    reversals = []
    already = set(CostPosting.objects.filter(
        reversal_of__petty_cash_entry=entry)
        .values_list("reversal_of_id", flat=True))
    for original in CostPosting.objects.filter(petty_cash_entry=entry,
                                               reversal_of__isnull=True):
        if original.id in already:
            continue
        reversals.append(post(
            site=original.site, cost_head=original.cost_head,
            state=original.state, source=original.source,
            amount=-original.amount, currency=original.currency,
            petty_cash_entry=entry, reversal_of=original, actor=actor))
    return reversals


def reverse_document(document, actor=None, states=None):
    """Reverse every non-reversal posting a document produced (§4A: Finance
    withdrawal, Void). Writes a negative mirror per posting with
    reversal_of set, so the drill-down shows the reversal rather than a
    silent erase. Idempotent per posting: a posting already reversed is
    skipped. Returns the reversal rows written."""
    originals = CostPosting.objects.filter(
        document=document, reversal_of__isnull=True)
    if states:
        originals = originals.filter(state__in=states)
    already = set(CostPosting.objects.filter(
        reversal_of__document=document)
        .values_list("reversal_of_id", flat=True))
    reversals = []
    for original in originals:
        if original.id in already:
            continue
        reversals.append(post(
            site=original.site, cost_head=original.cost_head,
            state=original.state, source=original.source,
            amount=-original.amount, currency=original.currency,
            document=document, document_line=original.document_line,
            ipr_line=original.ipr_line,
            is_stock_pool=original.is_stock_pool,
            staff_year=original.staff_year, staff_month=original.staff_month,
            work_package=original.work_package,
            reversal_of=original, actor=actor,
        ))
    return reversals


def document_net(document, state=None):
    """Net posted amount for a document (originals + reversals), optionally
    for one state. Used by tests and the drill-down."""
    from django.db.models import Sum

    qs = CostPosting.objects.filter(document=document)
    if state:
        qs = qs.filter(state=state)
    return qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")


# ---- Default cost heads (§6C.1) — seeded by migration ---------------------

DEFAULT_HEADS = [
    "Materials", "Labour & Staff", "Subcontract", "Plant & Equipment",
    "Transport & Freight", "Site Overheads", "Permits & Fees", "Other",
]
DEFAULT_POOLS = ["General Stock", "Foreign Exchange", "Stock Adjustment"]


def head(name):
    """Convenience lookup used by the trigger functions."""
    return CostHead.objects.get(name=name)

"""The submittal register.

Eight document types share one working life: the site raises a submittal, the
PM approves it internally, it is issued to the client or consultant, and it
comes back approved, approved-with-comments, or to be revised. They were built
one at a time, and the site dashboard grew a separate list request for each —
by the eighth type that was eight round trips serialising eight full lists
before a site page could paint. This module is the one query that replaces
them, and the place a ninth type joins without costing anything
(owner 2026-08-30: "the site page becomes heavier and longer").
"""
from django.db.models import Count, Q

# The register's order is the order of the work: inspect, approve materials,
# then the drawings and calculations behind them.
TYPES = ("IR", "MAR", "SD", "MS", "MXD", "BBS", "TWD", "MOC", "ABD")

LABELS = {
    "IR": "Inspection Request",
    "MAR": "Material Approval",
    "SD": "Shop Drawing",
    "MS": "Method Statement",
    "MXD": "Concrete Mix Design",
    "BBS": "Bar Bending Schedule",
    "TWD": "Temporary Works Design",
    "MOC": "Sample / Mock-up",
    # The record drawing: what was BUILT, reviewed by the Engineer with the
    # same codes as a shop drawing, then filed in the handover pack by link
    # (owner 2026-09-03). Before this it could only be uploaded as a file at
    # the end, with no review cycle at all.
    "ABD": "As-Built Drawing",
}

# The types that travel the submittal workflow: raised on site, gated by the
# PM, issued to the client, resulted. Listing the family in one place is the
# fix for how the civil types shipped — created and rendered, but absent from
# every workflow verb, so the Approve button the screen offered returned a
# 400 (found 2026-08-30, one day after they went live).
PM_GATED = ("MR", "IR", "MAR", "SD", "MS", "PMR",
            "MXD", "BBS", "TWD", "MOC", "ABD")

# Issued to the client for a result. IR is in the family but keeps its own
# closure flow (Part C), so it is listed where that matters, not here.
TO_CLIENT = ("MAR", "SD", "MS", "MXD", "BBS", "TWD", "MOC", "ABD")

# Where a submittal has come to rest. Everything else is still someone's job.
SETTLED = ("APPROVED", "APPROVED_WITH_COMMENTS", "REJECTED", "CLOSED")

# Waiting on the client rather than on us — worth separating, because chasing
# a consultant and finishing a drawing are different actions.
WITH_CLIENT = ("ISSUED",)


def summary(site_id, project_id=None):
    """Per-type counts for the site dashboard's card.

    One grouped query. It rides along on the dashboard request that is already
    being made, so the dashboard shows the state of the register without
    fetching the register itself."""
    from .models import Document

    qs = Document.objects.filter(site_id=site_id, doc_type__in=TYPES,
                                 is_void=False)
    if project_id:
        qs = qs.filter(project_id=project_id)
    rows = qs.values("doc_type").annotate(
        total=Count("id"),
        open=Count("id", filter=~Q(status__in=SETTLED)),
        with_client=Count("id", filter=Q(status__in=WITH_CLIENT)),
    )
    by_type = {r["doc_type"]: r for r in rows}
    return {
        "types": [
            {"doc_type": t, "label": LABELS[t],
             "total": by_type.get(t, {}).get("total", 0),
             "open": by_type.get(t, {}).get("open", 0),
             "with_client": by_type.get(t, {}).get("with_client", 0)}
            for t in TYPES if by_type.get(t, {}).get("total", 0)
        ],
        "open": sum(r["open"] for r in by_type.values()),
        "with_client": sum(r["with_client"] for r in by_type.values()),
        "total": sum(r["total"] for r in by_type.values()),
    }

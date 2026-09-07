"""The cost head master — the owner's page for it.

Cost heads existed only because migrations and feature code created them: 15
on production, nine of which the posting paths reached for by their exact
display text. There was no screen, which is the only reason a rename never
crashed procurement (owner 2026-09-07). Each head now carries a fixed internal
`code`, so the name here is the owner's to change.

Overheads: a head marked `overhead` is a company running cost that no project
causes — office rent, head-office salaries, licences. Its postings are kept
OUT of every site/project cost report and totalled on their own, because
charging them to whichever site happened to raise the payment misstates that
project's cost (owner 2026-09-07).
"""
from django.db.models import Count, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import fx
from .audit import audit
from .models import CostHead, CostPosting

MANAGE_ROLES = ("ADMIN", "FINANCE")
# What a head may be, beyond its name. `is_active` is set by the switch-off
# path, not by a create, so it is not in here.
FLAGS = ("is_pool", "overhead", "commercial")


def _slug(name):
    out = "".join(c if c.isalnum() else "_" for c in (name or "").upper())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")[:30]


def _unique_code(name):
    base = _slug(name) or "HEAD"
    code, n = base, 2
    while CostHead.objects.filter(code=code).exists():
        code = f"{base[:27]}_{n}"[:30]
        n += 1
    return code


def _usage():
    """How many postings each head carries — what makes it undeletable."""
    return {r["cost_head"]: r["n"] for r in
            CostPosting.objects.values("cost_head").annotate(n=Count("id"))}


def _row(c, usage):
    used = usage.get(c.id, 0)
    return {
        "id": c.id, "code": c.code, "name": c.name,
        "sort_order": c.sort_order, "is_pool": c.is_pool,
        "overhead": c.overhead, "commercial": c.commercial,
        "is_active": c.is_active, "is_system": c.is_system,
        "postings": used,
        # A head the code depends on stays; one that has carried money can be
        # switched off but never removed, because its postings are history.
        "can_delete": not c.is_system and not used,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def cost_head_list(request):
    """The master list, and adding to it."""
    if request.method == "POST":
        if request.user.role not in MANAGE_ROLES:
            return Response({"detail": "Finance or Admin manage cost heads."},
                            status=403)
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "A cost head needs a name."},
                            status=400)
        if CostHead.objects.filter(name__iexact=name).exists():
            return Response({"detail": f"'{name}' already exists."},
                            status=400)
        c = CostHead.objects.create(
            code=_unique_code(name), name=name[:60],
            sort_order=int(request.data.get("sort_order") or 100),
            **{f: bool(request.data.get(f)) for f in FLAGS})
        audit("cost_head", c.id, "COST_HEAD_ADDED", actor=request.user,
              detail={"code": c.code, "name": c.name,
                      "overhead": c.overhead, "is_pool": c.is_pool})
        return Response(_row(c, {}), status=201)

    if request.user.role not in MANAGE_ROLES + ("DIRECTOR", "SIGNATORY", "QS"):
        return Response({"detail": "Not permitted."}, status=403)
    usage = _usage()
    return Response([_row(c, usage) for c in CostHead.objects.all()])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def cost_head_detail(request, pk):
    """Edit a head, or remove one that never carried money."""
    if request.user.role not in MANAGE_ROLES:
        return Response({"detail": "Finance or Admin manage cost heads."},
                        status=403)
    c = CostHead.objects.filter(pk=pk).first()
    if c is None:
        return Response({"detail": "Cost head not found."}, status=404)
    used = CostPosting.objects.filter(cost_head=c).count()

    if request.method == "DELETE":
        # Both refusals matter. A system head is reached for by code from a
        # posting path, so removing it breaks that path outright; a head with
        # postings behind it is history, and history is not deleted here —
        # switch it off and it leaves the pickers instead.
        if c.is_system:
            return Response({"detail": f"'{c.name}' is used by the system "
                                       "itself and cannot be removed. Switch "
                                       "it off to take it out of the "
                                       "pickers."}, status=400)
        if used:
            return Response({"detail": f"'{c.name}' already carries {used} "
                                       "posting(s). Switch it off instead — "
                                       "removing it would erase cost "
                                       "history."}, status=400)
        audit("cost_head", c.id, "COST_HEAD_REMOVED", actor=request.user,
              detail={"code": c.code, "name": c.name})
        c.delete()
        return Response(status=204)

    before = {"name": c.name, "overhead": c.overhead,
              "is_active": c.is_active, "is_pool": c.is_pool}
    if "name" in request.data:
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "A cost head needs a name."},
                            status=400)
        if CostHead.objects.filter(name__iexact=name).exclude(pk=c.pk
                                                              ).exists():
            return Response({"detail": f"'{name}' already exists."},
                            status=400)
        c.name = name[:60]
    if "sort_order" in request.data:
        try:
            c.sort_order = int(request.data.get("sort_order") or 100)
        except (TypeError, ValueError):
            return Response({"detail": "Order must be a number."}, status=400)
    for f in FLAGS:
        if f in request.data:
            setattr(c, f, bool(request.data.get(f)))
    if "is_active" in request.data:
        active = bool(request.data.get("is_active"))
        # Switching off a head the code posts to would leave that path with
        # nowhere to book: payroll would skip the staff cost, petty cash would
        # refuse to replenish. It stays on.
        if not active and c.is_system:
            return Response({"detail": f"'{c.name}' is used by the system "
                                       "itself and must stay switched on."},
                            status=400)
        c.is_active = active
    c.save()
    changed = {k: [v, getattr(c, k)] for k, v in before.items()
               if v != getattr(c, k)}
    if changed:
        audit("cost_head", c.id, "COST_HEAD_EDITED", actor=request.user,
              detail={"code": c.code, "changed": changed})
    return Response(_row(c, _usage()))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def overheads_summary(request):
    """What the company spent on itself — the costs no project caused.

    These are excluded from every site cost report, so without this they
    would be money that left the company and appeared nowhere.
    """
    if request.user.role not in MANAGE_ROLES + ("DIRECTOR", "SIGNATORY"):
        return Response({"detail": "Cost data is restricted."}, status=403)
    rate = fx.usd_rate()
    heads = list(CostHead.objects.filter(overhead=True))
    by_head, totals = [], {"COMMITTED": 0, "INCURRED": 0, "PAID": 0}
    for c in heads:
        row = {"cost_head": c.name, "code": c.code}
        for st in totals:
            amt = sum(
                (fx.to_usd(r["t"] or 0, r["currency"], rate) for r in
                 CostPosting.objects.filter(cost_head=c, state=st)
                 .values("currency").annotate(t=Sum("amount"))),
                0)
            row[st.lower()] = float(round(amt, 2))
            totals[st] += amt
        by_head.append(row)
    return Response({
        "currency": "USD", "usd_rate": rate,
        "by_cost_head": by_head,
        "totals": {k.lower(): float(round(v, 2)) for k, v in totals.items()},
    })

"""Phone and utility bills — API (`/api/v1/bills/*`). Rules: core/bills.py."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import bills
from .models import BillAccount, BillCharge


def _read(request):
    if request.user.role not in bills.VIEW_ROLES:
        return Response({"detail": "Bill accounts are open to Finance, the "
                                   "Director and the signatory."}, status=403)
    return None


def _write(request):
    if request.user.role not in bills.EDIT_ROLES:
        return Response({"detail": "Finance keeps the bill accounts."},
                        status=403)
    return None


def _find(ident):
    qs = BillAccount.objects.select_related("site", "cost_head")
    if str(ident).upper().startswith("UTL-"):
        return qs.filter(ref__iexact=ident).first()
    return qs.filter(pk=ident).first() if str(ident).isdigit() else None


@api_view(["GET", "POST"])
def accounts(request):
    """GET: the register. POST: add one account — or, with `lines`, several
    of one provider pasted at once."""
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        if "lines" in request.data:
            n, msg = bills.add_many(request.data, request.user)
            if msg:
                return Response({"detail": msg}, status=400)
            return Response({"added": n}, status=201)
        a, msg = bills.save_account(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(bills.account_dict(a), status=201)
    return Response({
        "accounts": bills.accounts(request.GET.get("all") == "1"),
        "meta": bills.meta(),
        "can_edit": request.user.role in bills.EDIT_ROLES})


@api_view(["GET", "PATCH"])
def account_detail(request, ident):
    if (bad := _read(request)):
        return bad
    a = _find(ident)
    if a is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if (bad := _write(request)):
            return bad
        a, msg = bills.save_account(request.data, request.user, account=a)
        if msg:
            return Response({"detail": msg}, status=400)
    out = bills.account_dict(a)
    out.update(history=bills.history(a), meta=bills.meta(),
               can_edit=request.user.role in bills.EDIT_ROLES)
    return Response(out)


@api_view(["GET", "POST"])
def sheet(request):
    """GET ?period=YYYY-MM[&provider=]: the month's entry sheet.
    POST {period, rows}: enter the month's bills — all, or none."""
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        made, msg = bills.enter_bills(request.data.get("period"),
                                      request.data.get("rows"), request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        if not made:
            return Response({"detail": "Enter at least one bill's amount."},
                            status=400)
        return Response({"entered": len(made),
                         "total": sum(c.total for c in made)}, status=201)
    period = bills.month_of(request.GET.get("period")) or \
        bills._today().replace(day=1)
    out = bills.sheet(period, request.GET.get("provider") or "")
    out["can_edit"] = request.user.role in bills.EDIT_ROLES
    return Response(out)


@api_view(["GET"])
def to_pay(request):
    """Unpaid bills by provider; export=xlsx gives the payment list."""
    if (bad := _read(request)):
        return bad
    groups = bills.to_pay()
    want = (request.GET.get("provider") or "").lower()
    if want:
        groups = [g for g in groups if g["provider"].lower() == want]
    if request.GET.get("export") == "xlsx":
        from .views_ledger import _xlsx
        rows = [[b["provider"], b["account_no"], b["label"], b["kind_label"],
                 b["period_label"], b["bill_no"], b["due_date"],
                 b["site_code"], b["currency"], b["total"],
                 b["voucher"] or ""]
                for g in groups for b in g["bills"]]
        return _xlsx(
            "Bills to pay", f"As at {bills._today():%d %b %Y}",
            ["Provider", "Account / number", "Whose / where", "Kind",
             "Month", "Bill no.", "Due", "Site", "Currency", "Amount",
             "Voucher"], rows,
            ["Total", "", "", "", "", "", "", "", "",
             sum((g["total"] for g in groups), bills.ZERO), ""],
            [20, 18, 30, 12, 10, 16, 12, 8, 9, 14, 12], "bills-to-pay")
    return Response({"groups": groups,
                     "can_edit": request.user.role in bills.EDIT_ROLES})


@api_view(["POST"])
def charge_cancel(request, pk):
    if (bad := _write(request)):
        return bad
    c = BillCharge.objects.select_related("account", "account__site",
                                          "account__cost_head",
                                          "payable").filter(pk=pk).first()
    if c is None:
        return Response({"detail": "Not found."}, status=404)
    msg = bills.cancel_charge(c, request.user, request.data.get("reason"))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"cancelled": True})


@api_view(["GET"])
def people(request):
    """Employees to assign a phone to: ?q= a number or part of a name."""
    if (bad := _write(request)):
        return bad
    return Response({"people": bills.people(request.GET.get("q"))})


@api_view(["GET"])
def recoveries(request):
    """What is being recovered from salaries for phones over their
    allowance, and where each stands."""
    if (bad := _read(request)):
        return bad
    return Response({"recoveries": bills.recoveries()})


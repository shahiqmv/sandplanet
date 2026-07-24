"""Receivables API (Finance / QS / Director) — invoice due dates, aging
analysis and client statements of account. Read-only reporting over the
certified claims (IPCs) and client receipts."""
from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import receivables
from .models import Site

# Who may see the receivables ledger: Finance runs it; the QS owns the
# billing and the Director oversees cash-in (owner 2026-07-24).
RECEIVABLE_ROLES = ("FINANCE", "DIRECTOR", "ADMIN", "QS")


def _gate(request):
    if request.user.role not in RECEIVABLE_ROLES:
        return Response({"detail": "Not permitted."}, status=403)
    return None


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def aging(request):
    if (bad := _gate(request)):
        return bad
    as_of = _parse_date(request.query_params.get("as_of"))
    site_id = request.query_params.get("site")
    site_id = int(site_id) if site_id and site_id.isdigit() else None
    return Response(receivables.aging(as_of=as_of, site_id=site_id))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def clients(request):
    if (bad := _gate(request)):
        return bad
    return Response({"clients": receivables.client_accounts()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoices(request):
    if (bad := _gate(request)):
        return bad
    site_id = request.query_params.get("site")
    site_id = int(site_id) if site_id and site_id.isdigit() else None
    outstanding = request.query_params.get("outstanding") == "1"
    as_of = _parse_date(request.query_params.get("as_of"))
    return Response({"invoices": receivables.invoice_rows(
        site_id=site_id, as_of=as_of, only_outstanding=outstanding)})


def _get_site(request):
    sid = request.query_params.get("site")
    if not sid or not sid.isdigit():
        return None, Response({"detail": "A client (site) is required."},
                              status=400)
    try:
        return Site.objects.get(pk=int(sid)), None
    except Site.DoesNotExist:
        return None, Response({"detail": "Client not found."}, status=404)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def statement(request):
    if (bad := _gate(request)):
        return bad
    site, err = _get_site(request)
    if err:
        return err
    return Response(receivables.client_statement(
        site,
        date_from=_parse_date(request.query_params.get("from")),
        date_to=_parse_date(request.query_params.get("to"))))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def statement_pdf(request):
    if (bad := _gate(request)):
        return bad
    site, err = _get_site(request)
    if err:
        return err
    from .pdf import company_info, logo_src
    from .views_commercial import _render_pdf
    stmt = receivables.client_statement(
        site,
        date_from=_parse_date(request.query_params.get("from")),
        date_to=_parse_date(request.query_params.get("to")))
    ctx = {"logo_src": logo_src(), "co": company_info(),
           "stmt": stmt, "currency": "USD"}
    return _render_pdf("pdf/client_statement.html", ctx,
                       f"Statement-{site.code}")

"""Planet Mobile API (R6) — /api/mobile/v1/.

A thin, token-authenticated client surface over the existing business logic.
No new rules live here: queues reuse the desktop 'waiting on you' computation,
actions call the same transition service, and scoping is server-enforced.
"""
from django.contrib.auth import authenticate as dj_authenticate
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .audit import audit
from .mobile import MobileTokenAuthentication, new_token
from .models import MobileDevice
from .permissions import scoped_site_ids

MOBILE_AUTH = [MobileTokenAuthentication]


def me_payload(user):
    sids = scoped_site_ids(user)
    return {
        "id": user.id, "username": user.username,
        "full_name": user.full_name, "role": user.role,
        "role_label": user.get_role_display(),
        "is_signatory": user.role == "SIGNATORY",
        "all_sites": sids is None,
        "sites": [] if sids is None else sorted(sids),
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def m_login(request):
    """Sign in with the existing Planet username + password; returns a device
    token to carry as a Bearer header."""
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    user = dj_authenticate(username=username, password=password)
    if not user or not user.is_active:
        return Response({"detail": "Wrong username or password."}, status=401)
    device = MobileDevice.objects.create(
        user=user, token=new_token(),
        label=(request.META.get("HTTP_USER_AGENT") or "")[:120])
    audit("user", user.id, "MOBILE_SIGN_IN", actor=user,
          detail={"device": device.id})
    return Response({"token": device.token, "user": me_payload(user)},
                    status=201)


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_logout(request):
    """Revoke this device's token (and, later, its push subscription)."""
    device = getattr(request, "mobile_device", None)
    if device:
        MobileDevice.objects.filter(pk=device.pk).update(revoked=True)
    return Response({"detail": "Signed out."})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_me(request):
    return Response(me_payload(request.user))


# ---- Approver: queue / actioned / detail / actions ----------------------

# The document/status pairs an approver may action FROM MOBILE. Everything else
# in the desktop 'waiting on you' queue (DPR verify, DMA issue, PO issue,
# Finance payment tasks, Phase-1B PMR/IPR) stays desktop-only (R6 §2/§4).
APPROVABLE = {
    ("MR", "SUBMITTED"), ("IR", "SUBMITTED"), ("MAR", "SUBMITTED"),
    ("PR", "SUBMITTED"), ("PYR", "SUBMITTED"), ("PYR", "PM_APPROVED"),
    ("PV", "SUBMITTED"),
    ("IPR", "SUBMITTED"),   # Director/QS award the overseas order on mobile
    ("IPR", "APPROVED"),    # signatory authorises the order (raises the PO)
}


def _card_amount(ref, doc_type):
    from .models import Document, PaymentVoucherLine
    try:
        d = Document.objects.get(ref=ref)
    except Document.DoesNotExist:
        return None
    if doc_type == "PR":
        from .procurement import pr_grand_total
        return float(pr_grand_total(d))
    if doc_type == "PYR" and hasattr(d, "payment_request"):
        return float(d.payment_request.amount_requested or 0)
    if doc_type == "PV":
        return float(sum(
            (ln.amount or 0) for ln in
            PaymentVoucherLine.objects.filter(voucher=d)))
    if doc_type == "IPR" and hasattr(d, "import_order"):
        from .imports import ipr_order_total
        return float(ipr_order_total(d.import_order))
    return None


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_queue(request):
    """Pending approvals for this user — the desktop 'waiting on you' queue
    filtered to the items actionable on mobile, flattened to cards."""
    from .views_documents import pending_groups

    groups = pending_groups(request.user)
    cards = []
    for g in groups:
        for it in g["items"]:
            if (it["doc_type"], it["status"]) not in APPROVABLE:
                continue
            cards.append({**it, "amount": _card_amount(it["ref"],
                                                        it["doc_type"])})
    return Response({"count": len(cards), "items": cards})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_actioned(request):
    """Documents this user actioned (any client) in the last N days."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import Approval
    try:
        days = min(int(request.GET.get("days", 30)), 90)
    except (TypeError, ValueError):
        days = 30
    since = timezone.now() - timedelta(days=days)
    seen, items = set(), []
    for a in Approval.objects.filter(
            actor=request.user, acted_at__gte=since,
            action__in=("APPROVE", "AUTHORISE", "RETURN", "REJECT")) \
            .select_related("document", "document__site").order_by("-acted_at"):
        d = a.document
        if not d or d.ref in seen:
            continue
        seen.add(d.ref)
        items.append({
            "ref": d.ref, "doc_type": d.doc_type,
            "site_code": d.site.code if d.site_id else "—",
            "result": a.result or a.action, "acted_at": a.acted_at})
    return Response({"items": items[:80]})


def _pv_line_ref(ln):
    """Label for a voucher line: the source document's ref, or — for an
    overseas TT — the import order + milestone name."""
    if ln.source_document_id:
        return ln.source_document.ref
    m = ln.source_milestone
    if not m:
        return "—"
    try:
        return f"{m.order.document.ref} · {m.label}"
    except Exception:               # pragma: no cover - defensive
        return m.label or "—"


def _pr_vendor_summary(pr):
    """Short 'who we're paying' line for a PR: the awarded vendors."""
    names = []
    rev = pr.current_revision
    if rev is not None:
        for ln in rev.lines.all():
            net = (ln.amount_cash or 0) + (ln.amount_credit or 0)
            name = (ln.vendor or ln.free_text_desc or "").strip()
            if net > 0 and name and name not in names:
                names.append(name)
    if not names:
        return ""
    if len(names) <= 2:
        return ", ".join(names)
    return f"{names[0]}, {names[1]} +{len(names) - 2} more"


def _pv_line_detail(ln):
    """A readable summary of one voucher line so the signatory knows what the
    payment is for — payee, purpose, vendors — not just a document ref."""
    d = {"ref": _pv_line_ref(ln), "amount": float(ln.amount or 0),
         "currency": ln.currency, "kind": "", "title": "", "subtitle": "",
         "site_code": ""}
    src = ln.source_document
    if src is not None:
        d["site_code"] = src.site.code if src.site_id else ""
        if src.doc_type == "PYR" and hasattr(src, "payment_request"):
            pr = src.payment_request
            d["kind"] = "Payment request"
            d["title"] = pr.payee or "Payment"
            d["subtitle"] = " · ".join(
                x for x in (pr.purpose, getattr(pr.cost_head, "name", None))
                if x)
        elif src.doc_type == "PR":
            d["kind"] = "Procurement"
            d["title"] = _pr_vendor_summary(src) or "Materials procurement"
            d["subtitle"] = "Local purchase"
        else:
            d["kind"] = src.doc_type
            d["title"] = src.ref
    elif ln.source_milestone_id:
        m = ln.source_milestone
        d["kind"] = "Import payment"
        d["site_code"] = "HO"
        try:
            d["title"] = m.order.supplier.name
            d["subtitle"] = f"{m.order.document.ref} · {m.label}"
        except Exception:           # pragma: no cover - defensive
            d["title"] = m.label or "Milestone"
    elif ln.source_payable_id:
        p = ln.source_payable
        d["kind"] = "Credit payable"
        d["site_code"] = p.site.code if p.site_id else ""
        d["title"] = p.vendor or "Payable"
        d["subtitle"] = f"terms {p.terms or '—'} · due {p.due_date or '—'}"
    return d


def _document_payload(doc, request):
    """Read-only render for the approver detail screen."""
    from .models import PaymentVoucherLine
    from .serializers_documents import DocumentSerializer
    if doc.doc_type == "PV":
        qs = (PaymentVoucherLine.objects.filter(voucher=doc)
              .select_related("source_document__site",
                              "source_document__payment_request__cost_head",
                              "source_milestone__order__document",
                              "source_milestone__order__supplier",
                              "source_payable__site")
              .order_by("id"))
        lines = [_pv_line_detail(ln) for ln in qs]
        return {"ref": doc.ref, "doc_type": "PV", "status": doc.status,
                "doc_date": doc.doc_date,
                "prepared_by": (doc.created_by.full_name
                                if doc.created_by_id else None),
                "amount": float(sum(x["amount"] for x in lines)),
                "line_count": len(lines), "lines": lines}
    return DocumentSerializer(doc, context={"request": request}).data


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_document(request, ref):
    from .models import Document
    from .permissions import scoped_site_ids
    try:
        doc = Document.objects.select_related("site", "current_revision").get(
            ref=ref, is_void=False)
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    sids = scoped_site_ids(request.user)
    if sids is not None and doc.site_id not in sids and doc.doc_type != "PV":
        return Response({"detail": "Not found."}, status=404)
    return Response(_document_payload(doc, request))


def _act(request, ref, kind):
    """Approve/return a document from mobile, reusing the exact desktop service
    functions. Returns a DRF Response."""
    from .models import Document

    try:
        doc = Document.objects.select_related("current_revision").get(
            ref=ref, is_void=False)
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    comment = (request.data.get("comment") or "").strip()
    if kind == "return" and not comment:
        return Response({"detail": "A reason is required to return."},
                        status=400)
    # 409 if it's no longer in a mobile-actionable state (someone beat us to it)
    if (doc.doc_type, doc.status) not in APPROVABLE:
        return Response({"detail": f"Already actioned — {doc.ref} is now "
                        f"{doc.status}."}, status=409)

    if doc.doc_type == "PV":
        from . import vouchers
        if request.user.role not in ("SIGNATORY", "ADMIN"):
            return Response({"detail": "Only a signatory approves a voucher."},
                            status=403)
        if kind == "return":
            return Response({"detail": "Query voucher lines on the desktop for "
                             "now."}, status=400)
        err = vouchers.approve_voucher(doc, request.user)
        if err:
            return Response({"detail": err}, status=400)
    elif doc.doc_type == "PYR":
        from .payments import pyr_action
        result = pyr_action(request, doc, "approve" if kind == "approve"
                            else "return")
        if isinstance(result, Response) and result.status_code >= 400:
            return result
    elif doc.doc_type == "IPR" and doc.status == "APPROVED":
        # signatory authorises the overseas order — commits it and raises the PO
        from .views_documents import _do_authorise, _do_return
        result = (_do_return if kind == "return" else _do_authorise)(
            request, doc, comment)
        if isinstance(result, Response) and result.status_code >= 400:
            return result
    else:
        from .views_documents import _do_approve, _do_return
        fn = _do_approve if kind == "approve" else _do_return
        result = fn(request, doc, comment)
        if isinstance(result, Response) and result.status_code >= 400:
            return result

    audit("document", doc.id, f"MOBILE_{kind.upper()}", actor=request.user,
          detail={"ref": doc.ref, "channel": "mobile"})
    doc.refresh_from_db()
    return Response(_document_payload(doc, request))


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_approve(request, ref):
    return _act(request, ref, "approve")


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_return(request, ref):
    return _act(request, ref, "return")


# ---- Originator: my requests / timeline / alerts ------------------------

TRACKABLE = ("MR", "IR", "MAR", "PMR", "PR", "PYR")

# A live status is a "current" step; these read as finished/terminal.
_TERMINAL = {"CLOSED", "COMPLETE", "PAID", "RECEIVED", "REJECTED", "CANCELLED",
             "PAID_PO_ISSUED", "VERIFIED", "ACKNOWLEDGED"}


def _request_line(doc):
    bits = [doc.site.code] if doc.site_id else []
    if doc.project_id:
        bits.append(doc.project.code)
    bits.append(doc.status.replace("_", " ").title())
    return " · ".join(bits)


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_requests(request):
    """Documents this user raised, newest activity first, with an unread-change
    dot when an alert about them is still unread."""
    from .models import Document, Notification
    docs = Document.objects.filter(
        created_by=request.user, is_void=False, doc_type__in=TRACKABLE) \
        .select_related("site", "project").order_by("-updated_at")[:60]
    unread_refs = set(Notification.objects.filter(
        recipient=request.user, read_at__isnull=True)
        .values_list("doc_ref", flat=True))
    items = [{
        "ref": d.ref, "doc_type": d.doc_type,
        "site_code": d.site.code if d.site_id else "—",
        "status": d.status, "status_label": d.status.replace("_", " ").title(),
        "line": _request_line(d), "updated_at": d.updated_at,
        "unread": d.ref in unread_refs,
    } for d in docs]
    return Response({"items": items})


def _timeline(doc):
    """A tracking stepper derived from the document's own status audit plus its
    linked downstream documents — no new chain model (R6 §5.5)."""
    steps = [{"label": "Raised", "ref": doc.ref,
              "when": doc.created_at.date().isoformat(), "state": "done"}]
    for a in doc.approvals.select_related("actor").order_by("acted_at"):
        steps.append({
            "label": (a.result or a.action or "").replace("_", " ").title(),
            "ref": a.actor.full_name if a.actor_id else (a.actor_role or ""),
            "when": a.acted_at.date().isoformat(), "state": "done"})

    def add_linked(d, hop=0):
        seen = set()
        links = (list(d.links_from.select_related("to_document")) +
                 list(d.links_to.select_related("from_document")))
        for lk in links:
            other = (lk.to_document if lk.from_document_id == d.id
                     else lk.from_document)
            if (not other or other.id == doc.id or other.id in seen
                    or other.doc_type in ("PO",)):
                continue
            seen.add(other.id)
            steps.append({
                "label": f"{other.doc_type} · "
                         f"{other.status.replace('_', ' ').title()}",
                "ref": other.ref,
                "when": other.doc_date.isoformat() if other.doc_date else "",
                "state": "done" if other.status in _TERMINAL else "current"})
            if hop < 1 and other.doc_type in ("MR", "PR", "LM"):
                add_linked(other, hop + 1)   # e.g. MR→LM→GRN

    add_linked(doc)
    return steps


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_timeline(request, ref):
    from .models import Document
    try:
        doc = Document.objects.select_related("site", "project").get(ref=ref)
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    sids = scoped_site_ids(request.user)
    if (doc.created_by_id != request.user.id and sids is not None
            and doc.site_id not in sids):
        return Response({"detail": "Not found."}, status=404)
    return Response({"ref": doc.ref, "doc_type": doc.doc_type,
                     "title_line": _request_line(doc),
                     "status": doc.status, "steps": _timeline(doc)})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_alerts(request):
    """The originator alerts feed — the existing Notification records."""
    from .models import Notification
    from .views_notify import NotificationSerializer
    qs = Notification.objects.filter(recipient=request.user)[:40]
    unread = Notification.objects.filter(
        recipient=request.user, read_at__isnull=True).count()
    return Response({"unread": unread,
                     "items": NotificationSerializer(qs, many=True).data})


# ---- Web push subscriptions ---------------------------------------------

@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_vapid_key(request):
    from .push import vapid_public_key
    key = vapid_public_key()
    return Response({"public_key": key, "enabled": bool(key)})


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_push_subscribe(request):
    """Register this browser's push endpoint. Body: {endpoint, keys:{p256dh,
    auth}}."""
    from .models import PushSubscription
    endpoint = (request.data.get("endpoint") or "").strip()
    keys = request.data.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return Response({"detail": "endpoint + keys are required."}, status=400)
    sub, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "p256dh": keys["p256dh"][:200],
                  "auth": keys["auth"][:100],
                  "label": (request.META.get("HTTP_USER_AGENT") or "")[:120]})
    return Response({"id": sub.id}, status=201)


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_push_unsubscribe(request):
    from .models import PushSubscription
    endpoint = (request.data.get("endpoint") or "").strip()
    PushSubscription.objects.filter(user=request.user,
                                    endpoint=endpoint).delete()
    return Response({"ok": True})


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_alerts_read(request):
    from django.utils import timezone

    from .models import Notification
    qs = Notification.objects.filter(recipient=request.user,
                                     read_at__isnull=True)
    ids = request.data.get("ids")
    if ids:
        qs = qs.filter(id__in=ids)
    qs.update(read_at=timezone.now())
    return Response({"ok": True})

"""The discussion on a document (owner 2026-10-07).

A conversation that lives on the thing it is about — a payment request, a
material request, a daily report, a claim, a payroll run — where a message
can be put to a person and sits on their My Tasks until it is answered.

Rules the owner set:
  * anyone with a login can be addressed, but only people who can SEE the
    document; a worker-level user is never chased about a voucher they
    cannot open;
  * any reply in the thread by someone other than the asker answers the
    open follow-ups (the PD may answer what was put to the Signatory), and
    the person asked can also mark one answered without replying;
  * a thread never blocks the workflow; it is a conversation, not a gate.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .audit import audit
from .models import Comment, CommentRecipient, Document, User
from .permissions import scoped_site_ids

MAX_BODY = 2000
ATTENDANCE_HO_ROLES = ("HO_HR", "DIRECTOR", "FINANCE", "SIGNATORY", "ADMIN",
                       "PA")


# ---- what a thread is about ---------------------------------------------------

def canonical(key):
    """"ref:<REF>" — a document named by its reference, which is all a
    viewer may have — becomes "doc:<id>". Anything else is returned as is."""
    if str(key).startswith("ref:"):
        doc = Document.objects.filter(ref__iexact=key[4:],
                                      is_void=False).only("id").first()
        return f"doc:{doc.id}" if doc else key
    return key


class AttendanceDay:
    """A site's register for one day — not a record of its own, one row
    per worker, so the thread hangs off the pair (owner 2026-10-07)."""
    def __init__(self, site, day):
        self.site, self.day = site, day
        self.site_id = site.id

    @property
    def ref(self):
        return f"ATT-{self.site.code}-{self.day:%Y-%m-%d}"


def parse_key(key):
    """("doc"|"claim"|"payroll", id), ("att", (site_id, day)) or None."""
    try:
        kind, ident = str(key).split(":", 1)
    except (ValueError, AttributeError):
        return None
    if kind == "att":
        try:
            site_id, day = ident.split(":", 1)
            from datetime import date as _date
            return "att", (int(site_id), _date.fromisoformat(day))
        except ValueError:
            return None
    try:
        ident = int(ident)
    except ValueError:
        return None
    if kind not in ("doc", "claim", "payroll"):
        return None
    return kind, ident


def target(key):
    """The object a thread hangs off, or None."""
    parsed = parse_key(key)
    if parsed is None:
        return None
    kind, ident = parsed
    if kind == "att":
        from .models import Site
        site = Site.objects.filter(pk=ident[0]).first()
        return AttendanceDay(site, ident[1]) if site else None
    if kind == "doc":
        return Document.objects.select_related("site").filter(
            pk=ident, is_void=False).first()
    if kind == "claim":
        from .models import ProgressClaim
        return ProgressClaim.objects.select_related("project__site").filter(
            pk=ident).first()
    from .models import PayrollRun
    return PayrollRun.objects.select_related("site").filter(pk=ident).first()


def describe(key, obj):
    """The few facts a task card or a notification needs."""
    kind = parse_key(key)[0]
    if kind == "att":
        return {"ref": obj.ref, "doc_type": "ATT", "doc_date": obj.day,
                "status": "", "site_id": obj.site_id,
                "site_code": obj.site.code, "day": obj.day.isoformat()}
    if kind == "doc":
        return {"ref": obj.ref, "doc_type": obj.doc_type,
                "doc_date": obj.doc_date, "status": obj.status,
                "site_id": obj.site_id}
    if kind == "claim":
        created = getattr(obj, "created_at", None)
        return {"ref": obj.ref, "doc_type": "CLAIM",
                "doc_date": obj.work_done_upto
                or (created.date() if created else timezone.localdate()),
                "status": obj.status, "site_id": obj.project.site_id,
                "project_id": obj.project_id}
    # "PAY" is what My Tasks already uses to open a payroll run
    return {"ref": obj.ref or f"PRL {obj.year}-{obj.month:02d}",
            "doc_type": "PAY", "doc_date": obj.created_at.date(),
            "status": obj.status, "site_id": obj.site_id, "run_id": obj.id,
            "site_code": obj.site.code if obj.site_id else None}


def can_see(user, key, obj):
    """May this user open the thing the thread is about?"""
    kind = parse_key(key)[0]
    if not user.is_active:
        return False
    if kind == "att":
        # the site's own team, and the head-office roles that run or pay it
        if user.role in ATTENDANCE_HO_ROLES:
            return True
        ids = scoped_site_ids(user)
        return ids is None or obj.site_id in ids
    if kind == "doc":
        from .views_documents import SCA_VIEW_ROLES
        ids = scoped_site_ids(user)
        if ids is not None and obj.site_id not in ids:
            return False
        if obj.doc_type == "SCA" and user.role not in SCA_VIEW_ROLES:
            return False
        return True
    if kind == "claim":
        from .views_commercial import _can_view_value
        return _can_view_value(user, obj.project)
    from .views_payroll import _can_see_run

    class _R:                              # the helper reads request.user
        pass
    r = _R()
    r.user = user
    return _can_see_run(r, obj)


def site_of(key, obj):
    return describe(key, obj)["site_id"]


# ---- people ---------------------------------------------------------------------

def _chain(key, obj):
    """The people on this document, offered first in the picker: whoever
    raised it, the site's PMs, and the roles that act on it."""
    kind = parse_key(key)[0]
    people, roles = [], []
    if kind == "att":
        # the site's team first: its PMs and whoever is allocated to it
        people += list(obj.site.current_pms())
        for u in User.objects.filter(
                is_active=True, role__in=("SITE_ADMIN", "SITE_ENGINEER"),
                site_allocations__site=obj.site,
                site_allocations__to_date__isnull=True).distinct():
            people.append(u)
        roles += ["HO_HR", "DIRECTOR", "FINANCE", "SIGNATORY"]
    elif kind == "doc":
        if obj.created_by_id:
            people.append(obj.created_by)
        if obj.site_id:
            people += list(obj.site.current_pms())
        t = obj.doc_type
        if t in ("PYR", "PR", "PV", "PO", "IPR", "PMR"):
            roles += ["DIRECTOR", "SIGNATORY", "FINANCE", "HO_PURCHASING"]
        elif t in ("MR", "LM", "GRN", "MTN"):
            roles += ["HO_PURCHASING", "DIRECTOR"]
        elif t in ("DPR", "DMA", "INC", "TBT"):
            roles += ["DIRECTOR", "SIGNATORY"]
        elif t in ("OBR", "WCR"):
            roles += ["HO_HR", "DIRECTOR"]
        elif t in ("SVC", "SCA", "VO", "IPC"):
            roles += ["QS", "DIRECTOR", "SIGNATORY", "FINANCE"]
        else:
            roles += ["DIRECTOR"]
    elif kind == "claim":
        if obj.project.qs_id:
            people.append(obj.project.qs)
        people += list(obj.project.site.current_pms())
        roles += ["QS", "DIRECTOR", "FINANCE", "SIGNATORY"]
    else:
        if obj.site_id:
            people += list(obj.site.current_pms())
        roles += ["HO_HR", "DIRECTOR", "FINANCE", "SIGNATORY"]
    for u in User.objects.filter(is_active=True, role__in=roles).order_by(
            "full_name"):
        people.append(u)
    out, seen = [], set()
    for u in people:
        if u.id not in seen and u.is_active:
            seen.add(u.id)
            out.append(u)
    return out


def people(key, obj, q="", exclude=None, limit=12):
    """Who can be addressed on this thread: the document's own people
    first, then anyone else who can see it, by name."""
    q = (q or "").strip().lower()
    first = [u for u in _chain(key, obj)
             if not q or q in (u.full_name or "").lower()
             or q in (u.username or "").lower()]
    rows = [u for u in first if u.id != exclude]
    if q:
        extra = User.objects.filter(is_active=True).filter(
            Q(full_name__icontains=q) | Q(username__icontains=q)).exclude(
            id__in=[u.id for u in rows]).order_by("full_name")[:40]
        rows += [u for u in extra if u.id != exclude and can_see(u, key, obj)]
    return [{"id": u.id, "name": u.full_name or u.username,
             "role": u.get_role_display() if hasattr(u, "get_role_display")
             else u.role}
            for u in rows[:limit]]


# ---- the thread ------------------------------------------------------------------

def _row(c, me):
    recs = list(c.recipients.select_related("user", "answered_by"))
    return {
        "id": c.id, "kind": c.kind, "body": c.body,
        "author": c.author.full_name or c.author.username,
        "author_id": c.author_id, "mine": c.author_id == me.id,
        "reply_to": c.reply_to_id, "status_at": c.status_at,
        "created_at": c.created_at,
        "to": [{"id": r.user_id, "name": r.user.full_name or r.user.username,
                "answered": r.answered_at is not None,
                "answered_by": (r.answered_by.full_name
                                if r.answered_by_id else None),
                "answered_at": r.answered_at, "recipient_id": r.id,
                "me": r.user_id == me.id} for r in recs],
        "open": any(r.answered_at is None for r in recs),
    }


def thread(key, obj, me):
    rows = (Comment.objects.filter(thread=key)
            .select_related("author").prefetch_related("recipients"))
    comments = [_row(c, me) for c in rows]
    return {
        "key": key, "about": describe(key, obj), "comments": comments,
        "open_count": sum(1 for c in comments if c["open"]),
        "open_for_me": sum(1 for c in comments
                           for r in c["to"] if r["me"] and not r["answered"]),
    }


@transaction.atomic
def post(key, obj, me, body, to_ids=None, reply_to=None):
    """Add to the thread. Returns (comment, error)."""
    body = (body or "").strip()
    if not body:
        return None, "Write the message."
    if len(body) > MAX_BODY:
        return None, f"Keep it under {MAX_BODY} characters."
    to_ids = [int(i) for i in (to_ids or []) if str(i).strip()]
    recipients = []
    for u in User.objects.filter(id__in=to_ids, is_active=True):
        if u.id == me.id:
            continue
        if not can_see(u, key, obj):
            return None, (f"{u.full_name or u.username} cannot see this "
                          "document, so cannot be asked about it.")
        recipients.append(u)
    if to_ids and not recipients and all(i == me.id for i in to_ids):
        return None, "Put the question to somebody else."
    parent = None
    if reply_to:
        parent = Comment.objects.filter(pk=reply_to, thread=key).first()
    about = describe(key, obj)
    c = Comment.objects.create(
        thread=key, document=obj if parse_key(key)[0] == "doc" else None,
        kind="FOLLOWUP" if recipients else "NOTE", body=body, author=me,
        reply_to=parent, status_at=str(about["status"] or "")[:30])
    for u in recipients:
        CommentRecipient.objects.create(comment=c, user=u)
    # A reply by anyone other than the asker answers what was put to
    # anyone on this thread (owner: the PD may answer the Signatory's
    # question). The asker's own further notes do not answer their own ask.
    # A NEW question put to others is not an answer either — it answers
    # only what was put to its author.
    now = timezone.now()
    answered = (CommentRecipient.objects
                .filter(comment__thread=key, answered_at__isnull=True)
                .exclude(comment=c).exclude(comment__author=me))
    if recipients:
        answered = answered.filter(user=me)
    askers = {r.comment.author for r in answered.select_related(
        "comment__author")}
    answered.update(answered_at=now, answered_by=me, answer=c)
    from .notify import notify_user
    who = me.full_name or me.username
    doc = obj if parse_key(key)[0] == "doc" else None
    for u in recipients:
        notify_user(u, f"{who} asked on {about['ref']}", body[:300],
                    doc=doc, category="approval")
    for asker in askers:
        if asker.id != me.id:
            notify_user(asker, f"{who} replied on {about['ref']}", body[:300],
                        doc=doc, category="alert")
    audit("discussion", c.id, "COMMENT_POSTED", actor=me,
          detail={"thread": key, "ref": about["ref"], "kind": c.kind,
                  "to": [u.id for u in recipients]})
    return c, None


def mark_answered(rec, me):
    """The person asked, or the asker, closes a follow-up without a reply."""
    if rec.answered_at is not None:
        return "Already answered."
    if me.id not in (rec.user_id, rec.comment.author_id):
        return "Only the person asked, or the asker, can mark it answered."
    rec.answered_at = timezone.now()
    rec.answered_by = me
    rec.save(update_fields=["answered_at", "answered_by"])
    audit("discussion", rec.comment_id, "FOLLOWUP_MARKED_ANSWERED", actor=me,
          detail={"thread": rec.comment.thread, "recipient": rec.user_id})
    return None


# ---- the action list -------------------------------------------------------------

def _item(c, r=None):
    obj = c.document or target(c.thread)
    if obj is None:
        return None
    about = describe(c.thread, obj)
    who = c.author.full_name or c.author.username
    age = (timezone.now() - c.created_at).days
    return {**about, "thread": c.thread, "comment_id": c.id,
            "recipient_id": r.id if r else None,
            "asked_at": c.created_at, "days_open": age,
            "asked_by": who, "body": c.body[:200],
            "to": [x.user.full_name or x.user.username
                   for x in c.recipients.all() if x.answered_at is None],
            "hint": f"{who}: {c.body[:140]}"}


def open_followups(user, limit=100):
    """Follow-ups waiting on this user, as My Tasks items: newest first."""
    rows = (CommentRecipient.objects
            .filter(user=user, answered_at__isnull=True)
            .select_related("comment__author", "comment__document__site")
            .prefetch_related("comment__recipients__user")
            .order_by("-comment__created_at")[:limit])
    items = [_item(r.comment, r) for r in rows]
    return [i for i in items if i]


def asked_by_me(user, limit=100):
    """Questions this user put to others that nobody has answered yet —
    what is outstanding, without hunting through documents."""
    rows = (Comment.objects.filter(author=user, kind="FOLLOWUP",
                                   recipients__answered_at__isnull=True)
            .distinct().select_related("author", "document__site")
            .prefetch_related("recipients__user")
            .order_by("-created_at")[:limit])
    items = [_item(c) for c in rows]
    return [i for i in items if i]


def counts_for_documents(doc_ids):
    """{document_id: (comments, open follow-ups)} for list rows."""
    from django.db.models import Count
    out = {}
    for row in (Comment.objects.filter(document_id__in=doc_ids)
                .values("document_id").annotate(n=Count("id"))):
        out[row["document_id"]] = [row["n"], 0]
    for row in (CommentRecipient.objects
                .filter(comment__document_id__in=doc_ids,
                        answered_at__isnull=True)
                .values("comment__document_id")
                .annotate(n=Count("comment_id", distinct=True))):
        out.setdefault(row["comment__document_id"], [0, 0])[1] = row["n"]
    return out

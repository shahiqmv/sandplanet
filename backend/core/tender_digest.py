"""Read a tender's document pack into a digest the QS reviews.

A big enquiry arrives as hundreds of pages — instructions to tenderers,
conditions of contract, specification, drawings register, the bill — and the
first day of a tender is spent finding out what is in it: what is being asked
for, when it is due and in what form, which bonds and insurances are wanted,
what the contract will do to us, and which points are unclear enough to ask
the client about. This module does that first read (owner 2026-09-16).

The shape is the one BOQ capture set: Claude drafts, a person commits. The
digest is a record on the tender that the QS reads; nothing in it changes the
tender by itself, and the candidate queries it lists only become a Tender
Query when someone raises them.

Reading is limited to documents held on the server. A pack filed as a
OneDrive or Dropbox link is not readable here, and the digest says which
documents it could not read rather than pretending to have read the pack.

The Claude call reads ANTHROPIC_API_KEY from the environment and the model
from the `tender_digest_model` company parameter. It runs in a background
thread because a full pack can take minutes and gunicorn's workers are
synchronous; the screen polls the record.
"""
import json
import logging
import os
import threading
from decimal import Decimal

from django.utils import timezone

from .boq_extract import ExtractionError, excel_pages, pdf_pages

log = logging.getLogger("tender_digest")

DEFAULT_MODEL = "claude-opus-5"
_MAX_OUTPUT_TOKENS = 16000
# Roughly 500k tokens of pack text. Opus 5 reads a million, but a pack that
# size is several tenders' worth and is better split by the QS.
_MAX_PACK_CHARS = 2_000_000
# Anthropic first-party list price, USD per million tokens, for the estimate
# shown before the button is pressed and the cost stamped on the record.
_PRICES = {
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10")),
    "claude-fable-5-1": (Decimal("10"), Decimal("50")),
}
# A worker restart kills a running thread without a trace; a record still
# RUNNING after this long is reported failed rather than spinning for ever.
_STALE_MINUTES = 20

READABLE = {"application/pdf": "pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml"
            ".sheet": "xlsx", "application/vnd.ms-excel": "xlsx"}


def model_name():
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="tender_digest_model").value
        return (v or "").strip() or DEFAULT_MODEL
    except CompanyParameter.DoesNotExist:
        return DEFAULT_MODEL


def _kind(att):
    name = (att.file_name or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return "xlsx"
    return READABLE.get((att.content_type or "").lower())


# ---- what the pack holds ------------------------------------------------

def pack_documents(tender):
    """The tender's documents split into what can be read here and what
    cannot (links, and file types the reader does not handle)."""
    readable, skipped = [], []
    for a in tender.document.attachments.exclude(
            kind="GENERATED_PDF").order_by("id"):
        if a.external_url:
            skipped.append({"name": a.file_name, "why": "kept elsewhere "
                            "(link) — upload the file to read it"})
        elif not a.file:
            skipped.append({"name": a.file_name, "why": "no file"})
        elif _kind(a) is None:
            skipped.append({"name": a.file_name,
                            "why": "not a PDF or Excel file"})
        else:
            readable.append(a)
    return readable, skipped


def read_pack(attachments):
    """Every readable document as page-marked text, in filing order, up to
    the size cap. Returns (text, read, skipped)."""
    parts, read, skipped, size = [], [], [], 0
    for a in attachments:
        try:
            with a.file.open("rb") as fh:
                pages = pdf_pages(fh) if _kind(a) == "pdf" else excel_pages(fh)
        except ExtractionError as e:
            skipped.append({"name": a.file_name, "why": str(e)})
            continue
        except Exception as e:                   # a corrupt upload
            skipped.append({"name": a.file_name, "why": f"could not be read "
                            f"({e})"})
            continue
        body = "\n\n".join(f"[{a.file_name} — PAGE {i + 1}]\n{p}"
                           for i, p in enumerate(pages) if p.strip())
        if size + len(body) > _MAX_PACK_CHARS:
            skipped.append({"name": a.file_name, "why": "over the size the "
                            "digest reads at once — read it separately"})
            continue
        parts.append(f"===== DOCUMENT: {a.file_name} ({a.get_kind_display()})"
                     f" =====\n{body}")
        read.append({"name": a.file_name, "kind": a.kind, "pages": len(pages)})
        size += len(body)
    return "\n\n".join(parts), read, skipped


def estimate(tender):
    """What reading this pack would cost, from the files' sizes, so the QS
    sees a number before pressing the button. Text is roughly four
    characters a token; PDFs are mostly layout, so the byte size is scaled
    down rather than taken as text."""
    readable, skipped = pack_documents(tender)
    chars = 0
    for a in readable:
        bytes_ = a.size_bytes or 0
        chars += bytes_ // 3 if _kind(a) == "pdf" else bytes_ // 6
    chars = min(chars, _MAX_PACK_CHARS)
    tokens = chars // 4
    model = model_name()
    price_in, price_out = _PRICES.get(model, _PRICES[DEFAULT_MODEL])
    usd = (Decimal(tokens) * price_in + Decimal(6000) * price_out) \
        / Decimal(1_000_000)
    return {"documents": [{"name": a.file_name, "kind": a.get_kind_display()}
                          for a in readable],
            "skipped": skipped, "approx_tokens": tokens,
            "approx_usd": str(usd.quantize(Decimal("0.01"))), "model": model}


# ---- the model call -----------------------------------------------------

_SYSTEM = (
    "You are a senior quantity surveyor's assistant at a Maldivian marine and "
    "civil construction contractor. You have been handed the complete document "
    "pack of a tender enquiry as page-marked text. Read all of it and produce "
    "the first-day digest the estimating team needs before pricing.\n\n"
    "Rules:\n"
    "- Report only what the documents say. Do not invent dates, sums, or "
    "clauses. Where the pack is silent on something the team would expect "
    "(e.g. no bond stated), say it is not stated.\n"
    "- Every item carries a source: the document name and page it came from, "
    "as 'name p.N'. Quote short phrases where the wording itself matters "
    "(deadlines, percentages, liquidated damages).\n"
    "- Candidate queries are points that are ambiguous, contradictory between "
    "documents, missing, or would change the price materially. Write each as "
    "a question the client can answer, with the reference the client needs "
    "to look at.\n"
    "- Keep every text field concise: a line or two, not paragraphs.\n"
    "- Dates are given as written in the pack plus an ISO date when it can be "
    "read unambiguously; otherwise leave the ISO field empty."
)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "scope", "key_dates", "submission", "commercial",
                 "risks", "queries", "documents_missing"],
    "properties": {
        "summary": {"type": "string",
                    "description": "Three or four sentences: who the client "
                                   "is, what the works are, where, and the "
                                   "form of contract."},
        "scope": {"type": "array", "items": {"type": "object",
                  "additionalProperties": False,
                  "required": ["item", "source"],
                  "properties": {"item": {"type": "string"},
                                 "source": {"type": "string"}}}},
        "key_dates": {"type": "array", "items": {"type": "object",
                      "additionalProperties": False,
                      "required": ["label", "as_written", "iso", "source"],
                      "properties": {"label": {"type": "string"},
                                     "as_written": {"type": "string"},
                                     "iso": {"type": "string"},
                                     "source": {"type": "string"}}}},
        "submission": {"type": "object", "additionalProperties": False,
                       "required": ["how", "deliverables"],
                       "properties": {
                           "how": {"type": "string",
                                   "description": "Where and in what form "
                                                  "the offer is submitted."},
                           "deliverables": {"type": "array", "items": {
                               "type": "object", "additionalProperties": False,
                               "required": ["item", "source"],
                               "properties": {"item": {"type": "string"},
                                              "source": {"type": "string"}}}}}},
        "commercial": {"type": "array",
                       "description": "Bonds, insurances, retention, payment "
                                      "terms, liquidated damages, defects "
                                      "period, validity, currency, taxes.",
                       "items": {"type": "object",
                                 "additionalProperties": False,
                                 "required": ["topic", "detail", "source"],
                                 "properties": {"topic": {"type": "string"},
                                                "detail": {"type": "string"},
                                                "source": {"type": "string"}}}},
        "risks": {"type": "array", "items": {"type": "object",
                  "additionalProperties": False,
                  "required": ["risk", "detail", "source"],
                  "properties": {"risk": {"type": "string"},
                                 "detail": {"type": "string"},
                                 "source": {"type": "string"}}}},
        "queries": {"type": "array", "items": {"type": "object",
                    "additionalProperties": False,
                    "required": ["question", "reference", "why"],
                    "properties": {"question": {"type": "string"},
                                   "reference": {"type": "string"},
                                   "why": {"type": "string"}}}},
        "documents_missing": {"type": "array", "items": {"type": "string"},
                              "description": "Documents the pack refers to "
                                             "but which are not in it."},
    },
}


def _call_claude(pack_text, model):
    """One digest call. Isolated so tests can monkeypatch it. Returns
    (digest dict, usage dict)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError(
            "The pack digest needs an ANTHROPIC_API_KEY — ask the "
            "administrator to set it in the server environment.")
    try:
        import anthropic
    except ImportError:                          # pragma: no cover - env dep
        raise ExtractionError("The anthropic SDK isn't installed on the server.")
    client = anthropic.Anthropic(api_key=key)
    content = [
        # The pack is cached so a follow-up read of the same tender (a second
        # digest after more documents, later an "ask the pack") reuses it.
        {"type": "text", "text": pack_text,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Produce the digest of this tender pack."},
    ]
    try:
        with client.beta.messages.stream(
                model=model, max_tokens=_MAX_OUTPUT_TOKENS, system=_SYSTEM,
                thinking={"type": "adaptive"},
                output_config={"effort": "high",
                               "format": {"type": "json_schema",
                                          "schema": _SCHEMA}},
                # A policy decline reruns on a substitute model rather than
                # leaving the QS with nothing.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": content}]) as stream:
            msg = stream.get_final_message()
    except Exception as e:                       # pragma: no cover - network
        raise ExtractionError(f"The digest model failed: {e}")
    if msg.stop_reason == "refusal":
        raise ExtractionError("The model declined to read this pack.")
    text = next((b.text for b in msg.content
                 if getattr(b, "type", None) == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        raise ExtractionError("The model returned no readable digest.")
    u = msg.usage
    usage = {"input": (u.input_tokens or 0)
             + (getattr(u, "cache_creation_input_tokens", 0) or 0)
             + (getattr(u, "cache_read_input_tokens", 0) or 0),
             "output": u.output_tokens or 0, "model": msg.model}
    return data, usage


def _cost(usage):
    price_in, price_out = _PRICES.get(usage.get("model") or "",
                                      _PRICES[DEFAULT_MODEL])
    return ((Decimal(usage["input"]) * price_in
             + Decimal(usage["output"]) * price_out)
            / Decimal(1_000_000)).quantize(Decimal("0.0001"))


# ---- the record ---------------------------------------------------------

def start(tender, actor, background=True):
    """Open a digest record and run it. Returns (digest, error)."""
    from .audit import audit
    from .models import TenderDigest
    running = tender.digests.filter(status="RUNNING").first()
    if running and not is_stale(running):
        return None, "The pack is already being read."
    readable, skipped = pack_documents(tender)
    if not readable:
        return None, ("Nothing here can be read: upload the pack's PDF or "
                      "Excel files under Documents first. Links are not "
                      "readable.")
    d = TenderDigest.objects.create(
        tender=tender, status="RUNNING", model=model_name(),
        started_by=actor, documents=[], skipped=skipped)
    audit("tender", tender.id, "TENDER_DIGEST_STARTED", actor=actor,
          detail={"ref": tender.document.ref, "digest": d.id,
                  "documents": len(readable)})
    from django.conf import settings
    if background and not getattr(settings, "TESTING", False):
        threading.Thread(target=run, args=(d.id, True), daemon=True).start()
    else:
        run(d.id, False)
        d.refresh_from_db()
    return d, None


def run(digest_id, own_thread=True):
    """The whole read. Every outcome lands on the record.

    On its own thread the DB connection is this thread's to open and close;
    run inline (tests) it is the caller's, and closing it under a request
    breaks the request (CI on Postgres, 2026-09-16)."""
    from django.db import close_old_connections

    from .models import TenderDigest
    if own_thread:
        close_old_connections()
    d = TenderDigest.objects.select_related("tender__document").get(
        pk=digest_id)
    try:
        readable, skipped = pack_documents(d.tender)
        text, read, more_skipped = read_pack(readable)
        if not read:
            raise ExtractionError("None of the documents could be read.")
        data, usage = _call_claude(text, d.model)
        d.result = data
        d.documents = read
        d.skipped = skipped + more_skipped
        d.input_tokens = usage["input"]
        d.output_tokens = usage["output"]
        d.model = usage.get("model") or d.model
        d.cost_usd = _cost(usage)
        d.status = "DONE"
    except ExtractionError as e:
        d.status, d.error = "FAILED", str(e)
    except Exception as e:                       # never leave it RUNNING
        log.exception("Tender digest %s failed", digest_id)
        d.status, d.error = "FAILED", f"The read failed: {e}"
    d.finished_at = timezone.now()
    d.save()
    if own_thread:
        close_old_connections()


def is_stale(d):
    return (d.status == "RUNNING" and d.started_at
            < timezone.now() - timezone.timedelta(minutes=_STALE_MINUTES))


def payload(d):
    if d is None:
        return None
    if is_stale(d):
        d.status, d.error = "FAILED", ("The read did not finish — the server "
                                       "restarted while it ran. Read again.")
        d.finished_at = timezone.now()
        d.save(update_fields=["status", "error", "finished_at"])
    return {"id": d.id, "status": d.status, "model": d.model,
            "started_at": d.started_at, "finished_at": d.finished_at,
            "started_by": d.started_by.full_name if d.started_by else "",
            "documents": d.documents, "skipped": d.skipped,
            "result": d.result, "error": d.error,
            "input_tokens": d.input_tokens, "output_tokens": d.output_tokens,
            "cost_usd": str(d.cost_usd) if d.cost_usd is not None else None,
            "raised_query_ref": d.raised_query.ref if d.raised_query_id else None}


def raise_queries(d, picks, actor):
    """Turn the chosen candidate queries into a TQ sheet the QS finishes.

    `picks` are indexes into the digest's queries. One sheet per digest: a
    second press adds to the sheet already opened from it, unless that sheet
    has gone to the client."""
    from . import tenders as svc
    if d.status != "DONE" or not d.result:
        return None, "There is no digest to raise queries from."
    cands = d.result.get("queries") or []
    chosen = [cands[i] for i in picks if 0 <= i < len(cands)]
    if not chosen:
        return None, "Tick at least one query to raise."
    t = d.tender
    q = d.raised_query if d.raised_query_id else None
    if q is not None and q.is_issued:
        q = None
    if q is None:
        q, err = svc.open_query(
            t, {"subject": "Points arising from the tender pack"}, actor)
        if err:
            return None, err
        d.raised_query = q
        d.save(update_fields=["raised_query"])
    have = {i.question.strip() for i in q.items.all()}
    added = 0
    for c in chosen:
        if c["question"].strip() in have:
            continue
        _item, err = svc.add_question(
            t, q.id, {"question": c["question"], "reference": c["reference"]},
            actor)
        if err:
            return None, err
        added += 1
    from .audit import audit
    audit("tender", t.id, "TENDER_DIGEST_QUERIES_RAISED", actor=actor,
          detail={"ref": t.document.ref, "query": q.ref, "added": added})
    return q, None

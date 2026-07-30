"""Capture an MS Project construction programme from a PDF into reviewable
activities, using Claude — the same pattern as the BOQ capture (boq_extract).

Users kept getting garbled rows from raw PDF text (columns and Gantt labels
bleed into the task names). Claude reconstructs the task table reliably. Nothing
is auto-committed: the extracted activities are returned for the PM to review
and correct before importing into the live programme.

Reads ANTHROPIC_API_KEY from the environment and the model from the
`programme_extract_model` company parameter (default Claude Sonnet). Text
extraction is the shared, testable boq_extract.pdf_pages.
"""
import os
import re

from .boq_extract import ExtractionError, _batches, pdf_pages

DEFAULT_MODEL = "claude-sonnet-5"

# A programme task table is dense: every row becomes a structured activity, so
# a page of ~40 rows emits far more output than its input text suggests. The
# shared BOQ batcher (24k input chars/call) packed 5 MS-Project pages — ~200
# tasks — into one call, whose tool_use JSON then overran an 8k max_tokens cap
# and was silently truncated to a handful of rows. Batch ~one page per call so
# the output always fits, and give the response generous headroom.
_PAGE_BATCH_CHARS = 6000
_MAX_TOKENS = 16000

_SYSTEM = (
    "You extract a construction project programme (an MS Project / Primavera "
    "schedule printout) from the given document text into structured "
    "activities. Rules:\n"
    "- Return one activity per task or milestone, in document (row) order.\n"
    "- `level` is the outline indent: 0 for a top-level summary/phase, 1 for "
    "its children, 2 for theirs, and so on. Preserve the hierarchy shown by the "
    "row indentation or WBS numbering.\n"
    "- `duration_days` is the working-day duration as a whole number; a "
    "milestone is 0. `is_milestone` is true for 0-day items or diamond "
    "milestones.\n"
    "- `start` and `finish` are ISO dates (YYYY-MM-DD); convert whatever date "
    "format is printed. Leave blank if a row has none.\n"
    "- `progress` is the percent complete as a number 0-100 only if the "
    "schedule prints it; otherwise omit it.\n"
    "- `predecessors` is the raw predecessor cell (e.g. '12FS+2 days') if "
    "shown.\n"
    "- Skip the page header/footer, the Gantt timescale labels (months, weeks, "
    "day numbers), the legend, the column-header row and page numbers. Never "
    "invent tasks, dates or durations that aren't in the document."
)

_TOOL = {
    "name": "emit_programme",
    "description": "Return the structured programme activities from the document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "activities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "level": {"type": "integer"},
                        "duration_days": {"type": "integer"},
                        "start": {"type": "string"},
                        "finish": {"type": "string"},
                        "is_milestone": {"type": "boolean"},
                        "predecessors": {"type": "string"},
                        "progress": {"type": "number"},
                        "page": {"type": "integer"},
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["activities"],
    },
}


def _model_name():
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="programme_extract_model").value
        return (v or "").strip() or DEFAULT_MODEL
    except CompanyParameter.DoesNotExist:
        return DEFAULT_MODEL


def _call_claude(content, model):
    """One structured extraction call. Isolated so tests can monkeypatch it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError(
            "Programme capture needs an ANTHROPIC_API_KEY — ask the "
            "administrator to set it in the server environment.")
    try:
        import anthropic
    except ImportError:                          # pragma: no cover - env dep
        raise ExtractionError("The anthropic SDK isn't installed on the server.")
    client = anthropic.Anthropic(api_key=key)
    try:
        msg = client.messages.create(
            model=model, max_tokens=_MAX_TOKENS, system=_SYSTEM, tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_programme"},
            messages=[{"role": "user", "content": content}])
    except Exception as e:                        # pragma: no cover - network
        raise ExtractionError(f"The extraction model failed: {e}")
    # A truncated response drops activities silently — surface it instead of
    # returning a partial programme.
    if getattr(msg, "stop_reason", None) == "max_tokens":
        raise ExtractionError(
            "That programme page has too many tasks to read in one pass — "
            "split the PDF into fewer pages and try again.")
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ExtractionError("The model returned no activities.")


def structure(pages, model=None):
    """Run the (possibly batched) extraction over the document pages."""
    model = model or _model_name()
    acts = []
    for batch in _batches(pages, max_chars=_PAGE_BATCH_CHARS):
        header = ("Extract the project programme from this document text. "
                  "Page markers are shown as [PAGE n].\n\n")
        body = "\n\n".join(f"[PAGE {n}]\n{text}" for n, text in batch)
        out = _call_claude(header + body, model) or {}
        acts.extend(out.get("activities") or [])
    return acts


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _iso(v):
    s = str(v or "").strip()
    return s if _ISO.match(s) else ""


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pct(v):
    try:
        return max(0.0, min(round(float(v), 2), 100.0))
    except (TypeError, ValueError):
        return 0


def normalise(acts):
    """Coerce model rows to the programme-import shape."""
    out = []
    for a in acts:
        name = str(a.get("name") or "").strip()
        if not name:
            continue
        dur = _int(a.get("duration_days"))
        out.append({
            "name": name,
            "indent": max(0, min(_int(a.get("level")) or 0, 8)),
            "duration_days": dur,
            "start": _iso(a.get("start")),
            "finish": _iso(a.get("finish")),
            "is_milestone": bool(a.get("is_milestone")) or dur == 0,
            "predecessors": str(a.get("predecessors") or "").strip()[:200],
            "progress": _pct(a.get("progress")),
        })
    return out


def run_capture(upload, model=None):
    """Read + extract an uploaded programme PDF into review-ready activities.
    Returns (activities, error)."""
    name = (getattr(upload, "name", "") or "").lower()
    if not name.endswith(".pdf"):
        return None, "Upload the programme as a PDF (an MS Project export)."
    pages = pdf_pages(upload)
    acts = normalise(structure(pages, model))
    if not acts:
        return None, ("No programme activities were found in that PDF — check "
                      "it's the schedule/task list and try again.")
    return acts, None

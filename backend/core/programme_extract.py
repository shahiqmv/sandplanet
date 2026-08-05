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
    try:
        client = anthropic.Anthropic(api_key=key)
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
    """Run the (possibly batched) extraction over the document pages.

    One page batch = one model call. A multi-page programme is many batches,
    so they run CONCURRENTLY — wall time is the slowest single page, not the
    sum, which keeps a 6-page programme inside the request timeout instead of
    stacking six sequential calls past it. Order is preserved."""
    from concurrent.futures import ThreadPoolExecutor
    model = model or _model_name()
    batches = _batches(pages, max_chars=_PAGE_BATCH_CHARS)

    def run(batch):
        header = ("Extract the project programme from this document text. "
                  "Page markers are shown as [PAGE n].\n\n")
        body = "\n\n".join(f"[PAGE {n}]\n{text}" for n, text in batch)
        return _call_claude(header + body, model) or {}

    if len(batches) <= 1:
        outs = [run(b) for b in batches]
    else:
        with ThreadPoolExecutor(max_workers=min(len(batches), 5)) as ex:
            outs = list(ex.map(run, batches))       # ex.map preserves order

    acts = []
    for out in outs:
        items = out.get("activities") if isinstance(out, dict) else None
        if isinstance(items, list):        # only a list; never spread a string
            acts.extend(items)
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
        if isinstance(a, str):            # model returned a bare task name
            a = {"name": a}
        elif not isinstance(a, dict):     # anything else is unusable — skip it
            continue
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


# ---- deterministic table parse (primary path) ---------------------------
# An MS Project / Primavera PDF export is a clean table: a sequential ID column,
# an indented Task Name, Duration, Start, Finish, then the Gantt bars. Reading it
# straight from the word geometry captures EVERY row (the ID column proves none
# are dropped) and takes the outline level from the name indentation — so it is
# exact and repeatable, unlike the model, which was silently dropping rows and a
# whole page at a time and mis-guessing levels (owner/team 2026-08-04). The model
# stays as a fallback for a non-tabular or scanned PDF.

_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")
_DUR = re.compile(r"^\d+(?:\.\d+)?$")
_MIN_TABLE_ROWS = 8          # below this it isn't a recognisable task table


def _page_rows(page, tol=3):
    """Cluster a page's words into visual rows (by y), each sorted left→right."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    rows = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        for r in rows:
            if abs(r["top"] - w["top"]) <= tol:
                r["ws"].append(w)
                break
        else:
            rows.append({"top": w["top"], "ws": [w]})
    for r in rows:
        r["ws"].sort(key=lambda w: w["x0"])
    return sorted(rows, key=lambda r: r["top"])


def _mdy_iso(tok):
    m = _MDY.match(tok)
    if not m:
        return ""
    mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if yr < 100:
        yr += 2000
    try:
        from datetime import date
        return date(yr, mo, da).isoformat()
    except ValueError:
        return ""


def _level_bands(x0s, tol=3.0):
    """Distinct name-column x-positions → outline level 0,1,2,… The indent step
    and left margin vary by export, so derive the bands from the data."""
    bands = []
    for x in sorted(x0s):
        if not bands or x - bands[-1] > tol:
            bands.append(x)
    return bands


def parse_pdf_programme(upload):
    """Deterministic capture from the table geometry. Returns (activities, meta)
    or (None, None) when the PDF isn't a recognisable MS Project task table (the
    caller then falls back to the model)."""
    import pdfplumber
    try:
        upload.seek(0)
    except Exception:                             # pragma: no cover
        pass
    all_rows = []                                 # (page_index, clustered_rows)
    with pdfplumber.open(upload) as pdf:
        for pi, page in enumerate(pdf.pages):
            all_rows.append((pi, _page_rows(page)))

    # The ID column = the leftmost cluster of rows whose first word is an integer
    # (this excludes the Gantt timescale numbers, which sit far to the right).
    lead_int_x = [r["ws"][0]["x0"] for _, rows in all_rows for r in rows
                  if r["ws"] and r["ws"][0]["text"].isdigit()]
    if not lead_int_x:
        return None, None
    id_x = min(lead_int_x)
    name_zone = id_x + 15                         # left edge of the name column

    raw = []
    for pi, rows in all_rows:
        for r in rows:
            ws = r["ws"]
            if not ws:
                continue
            first = ws[0]
            is_data = first["text"].isdigit() and first["x0"] <= name_zone
            if not is_data:
                # A wrapped task name continues on the next line: indented into
                # the name column, no ID/dates, and directly under its own row.
                # The vertical-proximity check keeps the page-bottom Gantt legend
                # ("Task / Split / Milestone / Summary / Manual Task …") from
                # being glued onto the last activity.
                if (raw and first["x0"] > name_zone
                        and raw[-1]["page"] == pi + 1
                        and 0 < r["top"] - raw[-1]["_top"] < 20
                        and not any(_MDY.match(w["text"]) for w in ws)):
                    raw[-1]["name"] += " " + " ".join(w["text"] for w in ws)
                    raw[-1]["_top"] = r["top"]
                continue
            seq = int(first["text"])
            rest = ws[1:]
            name, dur, i = [], None, 0
            while i < len(rest):
                t = rest[i]["text"]
                nxt = rest[i + 1]["text"].lower() if i + 1 < len(rest) else ""
                if _DUR.match(t) and nxt.startswith("day"):
                    dur = int(float(t))
                    i += 2
                    break
                name.append(t)
                i += 1
            if not name:
                continue
            dates = []
            for w in rest[i:]:
                iso = _mdy_iso(w["text"])
                if iso:
                    dates.append(iso)
                    if len(dates) >= 2:
                        break
            raw.append({
                "seq": seq, "name": " ".join(name),
                "name_x0": rest[0]["x0"], "duration_days": dur, "page": pi + 1,
                "_top": r["top"],
                "start": dates[0] if dates else "",
                "finish": dates[1] if len(dates) > 1 else "",
            })

    if len(raw) < _MIN_TABLE_ROWS:
        return None, None

    bands = _level_bands([r["name_x0"] for r in raw])

    def level_of(x0):
        lvl = 0
        for i, b in enumerate(bands):
            if x0 >= b - 1.5:
                lvl = i
        return lvl

    acts = []
    for r in raw:
        dur = r["duration_days"]
        acts.append({
            "name": r["name"].strip(),
            "indent": max(0, min(level_of(r["name_x0"]), 8)),
            "duration_days": dur,
            "start": r["start"], "finish": r["finish"],
            "is_milestone": dur == 0,
            "predecessors": "", "progress": 0,
            "seq": r["seq"],
        })
    seqs = [r["seq"] for r in raw]
    meta = {"count": len(acts), "first": min(seqs), "last": max(seqs),
            "missing": sorted(set(range(min(seqs), max(seqs) + 1)) - set(seqs))}
    return acts, meta


def run_capture(upload, model=None):
    """Read + extract an uploaded programme PDF into review-ready activities.
    Returns (activities, meta, error). Tries the deterministic table parser
    first (exact + repeatable); falls back to the model for a non-tabular PDF."""
    name = (getattr(upload, "name", "") or "").lower()
    if not name.endswith(".pdf"):
        return None, None, "Upload the programme as a PDF (an MS Project export)."
    try:
        acts, meta = parse_pdf_programme(upload)
    except Exception:                             # pragma: no cover - defensive
        acts, meta = None, None
    if acts:
        return acts, meta, None
    # Fallback: a non-MS-Project layout or a scanned PDF — let the model read it.
    try:
        upload.seek(0)
    except Exception:                             # pragma: no cover
        pass
    pages = pdf_pages(upload)
    acts = normalise(structure(pages, model))
    if not acts:
        return None, None, ("No programme activities were found in that PDF — "
                            "check it's the schedule/task list and try again.")
    return acts, None, None

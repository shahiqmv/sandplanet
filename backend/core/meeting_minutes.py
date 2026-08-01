"""Claude-drafted meeting minutes (owner 2026-07-31, meeting module Phase 2).

The organiser types rough notes; Claude turns them into clean structured
minutes and extracts the action items (what / who / by when) for review. Mirrors
the isolated-_call_claude + tool-calling pattern of boq_extract / programme_
extract so tests can monkeypatch the model call. Needs ANTHROPIC_API_KEY.
"""
import os

from .boq_extract import ExtractionError

DEFAULT_MODEL = "claude-sonnet-5"

_SYSTEM = (
    "You are minuting a business meeting for a construction company (client "
    "reviews, site meetings, new-client/BD discussions). From the organiser's "
    "rough notes, produce clean, professional minutes AND extract the action "
    "items.\n"
    "Minutes: a concise structured write-up — a short context line, then the "
    "discussion grouped under simple topic headings, then a 'Decisions' list. "
    "Plain text with simple headings; no markdown tables.\n"
    "Action items: every concrete follow-up — what is to be done, who owns it "
    "(the person or party named in the notes), and a due date. Return due_date "
    "as YYYY-MM-DD when a date is given or can be computed from the meeting "
    "date; otherwise leave it blank.\n"
    "Never invent facts, attendees, decisions or dates — use only what the "
    "notes contain."
)

_TOOL = {
    "name": "emit_minutes",
    "description": "Return the drafted minutes and the extracted action items.",
    "input_schema": {
        "type": "object",
        "properties": {
            "minutes": {"type": "string",
                        "description": "The structured minutes, plain text."},
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "owner": {"type": "string"},
                        "due_date": {"type": "string"},
                    },
                    "required": ["description"],
                },
            },
        },
        "required": ["minutes", "action_items"],
    },
}


def _model_name():
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="meeting_minutes_model").value
        return (v or "").strip() or DEFAULT_MODEL
    except CompanyParameter.DoesNotExist:
        return DEFAULT_MODEL


def _call_claude(content, model):
    """One structured extraction call. Isolated so tests can monkeypatch it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError(
            "Minutes drafting needs an ANTHROPIC_API_KEY — ask the "
            "administrator to set it in the server environment.")
    try:
        import anthropic
    except ImportError:                          # pragma: no cover - env dep
        raise ExtractionError("The anthropic SDK isn't installed on the server.")
    client = anthropic.Anthropic(api_key=key)
    try:
        msg = client.messages.create(
            model=model, max_tokens=4000, system=_SYSTEM, tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_minutes"},
            messages=[{"role": "user", "content": content}])
    except Exception as e:                        # pragma: no cover - network
        raise ExtractionError(f"The minutes model failed: {e}")
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ExtractionError("The model returned no minutes.")


def _clean_date(v):
    from django.utils.dateparse import parse_date
    if not v:
        return ""
    d = parse_date(str(v).strip()[:10])
    return d.isoformat() if d else ""


def _context(meeting, notes):
    type_label = dict(meeting.Type.choices).get(meeting.meeting_type,
                                                meeting.meeting_type)
    who = (meeting.project.code if meeting.project_id
           else meeting.org_name or (meeting.site.code if meeting.site_id
                                     else ""))
    names = [a.user.full_name if a.user_id else a.name
             for a in meeting.attendees.all()]
    lines = [
        f"Meeting: {meeting.title}",
        f"Type: {type_label}",
        f"Date: {meeting.scheduled_at:%Y-%m-%d}",
    ]
    if who:
        lines.append(f"With: {who}")
    if names:
        lines.append("Attendees: " + ", ".join(n for n in names if n))
    if meeting.agenda.strip():
        lines.append(f"Agenda:\n{meeting.agenda.strip()}")
    lines.append(f"\nRough notes:\n{notes.strip()}")
    return "\n".join(lines)


def draft_minutes(meeting, notes, model=None):
    """Draft minutes + action items from rough notes. Returns
    (minutes_text, [action_item dicts], error)."""
    if not (notes or "").strip():
        return None, None, "Type some notes for Claude to work from."
    try:
        out = _call_claude(_context(meeting, notes),
                           model or _model_name()) or {}
    except ExtractionError as e:
        return None, None, str(e)
    minutes = (out.get("minutes") or "").strip()
    actions = []
    for a in (out.get("action_items") or []):
        desc = (a.get("description") or "").strip()
        if not desc:
            continue
        actions.append({
            "description": desc,
            "owner_name": (a.get("owner") or "").strip()[:160],
            "due_date": _clean_date(a.get("due_date")),
            "status": "OPEN",
        })
    return minutes, actions, None

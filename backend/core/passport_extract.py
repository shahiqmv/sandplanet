"""Capture candidate details from a passport image/PDF into the new-case form.

HR uploads the passport bio-data (photo) page; Claude reads it into structured
fields (full name, passport no, nationality, DOB, gender, expiry) that prefill
the new onboarding-case form for review before saving. The same image is then
stored as the passport-copy checklist document (the frontend uploads it to the
case after creation).

Reads ANTHROPIC_API_KEY from the environment and the model from the
`passport_extract_model` company parameter (default Claude Sonnet, a vision
model). The Claude call is isolated so tests can monkeypatch it.
"""
import base64
import os
import re

DEFAULT_MODEL = "claude-sonnet-5"
_MAX_BYTES = 6 * 1024 * 1024

_MEDIA = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
          "webp": "image/webp", "gif": "image/gif"}


class ScanError(Exception):
    """A user-facing passport-scan failure (bad file, missing key, model error)."""


_SYSTEM = (
    "You read a passport bio-data (photo) page and extract the holder's "
    "details. Rules:\n"
    "- full_name: the holder's full name in Latin letters, as printed.\n"
    "- passport_no: the passport / document number.\n"
    "- nationality: the country of nationality in plain English (e.g. 'Indian', "
    "'Sri Lankan', 'Bangladeshi'), never a code.\n"
    "- date_of_birth and passport_expiry: ISO yyyy-mm-dd.\n"
    "- gender: 'Male' or 'Female'.\n"
    "- Cross-check the machine-readable zone (MRZ) at the bottom when a printed "
    "field is unclear. Leave a field blank only if you genuinely cannot read "
    "it — never guess a value that isn't on the page."
)

_TOOL = {
    "name": "emit_passport",
    "description": "Return the passport holder's details read from the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "passport_no": {"type": "string"},
            "nationality": {"type": "string"},
            "date_of_birth": {"type": "string"},
            "passport_expiry": {"type": "string"},
            "gender": {"type": "string", "enum": ["Male", "Female", ""]},
        },
        "required": [],
    },
}


def _model_name():
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="passport_extract_model").value
        return (v or "").strip() or DEFAULT_MODEL
    except CompanyParameter.DoesNotExist:
        return DEFAULT_MODEL


def _content_block(raw, name):
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    b64 = base64.standard_b64encode(raw).decode()
    if ext == "pdf":
        return {"type": "document",
                "source": {"type": "base64", "media_type": "application/pdf",
                           "data": b64}}
    media = _MEDIA.get(ext)
    if not media:
        raise ScanError("Upload the passport as a JPG, PNG or PDF.")
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": b64}}


def _call_claude(block, model):
    """One structured passport read. Isolated so tests can monkeypatch it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ScanError(
            "Passport scanning needs an ANTHROPIC_API_KEY — ask the "
            "administrator to set it in the server environment.")
    try:
        import anthropic
    except ImportError:                          # pragma: no cover - env dep
        raise ScanError("The anthropic SDK isn't installed on the server.")
    client = anthropic.Anthropic(api_key=key)
    try:
        msg = client.messages.create(
            model=model, max_tokens=1000, system=_SYSTEM, tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_passport"},
            messages=[{"role": "user", "content": [
                block,
                {"type": "text",
                 "text": "Extract the holder's details from this passport."}]}])
    except Exception as e:                       # pragma: no cover - network
        raise ScanError(f"The passport reader failed: {e}")
    for b in msg.content:
        if getattr(b, "type", None) == "tool_use":
            return b.input
    raise ScanError("The reader returned no details.")


def _iso(s):
    """Keep a clean yyyy-mm-dd, else blank (HR completes it on review)."""
    s = (s or "").strip()
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""


def normalise(out):
    out = out or {}

    def g(k):
        return str(out.get(k) or "").strip()

    gender = g("gender").title()
    return {
        "full_name": g("full_name"),
        "passport_no": g("passport_no"),
        "nationality": g("nationality"),
        "date_of_birth": _iso(g("date_of_birth")),
        "passport_expiry": _iso(g("passport_expiry")),
        "gender": gender if gender in ("Male", "Female") else "",
    }


def scan(fileobj, model=None):
    """Read a passport file into normalised candidate fields."""
    raw = fileobj.read()
    if not raw:
        raise ScanError("The uploaded file is empty.")
    if len(raw) > _MAX_BYTES:
        raise ScanError("That file is too large — keep the passport scan "
                        "under 6 MB.")
    block = _content_block(raw, getattr(fileobj, "name", "") or "")
    return normalise(_call_claude(block, model or _model_name()))

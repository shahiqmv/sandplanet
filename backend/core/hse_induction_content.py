"""The shape of the safety induction form, SP-HSE-F01 (owner 2026-10-26),
transcribed from the approved form in its order. The words are in core/form_i18n (en.json and one file per language); this
module holds the form's shape. A new revision of the form is a new FORM_REV,
so a session records the revision it was printed from.
"""
from .form_i18n import english

FORM_REV = "F01 Rev 1"   # Rev 1: the starter-kit line (owner 2026-10-26)

FILING = ("File the signed original on site and send a scan to HR, Head "
          "Office. Upload the signed copy to Planet: it records each "
          "participant's induction.")

TOPIC_NOS = ["01", "02", "03", "04", "05", "06"]


def _bullet_keys(no):
    en, i, keys = english(), 1, []
    while f"topic_{no}_{i}" in en:
        keys.append(f"topic_{no}_{i}")
        i += 1
    return keys


# (no, title key, [bullet keys]) — the six sections, in the form's order;
# the PPE starter-kit line is "ppe_received" (Rev 1, owner 2026-10-26)
TOPIC_KEYS = [(no, f"topic_{no}", _bullet_keys(no)) for no in TOPIC_NOS]
# (no, English title, [English bullets])
TOPICS = [(no, english()[t], [english()[b] for b in bs])
          for no, t, bs in TOPIC_KEYS]

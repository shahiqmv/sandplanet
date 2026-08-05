"""IM30 — Maldives Immigration 'Visa Applicant Information Form'.

Sri-Lankan work-permit candidates must submit this alongside the Letter of
Appointment. Rather than hand-fill and scan, we overlay the onboarding case's
data — plus the signatory's approval stamp and the round company seal — onto the
official blank form with PyMuPDF, at coordinates measured once from the template
(owner 2026-08-05). Deterministic: no layout is inferred at run time.
"""
from django.conf import settings

TEMPLATE = settings.BASE_DIR / "pdf_templates" / "im30" / "im30_blank.pdf"
INK = (0.05, 0.12, 0.42)          # pen-navy, like a filled-in form
FONT = "helv"

# --- simple text fields: key -> (x, baseline_y, max_width) -----------------
# Coordinates in PDF points (A4, top-left origin), measured from the template's
# field boxes.
TEXT = {
    "port_of_entry": (71, 164, 147),
    "name": (110, 201, 446),
    "gender": (213, 226, 44),
    "nationality": (308, 226, 106),
    "passport_no": (106, 254, 124),
    "old_passport_no": (432, 254, 125),
    "purpose_of_stay": (93, 307, 185),
    "work_site": (340, 307, 216),
    "home_address": (111, 333, 446),
    "email": (340, 363, 216),
    "mobile": (110, 389, 168),
    "company": (115, 661, 196),
    "reg_no": (452, 664, 106),
    "signee": (115, 684, 196),
    "sponsor_mobile": (383, 694, 57),
    "designation": (88, 707, 224),
}

# --- date fields split into DD / MM / YYYY sub-boxes: key -> (xDD, xMM, xYYYY, y)
DATES = {
    "dob": (94, 117, 140, 226),
    "expiry": (294, 317, 340, 253),
    "sponsor_date": (352, 377, 401, 771),
}

# --- checkboxes: name -> box (x0, y0, x1, y1) for a drawn tick --------------
VISA_WORK = (231.9, 152.5, 250.2, 167.8)
MARITAL = {
    "SINGLE": (474.2, 213.8, 492.6, 229.2),
    "MARRIED": (515.5, 213.8, 533.9, 229.2),
}

# --- image boxes: (x0, y0, x1, y1) -----------------------------------------
SIGNATURE_BOX = (326, 718, 442, 747)      # the sponsor 'Signature' cell
SEAL_BOX = (474, 699, 558, 781)           # 'Seal of the sponsor' area


def _fit_size(page, s, max_width, base=10.0):
    """Largest font size ≤ base that keeps `s` within max_width (down to 6pt)."""
    import fitz
    size = base
    while size > 6 and fitz.get_text_length(s, fontname=FONT,
                                            fontsize=size) > max_width:
        size -= 0.5
    return size


def _tick(page, box):
    """A hand-style check mark inside a checkbox."""
    import fitz
    x0, y0, x1, y1 = box
    p1 = fitz.Point(x0 + 3, y0 + (y1 - y0) * 0.55)
    p2 = fitz.Point(x0 + (x1 - x0) * 0.42, y1 - 3)
    p3 = fitz.Point(x1 - 2, y0 + 2)
    page.draw_line(p1, p2, color=INK, width=1.6)
    page.draw_line(p2, p3, color=INK, width=1.6)


def render_bytes(fields, *, signature=None, seal=None):
    """Fill the IM30 template from `fields` (all text) + optional signature/seal
    image bytes; return the finished PDF as bytes."""
    import fitz

    doc = fitz.open(str(TEMPLATE))
    page = doc[0]

    for key, (x, y, maxw) in TEXT.items():
        val = (fields.get(key) or "").strip()
        if not val:
            continue
        if key != "email":
            val = val.upper()
        size = _fit_size(page, val, maxw)
        page.insert_text((x, y), val, fontname=FONT, fontsize=size, color=INK)

    for key, (xd, xm, xy, y) in DATES.items():
        raw = (fields.get(key) or "").strip()
        parts = [p for p in raw.replace("-", "/").split("/") if p]
        if len(parts) == 3:
            dd, mm, yy = parts
            for xx, txt in ((xd, dd.zfill(2)), (xm, mm.zfill(2)), (xy, yy)):
                page.insert_text((xx, y), txt, fontname=FONT, fontsize=10,
                                 color=INK)

    # Work Visa is always the box for a work-permit candidate.
    _tick(page, VISA_WORK)
    marital = (fields.get("marital_status") or "").strip().upper()
    if marital in MARITAL:
        _tick(page, MARITAL[marital])

    if signature:
        page.insert_image(fitz.Rect(*SIGNATURE_BOX), stream=signature,
                          keep_proportion=True)
    if seal:
        page.insert_image(fitz.Rect(*SEAL_BOX), stream=seal,
                          keep_proportion=True)

    out = doc.tobytes()
    doc.close()
    return out

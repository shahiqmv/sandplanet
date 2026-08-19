"""Receipt-sized salary slips for an 80mm autocut thermal printer.

A thermal printer feeds and cuts at the END OF THE PAGE, so a fixed page height
would spit out the whole page whatever the slip's length — a short slip for a
worker with no deductions would come out trailing a hand's width of blank
paper, every time, for every worker on the run.

So each slip is rendered onto a deliberately over-tall page and then CROPPED to
what was actually drawn, plus a feed margin to clear the cutter. The cut lands
just past the last line.

Owner 2026-08-18: 80mm roll, 72mm printable. The A5 slip stays as it is — this
is a second format, not a replacement.
"""
import logging

log = logging.getLogger(__name__)

MM = 72 / 25.4                  # PDF points per millimetre
PAGE_W_MM = 72                  # printable width of an 80mm roll
RENDER_H_MM = 400               # tall enough for the longest slip; cropped away
FEED_MM = 8                     # paper past the last line, to clear the blade
MIN_H_MM = 60                   # never cut absurdly short if measuring fails


def _content_bottom(page):
    """Lowest y of anything actually drawn on the page, in points.

    Both text and vector rules count — the slip's last element is a dashed
    separator or a signature line as often as it is a word.
    """
    bottom = 0.0
    for x0, y0, x1, y1, *_ in page.get_text("words"):
        bottom = max(bottom, y1)
    try:
        for d in page.get_drawings():
            r = d.get("rect")
            if r is not None:
                bottom = max(bottom, r.y1)
    except Exception:                    # pragma: no cover - defensive
        log.exception("get_drawings failed; measuring from text only")
    return bottom


def render_slips(htmls):
    """One PDF, one page per slip, each cropped to its own length.

    A page per slip is what makes the autocut usable for a whole run: the
    printer cuts between workers, so the slips come off the roll already
    separated and in order.
    """
    from django.conf import settings
    import fitz
    from weasyprint import HTML

    out = fitz.open()
    for html in htmls:
        pdf = HTML(string=html,
                   base_url=str(settings.MEDIA_ROOT)).write_pdf()
        src = fitz.open("pdf", pdf)
        for page in src:
            bottom = _content_bottom(page)
            height = max(bottom + FEED_MM * MM, MIN_H_MM * MM)
            # Never grow the page — if the slip genuinely overflowed the render
            # height, keep the full page rather than silently losing a line.
            height = min(height, page.rect.height)
            page.set_cropbox(fitz.Rect(0, 0, page.rect.width, height))
            out.insert_pdf(src, from_page=page.number, to_page=page.number)
        src.close()
    data = out.tobytes()
    out.close()
    return data


# ---- ESC/POS ----------------------------------------------------------------
# The printers these slips go to speak raw ESC/POS on port 9100 and nothing
# else — no IPP, no AirPrint, no PDF interpreter. HR and Finance print from
# Windows PCs, so the rasterising happens HERE, where PyMuPDF and Pillow already
# live: the office end then needs nothing installed but a socket.

ESC, GS = b"\x1b", b"\x1d"
DOTS = 576              # 80mm head at 203dpi — the slip is generated to match
BAND_ROWS = 128         # rows per GS v 0 command


def _page_raster(page):
    """One page -> ESC/POS raster bands."""
    import fitz
    from PIL import Image

    # Scale from the page's own width to the head's, so a slip cropped to any
    # length still lands 1:1 across.
    scale = DOTS / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                          colorspace=fitz.csGRAY, alpha=False)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if img.width != DOTS:                 # pad, never stretch
        canvas = Image.new("L", (DOTS, img.height), 255)
        canvas.paste(img, (0, 0))
        img = canvas
    # Dither, not a hard threshold: 1-bit output would otherwise drop the thin
    # separator rules and break up the small type.
    raw = img.convert("1").tobytes()
    row_bytes = (DOTS + 7) // 8
    out = bytearray()
    for top in range(0, img.height, BAND_ROWS):
        rows = min(BAND_ROWS, img.height - top)
        band = bytearray(raw[top * row_bytes:(top + rows) * row_bytes])
        for i, b in enumerate(band):
            band[i] = b ^ 0xFF            # Pillow: 1 = white; ESC/POS: 1 = burn
        out += GS + b"v0\x00"
        out += bytes([row_bytes & 0xFF, row_bytes >> 8,
                      rows & 0xFF, rows >> 8])
        out += bytes(band)
    return bytes(out)


def escpos_bytes(pdf_bytes, limit=None):
    """A slips PDF -> a ready-to-send ESC/POS job, one cut per slip."""
    import fitz

    doc = fitz.open("pdf", pdf_bytes)
    job = bytearray(ESC + b"@")                     # initialise once
    pages = list(doc)[:limit] if limit else list(doc)
    for page in pages:
        job += _page_raster(page)
        job += b"\n" * 2
        job += GS + b"V\x42\x00"                    # feed to cutter, partial cut
    doc.close()
    return bytes(job), len(pages)

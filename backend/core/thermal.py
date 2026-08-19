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

"""Company Profile — the PDF generator.

Ported from the owner's working WeasyPrint scripts (profile_full.py /
profile_css.txt): the static front matter + a project page per ongoing entry +
a references grid + back cover, rendered in one WeasyPrint pass with the entry
images base64-embedded from storage. Optional Ghostscript compression trims the
result to email size once `gs` is on the image (graceful no-op otherwise).

Static legacy pages (the ~45 historical completed projects) will be stitched in
from profile_static_assets in a later phase; this renders everything it has now.
"""
import base64
import logging
import os
import shutil
import subprocess
import tempfile
from html import escape

from django.core.files.storage import default_storage

log = logging.getLogger(__name__)

# ---- brand facts (baked into the static pages) ---------------------------
TAGLINE = "We go above and beyond on every job. PERIOD"
SUMMARY_FALLBACK = ""
REFEREES = [
    ("Soundarajah R", "Director", "V I C M Consultants (Pvt) Ltd"),
    ("TS Chua", "GM, Projects &amp; Engineering", "CDL Hospitality Trusts"),
    ("Mahesh Kumar", "Resident Project Director", "RLB Hooloomann Maldives"),
    ("Nalin Maheepala", "Director of Engineering", "Velaa Private Island"),
    ("Ibrahim Ayyoob", "Director of Engineering", "Baglioni Maldives"),
    ("Mohamed Adam", "Chief Engineer", "Jumeirah Maldives"),
    ("Shanawaz Khan", "Chief Engineer", "Cheval Blanc Randheli"),
]


def _uri(field):
    """base64 data-URI for a stored image field (empty string when missing)."""
    if not field:
        return ""
    try:
        with default_storage.open(field.name, "rb") as f:
            raw = f.read()
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    except Exception:                            # pragma: no cover - defensive
        log.exception("profile image read failed: %s", getattr(field, "name", ""))
        return ""


_RING = None


def logo(cls):
    """The official ring emblem beside the horizontal SAND PLANET wordmark.

    VECTOR (sp-mark.svg), not the PNG it used to be: the final PDF is passed
    through Ghostscript at 110dpi to keep it emailable, and that downsampled
    the logo along with the photographs — at 14mm on the cover it came out
    about 60 pixels wide and visibly pixelated (owner 2026-08-19). Vector art
    is not resampled, so it stays sharp at any size and costs less than the
    bitmap did.
    """
    global _RING
    if _RING is None:
        from django.conf import settings
        p = (settings.BASE_DIR / "pdf_templates" / "assets" / "sp-mark.svg")
        _RING = "data:image/svg+xml;base64," + base64.b64encode(
            p.read_bytes()).decode()
    return (f'<span class="lock {cls}"><img class="lr" src="{_RING}">'
            f'<span class="lt"><span class="s">SAND</span>PLANET</span></span>')


def _bar(section):
    return (f'<div class="topbar">{logo("logo")}'
            f'<div class="sec">{section}</div></div>')


def _foot():
    return (f'<div class="foot">{logo("flogo")}'
            f'<span class="ft">{TAGLINE}</span></div>')


def _project_page(entry):
    feat = _uri(entry.featured_image)
    gallery = [_uri(g.image) for g in entry.gallery.all()][:6]
    gallery = [g for g in gallery if g]
    ncol = 3 if len(gallery) >= 3 else max(1, len(gallery))
    gcells = "".join(f'<div class="g"><img src="{g}"></div>' for g in gallery)
    grid = (f'<div class="grid6" style="grid-template-columns:repeat({ncol},'
            f'1fr);">{gcells}</div>' if gcells else "")
    label = escape(entry.start_label or "Commenced")
    start = escape(entry.start_value or "")
    section = "Ongoing Projects" if entry.status == "ONGOING" else "References"
    summary = (f'<div class="summary">{escape(entry.summary)}</div>'
               if (entry.summary or "").strip() else "")
    return (f'<div class="page">{_bar(section)}'
            f'<div class="hero"><img src="{feat}">'
            f'<div class="client">{escape(entry.client_display or "")}</div>'
            f'</div><div class="phead">'
            f'<div class="pname">{escape(entry.project_name or "")}</div>'
            f'<div class="start"><span class="dot"></span>{label} {start}</div>'
            f'</div><div class="pbody">{summary}{grid}</div>{_foot()}</div>')


def _cover(hero, style="FULL"):
    """The front page.

    Three treatments, because the original — photo band on top, white title
    block below — is the same rhythm as every project page, and a cover that
    looks like the inside pages is not a cover (owner 2026-08-19).
    """
    if style == "BAND":
        img = f'<img class="cov-img" src="{hero}">' if hero else ""
        return (f'<div class="page cover">{img}<div class="cov-imgtint"></div>'
                f'<div class="cov-band">{logo("cov-logo")}'
                f'<div class="cov-rule"></div>'
                f'<div class="cov-title">Company<br>Profile</div>'
                f'<div class="cov-sub">Construction · Design &amp; Build · '
                f'Marine Works</div>'
                f'<div class="cov-foot"><span>Malé · Republic of Maldives</span>'
                f'<span>2026</span></div></div></div>')

    img = f'<img class="fc-img" src="{hero}">' if hero else ""
    # A photograph this good should carry the page. The scrim is what makes
    # white type legible over it without dulling the water.
    if style == "TOP":
        # Title in the SKY. On an aerial the subject sits low in the frame, so
        # putting the type at the bottom covers the very thing being shown —
        # the pool and its decking disappeared behind it (owner 2026-08-19).
        return (f'<div class="page fullcover">{img}'
                '<div class="fc-scrim-top"></div>'
                f'<div class="fc-head">{logo("fc-logo")}'
                '<div class="fc-rule"></div>'
                '<div class="fc-title">Company<br>Profile</div>'
                '<div class="fc-sub">Construction · Design &amp; Build · '
                'Marine Works</div></div>'
                '<div class="fc-foot-b"><span>Malé · Republic of Maldives'
                '</span><span>2026</span></div></div>')

    return (f'<div class="page fullcover">{img}'
            '<div class="fc-scrim"></div>'
            f'<div class="fc-top">{logo("fc-logo")}</div>'
            '<div class="fc-body">'
            '<div class="fc-rule"></div>'
            '<div class="fc-title">Company<br>Profile</div>'
            '<div class="fc-sub">Construction · Design &amp; Build · Marine Works'
            '</div>'
            '<div class="fc-foot"><span>Malé · Republic of Maldives</span>'
            '<span>2026</span></div></div></div>')


def _story():
    return (f'<div class="page">{_bar("Who We Are")}<div class="txtpage">'
            '<div class="eyebrow">The Story Behind</div>'
            '<h1 class="bigtitle">Built by two <span class="amber">childhood '
            'friends</span><br>from Fuvahmulah.</h1>'
            '<div class="lead">Sand Planet Pvt Ltd was established in 2015 with '
            'a strong will to climb the ladder, founded by two childhood '
            'friends who had filled key positions across both the corporate '
            'world and the public sector.</div><div class="cols">'
            '<p>Determined to make the construction fraternity more dynamic, '
            'the founders brought their experience in senior public and private '
            'roles to building a premier player in the industry.</p>'
            '<p>Our mission is to encourage shared performance and '
            'responsibility, and to ensure a higher degree of professionalism '
            'in every venture. That approach delivered an outstanding '
            'result on the very first project we carried out.</p>'
            '<p>We provide professional, client-focused construction solutions '
            'across general contracting, construction management, design-build '
            'and pre-construction planning, for projects of every scale, from '
            'a single office fit-up to major resort development.</p>'
            '<p>We are a 100% team-driven company. Our people hail from every '
            'craft and discipline in the field, letting us combine innovative '
            'construction methods with accountable project management to get '
            'the job done.</p></div>'
            '<div class="pullquote">“We go above and beyond on every project, '
            'and deliver on our promises with integrity.”</div>'
            f'</div>{_foot()}</div>')


def _corporate():
    """The "company at a glance" table — rows and the vision/mission text now
    come from the database, because the figures move (total staff most of all)
    and a redeploy to change a headcount is absurd (owner 2026-08-19)."""
    from .models import ProfileCorporateRow, ProfileSettings

    st = ProfileSettings.get()
    rows = [(r.label, r.value) for r in
            ProfileCorporateRow.objects.filter(is_active=True)]
    irs = "".join(f'<div class="ir"><span class="ik">{escape(k)}</span>'
                  # value may legitimately carry <br> between people
                  f'<span class="iv">{v}</span></div>' for k, v in rows)
    return (f'<div class="page">{_bar("Corporate Information")}'
            '<div class="txtpage"><div class="eyebrow">Corporate Information'
            '</div><h2 class="bigtitle2">The company at a glance</h2>'
            f'<div class="inforows">{irs}</div><div class="vm">'
            '<div class="vmbox"><div class="vmh">Our Vision</div>'
            f'<p>{escape(st.vision)}</p></div>'
            '<div class="vmbox amberbox"><div class="vmh">Our Mission</div>'
            f'<p>{escape(st.mission)}</p></div></div>'
            f'</div>{_foot()}</div>')


def _avatar(person):
    """A management portrait: the uploaded photo, else a committed file, else
    a navy initials placeholder."""
    from django.conf import settings

    if person.photo:
        uri = _uri(person.photo)
        if uri:
            return f'<div class="mavatar"><img src="{uri}"></div>'
    slug = "".join(c.lower() for c in person.name if c.isalnum())
    p = settings.BASE_DIR / "core" / "profile_seed" / "mgmt" / f"{slug}.jpg"
    if p.exists():
        uri = "data:image/jpeg;base64," + base64.b64encode(
            p.read_bytes()).decode()
        return f'<div class="mavatar"><img src="{uri}"></div>'
    initials = "".join(w[0] for w in person.name.split()[:2]).upper()
    return f'<div class="mavatar mph">{initials}</div>'


def _management():
    """Key management personnel — a database list, not four hardcoded tuples,
    so a director can be added without a deploy (owner 2026-08-19)."""
    from .models import ProfileManagement

    people = list(ProfileManagement.objects.filter(is_active=True))
    cards = ""
    for person in people:
        cards += (f'<div class="mcard">{_avatar(person)}<div class="minfo">'
                  f'<div class="mname">{escape(person.name)}</div>'
                  f'<div class="mrole">{escape(person.role)}</div>'
                  f'<div class="mintro">{escape(person.intro)}</div>'
                  '</div></div>')
    # Two columns at full size hold six without crowding — measured, not
    # guessed. Only past that do the cards have to give up room.
    tight = " mgrid-tight" if len(people) > 6 else ""
    return (f'<div class="page">{_bar("Management")}<div class="txtpage">'
            '<div class="eyebrow">Leadership</div>'
            '<h2 class="bigtitle2">Key management personnel</h2></div>'
            f'<div class="mgrid{tight}">{cards}</div>{_foot()}</div>')


def _divider(hero, num="01", title="ONGOING<br>PROJECTS",
             sub="Live works across the Maldivian atolls"):
    # object-position decides WHICH vertical slice of the photo the strip
    # shows. Centred cut straight through the pool (owner 2026-08-20).
    from .models import ProfileSettings
    pos = {"LEFT": "left", "RIGHT": "right"}.get(
        ProfileSettings.get().divider_focus, "center")
    strip = (f'<div class="div-strip">'
             f'<img src="{hero}" style="object-position:{pos} center;"></div>'
             if hero else "")
    return (f'<div class="page divider">{strip}{_bar("")}'
            f'<div class="div-center"><div class="div-num">{num}</div>'
            f'<div class="div-title">{title}</div><div class="div-line"></div>'
            f'<div class="div-sub">{sub}</div></div></div>')


def _ref_card(e):
    img = _uri(e.featured_image)
    wrap = (f'<div class="ref-imgwrap"><img src="{img}">'
            f'<span class="ref-client">{escape(e.client_display or "")}'
            f'</span></div>' if img else '<div class="ref-imgwrap"></div>')
    return (f'<div class="refcard">{wrap}'
            f'<div class="ref-title">{escape(e.project_name or "")}</div>'
            f'<div class="ref-period">{escape(e.start_value or "")}</div></div>')


def _ref_divider(hero):
    return _divider(hero, num="02", title="PROJECT<br>REFERENCES",
                    sub="Delivered across the Maldivian atolls")


_REF_PER_PAGE = 9   # 3 cols × 3 rows — safe on height with title + period


def _reference_pages(completed):
    pages = ""
    chunks = [completed[i:i + _REF_PER_PAGE]
              for i in range(0, len(completed), _REF_PER_PAGE)]
    for ci, chunk in enumerate(chunks):
        cards = "".join(_ref_card(e) for e in chunk)
        head = ('<div class="refhead"><div class="eyebrow">Completed Projects'
                '</div><h2 class="refh2">Selected project references</h2></div>'
                if ci == 0 else "")
        pages += (f'<div class="page">{_bar("References")}{head}'
                  f'<div class="refgrid">{cards}</div>{_foot()}</div>')
    return pages


def _referees():
    from .models import ProfileReferee
    rows = [(r.name, r.role, r.org, r.email)
            for r in ProfileReferee.objects.all()]
    if not rows:
        rows = [(n, r, o, "") for n, r, o in REFEREES]
    boxes = "".join(
        f'<div class="rfbox"><div class="rf-name">{escape(n)}</div>'
        f'<div class="rf-role">{escape(r)}</div>'
        f'<div class="rf-org">{escape(o)}</div>'
        + (f'<div class="rf-email">{escape(e)}</div>' if e else "")
        + '</div>'
        for n, r, o, e in rows)
    return (f'<div class="page">{_bar("Referees")}<div class="txtpage">'
            '<div class="eyebrow">References</div>'
            '<h2 class="bigtitle2">Trusted by the industry</h2>'
            f'<div class="rfgrid">{boxes}</div></div>{_foot()}</div>')


def _back():
    return ('<div class="page backcover">'
            f'<div class="bc-top">{logo("bc-logo")}</div>'
            '<div class="bc-rule"></div>'
            f'<div class="bc-tag">{TAGLINE}</div><div class="bc-contact">'
            '<div class="bc-row"><span class="bc-k">Address</span>'
            "<span>Ma. Maaraadha Aage, Dhanburuh Magu, Malé, Rep. of Maldives "
            '· 20162</span></div><div class="bc-row"><span class="bc-k">Phone'
            '</span><span>+960 799 2611</span></div><div class="bc-row">'
            '<span class="bc-k">Email</span><span>info@sandplanet.mv</span>'
            '</div></div><div class="bc-foot">Company Profile · Version 2.0 · '
            '2026</div></div>')


_WATERMARK = ('body::after{content:"PREVIEW";position:fixed;top:46%;left:0;'
              'right:0;text-align:center;font-size:64pt;font-weight:bold;'
              'color:rgba(227,138,46,.16);transform:rotate(-28deg);'
              'letter-spacing:8pt;}')


def build_html():
    from .models import ProfileEntry
    ongoing = list(ProfileEntry.objects.filter(status="ONGOING")
                   .prefetch_related("gallery").order_by("sort_order"))
    completed = list(ProfileEntry.objects.filter(status="COMPLETED")
                     .order_by("sort_order", "-completed_at"))
    # The cover used to be whichever ongoing project sorted first, so
    # reordering the projects silently changed the cover (owner 2026-08-19).
    # A chosen image wins; the old behaviour is the fallback.
    from .models import ProfileSettings
    st = ProfileSettings.get()
    hero = _uri(st.cover_image) if st.cover_image else ""
    if not hero:
        hero = _uri(ongoing[0].featured_image) if ongoing else ""
    parts = [_cover(hero, st.cover_style), _story(), _corporate(),
             _management(),
             _divider(hero)]
    parts += [_project_page(e) for e in ongoing]
    if completed:
        parts.append(_ref_divider(hero))
        parts.append(_reference_pages(completed))
    parts += [_referees(), _back()]
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
            + "".join(parts) + "</body></html>")


def _compress(pdf_bytes):
    """Ghostscript downsample to ~110 dpi + dedupe images (the proven recipe).
    No-op when gs isn't on the image, so the generator still works everywhere."""
    gs = shutil.which("gs") or shutil.which("gswin64c")
    if not gs:
        return pdf_bytes
    inp = outp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fin:
            fin.write(pdf_bytes)
            inp = fin.name
        outp = inp + ".out.pdf"
        subprocess.run(
            [gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
             "-dNOPAUSE", "-dBATCH", "-dQUIET", "-dDetectDuplicateImages=true",
             "-dDownsampleColorImages=true", "-dColorImageResolution=110",
             "-dDownsampleGrayImages=true", "-dGrayImageResolution=110",
             "-dColorImageDownsampleType=/Bicubic",
             f"-sOutputFile={outp}", inp],
            check=True, timeout=180)
        with open(outp, "rb") as f:
            out = f.read()
        return out if out[:4] == b"%PDF" else pdf_bytes
    except Exception:                            # pragma: no cover - defensive
        log.exception("profile PDF compression failed")
        return pdf_bytes
    finally:
        for p in (inp, outp):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


def generate(mode="final"):
    """Render the profile PDF. mode='preview' → watermarked + uncompressed;
    'final' → compressed (email size)."""
    from weasyprint import CSS, HTML
    css = _CSS_TEXT + (_WATERMARK if mode == "preview" else "")
    pdf = HTML(string=build_html()).write_pdf(stylesheets=[CSS(string=css)])
    return pdf if mode == "preview" else _compress(pdf)


_CSS_TEXT = r"""
@page { size:A4; margin:0; }
body { font-family:"Carlito","DejaVu Sans",sans-serif; color:#22303B; }
.page { width:210mm; height:297mm; position:relative; background:#FFFFFF;
        page-break-after:always; overflow:hidden; }
.s{color:#1685CC;} .s2{color:#C7A76A;}
/* slim light header + footer */
.topbar{height:13mm;display:flex;align-items:center;justify-content:space-between;padding:0 16mm;border-bottom:0.6pt solid #E5EAEE;}
.tl{display:flex;align-items:center;gap:3mm;}
.brand{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:11.5pt;letter-spacing:3.5pt;color:#0E3A5C;}
.sec{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:8.5pt;letter-spacing:3pt;color:#E38A2E;text-transform:uppercase;}
.foot{position:absolute;left:16mm;right:16mm;bottom:9mm;display:flex;align-items:center;justify-content:space-between;border-top:0.6pt solid #E5EAEE;padding-top:3.5mm;}
.fb{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:9pt;letter-spacing:2.5pt;color:#0E3A5C;}
.ft{font-size:8pt;color:#95A2AB;font-style:italic;}
.eyebrow{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:9.5pt;letter-spacing:3pt;text-transform:uppercase;color:#E38A2E;}
.amber{color:#E38A2E;}
/* logo lockup: official ring emblem + SAND PLANET wordmark (never redrawn) */
.lock{display:inline-flex;align-items:center;gap:2.5mm;}
.lt{font-family:"DejaVu Sans Condensed";font-weight:bold;letter-spacing:3pt;color:#0E3A5C;}
.s{color:#29ABE2;}
.topbar .lr{height:8mm;} .topbar .lt{font-size:12.5pt;}
.foot .lr{height:5mm;} .foot .lt{font-size:9pt;letter-spacing:2pt;}
.cov-logo{display:inline-flex;margin-bottom:9mm;}
.cov-logo .lr{height:14mm;} .cov-logo .lt{font-size:18pt;letter-spacing:4.5pt;}
.bc-logo .lr{height:16mm;} .bc-logo .lt{font-size:21pt;letter-spacing:5pt;}
/* cover: image top, white title band */
.cover{background:#FFFFFF;}
/* Full-bleed cover: the photograph IS the page. White type sits on a scrim
   that darkens only the lower third, so the water keeps its colour. */
.fullcover{background:#0E3A5C;position:relative;overflow:hidden;}
.fc-img{position:absolute;top:0;left:0;width:100%;height:297mm;object-fit:cover;}
.fc-scrim{position:absolute;left:0;right:0;top:0;height:297mm;
  background:linear-gradient(to bottom,rgba(14,58,92,.42) 0%,rgba(14,58,92,.10) 26%,rgba(14,58,92,.30) 55%,rgba(9,38,60,.88) 100%);}
.fc-top{position:absolute;top:16mm;left:18mm;}
.fc-logo .lr{height:13mm;} .fc-logo .lt{font-size:17pt;letter-spacing:4pt;color:#fff;}
.fc-logo .s{color:#fff;}
.fc-body{position:absolute;left:18mm;right:18mm;bottom:16mm;}
.fc-rule{width:30mm;height:2mm;background:#E38A2E;margin-bottom:7mm;}
.fc-title{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:52pt;
  line-height:0.95;letter-spacing:.5pt;color:#FFFFFF;}
.fc-sub{margin-top:6mm;font-size:12pt;letter-spacing:1pt;color:#DCE6ED;}
.fc-foot{margin-top:9mm;display:flex;justify-content:space-between;
  color:#AFC2CF;font-size:9pt;letter-spacing:.5pt;
  border-top:0.6pt solid rgba(255,255,255,.28);padding-top:4mm;}
/* Title-in-the-sky variant: the scrim darkens the TOP instead, so the work in
   the lower half of the photograph is left completely clear. */
.fc-scrim-top{position:absolute;left:0;right:0;top:0;height:297mm;
  background:linear-gradient(to bottom,rgba(9,38,60,.78) 0%,rgba(14,58,92,.44) 34%,rgba(14,58,92,.06) 56%,rgba(14,58,92,.22) 100%);}
.fc-head{position:absolute;top:20mm;left:18mm;right:18mm;}
.fc-head .fc-rule{margin-top:9mm;}
.fc-foot-b{position:absolute;left:18mm;right:18mm;bottom:14mm;display:flex;
  justify-content:space-between;color:#E4EDF3;font-size:9pt;letter-spacing:.5pt;
  border-top:0.6pt solid rgba(255,255,255,.30);padding-top:4mm;}
.cov-img{position:absolute;top:0;left:0;width:100%;height:176mm;object-fit:cover;}
.cov-imgtint{position:absolute;top:0;left:0;right:0;height:176mm;background:linear-gradient(to bottom,rgba(14,58,92,.06),rgba(14,58,92,.30));}
.cov-top{position:absolute;top:15mm;left:18mm;display:flex;align-items:center;gap:4mm;}
.cov-brand{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:15pt;letter-spacing:5pt;color:#fff;}
.cov-band{position:absolute;top:176mm;left:0;right:0;bottom:0;padding:18mm 18mm 0 18mm;}
.cov-rule{width:30mm;height:2mm;background:#E38A2E;margin-bottom:8mm;}
.cov-title{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:48pt;line-height:0.98;letter-spacing:.5pt;color:#0E3A5C;}
.cov-sub{margin-top:7mm;font-size:12pt;letter-spacing:.5pt;color:#5E6D78;}
.cov-foot{position:absolute;left:18mm;right:18mm;bottom:14mm;display:flex;justify-content:space-between;color:#95A2AB;font-size:9pt;letter-spacing:.5pt;border-top:0.6pt solid #E5EAEE;padding-top:4mm;}
/* text pages */
.txtpage{padding:13mm 18mm 0 18mm;}
.bigtitle{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:30pt;line-height:1.08;color:#0E3A5C;margin:4mm 0 0 0;}
.bigtitle2{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:26pt;color:#0E3A5C;margin:3mm 0 8mm 0;}
.lead{font-size:13pt;line-height:1.6;color:#3C4954;margin:7mm 0 0 0;max-width:170mm;}
.cols{column-count:2;column-gap:10mm;margin-top:7mm;}
.cols p{font-size:10.5pt;line-height:1.62;color:#47535D;margin:0 0 4mm 0;text-align:justify;}
.pullquote{margin-top:9mm;border-left:3pt solid #E38A2E;padding:2mm 0 2mm 7mm;font-family:"DejaVu Sans Condensed";font-size:17pt;font-weight:bold;color:#0E3A5C;line-height:1.3;}
/* divider: light, image strip on the right */
.divider{background:#F6F4F0;}
/* Was 74mm — a quarter of the photograph, which on the pool aerial showed
   the water and nothing else around it (owner 2026-08-20). */
.div-strip{position:absolute;top:0;right:0;width:92mm;height:100%;overflow:hidden;}
.div-strip img{width:100%;height:100%;object-fit:cover;}
.div-center{position:absolute;left:18mm;top:112mm;max-width:96mm;}
.div-num{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:20pt;color:#E38A2E;letter-spacing:2pt;}
.div-title{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:35pt;line-height:1.0;color:#0E3A5C;margin-top:2mm;}
.div-line{width:36mm;height:2mm;background:#E38A2E;margin:7mm 0;}
.div-sub{color:#5E6D78;font-size:12pt;}
/* project page: hero then title BELOW on white */
.hero{position:relative;width:100%;height:120mm;overflow:hidden;}
.hero>img{width:100%;height:100%;object-fit:cover;}
.hero .client{position:absolute;top:0;left:0;background:#E38A2E;color:#fff;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:10pt;letter-spacing:2pt;text-transform:uppercase;padding:2mm 5mm;}
.phead{padding:7mm 16mm 0 16mm;}
.pname{font-family:"DejaVu Sans Condensed";font-weight:bold;color:#0E3A5C;font-size:23pt;line-height:1.05;}
.start{margin-top:2.5mm;color:#95A2AB;font-size:10pt;display:flex;align-items:center;gap:2.5mm;}
.dot{width:2.2mm;height:2.2mm;background:#E38A2E;border-radius:50%;display:inline-block;}
.pbody{padding:5mm 16mm 0 16mm;}
.summary{font-size:11.5pt;line-height:1.65;color:#3C4954;text-align:justify;border-left:3pt solid #E38A2E;padding-left:6mm;}
.grid6{display:grid;grid-template-columns:repeat(3,1fr);gap:3.5mm;margin-top:7mm;}
.grid6 .g{height:36mm;overflow:hidden;background:#EEF1F3;border-radius:1mm;}
.grid6 .g img{width:100%;height:100%;object-fit:cover;}
/* references: light cards */
.refhead{padding:11mm 16mm 0 16mm;}
.refh2{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:22pt;color:#0E3A5C;margin:2mm 0 0 0;}
.refgrid{padding:7mm 16mm 0 16mm;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6mm;}
.refcard{background:#fff;border:0.6pt solid #E5EAEE;border-radius:1.5mm;overflow:hidden;box-shadow:0 1pt 3pt rgba(16,52,79,.06);}
.ref-imgwrap{position:relative;height:40mm;overflow:hidden;background:#EEF1F3;}
.ref-imgwrap img{width:100%;height:100%;object-fit:cover;}
.ref-client{position:absolute;left:0;bottom:0;background:#0E3A5C;color:#fff;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:7.5pt;letter-spacing:1pt;text-transform:uppercase;padding:1.5mm 3mm;}
.ref-title{font-size:9.5pt;font-weight:bold;color:#22303B;margin:2.5mm 3.5mm 0 3.5mm;line-height:1.25;}
.ref-period{font-size:8pt;color:#95A2AB;margin:1mm 3.5mm 3.5mm 3.5mm;}
/* corporate info */
.inforows{margin-top:2mm;}
.ir{display:flex;border-bottom:0.6pt solid #E5EAEE;padding:3mm 0;}
.ik{flex:0 0 42mm;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:9pt;letter-spacing:1.4pt;text-transform:uppercase;color:#E38A2E;}
.iv{font-size:10.5pt;color:#3C4954;line-height:1.4;}
.vm{display:flex;gap:6mm;margin-top:9mm;}
.vmbox{flex:1;background:#F6F4F0;border:0.6pt solid #E5EAEE;border-radius:2mm;padding:6mm;}
.vmh{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:12pt;letter-spacing:1.5pt;text-transform:uppercase;color:#0E3A5C;margin-bottom:3mm;}
.vmbox p{font-size:10pt;line-height:1.6;color:#47535D;margin:0;}
/* The navy Mission box comes LAST on purpose. ".vmbox p" and ".amberbox p"
   have equal specificity, so whichever is declared later wins — with the
   order reversed, the dark body colour was landing on the navy panel and the
   mission statement could not be read (owner 2026-08-20). */
.amberbox{background:#0E3A5C;border-color:#0E3A5C;}
.amberbox .vmh{color:#E9B96E;}
.amberbox p{color:#F2ECE0;}
/* key management */
.mgrid{padding:9mm 18mm 0 18mm;display:grid;grid-template-columns:1fr 1fr;gap:7mm;}
/* Five or more people: the cards have to give up some room or the page
   overflows. Photo, name and role stay legible; the bio tightens. */
.mgrid-tight{padding:6mm 14mm 0 14mm;gap:4.5mm;}
.mgrid-tight .mcard{padding:4mm;gap:3.5mm;}
.mgrid-tight .mavatar{flex:0 0 19mm;width:19mm;height:19mm;}
.mgrid-tight .mph{font-size:14pt;}
.mgrid-tight .mname{font-size:12pt;}
.mgrid-tight .mintro{font-size:7.4pt;line-height:1.35;}
.mcard{display:flex;gap:5mm;background:#F6F4F0;border:0.6pt solid #E5EAEE;border-radius:2mm;padding:6mm;}
.mavatar{flex:0 0 26mm;width:26mm;height:26mm;border-radius:50%;overflow:hidden;background:#0E3A5C;}
.mavatar img{width:100%;height:100%;object-fit:cover;}
.mph{display:flex;align-items:center;justify-content:center;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:19pt;color:#fff;letter-spacing:1pt;}
.minfo{flex:1;}
.mname{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:14pt;color:#0E3A5C;line-height:1.1;}
.mrole{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:8.5pt;color:#E38A2E;text-transform:uppercase;letter-spacing:1.2pt;margin-top:1.5mm;}
.mintro{font-size:9pt;color:#47535D;line-height:1.5;margin-top:3mm;}
/* referees */
.rfgrid{display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-top:4mm;}
.rfbox{background:#F6F4F0;border:0.6pt solid #E5EAEE;border-left:3pt solid #E38A2E;border-radius:1.5mm;padding:5mm 6mm;min-height:19mm;}
.rf-name{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:13pt;color:#0E3A5C;}
.rf-role{font-size:9.5pt;color:#3C4954;margin-top:1mm;}
.rf-org{font-size:9pt;color:#95A2AB;margin-top:0.5mm;}
.rf-email{font-size:9pt;color:#1685CC;margin-top:1.5mm;}
/* back cover: light */
.backcover{background:#F6F4F0;}
.bc-top{position:absolute;top:40mm;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:5mm;}
.bc-brand{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:22pt;letter-spacing:6pt;color:#0E3A5C;}
.bc-rule{position:absolute;top:82mm;left:50%;margin-left:-18mm;width:36mm;height:2mm;background:#E38A2E;}
.bc-tag{position:absolute;top:95mm;left:0;right:0;text-align:center;color:#5E6D78;font-size:13pt;font-style:italic;letter-spacing:.5pt;}
.bc-contact{position:absolute;top:150mm;left:38mm;right:38mm;}
.bc-row{display:flex;border-top:0.6pt solid #DDE3E7;padding:4mm 0;color:#22303B;font-size:11pt;}
.bc-k{flex:0 0 28mm;font-family:"DejaVu Sans Condensed";font-weight:bold;letter-spacing:1.5pt;text-transform:uppercase;font-size:9pt;color:#E38A2E;}
.bc-foot{position:absolute;bottom:16mm;left:0;right:0;text-align:center;color:#95A2AB;font-size:8.5pt;letter-spacing:1pt;}
"""

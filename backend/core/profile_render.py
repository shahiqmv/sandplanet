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
TAGLINE = "We go above and beyond on every job."
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
    """The official ring emblem (sp-ring.png — the owner's exact rings, never
    redrawn) beside the horizontal SAND PLANET wordmark."""
    global _RING
    if _RING is None:
        from django.conf import settings
        p = (settings.BASE_DIR / "pdf_templates" / "assets" / "sp-ring.png")
        _RING = "data:image/png;base64," + base64.b64encode(
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


def _cover(hero):
    img = f'<img class="cov-img" src="{hero}">' if hero else ""
    return (f'<div class="page cover">{img}<div class="cov-imgtint"></div>'
            f'<div class="cov-band">{logo("cov-logo")}'
            f'<div class="cov-rule"></div>'
            f'<div class="cov-title">Company<br>Profile</div>'
            f'<div class="cov-sub">Construction · Resort Supplies · Marine '
            f'Works</div>'
            f'<div class="cov-foot"><span>Malé · Republic of Maldives</span>'
            f'<span>2026</span></div></div></div>')


def _story():
    return (f'<div class="page">{_bar("Who We Are")}<div class="txtpage">'
            '<div class="eyebrow">The Story Behind</div>'
            '<h1 class="bigtitle">Built by two <span class="amber">childhood '
            'friends</span><br>from Fuvahmulah.</h1>'
            '<div class="lead">Sand Planet Pvt Ltd was established in 2015 with '
            'a strong will to climb the ladder — founded by two childhood '
            'friends who had filled key positions across both the corporate '
            'world and the public sector.</div><div class="cols">'
            '<p>Determined to make the construction fraternity more dynamic, '
            'the founders brought their experience in senior public and private '
            'roles to building a premier player in the industry.</p>'
            '<p>Our mission is to encourage shared performance and '
            'responsibility, and to ensure a higher degree of professionalism '
            'in every venture — an approach that delivered an outstanding '
            'result on the very first project we carried out.</p>'
            '<p>We provide professional, client-focused construction solutions '
            'across general contracting, construction management, design-build '
            'and pre-construction planning — for projects of every scale, from '
            'a single office fit-up to major resort development.</p>'
            '<p>We are a 100% team-driven company. Our people hail from every '
            'craft and discipline in the field, letting us combine innovative '
            'construction methods with accountable project management to get '
            'the job done.</p></div>'
            '<div class="pullquote">“We go above and beyond on every project, '
            'and deliver on our promises with integrity.”</div>'
            f'</div>{_foot()}</div>')


def _corporate():
    rows = [
        ("Legal form", "Private Limited Company"),
        ("Shareholders", "Ahmed Shahiq · Ibrahim Fikury Hussain"),
        ("Senior management",
         "Ahmed Shahiq — Managing Director<br>"
         "Ibrahim Fikury Hussain — Director, Business Development<br>"
         "Muditha Samanthilaka — Director of Projects<br>"
         "Waseem Ali — Director of Marine Projects"),
        ("Registered office", "Ma. Maaraadha Aage', Dhanburuh Magu, Malé"),
        ("Registration", "C-0059/2015 · TIN 1052866GST501"),
        ("Bankers", "Bank of Maldives Public Ltd"),
        ("Auditors", "AH Associates"),
        ("Total staff", "106 personnel"),
    ]
    irs = "".join(f'<div class="ir"><span class="ik">{k}</span>'
                  f'<span class="iv">{v}</span></div>' for k, v in rows)
    return (f'<div class="page">{_bar("Corporate Information")}'
            '<div class="txtpage"><div class="eyebrow">Corporate Information'
            '</div><h2 class="bigtitle2">The company at a glance</h2>'
            f'<div class="inforows">{irs}</div><div class="vm">'
            '<div class="vmbox"><div class="vmh">Our Vision</div><p>To become a '
            'competitive leader in the Maldivian construction industry and in '
            'resort supplies, delivering projects that precisely meet our '
            "clients' requirements while upholding international standards.</p>"
            '</div><div class="vmbox amberbox"><div class="vmh">Our Mission'
            '</div><p>To undertake construction with a focus on becoming a '
            'competitive leader in product costing, building excellence in '
            'every aspect to meet stringent requirements for quality, on-time '
            'delivery, safety and environmental care.</p></div></div>'
            f'</div>{_foot()}</div>')


MANAGEMENT = [
    ("Ahmed Shahiq", "Managing Director",
     "Co-founder and Managing Director of Sand Planet, leading the company's "
     "strategy, growth and delivery across construction, resort supplies and "
     "marine works since 2015."),
    ("Ibrahim Fikury Hussain", "Director, Business Development",
     "Co-founder and Director of Business Development, building the client "
     "relationships and new opportunities that drive the company's work across "
     "the resort sector."),
    ("Muditha Samanthilaka", "Director of Projects",
     "Director of Projects, overseeing planning, execution and quality across "
     "the company's building and fit-out portfolio."),
    ("Waseem Ali", "Director of Marine Projects",
     "Director of Marine Projects, leading the company's marine and coastal "
     "works, including breakwaters, revetments, piling and jetties."),
]


def _avatar(name):
    """A management portrait — a committed photo (core/profile_seed/mgmt/
    <initials-slug>.jpg) if present, else a navy initials placeholder."""
    from django.conf import settings
    slug = "".join(c.lower() for c in name if c.isalnum())
    p = settings.BASE_DIR / "core" / "profile_seed" / "mgmt" / f"{slug}.jpg"
    if p.exists():
        uri = "data:image/jpeg;base64," + base64.b64encode(
            p.read_bytes()).decode()
        return f'<div class="mavatar"><img src="{uri}"></div>'
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    return f'<div class="mavatar mph">{initials}</div>'


def _management():
    cards = ""
    for name, role, intro in MANAGEMENT:
        cards += (f'<div class="mcard">{_avatar(name)}<div class="minfo">'
                  f'<div class="mname">{escape(name)}</div>'
                  f'<div class="mrole">{escape(role)}</div>'
                  f'<div class="mintro">{escape(intro)}</div></div></div>')
    return (f'<div class="page">{_bar("Management")}<div class="txtpage">'
            '<div class="eyebrow">Leadership</div>'
            '<h2 class="bigtitle2">Key management personnel</h2></div>'
            f'<div class="mgrid">{cards}</div>{_foot()}</div>')


def _divider(hero, num="01", title="ONGOING<br>PROJECTS",
             sub="Live works across the Maldivian atolls"):
    strip = f'<div class="div-strip"><img src="{hero}"></div>' if hero else ""
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
    rows = [(r.name, r.role, r.org) for r in ProfileReferee.objects.all()]
    if not rows:
        rows = REFEREES
    boxes = "".join(f'<div class="rfbox"><div class="rf-name">{escape(n)}</div>'
                    f'<div class="rf-role">{escape(r)}</div>'
                    f'<div class="rf-org">{escape(o)}</div></div>'
                    for n, r, o in rows)
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
    hero = _uri(ongoing[0].featured_image) if ongoing else ""
    parts = [_cover(hero), _story(), _corporate(), _management(),
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
.div-strip{position:absolute;top:0;right:0;width:74mm;height:100%;overflow:hidden;}
.div-strip img{width:100%;height:100%;object-fit:cover;}
.div-center{position:absolute;left:18mm;top:112mm;max-width:118mm;}
.div-num{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:20pt;color:#E38A2E;letter-spacing:2pt;}
.div-title{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:42pt;line-height:1.0;color:#0E3A5C;margin-top:2mm;}
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
.amberbox{background:#0E3A5C;border-color:#0E3A5C;}
.amberbox .vmh{color:#E9B96E;}
.amberbox p{color:#EBE1CE;}
.vmh{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:12pt;letter-spacing:1.5pt;text-transform:uppercase;color:#0E3A5C;margin-bottom:3mm;}
.vmbox p{font-size:10pt;line-height:1.6;color:#47535D;margin:0;}
/* key management */
.mgrid{padding:9mm 18mm 0 18mm;display:grid;grid-template-columns:1fr 1fr;gap:7mm;}
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

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


def ring(sz, mid="#fff"):
    return (f'<svg width="{sz}" height="{sz}" viewBox="0 0 100 100">'
            f'<circle cx="50" cy="50" r="44" fill="none" stroke="#29ABE2" '
            f'stroke-width="11"/><circle cx="53" cy="46" r="30" fill="none" '
            f'stroke="{mid}" stroke-width="8"/><circle cx="55" cy="44" r="19" '
            f'fill="none" stroke="#29ABE2" stroke-width="5"/></svg>')


def _bar(section):
    return (f'<div class="topbar"><div class="tl">{ring(30)}'
            f'<span class="brand"><span class="s">SAND</span>PLANET</span></div>'
            f'<div class="sec">{section}</div></div>')


def _foot():
    return (f'<div class="foot"><span class="fb"><span class="s2">SAND</span>'
            f'PLANET</span><span class="ft">{TAGLINE}</span></div>')


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
    return (f'<div class="page">{_bar("Ongoing Projects")}'
            f'<div class="hero"><img src="{feat}"><div class="hero-tint"></div>'
            f'<div class="hero-text"><div class="client">'
            f'{escape(entry.client_display or "")}</div>'
            f'<div class="pname">{escape(entry.project_name or "")}</div>'
            f'<div class="start"><span class="dot"></span>{label} {start}</div>'
            f'</div></div><div class="pbody">'
            f'<div class="summary">{escape(entry.summary or "")}</div>'
            f'{grid}</div>{_foot()}</div>')


def _cover(hero):
    img = f'<img class="cov-img" src="{hero}">' if hero else ""
    return (f'<div class="page cover">{img}<div class="cov-tint"></div>'
            f'<div class="cov-top">{ring(46)}<span class="cov-brand">'
            f'<span class="s">SAND</span>PLANET</span></div>'
            f'<div class="cov-mid"><div class="cov-rule"></div>'
            f'<div class="cov-title">COMPANY<br>PROFILE</div>'
            f'<div class="cov-sub">Construction · Resort Supplies · Marine '
            f'Works</div></div><div class="cov-foot">'
            f'<span>Malé · Republic of Maldives</span>'
            f'<span>Version 2.0 · 2026</span></div></div>')


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
        ("Legal form", "Private company with limited liability, Republic of "
         "Maldives"),
        ("Shareholders", "Ahmed Shahiq · Ibrahim Fikury Hussain"),
        ("Senior management", "Ahmed Shahiq — Managing Director · Ibrahim "
         "Fikury Hussain — Director, Business Development · Muditha "
         "Samanthilaka — Director of Projects · Waseem Ali — Director of "
         "Marine Projects"),
        ("Registered office", "Ma. Maaraadha Aage', Dhanburuh Magu, Malé"),
        ("Registration", "C-656/2006 · TIN 1004853GST501"),
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
            'competitive leader in product costing — building excellence in '
            'every aspect to meet stringent requirements for quality, on-time '
            'delivery, safety and environmental care.</p></div></div>'
            f'</div>{_foot()}</div>')


def _divider(hero):
    img = f'<img class="div-img" src="{hero}">' if hero else ""
    return (f'<div class="page divider">{img}<div class="div-tint"></div>'
            f'{_bar("")}<div class="div-center"><div class="div-num">01</div>'
            '<div class="div-title">ONGOING<br>PROJECTS</div>'
            '<div class="div-line"></div>'
            '<div class="div-sub">Live works across the Maldivian atolls</div>'
            '</div></div>')


def _ref_card(e):
    img = _uri(e.featured_image)
    wrap = (f'<div class="ref-imgwrap"><img src="{img}">'
            f'<span class="ref-client">{escape(e.client_display or "")}'
            f'</span></div>' if img else '<div class="ref-imgwrap"></div>')
    return (f'<div class="refcard">{wrap}'
            f'<div class="ref-title">{escape(e.project_name or "")}</div>'
            f'<div class="ref-period">{escape(e.start_value or "")}</div></div>')


def _ref_divider(hero):
    img = f'<img class="div-img" src="{hero}">' if hero else ""
    return (f'<div class="page divider">{img}<div class="div-tint"></div>'
            f'{_bar("")}<div class="div-center"><div class="div-num">02</div>'
            '<div class="div-title">PROJECT<br>REFERENCES</div>'
            '<div class="div-line"></div>'
            '<div class="div-sub">Delivered across the Maldivian atolls</div>'
            '</div></div>')


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
    boxes = "".join(f'<div class="rfbox"><div class="rf-name">{n}</div>'
                    f'<div class="rf-role">{r}</div>'
                    f'<div class="rf-org">{o}</div></div>'
                    for n, r, o in REFEREES)
    return (f'<div class="page">{_bar("Referees")}<div class="txtpage">'
            '<div class="eyebrow">References</div>'
            '<h2 class="bigtitle2">Trusted by the industry</h2>'
            f'<div class="rfgrid">{boxes}</div></div>{_foot()}</div>')


def _back():
    return ('<div class="page backcover"><div class="bc-top">'
            f'{ring(52)}<div class="bc-brand"><span class="s">SAND</span>'
            'PLANET</div></div><div class="bc-rule"></div>'
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
    parts = [_cover(hero), _story(), _corporate(), _divider(hero)]
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
body { font-family:"Carlito","DejaVu Sans",sans-serif; color:#20160C; }
.page { width:210mm; height:297mm; position:relative; background:#F3ECDE;
        page-break-after:always; overflow:hidden; }
.s{color:#7FB6D6;} .s2{color:#B39B72;}
.topbar{height:14mm;background:#0E3A5C;display:flex;align-items:center;justify-content:space-between;padding:0 12mm;}
.tl{display:flex;align-items:center;gap:3mm;}
.brand{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:12pt;letter-spacing:3.5pt;color:#fff;}
.sec{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:10pt;letter-spacing:3pt;color:#E9B96E;text-transform:uppercase;}
.foot{position:absolute;left:12mm;right:12mm;bottom:8mm;display:flex;align-items:center;justify-content:space-between;border-top:1pt solid #D8C8AC;padding-top:4mm;}
.fb{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:10pt;letter-spacing:2.5pt;color:#0E3A5C;}
.ft{font-size:8.5pt;color:#8A7A5E;font-style:italic;}
.eyebrow{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:9.5pt;letter-spacing:3pt;text-transform:uppercase;color:#E38A2E;}
.amber{color:#E38A2E;}
.cover{background:#0E3A5C;}
.cov-img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
.cov-tint{position:absolute;inset:0;background:linear-gradient(to bottom,rgba(14,58,92,.72),rgba(14,58,92,.92));}
.cov-top{position:absolute;top:20mm;left:18mm;display:flex;align-items:center;gap:4mm;}
.cov-brand{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:17pt;letter-spacing:5pt;color:#fff;}
.cov-mid{position:absolute;left:18mm;top:120mm;}
.cov-rule{width:34mm;height:2mm;background:#E38A2E;margin-bottom:9mm;}
.cov-title{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:52pt;line-height:1.0;letter-spacing:2pt;color:#fff;}
.cov-sub{margin-top:7mm;font-size:12pt;letter-spacing:1pt;color:#E9D9BE;}
.cov-foot{position:absolute;left:18mm;right:18mm;bottom:16mm;display:flex;justify-content:space-between;color:#B9CBD8;font-size:9pt;letter-spacing:1pt;border-top:1pt solid rgba(255,255,255,.25);padding-top:4mm;}
.txtpage{padding:14mm 16mm 0 16mm;}
.bigtitle{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:30pt;line-height:1.08;color:#0E3A5C;margin:4mm 0 0 0;}
.bigtitle2{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:26pt;color:#0E3A5C;margin:3mm 0 8mm 0;}
.lead{font-size:13pt;line-height:1.6;color:#3A2E1E;margin:7mm 0 0 0;max-width:170mm;}
.cols{column-count:2;column-gap:10mm;margin-top:7mm;}
.cols p{font-size:10.5pt;line-height:1.62;color:#4A3E2E;margin:0 0 4mm 0;text-align:justify;}
.pullquote{margin-top:9mm;border-left:3pt solid #E38A2E;padding:2mm 0 2mm 7mm;font-family:"DejaVu Sans Condensed";font-size:17pt;font-weight:bold;color:#0E3A5C;line-height:1.3;}
.divider{background:#0E3A5C;}
.div-img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
.div-tint{position:absolute;inset:0;background:linear-gradient(120deg,rgba(14,58,92,.94),rgba(14,58,92,.78));}
.divider .topbar{background:transparent;}
.div-center{position:absolute;left:18mm;top:110mm;}
.div-num{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:22pt;color:#E38A2E;letter-spacing:2pt;}
.div-title{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:46pt;line-height:1.0;color:#fff;margin-top:2mm;}
.div-line{width:40mm;height:2mm;background:#E38A2E;margin:8mm 0;}
.div-sub{color:#E9D9BE;font-size:12pt;letter-spacing:.5pt;}
.hero{position:relative;width:100%;height:150mm;overflow:hidden;}
.hero>img{width:100%;height:100%;object-fit:cover;}
.hero-tint{position:absolute;inset:0;background:linear-gradient(to bottom,rgba(14,58,92,0) 42%,rgba(14,58,92,.86) 100%);}
.hero-text{position:absolute;left:0;right:0;bottom:0;padding:0 12mm 9mm 12mm;}
.client{display:inline-block;background:#E38A2E;color:#fff;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:12pt;letter-spacing:2.5pt;text-transform:uppercase;padding:2mm 6mm;}
.pname{font-family:"DejaVu Sans Condensed";font-weight:bold;color:#fff;font-size:24pt;line-height:1.05;margin-top:4mm;max-width:180mm;text-shadow:0 1px 6px rgba(0,0,0,.35);}
.start{margin-top:3mm;color:#F3ECDE;font-size:10.5pt;display:flex;align-items:center;gap:2.5mm;}
.dot{width:2.4mm;height:2.4mm;background:#E9B96E;border-radius:50%;display:inline-block;}
.pbody{padding:8mm 12mm 0 12mm;}
.summary{font-size:12pt;line-height:1.7;color:#3A2E1E;text-align:justify;border-left:3pt solid #E38A2E;padding-left:6mm;max-width:180mm;}
.grid6{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm;margin-top:9mm;}
.grid6 .g{height:38mm;overflow:hidden;background:#E4D9C4;}
.grid6 .g img{width:100%;height:100%;object-fit:cover;}
.refhead{padding:12mm 16mm 0 16mm;}
.refh2{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:22pt;color:#0E3A5C;margin:2mm 0 0 0;}
.refgrid{padding:8mm 16mm 0 16mm;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6mm;}
.ref-imgwrap{position:relative;height:44mm;overflow:hidden;background:#D8C8AC;}
.ref-imgwrap img{width:100%;height:100%;object-fit:cover;}
.ref-client{position:absolute;left:0;bottom:0;background:#0E3A5C;color:#fff;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:8pt;letter-spacing:1.2pt;text-transform:uppercase;padding:1.5mm 3mm;}
.ref-title{font-size:10pt;font-weight:bold;color:#20160C;margin-top:2.5mm;line-height:1.25;}
.ref-period{font-size:8.5pt;color:#8A7A5E;margin-top:1mm;}
.inforows{margin-top:2mm;}
.ir{display:flex;border-bottom:1pt solid #DFD2BB;padding:3mm 0;}
.ik{flex:0 0 42mm;font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:9pt;letter-spacing:1.4pt;text-transform:uppercase;color:#E38A2E;}
.iv{font-size:10.5pt;color:#3A2E1E;line-height:1.4;}
.vm{display:flex;gap:6mm;margin-top:9mm;}
.vmbox{flex:1;background:#fff;border:1pt solid #E0D3BC;padding:6mm;}
.amberbox{background:#0E3A5C;}
.amberbox .vmh,.amberbox p{color:#fff;}
.vmh{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:13pt;letter-spacing:1.5pt;text-transform:uppercase;color:#0E3A5C;margin-bottom:3mm;}
.vmbox p{font-size:10pt;line-height:1.6;color:#4A3E2E;margin:0;}
.rfgrid{display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-top:4mm;}
.rfbox{background:#fff;border:1pt solid #E0D3BC;border-left:3pt solid #E38A2E;padding:5mm 6mm;min-height:20mm;}
.rf-name{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:13pt;color:#0E3A5C;}
.rf-role{font-size:9.5pt;color:#3A2E1E;margin-top:1mm;}
.rf-org{font-size:9pt;color:#8A7A5E;margin-top:0.5mm;}
.backcover{background:#0E3A5C;}
.bc-top{position:absolute;top:34mm;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:5mm;}
.bc-brand{font-family:"DejaVu Sans Condensed";font-weight:bold;font-size:24pt;letter-spacing:6pt;color:#fff;}
.bc-rule{position:absolute;top:78mm;left:50%;margin-left:-20mm;width:40mm;height:2mm;background:#E38A2E;}
.bc-tag{position:absolute;top:92mm;left:0;right:0;text-align:center;color:#E9D9BE;font-size:13pt;font-style:italic;letter-spacing:.5pt;}
.bc-contact{position:absolute;top:150mm;left:40mm;right:40mm;}
.bc-row{display:flex;border-top:1pt solid rgba(255,255,255,.2);padding:4mm 0;color:#fff;font-size:11pt;}
.bc-k{flex:0 0 28mm;font-family:"DejaVu Sans Condensed";font-weight:bold;letter-spacing:1.5pt;text-transform:uppercase;font-size:9pt;color:#E9B96E;}
.bc-foot{position:absolute;bottom:16mm;left:0;right:0;text-align:center;color:#7FA0B6;font-size:8.5pt;letter-spacing:1pt;}
"""

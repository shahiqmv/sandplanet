"""Assemble the standalone Procurement Planning guide — one self-contained HTML
file with the demo screenshots embedded as data URIs, so it can be shared with
the team as a single portable file.

    python build_procurement_guide.py   (run from guide/, after capture)
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).parent
SHOTS = HERE / "screenshots-procurement"
OUT = HERE / "Procurement_Planning_Guide.html"


def data_uri(name):
    raw = (SHOTS / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def fig(name, caption):
    return (f'<figure><img src="{data_uri(name)}" alt="{caption}">'
            f'<figcaption>{caption}</figcaption></figure>')


CSS = """
:root{--navy:#10344f;--sky:#1685cc;--ink:#22333f;--muted:#5a6b78;
  --line:#dbe6ee;--soft:#eef5fa;--paper:#fff;--bg:#f4f1ea;
  --ok:#137a4b;--warn:#b06f00;--alert:#b3261e;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.55;font-size:16px}
.wrap{max-width:940px;margin:0 auto;padding:0 22px 90px}
header.cover{background:var(--navy);color:#fff;margin:0 0 34px;
  padding:52px 22px 46px}
header.cover .inner{max-width:940px;margin:0 auto}
.brand{font-weight:800;letter-spacing:.16em;font-size:13px;opacity:.8}
h1{font-size:34px;margin:10px 0 8px;line-height:1.1}
.cover p{font-size:16px;color:#cfe0ec;max-width:640px;margin:8px 0 0}
h2{color:var(--navy);font-size:23px;margin:44px 0 6px;
  padding-bottom:6px;border-bottom:2px solid var(--sky)}
h3{color:var(--navy);font-size:17px;margin:26px 0 4px}
p{margin:10px 0}
strong{color:var(--navy)}
ul{margin:10px 0;padding-left:20px}
li{margin:6px 0}
figure{margin:20px 0;border:1px solid var(--line);border-radius:12px;
  overflow:hidden;background:var(--paper);box-shadow:0 1px 4px rgba(24,36,48,.07)}
figure img{display:block;width:100%}
figcaption{font-size:13px;color:var(--muted);padding:9px 14px;
  background:var(--soft);border-top:1px solid var(--line)}
.callout{background:var(--soft);border-left:4px solid var(--sky);
  border-radius:0 10px 10px 0;padding:12px 16px;margin:16px 0;font-size:15px}
.roles{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.role{flex:1;min-width:180px;background:var(--paper);border:1px solid var(--line);
  border-radius:10px;padding:12px 14px}
.role b{color:var(--navy);display:block;font-size:14px;margin-bottom:2px}
.role span{font-size:13.5px;color:var(--muted)}
.flow{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:14px;
  background:var(--navy);color:#dbeafd;border-radius:10px;padding:12px 16px;
  margin:14px 0;overflow-x:auto}
.chip{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12.5px;
  font-weight:700}
.chip.ok{background:#d8f0e2;color:var(--ok)}
.chip.warn{background:#fbeccb;color:var(--warn)}
.chip.alert{background:#f7d9d6;color:var(--alert)}
footer{color:var(--muted);font-size:13px;margin-top:50px;
  border-top:1px solid var(--line);padding-top:14px}
"""


BODY = f"""
<header class="cover"><div class="inner">
  <div class="brand">SAND PLANET</div>
  <h1>Procurement Planning — Team Guide</h1>
  <p>The per-project forward plan for key &amp; imported materials — set up before
     the orders exist, then it <em>watches</em> the real documents so the status
     keeps itself up to date. This guide walks the whole team through it.</p>
</div></header>

<div class="wrap">

<h2>What it is, in one paragraph</h2>
<p>Every project needs long-lead and imported materials planned <strong>well
  before</strong> anyone raises an order. The Procurement Plan is that forward
  view: one row per material, grouped into sections that mirror the client's own
  sheet. Planning is a <strong>joint effort of the QS and the project team</strong>
  — the QS is its custodian and coordinates it (and the alignment with the client),
  working alongside the PM. Purchasing then confirms the commercial detail, and the
  <strong>Director (PD) signs off</strong> the baseline. From there it
  <strong>watches the execution documents</strong> — the material approval, the
  import order, the site receipt — and updates each line's progress, ETA and risk
  automatically. Nobody re-types status.</p>

<div class="roles">
  <div class="role"><b>QS — custodian</b><span>Coordinates the plan and the client
    alignment, captures BOQ quotes, submits for pricing.</span></div>
  <div class="role"><b>Project team (PM)</b><span>Plan jointly with the QS, propose
    lines, and recommend the suppliers.</span></div>
  <div class="role"><b>Purchasing</b><span>Confirms the commercial fields and
    <strong>decides the supplier award</strong>; links the real orders.</span></div>
  <div class="role"><b>Director (PD)</b><span>Signs off the baseline.</span></div>
</div>

<h2>Where to find it</h2>
<p>Open <strong>Planning ▸ Procurement Schedule</strong> for the cross-project
  list, or a project's own <strong>Procurement</strong> tab. The list shows every
  project's plan with its live risk at a glance.</p>
{fig("01-planning-list", "Planning ▸ Procurement Schedule — every project's plan and its risk at a glance.")}

<h2>The plan at a glance</h2>
<p>A plan is grouped into sections (e.g. “A — Pool Plant &amp; Equipment”). Each
  line carries what the material is, how much, when it's needed on site, and — as
  execution starts — where it has actually reached.</p>
{fig("02-schedule-detail", "A signed-off plan. Pipeline dots, risk, live stage and committed value all update themselves.")}
<p>Reading a row, left to right:</p>
<ul>
  <li><strong>Supply</strong> — <em>Sand Planet</em> (we procure it) or the
    <strong>site code</strong> (the client supplies it).</li>
  <li><strong>Supplier / Country / Est. value</strong> — the plan estimate, and
    once an order is linked, the <strong>real supplier</strong> and the
    <strong>ordered value</strong> with the over/under variance.</li>
  <li><strong>Pipeline</strong> — six dots: TDS → Order → Production → Shipment →
    Delivery → ETA. They fill in from the linked documents.</li>
  <li><strong>Risk</strong> — <span class="chip ok">On track</span>
    <span class="chip warn">At risk</span> <span class="chip alert">Late ⚠</span>,
    worked out from the required date versus the projected arrival.</li>
  <li><strong>State</strong> — the live execution stage (Ordered → In production →
    Shipped → Delivered), with the approval state beneath it.</li>
</ul>

<h2>Building the plan — adding a line</h2>
<p>Lines are disciplined so the plan stays clean: the description comes from the
  item catalogue, the unit and category are pick-lists, and Supply is named
  (Sand Planet or the client). Set the required-on-site date, and tick
  <em>TDS / MAR required</em> if the material needs approval first.</p>
{fig("05-new-line", "Adding a line — catalogue-linked description, unit and category pick-lists, required date.")}

<h2>Bundling variant lines</h2>
<p>Some materials come in many variants — “Deck &amp; Fence Timber” in six sizes,
  pool plumbing across dozens of fittings. Each variant still needs its
  <strong>own line</strong>, because the order (IPR), shipment tracking and site
  receipt (GRN) all attach per line. But dozens of near-identical rows make the
  plan hard to read.</p>
<p>Give those lines the <strong>same “Bundle / group” label</strong> on the
  add-line form and they <strong>collapse into one tidy, expandable summary
  row</strong>. The summary rolls the variants up for you: the earliest required
  date, the total quantity (when they share a unit), the combined pipeline (a
  stage only shows done once <em>every</em> variant reaches it) and the
  <strong>worst risk</strong> in the group. Click the row to expand it and see —
  or track — each variant on its own.</p>
<div class="callout">A bundle <strong>splits automatically by supplier</strong>:
  the moment Purchasing awards different suppliers, the group divides so each
  summary still maps cleanly to one order. A bundle with only one line just shows
  as a normal row.</div>
<p>Bundling is <strong>purely for readability</strong> — every variant keeps its
  own record and its own documents; nothing is merged or lost. The client sees
  the same clean one-row-per-bundle view, with the detail one click away:
  on the <strong>live link</strong> a grouped item expands in place to list its
  variants, and the export comes in two flavours — <strong>Export client
  plan</strong> (grouped) or <strong>all variants</strong> (every size/fitting
  on its own row) for clients who want the full listing.</p>

<h2>BOQ quotes &amp; the supplier award</h2>
<p>During the BOQ stage the QS and project team already hold supplier quotes.
  Attach them to the line — supplier, price, lead time and the quote file — and
  flag the one the <strong>project team recommends</strong>. When the order is
  raised, <strong>Purchasing decides the award</strong> (the recommended supplier,
  or a new one), so there's one clean trail from BOQ quote → recommended →
  awarded supplier → ordered value.</p>
{fig("03-quotes-panel", "BOQ quotes on a line — recommended and awarded marked, the losing quote kept, the IPR linked.")}

<h2>The workflow</h2>
<div class="flow">QS + project team plan  →  Purchasing confirm  →  Director (PD) sign off  →  run by the PM</div>
<p>Planning is shared — the QS and the project team build it together, and anyone
  on that team can propose lines; Purchasing and the Director are the gates. Once
  the baseline is signed, day-to-day status updates need no approval. Adding a line
  to a signed plan simply <strong>reopens a change batch</strong> — the
  already-signed lines stay live.</p>

<h2>Watching execution — the Track panel</h2>
<p>This is the heart of it: instead of re-keying status, you <strong>link</strong>
  the real documents to a line and the pipeline fills itself in. Link the material
  approval (MAR), the import order (IPR) and the site receipt (GRN) — “Suggest
  matches” finds them for you. The shipment, ETA and delivery then derive
  automatically. The only manual stage is <em>Production</em>, for made-to-order
  items with no document of their own.</p>
{fig("04-track-panel", "The Track panel — link MAR / IPR / GRN; the rest of the pipeline derives itself.")}

<h2>Risk &amp; alerts</h2>
<ul>
  <li>Each line is <strong>On track / At risk / Late</strong>, from its required
    date versus a projected arrival (order date + lead time + freight allowance +
    a site buffer, or the live shipment ETA).</li>
  <li><strong>Late while still unordered</strong> is the worst case — flagged
    because the date can't be met even if the order goes out today.</li>
  <li>The PM and Purchasing get an alert the moment a line slips; the Director
    gets a <strong>weekly digest</strong> of everything late or at risk across all
    projects.</li>
  <li>Client-supplied lines that go quiet raise a <strong>“chase client update”</strong>
    reminder to the PM.</li>
</ul>

<h2>Who sees the money</h2>
<p>Estimates, quotes and ordered values are <strong>internal</strong> — Head
  Office, the Director, the QS and the project's own PM. Site staff see the same
  plan and progress <strong>without the price columns</strong>, so a schedule can
  be opened on site without exposing commercials.</p>
{fig("07-schedule-site-noprices", "The same plan as a Site Engineer — full progress, no value or quote columns.")}

<h2>Sharing with the client</h2>
<p>Two buttons on the plan header share it outward, with only the client-safe
  columns (no internal money, no supplier names):</p>
<ul>
  <li><strong>Export client plan</strong> — a formatted spreadsheet in the
    client's own layout.</li>
  <li><strong>Create client link</strong> — a live, read-only web link that always
    shows the current status, so the client never needs a fresh export.</li>
</ul>

<footer>Sand Planet · Procurement Planning · team guide. Screens shown are from
  the demo project (POOLS17); your live data will differ.</footer>
</div>
"""

HTML = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Procurement Planning — Team Guide</title><style>{CSS}</style>"
        f"</head><body>{BODY}</body></html>")

OUT.write_text(HTML, encoding="utf-8")
kb = len(HTML.encode("utf-8")) // 1024
print(f"Wrote {OUT.name} ({kb} KB)")

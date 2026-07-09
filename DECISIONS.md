# Decisions & deviations log

Deviations from `SP_Technical_Design.md`, with reasons, per the Build Brief.

## 2026-07-07 — D1: SQLite fallback for local dev until Docker Desktop is installed
The design commits to PostgreSQL 16 via docker-compose (Django + Postgres + MinIO).
The dev machine has no Docker Desktop yet (interactive install + WSL2 + license
acceptance — owner to install). `docker-compose.yml` is committed and remains the
canonical local environment; until Docker is available, `backend/config/settings.py`
falls back to SQLite when `POSTGRES_HOST` is unset so development can proceed.
No schema code may rely on SQLite-specific behavior; all migrations must be
re-verified against Postgres before M1 is called done.

## 2026-07-07 — D2: Repo lives inside OneDrive for now
The project folder is under OneDrive. `node_modules/` and `.venv/` cause heavy
sync churn. Mitigation for now: both are git-ignored; consider moving the repo to
a non-synced path (e.g. `C:\dev\`) or excluding the folder from OneDrive sync.

## 2026-07-07 — D3: Local-disk media fallback until MinIO (Docker) is available
Design: all user files to Spaces (MinIO locally). Without Docker Desktop the
default storage falls back to Django FileSystemStorage under `backend/media/`
(dev only, DEBUG-served). The S3 storage backend activates automatically when
`S3_ENDPOINT_URL` is set — staging/production always set it; the App Platform
"no persistent disk" rule is unaffected.

## 2026-07-07 — D4: WeasyPrint on Windows needs the GTK3 runtime
WeasyPrint requires GTK libraries. On Windows dev machines install them with
`winget install GtkD.GtkPlusRuntime.x64`; core/pdf.py auto-points WeasyPrint at
`C:\Program Files\Gtk-Runtime\bin` (override with `GTK_DLL_DIR`). RESOLVED
2026-07-07: installed on the dev machine — local PDF generation works.
Safety net kept: if the engine is missing, local dev (`PDF_REQUIRED=0`) skips
PDF with a logged warning; staging/production set `PDF_REQUIRED=1` so a missing
engine blocks issue there. Layout acceptance is still against the Excel prints.

## 2026-07-07 — R2: Quotation capture, MR-line matching, and Purchase Orders (owner-directed scope addition)
The R1 spec kept PR vendor rows as quote summaries and deferred any PO module
to Phase 3. Owner identified the gap: nothing ties supplier quotes to MR items,
so quotes cannot be tallied against the manifest. Added now (ahead of M5):
supplier database; quotation capture per PR (supplier's own line wording +
file); manual matching form quote-line -> MR line (supplier descriptions
differ by design); coverage tally blocks PR submit while MR lines are
unquoted/unawarded (explicit override with reason allowed); Director's PR
approval doubles as the award approval and auto-generates draft POs (global
PO-NNN numbering) per awarded supplier; LM prefills from POs. An MR line may
be split across suppliers.

## 2026-07-07 — R3: Finance role activated (supersedes decision 6 deferral)
Owner wants the full approval ladder for go-live: site users prepare, PM
approves site documents, HO Purchasing prepares PR/LM/PO, Director approves
the PR (award), and FINANCE — a new role — records payment / PO issuance
(slip no. / PO no.) on approved PRs. Purchasing no longer records payments.
Finance has HO-wide read scope; basic pay/passport remain HR+Admin only.

## 2026-07-08 — R3 addendum: Finance payroll access; vendor-level payment/PO refs
Finance also gets payroll export + attendance visibility (basic pay becomes
visible to Finance; passports/work permits remain HR+Admin). PR "Action
Taken" is vendor-specific, not a PR-level entry: the PO ref auto-fills into
each vendor row when POs generate on award approval; the payment ref is
recorded per vendor (Purchasing on receiving the slip/voucher from Finance,
or Finance directly) with the slip file attached; the PR page links each
vendor row to its quote, PO, and payment slip. PR status auto-advances:
APPROVED -> PAYMENT_PROCESSING (first vendor settled) -> PAID_PO_ISSUED (all).

## 2026-07-08 — R4: Projects under sites; programme milestones; DPR progress tracking
Supersedes the R1 premise "a site IS a project" (§2). Reality: clients keep
awarding new projects on the same site, each with its own scope, BOQ,
programme and timeline (e.g. "17 pools" programme at Vakkaru). Changes:
- New Project entity under Site (title, scope, dates, status, own contract
  value with the same sensitivity rule). DPR, TWS, IR and MAR now belong to
  a project; MR/GRN and the HO chain (PR/LM/PO) stay site-wise.
- Programme per project: activities/milestones (name, duration, start,
  finish, hierarchy by indent) imported by pasting from MS Project or added
  manually. DPR "work done" rows link to a programme activity and record
  today's progress % and cumulative % to date; issuing the DPR updates the
  activity's progress (audited).
- One DPR/TWS per PROJECT per working day; gap detection runs per project
  from the project's start date. Document numbering stays per SITE
  (TYPE-SITECODE-NNN, §4.1 unchanged) — refs remain unique and gap-free.
- Existing dev documents keep project=NULL; new documents require a project
  when the site has one.

## 2026-07-08 — R5: PM assignments page; Daily Manpower Allocation (DMA)
- PM accounts continue to be created under Users (one place for
  credentials), but PM ASSIGNMENTS get a dedicated management page: every
  PM with the sites they are site PM of, the projects they are project PM
  of, assignment history, and reassignment controls (Admin/Director).
- New internal document: Daily Manpower Allocation (DMA-SITECODE-NNN,
  one per SITE per day, site-wide — not per project). Early morning the
  PM allocates the day's tasks based on the TWSs issued the previous day;
  rows may come from any project's TWS or be GENERAL tasks not tied to a
  programme scope (site cleaning, material unloading, housekeeping).
  Each row: task, location, manpower category, workers, remarks; the
  document totals manpower at work by category. SE may prepare; only the
  PM issues. Internal document — printable PDF on the letterhead, not
  sent to the client.

## 2026-07-08 — R6: PDF stationery restyle to the owner's printed forms; Company page
Owner shared his real printed DPR ("neat and colors are very printer
friendly") and asked to apply the same look to all report PDFs. Done:
shared _styles.html/_footer.html/_letterhead.html includes with the exact
palette extracted from his PDF (sky #29ABE2, navy #16527E, bars #BFD3E3,
label fill #EAF1F6); dpr.html rebuilt to his form section-for-section
(fixed filler rows, Staff|Trades manpower split, photos sheet). The logo
is now a real IMAGE extracted from his stationery (assets/sp-logo.png —
closes the traced-SVG ring-color issue); Admin can replace it on the new
Company tab, which also manages legal name, registration no, TIN, address,
phone, email, website (company_* parameters). Every PDF footer now prints
the company identity line; the external PO adds reg no + phone.

## 2026-07-08 — R6 addendum: grouped menu + per-role Approvals queue
Owner: "HO Dashboard" → "Purchasing Dashboard"; menu needed re-arranging.
Approved option: five role-trimmed top-level groups — Approvals · Sites ·
Procurement (Purchasing Dashboard / Items / Suppliers) · People (Employees /
Payroll / PMs) · Admin (Site Setup / Users / Company) — plus a new
Approvals queue (GET /approvals/pending): each approver's landing page
lists exactly the documents blocked on them (PM: submitted MR/IR/MAR,
DPRs to verify, DMAs to issue; Director: submitted PRs; Purchasing: MRs
sent to HO, draft POs; Finance/Purchasing: approved PRs awaiting payment).
PMs get the grouped nav too (Approvals + Sites). Nav shows a live pending
count badge.

## 2026-07-08 — R7: SP_Design_Brief.md adopted ("drawing title block, island paper")
Owner delivered SP_Design_Brief.md + Requirements Spec R1 §7.4 (role
dashboards) from his design chat. Staged implementation:
- Stage 1 (done): tokens in index.css (sand canvas, sand-toned hairlines,
  4-tone chips), self-hosted Barlow Condensed / Inter / IBM Plex Mono
  (@fontsource), shared components in ui.jsx (Btn semantic variants, Chip,
  RefStamp, IssuedStamp, StampTile, Eyebrow, Stat-with-context,
  ActionCard); site dashboard leads with Today's-obligations stamp tiles
  (amber dashed → green rotated issued stamp); Approvals queue = severity
  action cards with age lines; Purchasing dashboard eyebrows + stats with
  context lines; 900px shell, 3px sky header rule, display-font brand.
- Stage 2 (done same day): HR dashboard (GET /dashboards/hr — month-lock
  stamp-tile board driving the payroll-ready signal, permit expiries
  within 60 days, closed-site reallocation alerts, workforce/OT stats;
  HR's landing page) and Management portfolio (GET /dashboards/portfolio,
  Director/Admin — per project: value, PM, % time elapsed vs programme
  progress, open items, on-track/watch/attention health; Portfolio
  sub-tab beside Approvals).
- Stage 3 (pending): FormCard restyle of document forms (auto-calc cells
  in mono on sand tint, inline validation copy); boat-board grouping on
  the Purchasing dashboard.
NOTE: the brief references two mockup JSX files (source of truth for look
and feel) that were not delivered — implementation follows the written
brief; reconcile if the owner supplies the mockups.

## 2026-07-08 — R8: DPR and TWS are SITE-WIDE; rows tagged per project
Supersedes R4's one-DPR-per-project rule after owner review. A site has
ONE client, so the client gets ONE daily report: DPR and TWS are one per
SITE per working day. Each Work Done / Planned Activity row is tagged
with its project (or General for untagged works — cleaning, unloading),
and DPR rows may link to that project's programme activity; issuing the
DPR rolls each row's to-date % into ITS OWN project's programme, so
per-project progress and the portfolio are unchanged. The DPR PDF groups
the task list PROJECT-WISE (owner: easier for the client to read); the
TWS PDF gains a Project column. Register/gap detection returns to
per-site (gap window from the earliest active project's start date).
IR/MAR remain project documents; the site PM verifies the site-wide DPR.
Existing per-project DPRs/TWSs stay valid history. Confirmed: same
client entity per site — a different client on the same island would be
a new site code.

## 2026-07-08 — R9: dynamic manpower (roster ↔ attendance ↔ allocation)
Owner round. Employee DB already allocates every employee to a site and
job categories share the DPR manpower list, so:
- DPR manpower entry: dynamic rows (category dropdown + count) instead of
  the fixed 17-category grid, plus a "Prefill from today's attendance"
  BUTTON (owner chose button over auto). Stored shape unchanged
  (category id → count) — old DPRs and the printed PDF layout untouched.
- Site dashboard "Manpower today" card: roster / present / absent /
  allocated-to-tasks headline; IDLE = present − workers in today's DMA
  (owner-confirmed definition); DPR-vs-attendance mismatch warning; top-4
  category bars (owner: top 4, click through for more).
- "Full breakdown" page (GET /sites/{id}/manpower): all categories
  roster/present/absent + the roster with each person's status today —
  names and categories only, never pay/passport.
- Honest-data rule: card says "attendance not entered yet today" instead
  of pretending zeros; idle only computed when attendance + DMA exist.

## 2026-07-08 — R9 addendum: DMA connected to attendance; strict categories
The allocation's availability comes from attendance: the DMA page shows
"N present today · M allocated · K not yet allocated", each category
option carries its present count, the Manpower-at-Work table compares
Allocated vs Present, and over-allocating a category raises a visible
warning (soft — the PM may still issue). The category field is no longer
free text: strictly the site's roster categories (full DPR list fallback
when the site has no roster yet); a legacy/TWS value outside the list
stays selectable but flagged "(not in category list)" until corrected.

## 2026-07-08 — R10 Phase A: dedicated Project workspace + in-app Gantt
Owner: projects have many components (programme, manpower plan, BOM,
budget, tender later) — a chip/sub-page is not enough. Phase A delivers
the PROJECT WORKSPACE page (opened from the site page's "Open project →"
or the portfolio's project stamp): Overview (progress-vs-time health,
stats, full detail block) · Programme · Documents, with BOM / Budget /
Tender tabs visibly reserved for later phases. Programme gains an
interactive Gantt built on Frappe Gantt (MIT, lightweight — chosen over
commercial dhtmlx/Bryntum; upgrade path kept open): bars from the
activities, progress fill from issued DPRs, drag-to-reschedule PATCHes
the activity (audited), milestones/summary rows styled; NEW
ProgrammeActivity.predecessors (comma ids) drives dependency arrows,
editable on the activity row. Documents tab (GET /projects/{id}/documents)
splits the project's own docs (IR/MAR + legacy per-project DPR/TWS) from
site-wide daily reports carrying rows tagged to this project.
Phase B decided: the QS builds the BOM from the BOQ (manual, assisted) —
no automatic tender-BOQ conversion. Phase C: budget via project-tagged
procurement; tender module.

## 2026-07-08 — R10 addendum: programme export + manpower histogram (award package)
Owner: the programme and manpower histogram are SENT to the client upon
award. Added: Project.manpower_plan (planned workers per month, edited on
the workspace's new "Manpower plan" tab with a live histogram preview)
and GET /projects/{id}/programme.pdf — a landscape letterhead PDF with
the programme of works (activity table + CSS Gantt: month grid, navy
summary bars, sky task bars with progress fill, milestone diamonds) and
a MANPOWER HISTOGRAM page (bars per month, peak, manpower summary note).
Downloaded via "⬇ Programme PDF" on the project page; a one-off export,
not a numbered document. WeasyPrint quirk: no `inset` shorthand.

## 2026-07-08 — R10 fix round: manpower REQUIREMENT per category; full creation form
Owner corrections: (1) the manpower plan is not a monthly total and not a
free-text summary — it is the REQUIREMENT per category, PM down to
unskilled workers, and the histogram is drawn from those numbers only.
manpower_plan is now [{category, workers}] with categories strictly from
the company manpower list (Staff/Trades optgroups, each once); the PDF
page reads "MANPOWER REQUIREMENT — BY CATEGORY" with total planned
manpower in the header; the free-text manpower summary is dropped from
the forms (DB column retained for history). (2) Project creation on the
site page is a proper card — code, title, LOA, start, planned finish,
project PM, scope — replacing the one-line chip form; creating opens the
project workspace directly. The 500 he hit was the stale detached dev
server, not the code.

## 2026-07-08 — R11: controlled categories + item create-on-the-fly
Owner: item categories, worker categories and item selection should all
be controlled lists, with a way to create a new item inline when one is
genuinely missing. Done:
- New ItemCategory model (migration 0014 seeds trade defaults + any
  categories existing items already used). Item.category is validated
  against the active list on save; ItemsPage category is a dropdown;
  managed on a new "Item Categories" page under Procurement (HO
  Purchasing/Admin). Deleting a category still in use deactivates it.
- Worker (manpower) categories finally get a UI: "Worker Categories"
  page under People (Admin) — the one company-wide list already driving
  DPR/DMA/project requirement/roster, split by DPR vs TWS list and
  Staff vs Trades. manpower-categories viewset gains delete (deactivate
  if used by an employee).
- MR/PR/LM/GRN item picker: when Purchasing/Admin types a description
  with no catalog match, an inline "+ Add … to catalog" button prompts
  for unit + category, creates the Item, and selects it — the flagged
  free-text path stays for site users who can't edit the catalog.

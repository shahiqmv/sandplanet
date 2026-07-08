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

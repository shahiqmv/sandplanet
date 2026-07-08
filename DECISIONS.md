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

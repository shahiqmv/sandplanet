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

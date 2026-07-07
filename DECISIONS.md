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

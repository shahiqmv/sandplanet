# Sand Planet — Site Documents

Production web application for Sand Planet's site documentation (DPR, TWS, IR,
MAR, MR, PR, LM, GRN), registers, and site timesheets. Authoritative documents:

- [CLAUDE_BUILD_BRIEF.md](CLAUDE_BUILD_BRIEF.md) — milestones and non-negotiables
- [SP_Site_Documents_Requirements_Specification_R1.md](SP_Site_Documents_Requirements_Specification_R1.md) — WHAT
- [SP_Technical_Design.md](SP_Technical_Design.md) — HOW
- [DECISIONS.md](DECISIONS.md) — recorded deviations

## Stack

Django 5 + DRF + PostgreSQL 16, React (Vite) SPA, WeasyPrint PDFs,
DO Spaces (MinIO locally). See the technical design for details.

## Local development

Canonical (requires Docker Desktop):

```
docker compose up
```

Without Docker (SQLite fallback, DECISIONS.md D1):

```
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py runserver
```

Frontend dev server (proxies /api to Django):

```
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Health check: http://127.0.0.1:8000/api/v1/health

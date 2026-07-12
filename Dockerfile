# Sand Planet — production image (M8). Build context is the repo root so the
# SPA and the Django app are built together; Django serves the built SPA.
#
#   docker build -t sandplanet .

# ---- Stage 1: build the SPA (base=/static/ in production) ----------------
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build            # -> /build/dist, assets under /static/

# ---- Stage 2: Django + gunicorn + WeasyPrint ----------------------------
FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# WeasyPrint's native libraries (Pango/Cairo/GDK-Pixbuf/ffi) + base fonts, so
# PDF generation works in the container (PDF_REQUIRED=1 in production).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
      libffi8 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
# Import templates (CSV masters for import_items / import_employees / etc.)
# so `python manage.py import_items /app/import-templates/<file>` works.
COPY import-templates/ /app/import-templates/
# The built SPA lands at /app/frontend/dist so BASE_DIR.parent/frontend/dist
# resolves (see settings.py TEMPLATES / STATICFILES_DIRS)
COPY --from=frontend /build/dist /app/frontend/dist

RUN chmod +x /app/backend/entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]

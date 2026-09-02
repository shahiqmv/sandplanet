#!/bin/sh
# Container start (M8): apply migrations, gather static (incl. the SPA under
# /static/assets/ with the manifest that WhiteNoise serves), then run
# gunicorn. Migrations and collectstatic are idempotent.
set -e

# Refuse to start if any production check fails — Django's own (DEBUG,
# secret key, HTTPS, cookies) and ours in core/checks.py (no HTML API pages,
# no admin, no developer apps). A regression is a deploy that does not
# happen, not a page somebody finds later (owner 2026-09-02).
python manage.py check --deploy --fail-level WARNING

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# First-deploy seed (sites, worker categories, company params, admin user) —
# idempotent; enable once with RUN_SEED=1, then leave it off.
if [ "${RUN_SEED:-0}" = "1" ]; then
  python manage.py seed
fi

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-300}" \
  --access-logfile - --error-logfile -

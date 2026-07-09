#!/bin/sh
# Container start (M8): apply migrations, gather static (incl. the SPA under
# /static/assets/ with the manifest that WhiteNoise serves), then run
# gunicorn. Migrations and collectstatic are idempotent.
set -e

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
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --access-logfile - --error-logfile -

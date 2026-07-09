#!/bin/sh
# Update the live app (M8): pull the latest code and redeploy.
# Run on the droplet:   bash update.sh
#
# Safe to run anytime — your database (Docker volume) and uploaded files
# (Spaces) are untouched; only the app code + frontend are rebuilt.
set -e
cd "$(dirname "$0")"

echo "==> Pulling latest code…"
git pull

echo "==> Rebuilding and restarting…"
docker compose -f docker-compose.prod.yml up -d --build

echo "==> Status:"
docker compose -f docker-compose.prod.yml ps
echo "Done."

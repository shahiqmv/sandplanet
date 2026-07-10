#!/usr/bin/env bash
# Rebuild the throwaway demo DB from scratch and seed the user-guide dataset.
# NEVER touches the live db.sqlite3 / :8000 tunnel — everything here is the
# --settings=config.settings_demo instance (db.demo.sqlite3 + media-demo/).
set -euo pipefail
cd "$(dirname "$0")"
PY="./.venv/Scripts/python.exe"
S="--settings=config.settings_demo"

echo "==> dropping db.demo.sqlite3 + media-demo"
rm -f db.demo.sqlite3
rm -rf media-demo

echo "==> migrate"
"$PY" manage.py migrate $S --noinput >/dev/null

echo "==> seed (master data)"
"$PY" manage.py seed $S

echo "==> seed_demo (worked dataset)"
"$PY" manage.py seed_demo $S "$@"

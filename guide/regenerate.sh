#!/usr/bin/env bash
# One command to rebuild the entire Planet User Guide from scratch:
#   demo DB  ->  demo server (:8001)  ->  screenshots  ->  letterhead PDFs
#   ->  Planet_User_Guide_R2.pdf
#
# Fully isolated: only ever touches the --settings=config.settings_demo
# instance (db.demo.sqlite3 + media-demo/ + port 8001). The live team-review
# server on :8000 and its db.sqlite3 are never touched.
#
#   bash regenerate.sh
set -euo pipefail
cd "$(dirname "$0")"
GUIDE="$PWD"
BACKEND="$(cd ../backend && pwd)"
PY="$BACKEND/.venv/Scripts/python.exe"
PORT=8001

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

# --- 0. never let this run against :8000 -------------------------------
kill_8001() {
  local pid
  pid=$(netstat -ano 2>/dev/null | grep ":$PORT" | grep LISTENING \
        | awk '{print $5}' | head -1 || true)
  [ -n "${pid:-}" ] && taskkill //PID "$pid" //F >/dev/null 2>&1 || true
}

say "1/5  Rebuild isolated demo database + seed"
bash "$BACKEND/regen_demo.sh"

say "2/5  (Re)start demo server on 127.0.0.1:$PORT"
kill_8001; sleep 1
( cd "$BACKEND" && DJANGO_SETTINGS_MODULE=config.settings_demo \
    "$PY" manage.py runserver 127.0.0.1:$PORT --noreload \
    > "$GUIDE/_server.log" 2>&1 & )
for i in $(seq 1 20); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/api/v1/health" && break
  sleep 0.5
done
echo "   server up"

say "3/5  Capture screenshots (Playwright)"
( cd "$GUIDE" && rm -f screenshots/[0-9]*.png && node capture.mjs )

say "4/5  Render letterhead PDFs to PNG"
( cd "$BACKEND" && rm -f "$GUIDE"/screenshots/pdf-*.png && \
    "$PY" manage.py render_pdfs --settings=config.settings_demo )

say "5/5  Build Planet_User_Guide_R2.pdf"
( cd "$GUIDE" && "$PY" build_guide.py )

# Publish to the live team-review server's media dir so the existing shared
# tunnel link serves the latest build. This copies ONE static file — it does
# not touch the live database or restart the :8000 process.
PUBLISH="$BACKEND/media/guide"
mkdir -p "$PUBLISH"
cp "$GUIDE/Planet_User_Guide_R2.pdf" "$PUBLISH/Planet_User_Guide_R2.pdf"
echo "   published to $PUBLISH (served at <tunnel>/media/guide/Planet_User_Guide_R2.pdf)"

kill_8001
say "Done — $GUIDE/Planet_User_Guide_R2.pdf"

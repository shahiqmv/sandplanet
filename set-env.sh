#!/bin/sh
# Set (or replace) one variable in .env without opening an editor.
#
#   bash set-env.sh SHIPSGO_API_KEY 'your-shipsgo-token'
#   bash set-env.sh SHIPSGO_WEBHOOK_SECRET 'the-secret-key'
#
# Wrap the value in single quotes so the shell doesn't mangle it. Re-running
# with the same KEY overwrites the old value (never duplicates a line).
# After setting secrets, run `bash update.sh` so the app picks them up.
set -e
cd "$(dirname "$0")"

KEY="$1"
VALUE="$2"
if [ -z "$KEY" ] || [ $# -lt 2 ]; then
  echo "usage: bash set-env.sh KEY VALUE"
  echo "example: bash set-env.sh SHIPSGO_API_KEY 'abc123'"
  exit 1
fi

touch .env
# drop any existing line for this exact key, then append the new value
grep -v "^${KEY}=" .env > .env.tmp 2>/dev/null || true
printf '%s=%s\n' "$KEY" "$VALUE" >> .env.tmp
mv .env.tmp .env
chmod 600 .env 2>/dev/null || true
echo "OK — ${KEY} set in .env. Run 'bash update.sh' to apply."

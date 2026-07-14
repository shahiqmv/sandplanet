#!/bin/sh
# Update the live app (M8): pull the latest code and redeploy.
# Run on the droplet:   bash update.sh
#
# Safe to run anytime — your database (Docker volume) and uploaded files
# (Spaces) are untouched; only the app code + frontend are rebuilt.
#
# Hardened (2026-07-14) so a small droplet doesn't drop your console mid-build:
#   * creates a 2G swap file the first time (the frontend/vite build is
#     memory-heavy; without swap the OOM killer can kill your SSH/console),
#   * builds with BuildKit (faster, lower memory),
#   * runs the pull+build+restart DETACHED with a log, so losing the console
#     no longer kills the deploy — reconnect and `tail -f deploy.log`.
set -e
cd "$(dirname "$0")"

DEPLOY_LOG="$(pwd)/deploy.log"

# Faster, lower-memory image builds.
export DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1

run_deploy() {
  echo "==> $(date '+%Y-%m-%d %H:%M:%S') Pulling latest code…"
  git pull
  echo "==> Rebuilding and restarting (BuildKit)…"
  docker compose -f docker-compose.prod.yml up -d --build
  echo "==> Status:"
  docker compose -f docker-compose.prod.yml ps
  echo "Done."
}

# The detached worker re-invokes the script with --run; it must NOT try to set
# up swap or re-detach — it just does the work.
if [ "$1" = "--run" ]; then
  run_deploy
  exit 0
fi

maybe_sudo() {
  if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

ensure_swap() {
  swap_lines=$(grep -c '^/' /proc/swaps 2>/dev/null || echo 0)
  if [ "$swap_lines" -gt 0 ] || [ -f /swapfile ]; then
    return 0                              # swap already present — nothing to do
  fi
  echo "==> No swap found — creating a 2G swap file so the build can't OOM the"
  echo "    console (one-time)…"
  ( set -e
    maybe_sudo fallocate -l 2G /swapfile 2>/dev/null \
      || maybe_sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    maybe_sudo chmod 600 /swapfile
    maybe_sudo mkswap /swapfile
    maybe_sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab 2>/dev/null \
      || echo '/swapfile none swap sw 0 0' | maybe_sudo tee -a /etc/fstab >/dev/null
  ) && echo "    swap ready." \
    || echo "!! Could not create swap automatically — the deploy will still run;"
}

ensure_swap

# Run the deploy detached (setsid + nohup) so a dropped console can't kill it,
# then follow the log. Ctrl-C or a lost console only stops the tail.
: > "$DEPLOY_LOG"
echo "==> Deploying in the background — safe to lose the console."
echo "    Log: $DEPLOY_LOG   (reconnect any time and: tail -f deploy.log)"
setsid nohup sh "$0" --run >"$DEPLOY_LOG" 2>&1 &
deploy_pid=$!
echo "==> Deploy PID: $deploy_pid"
sleep 1
tail -f --pid="$deploy_pid" "$DEPLOY_LOG" 2>/dev/null || tail -n +1 "$DEPLOY_LOG"
echo "==> Deploy process finished (full log in $DEPLOY_LOG)."

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
  # Caddy's config is a single-file bind mount, and `git pull` REPLACES the
  # file rather than editing it. Docker binds the old inode, so the running
  # container keeps serving the config it started with — a `caddy reload`
  # dutifully re-reads the stale file and reports success. Recreating the
  # container is the only thing that picks up a Caddyfile change (found the
  # hard way when the camera relay's routes silently never appeared,
  # 2026-08-12).
  echo "==> Recreating caddy so Caddyfile changes take effect…"
  docker compose -f docker-compose.prod.yml up -d --force-recreate caddy
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

ensure_crons() {
  # Every scheduled job this app depends on, installed idempotently by
  # marker comment. Written after the conformance audit (2026-08-28) found
  # the compliance alerts running on the server but recorded NOWHERE in the
  # repo — a rebuilt droplet would have silently lost permit expiry, bond
  # expiry, onboarding clocks, procurement risk and meeting reminders. And
  # the backup, which had never been scheduled at all.
  APP_DIR="$(pwd)"
  C="cd $APP_DIR && docker compose -f docker-compose.prod.yml exec -T web python manage.py"

  add_cron() {   # $1 marker  $2 schedule  $3 command  $4 human name
    if crontab -l 2>/dev/null | grep -qF "$1"; then return 0; fi
    echo "==> Scheduling $4…"
    ( crontab -l 2>/dev/null; echo "$1"; echo "$2 $3" ) | crontab - \
      && echo "    $4 scheduled." \
      || echo "!! Could not install cron for $4 — add by hand: $2 $3"
  }

  add_cron "# planet-backup" "20 2 * * *" \
    "$APP_DIR/deploy/backup.sh >> /var/log/planet-backup.log 2>&1" \
    "the nightly database backup (02:20, off-server copy)"
  add_cron "# planet-backup-verify" "40 3 * * 0" \
    "$APP_DIR/deploy/backup.sh --verify >> /var/log/planet-backup.log 2>&1" \
    "the weekly restore test (Sunday 03:40)"
  add_cron "# planet-poll-trackings" "0 6 * * *" \
    "$C poll_trackings >> $APP_DIR/tracking-poll.log 2>&1" \
    "the daily shipment-tracking poll"
  add_cron "# planet-onboarding-clocks" "0 6 * * *" \
    "$C onboarding_clocks >> /var/log/onboarding_clocks.log 2>&1" \
    "onboarding medical / visa expiry alerts"
  add_cron "# planet-training-expiry" "45 6 * * *" \
    "$C training_expiry >> /var/log/training_expiry.log 2>&1" \
    "training/competency expiry reminders"

  add_cron "# planet-bonds-expiry" "30 6 * * *" \
    "$C bonds_expiry >> /var/log/bonds_expiry.log 2>&1" \
    "bond and insurance expiry alerts"
  add_cron "# planet-procurement-risk" "0 7 * * *" \
    "$C procurement_risk >> /var/log/procurement_risk.log 2>&1" \
    "procurement late-risk alerts"
  add_cron "# planet-procurement-digest" "5 7 * * 1" \
    "$C procurement_risk --digest >> /var/log/procurement_risk.log 2>&1" \
    "the weekly procurement digest"
  add_cron "# planet-meeting-reminders" "*/15 * * * *" \
    "$C meeting_reminders >> /var/log/meeting_reminders.log 2>&1" \
    "meeting reminders"
}

ensure_crons

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

#!/usr/bin/env bash
# Nightly database backup — local copy, off-server copy, and a real restore
# test. Written after the conformance audit (2026-08-28) found four ad-hoc
# hand-made dumps and no automation at all.
#
#   deploy/backup.sh              take a backup (cron does this nightly)
#   deploy/backup.sh --verify     take one, then prove it restores
#   deploy/backup.sh --test-only  restore the newest existing dump and stop
#
# A backup nobody has restored is a rumour, so --verify restores the dump
# into a scratch database inside the Postgres container and counts its rows.
set -euo pipefail

cd /root/sandplanet
COMPOSE="docker compose -f docker-compose.prod.yml"
DIR=/root/backups
KEEP_LOCAL_DAYS=14
KEEP_REMOTE_DAYS=35
STAMP=$(date +%Y%m%d-%H%M)
NAME="planet-${STAMP}.sql.gz"
mkdir -p "$DIR"

# Read the two values we need WITHOUT sourcing .env — a password containing
# something like $8 would be expanded by the shell (and under `set -u` kills
# the script outright).
env_val() { sed -n "s/^$1=//p" ./.env | head -1 | tr -d '"'"'"'"' ; }
PGUSER_="$(env_val POSTGRES_USER)"; PGUSER_="${PGUSER_:-planet}"
PGDB_="$(env_val POSTGRES_DB)"; PGDB_="${PGDB_:-planet}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

restore_test() {
  local file="$1"
  local scratch="restore_test_${STAMP//-/_}"   # no hyphens in a DB name
  log "restore test: loading $(basename "$file") into $scratch"
  $COMPOSE exec -T db psql -U "$PGUSER_" -d postgres \
      -c "DROP DATABASE IF EXISTS $scratch;" >/dev/null
  $COMPOSE exec -T db psql -U "$PGUSER_" -d postgres \
      -c "CREATE DATABASE $scratch;" >/dev/null
  if ! gunzip -c "$file" | $COMPOSE exec -T db psql -q -v ON_ERROR_STOP=1 \
        -U "$PGUSER_" -d "$scratch" >/dev/null 2>/tmp/restore_err; then
    log "RESTORE FAILED — see /tmp/restore_err"
    tail -5 /tmp/restore_err
    $COMPOSE exec -T db psql -U "$PGUSER_" -d postgres \
        -c "DROP DATABASE IF EXISTS $scratch;" >/dev/null || true
    return 1
  fi
  local docs emps
  docs=$($COMPOSE exec -T db psql -tAc \
      "SELECT count(*) FROM core_document;" -U "$PGUSER_" -d "$scratch")
  emps=$($COMPOSE exec -T db psql -tAc \
      "SELECT count(*) FROM core_employee;" -U "$PGUSER_" -d "$scratch")
  $COMPOSE exec -T db psql -U "$PGUSER_" -d postgres \
      -c "DROP DATABASE IF EXISTS $scratch;" >/dev/null
  log "restore OK — ${docs// /} documents, ${emps// /} employees recovered"
}

if [ "${1:-}" = "--test-only" ]; then
  newest=$(ls -t "$DIR"/planet-*.sql.gz 2>/dev/null | head -1 || true)
  [ -n "$newest" ] || { log "no backup to test"; exit 1; }
  restore_test "$newest"
  exit $?
fi

log "dumping $PGDB_"
$COMPOSE exec -T db pg_dump -U "$PGUSER_" "$PGDB_" | gzip -9 > "$DIR/$NAME"
SIZE=$(stat -c%s "$DIR/$NAME")
if [ "$SIZE" -lt 100000 ]; then
  log "ABORT — dump is only ${SIZE} bytes, refusing to keep it"
  rm -f "$DIR/$NAME"
  exit 1
fi
log "local copy $DIR/$NAME ($((SIZE / 1048576)) MB)"

# Off-server copy — a backup on the machine it protects is not a backup.
if ! $COMPOSE exec -T web python manage.py backup_upload \
        --name "$NAME" --keep-days "$KEEP_REMOTE_DAYS" < "$DIR/$NAME"; then
  log "WARNING: off-server upload failed — local copy kept"
fi

find "$DIR" -name 'planet-*.sql.gz' -mtime +$KEEP_LOCAL_DAYS -delete
log "local copies: $(ls -1 "$DIR"/planet-*.sql.gz 2>/dev/null | wc -l)"

if [ "${1:-}" = "--verify" ]; then
  restore_test "$DIR/$NAME"
fi
log "done"

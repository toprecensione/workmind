#!/usr/bin/env bash
# WorkMind — nightly PostgreSQL backup
# Keeps 30 daily dumps + 12 monthly dumps.
# Cron: 02:30 every night (systemd timer or crontab).

set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-$HOME/backups}
DB_NAME=workmind
DB_USER=workmind
DB_HOST=localhost
DB_PORT=5432
KEEP_DAILY=30
KEEP_MONTHLY=12

DATE=$(date +%Y-%m-%d)
MONTH=$(date +%Y-%m)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"

DUMP_FILE="$BACKUP_DIR/daily/workmind_${TIMESTAMP}.pgdump"

echo "[$(date -Iseconds)] Starting backup → $DUMP_FILE"

PGPASSWORD="Wm2026Bender!Pg" pg_dump   -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"   -Fc --no-password   "$DB_NAME" > "$DUMP_FILE"

SIZE=$(du -sh "$DUMP_FILE" | cut -f1)
echo "[$(date -Iseconds)] Dump done. Size: $SIZE"

# Keep monthly copy on the 1st of each month
DAY_OF_MONTH=$(date +%-d)
if [ "$DAY_OF_MONTH" -eq 1 ]; then
  MONTHLY_FILE="$BACKUP_DIR/monthly/workmind_${MONTH}.pgdump"
  cp "$DUMP_FILE" "$MONTHLY_FILE"
  echo "[$(date -Iseconds)] Monthly copy → $MONTHLY_FILE"
fi

# Prune old daily backups
find "$BACKUP_DIR/daily" -name *.pgdump -mtime +${KEEP_DAILY} -delete || true
# Prune old monthly backups (keep last N months)
ls -1t "$BACKUP_DIR/monthly"/*.pgdump 2>/dev/null | tail -n +$((KEEP_MONTHLY + 1)) | xargs -r rm -- || true
echo "[$(date -Iseconds)] Backup complete."

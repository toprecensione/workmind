#!/bin/bash
# WorkMind — PostgreSQL Backup Script
# Creates a compressed pg_dump in /app/data/backups/
# Schedule with: 0 2 * * * /path/to/backup_pg.sh

set -euo pipefail

BACKUP_DIR="/app/data/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/workmind_$TIMESTAMP.sql.gz"
MAX_BACKUPS=7  # Keep last 7 days

mkdir -p "$BACKUP_DIR"

# Load env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
[ -f "$ROOT_DIR/.env" ] && export $(grep -E '^(POSTGRES_|DATABASE_URL)' "$ROOT_DIR/.env" | xargs)

echo "[backup] Starting PostgreSQL backup: $BACKUP_FILE"

# Run pg_dump inside the postgres container
docker exec workmind-postgres pg_dump \
    -U "${POSTGRES_USER:-workmind}" \
    -d "${POSTGRES_DB:-workmind}" \
    --no-owner \
    --no-acl \
    | gzip > "$BACKUP_FILE"

echo "[backup] Backup complete: $(du -sh "$BACKUP_FILE" | cut -f1)"

# Cleanup old backups
echo "[backup] Cleaning up backups older than $MAX_BACKUPS days..."
find "$BACKUP_DIR" -name "workmind_*.sql.gz" -mtime +$MAX_BACKUPS -delete

echo "[backup] Done. Remaining backups:"
ls -lh "$BACKUP_DIR"/workmind_*.sql.gz 2>/dev/null || echo "  (none)"

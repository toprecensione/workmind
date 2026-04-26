#!/bin/bash
# WorkMind — Run Alembic migrations
# Usage: ./scripts/migrate.sh [revision]
# Default: upgrade to head

set -euo pipefail

REVISION="${1:-head}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[migrate] Running Alembic migrations to: $REVISION"
echo "[migrate] Working directory: $ROOT_DIR/workmind-api"

cd "$ROOT_DIR/workmind-api"

# Check .env exists
if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "[migrate] ERROR: .env file not found at $ROOT_DIR/.env"
    echo "[migrate] Copy .env.example to .env and fill required values."
    exit 1
fi

# Export DATABASE_URL from .env
export $(grep -E '^DATABASE_URL=' "$ROOT_DIR/.env" | head -1)

if [ -z "${DATABASE_URL:-}" ]; then
    echo "[migrate] ERROR: DATABASE_URL not found in .env"
    exit 1
fi

echo "[migrate] DATABASE_URL: ${DATABASE_URL%:*}:***@${DATABASE_URL##*@}"  # mask password

alembic upgrade "$REVISION"

echo "[migrate] Done."

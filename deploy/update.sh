#!/usr/bin/env bash
# WorkMind 3 — Zero-downtime update script
# Run as: bash deploy/update.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"
API_DIR="$PROJECT_DIR/workmind-api"
FRONTEND_DIR="$PROJECT_DIR/workmind-frontend"

echo "==> WorkMind 3 update $(date '+%Y-%m-%d %H:%M:%S')"

# 1. Pull latest code
cd "$PROJECT_DIR"
git pull --ff-only

# 2. Backend: install new dependencies
"$VENV/bin/pip" install -q -e "$API_DIR"

# 3. Run Alembic migrations
cd "$API_DIR"
"$VENV/bin/alembic" upgrade head

# 4. Frontend: rebuild if sources changed
cd "$FRONTEND_DIR"
if command -v npm &>/dev/null; then
    npm ci --silent
    npm run build
fi

# 5. Reload services (graceful)
systemctl reload-or-restart workmind-api
systemctl restart workmind-celery
systemctl restart workmind-celery-beat

echo "==> Update complete."
systemctl status workmind-api --no-pager -l | tail -5

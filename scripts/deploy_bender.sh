#!/bin/bash
# WorkMind v2 — Deploy script for Bender (Ubuntu/Debian)
# Run once on a fresh Bender server to bootstrap the entire stack.
#
# Prerequisites on Bender:
#   - Docker + Docker Compose v2 installed
#   - Tailscale connected (workmind-bender.tail898ef4.ts.net)
#   - Tailscale HTTPS certs enabled in admin console
#   - This repo cloned to /opt/workmind-v2/
#
# Usage:
#   sudo bash scripts/deploy_bender.sh

set -euo pipefail
cd "$(dirname "$0")/.."

DEPLOY_DIR="/opt/workmind-v2"
TAILSCALE_HOST="workmind-bender.tail898ef4.ts.net"
CERT_DIR="/var/lib/tailscale/certs"

echo "=============================================="
echo "  WorkMind v2 — Bender Deployment"
echo "  $(date)"
echo "=============================================="

# ── 1. Check prerequisites ────────────────────────────────────────────────────
echo ""
echo "[1/8] Checking prerequisites..."

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose v2 not installed"; exit 1; }
command -v tailscale >/dev/null 2>&1 || { echo "ERROR: Tailscale not installed"; exit 1; }

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
if [ -z "$TAILSCALE_IP" ]; then
    echo "ERROR: Tailscale not connected. Run: sudo tailscale up"
    exit 1
fi
echo "  Tailscale IP: $TAILSCALE_IP"

# ── 2. TLS certificate ────────────────────────────────────────────────────────
echo ""
echo "[2/8] Obtaining Tailscale TLS certificate..."

if [ ! -f "$CERT_DIR/$TAILSCALE_HOST.crt" ]; then
    sudo tailscale cert "$TAILSCALE_HOST"
    echo "  Certificate obtained."
else
    echo "  Certificate already exists."
    # Refresh if older than 80 days
    CERT_AGE=$(( ($(date +%s) - $(stat -c %Y "$CERT_DIR/$TAILSCALE_HOST.crt")) / 86400 ))
    if [ "$CERT_AGE" -gt 80 ]; then
        echo "  Certificate is $CERT_AGE days old — renewing..."
        sudo tailscale cert "$TAILSCALE_HOST"
    fi
fi

# ── 3. Environment file ───────────────────────────────────────────────────────
echo ""
echo "[3/8] Checking .env configuration..."

if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found."
    echo "  Copy .env.example to .env and fill all required values:"
    echo "    cp .env.example .env && nano .env"
    exit 1
fi

# Verify required vars
REQUIRED_VARS=(POSTGRES_PASSWORD REDIS_PASSWORD WORKMIND_SECRET_KEY DEEPSEEK_API_KEY ANTHROPIC_API_KEY)
MISSING=0
for var in "${REQUIRED_VARS[@]}"; do
    VALUE=$(grep -E "^${var}=" .env | cut -d= -f2-)
    if [ -z "$VALUE" ]; then
        echo "  ERROR: $var is not set in .env"
        MISSING=1
    fi
done
[ $MISSING -eq 1 ] && exit 1
echo "  All required env vars present."

# ── 4. UFW firewall ───────────────────────────────────────────────────────────
echo ""
echo "[4/8] Configuring UFW firewall..."

if command -v ufw >/dev/null 2>&1; then
    sudo ufw --force reset
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow ssh
    sudo ufw allow in on tailscale0
    sudo ufw --force enable
    echo "  UFW configured: deny all, allow SSH + tailscale0."
else
    echo "  WARNING: UFW not found — firewall not configured."
fi

# ── 5. Build images ───────────────────────────────────────────────────────────
echo ""
echo "[5/8] Building Docker images..."
docker compose build --parallel

# ── 6. Start infrastructure ───────────────────────────────────────────────────
echo ""
echo "[6/8] Starting PostgreSQL and Redis..."
docker compose up -d postgres redis

echo "  Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    docker compose exec postgres pg_isready -U workmind -d workmind >/dev/null 2>&1 && break
    sleep 2
done
echo "  PostgreSQL ready."

# ── 7. Run migrations ─────────────────────────────────────────────────────────
echo ""
echo "[7/8] Running database migrations..."
docker compose run --rm workmind-api alembic upgrade head
echo "  Migrations complete."

# ── 8. Start all services ─────────────────────────────────────────────────────
echo ""
echo "[8/8] Starting all services..."
docker compose up -d

echo ""
echo "  Waiting for API to be healthy..."
for i in {1..20}; do
    STATUS=$(curl -sf "http://localhost:8000/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
    [ "$STATUS" = "ok" ] && break
    sleep 3
done

if [ "$STATUS" = "ok" ]; then
    echo "  API is healthy."
else
    echo "  WARNING: API health check did not return 'ok'. Check logs:"
    echo "    docker compose logs workmind-api"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Deployment complete!"
echo ""
echo "  WorkMind v2 is accessible at:"
echo "  https://$TAILSCALE_HOST"
echo ""
echo "  Quick checks:"
echo "    curl https://$TAILSCALE_HOST/health"
echo "    curl https://$TAILSCALE_HOST/health/ready"
echo ""
echo "  Monitor services:"
echo "    docker compose ps"
echo "    docker compose logs -f workmind-api"
echo "    https://$TAILSCALE_HOST/flower/   (Celery)"
echo ""
echo "  Run data migration from v1:"
echo "    python scripts/seed_from_json.py --source-dir /opt/workmind/data"
echo "=============================================="

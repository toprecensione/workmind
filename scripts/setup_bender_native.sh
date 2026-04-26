#!/usr/bin/env bash
# =============================================================================
# WorkMind v2 — One-shot setup script for Bender (Ubuntu 25.10, no Docker)
# REQUIRES SUDO. Run once:
#   sudo bash ~/workmind-v2/scripts/setup_bender_native.sh
#
# What it does:
#   1. Install PostgreSQL 17 + pgvector extension
#   2. Create workmind DB + user
#   3. Build SvelteKit frontend (npm)
#   4. Create Python venv + install dependencies
#   5. Run Alembic migrations (0001 → 0003)
#   6. Seed MEDIC org + users
#   7. Install systemd service + nginx snippet
#   8. Reload nginx + start service
# =============================================================================
set -euo pipefail

DEPLOY_DIR="${HOME}/workmind-v2"
VENV_DIR="${DEPLOY_DIR}/.venv"
STATIC_DIR="/var/www/medic"
NGINX_SNIPPET="/etc/nginx/snippets/workmind-v2.conf"
SERVICE_FILE="/etc/systemd/system/workmind-v2.service"
LOG_DIR="/var/log/workmind-v2"
DB_NAME="workmind"
DB_USER="workmind"
# Password pulled from .env
DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${DEPLOY_DIR}/.env" | cut -d'=' -f2)

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[v2-setup]${NC} $1"; }
warn() { echo -e "${YELLOW}[v2-setup WARN]${NC} $1"; }
err()  { echo -e "${RED}[v2-setup ERROR]${NC} $1"; exit 1; }

[[ $(id -u) -eq 0 ]] || err "Run with sudo: sudo bash $0"
[[ -f "${DEPLOY_DIR}/.env" ]] || err ".env not found in ${DEPLOY_DIR}. Copy .env.example first."

# ── 1. PostgreSQL ─────────────────────────────────────────────────────────────
log "Installing PostgreSQL 17 + pgvector..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    postgresql postgresql-contrib postgresql-17-pgvector \
    libpq-dev build-essential python3-dev 2>/dev/null

systemctl enable --now postgresql

log "Creating DB user and database..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
  ELSE
    ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${DB_NAME}' WHERE NOT EXISTS
  (SELECT FROM pg_database WHERE datname = '${DB_NAME}') \gexec
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};
SQL

# ── 2. Frontend build ─────────────────────────────────────────────────────────
log "Building SvelteKit frontend..."
cd "${DEPLOY_DIR}/workmind-frontend"
npm install --silent
npm run build

mkdir -p "${STATIC_DIR}"
cp -r build/. "${STATIC_DIR}/"
log "Frontend deployed to ${STATIC_DIR}"

# ── 3. Python venv ────────────────────────────────────────────────────────────
log "Creating Python virtual environment..."
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -e "${DEPLOY_DIR}/workmind-api"
# passlib/bcrypt for seed script
"${VENV_DIR}/bin/pip" install --quiet passlib[bcrypt]

# ── 4. Alembic migrations ─────────────────────────────────────────────────────
log "Running Alembic migrations..."
cd "${DEPLOY_DIR}/workmind-api"
set -a; source "${DEPLOY_DIR}/.env"; set +a
"${VENV_DIR}/bin/alembic" upgrade head

# ── 5. Seed MEDIC ─────────────────────────────────────────────────────────────
log "Seeding MEDIC org + users..."
"${VENV_DIR}/bin/python" "${DEPLOY_DIR}/scripts/seed_medic.py"

# ── 6. Systemd service ────────────────────────────────────────────────────────
log "Installing systemd service..."
mkdir -p "${LOG_DIR}"
cat > "${SERVICE_FILE}" <<UNIT
[Unit]
Description=WorkMind v2 API (FastAPI)
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=exec
User=${SUDO_USER:-$(logname)}
WorkingDirectory=${DEPLOY_DIR}/workmind-api
EnvironmentFile=${DEPLOY_DIR}/.env
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --log-level info
Restart=on-failure
RestartSec=5s
StandardOutput=append:${LOG_DIR}/api.log
StandardError=append:${LOG_DIR}/api.log

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable workmind-v2
systemctl restart workmind-v2

# ── 7. Nginx snippet ──────────────────────────────────────────────────────────
log "Configuring nginx for MEDIC frontend + API..."
mkdir -p /etc/nginx/snippets

cat > "${NGINX_SNIPPET}" <<'NGINX'
# WorkMind v2 MEDIC — API + static frontend
# Include this in your server block with: include snippets/workmind-v2.conf;

# FastAPI
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}

# SvelteKit immutable assets (1 year cache)
location /_app/immutable/ {
    root /var/www/medic;
    expires 1y;
    add_header Cache-Control "public, immutable";
}

# SvelteKit SPA root — serve static, fallback to index.html
location / {
    root /var/www/medic;
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "no-cache";
}
NGINX

# ── 8. Update existing nginx server block ─────────────────────────────────────
NGINX_SITE="/etc/nginx/sites-enabled/workmind"
if [[ -f "${NGINX_SITE}" ]]; then
    # Backup and replace the location / block to include our snippet
    cp "${NGINX_SITE}" "${NGINX_SITE}.bak.$(date +%s)"

    # Replace the existing location / { ... } block with our include
    python3 - "${NGINX_SITE}" <<'PYEOF'
import re, sys
path = sys.argv[1]
text = open(path).read()

# Remove all existing location blocks (replace with our snippet)
cleaned = re.sub(r'location\s+[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', '', text, flags=re.DOTALL)
# Add include before closing brace of server block
cleaned = cleaned.rstrip().rstrip('}').rstrip() + '\n\n    include snippets/workmind-v2.conf;\n}\n'
open(path, 'w').write(cleaned)
print("nginx config updated")
PYEOF

    nginx -t && systemctl reload nginx
    log "nginx updated and reloaded"
else
    warn "nginx site file not found at ${NGINX_SITE}. Add manually:"
    warn "  include snippets/workmind-v2.conf;"
fi

log ""
log "═══════════════════════════════════════════════════"
log "  WorkMind v2 — MEDIC interface deployed!"
log "═══════════════════════════════════════════════════"
log "  URL:     https://workmind-bender.tail898ef4.ts.net"
log "  Login:   medic1@ideasito.it / Medic2024!"
log "  API:     https://workmind-bender.tail898ef4.ts.net/api/"
log "  Logs:    journalctl -u workmind-v2 -f"
log "═══════════════════════════════════════════════════"

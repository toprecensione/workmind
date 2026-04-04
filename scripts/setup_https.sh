#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# WorkMind — HTTPS + Gunicorn + Nginx Setup
# Run as root: sudo bash scripts/setup_https.sh
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

INSTALL_DIR="${WORKMIND_INSTALL_DIR:-/home/emanuele/workmind}"
VENV="${INSTALL_DIR}/venv"

GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[WorkMind]${NC} $1"; }

# ── Self-signed SSL cert ──────────────────────────────────────────────
log "Generating self-signed SSL certificate..."
mkdir -p /etc/ssl/workmind
openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout /etc/ssl/workmind/workmind.key \
    -out /etc/ssl/workmind/workmind.crt \
    -subj "/C=IT/ST=Italy/O=WorkMind/CN=workmind.local" \
    2>/dev/null
chmod 600 /etc/ssl/workmind/workmind.key

# ── Install nginx ─────────────────────────────────────────────────────
log "Installing nginx..."
apt-get install -y -qq nginx > /dev/null 2>&1

# ── Copy config ───────────────────────────────────────────────────────
log "Configuring nginx..."
cp "${INSTALL_DIR}/scripts/nginx_workmind.conf" /etc/nginx/sites-available/workmind
ln -sf /etc/nginx/sites-available/workmind /etc/nginx/sites-enabled/workmind
rm -f /etc/nginx/sites-enabled/default
nginx -t

# ── Install gunicorn ──────────────────────────────────────────────────
log "Installing gunicorn..."
"${VENV}/bin/pip" install gunicorn > /dev/null 2>&1

# ── Update systemd service ───────────────────────────────────────────
log "Updating systemd service for gunicorn..."
cat > /etc/systemd/system/workmind.service << UNIT
[Unit]
Description=WorkMind Operational Assistant
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=emanuele
Group=emanuele
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${VENV}/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

# ── Reload and restart ───────────────────────────────────────────────
log "Restarting services..."
systemctl daemon-reload
systemctl enable workmind nginx
systemctl restart workmind
systemctl restart nginx

log "HTTPS setup complete!"
log "  UI: https://$(hostname -I | awk '{print $1}')"
log "  Cert: /etc/ssl/workmind/workmind.crt"

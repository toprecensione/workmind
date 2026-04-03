#!/usr/bin/env bash
# =============================================================================
# WorkMind — One-Command Ubuntu Installer
# CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/ORG/workmind/main/scripts/install.sh | bash
#   oppure: cd /opt/workmind && bash scripts/install.sh
#
# Questo script installa:
#   - Python 3.12, pip, venv
#   - Redis server
#   - Driver ODBC per SQL Server
#   - Tailscale VPN
#   - xfreerdp (per RDP capture)
#   - LibreDWG (per DWG → DXF)
#   - antiword (per .doc legacy)
#   - Tutte le dipendenze Python (requirements.txt)
#   - Servizio systemd workmind.service
#   - Logrotate configuration
#   - Cron job per auto-update orario
# =============================================================================

set -euo pipefail

INSTALL_DIR="${WORKMIND_INSTALL_DIR:-/opt/workmind}"
REPO_URL="${WORKMIND_REPO_URL:-}"
BRANCH="${WORKMIND_BRANCH:-main}"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_USER="workmind"
LOG_DIR="/var/log/workmind"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[WorkMind]${NC} $1"; }
warn() { echo -e "${YELLOW}[WorkMind WARN]${NC} $1"; }
err()  { echo -e "${RED}[WorkMind ERROR]${NC} $1"; exit 1; }

# ── Checks ────────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || err "Questo script richiede root. Usa: sudo bash install.sh"

log "WorkMind Installer — Ubuntu 22.04+"
log "Directory di installazione: ${INSTALL_DIR}"

# ── System packages ──────────────────────────────────────────────────────────
log "Aggiornamento pacchetti di sistema..."
apt-get update -qq

log "Installazione dipendenze di sistema..."
apt-get install -y -qq \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    git curl wget unzip \
    redis-server \
    cifs-utils \
    antiword \
    xvfb \
    freerdp2-x11 \
    build-essential \
    libssl-dev libffi-dev \
    2>/dev/null || {
    # Fallback per Ubuntu 22.04 senza python3.12
    warn "Python 3.12 non disponibile, uso Python 3.10"
    apt-get install -y -qq \
        python3 python3-venv python3-dev python3-pip \
        git curl wget unzip \
        redis-server \
        cifs-utils \
        antiword \
        xvfb \
        freerdp2-x11 \
        build-essential \
        libssl-dev libffi-dev
}

# ── ODBC Driver per SQL Server ─────────────────────────────────────────────
if ! dpkg -l | grep -q msodbcsql; then
    log "Installazione ODBC Driver 18 per SQL Server..."
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/22.04/prod jammy main" > /etc/apt/sources.list.d/mssql-release.list
    apt-get update -qq
    ACCEPT_EULA=Y apt-get install -y -qq msodbcsql18 unixodbc-dev 2>/dev/null || warn "ODBC driver non installato (non critico)"
else
    log "ODBC Driver per SQL Server già installato"
fi

# ── Tailscale VPN ────────────────────────────────────────────────────────────
if ! command -v tailscale &>/dev/null; then
    log "Installazione Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh 2>/dev/null || warn "Tailscale non installato (non critico)"
else
    log "Tailscale già installato"
fi

# ── LibreDWG (dwg2dxf) ───────────────────────────────────────────────────────
if ! command -v dwg2dxf &>/dev/null; then
    apt-get install -y -qq libredwg-tools 2>/dev/null || warn "LibreDWG non disponibile nei repo (non critico per DXF)"
fi

# ── Redis ─────────────────────────────────────────────────────────────────────
log "Configurazione Redis..."
systemctl enable redis-server
systemctl start redis-server

# ── Utente di sistema ─────────────────────────────────────────────────────────
if ! id "${SERVICE_USER}" &>/dev/null; then
    log "Creazione utente di sistema: ${SERVICE_USER}"
    useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

# ── Clone / Pull repository ──────────────────────────────────────────────────
if [ -d "${INSTALL_DIR}/.git" ]; then
    log "Repository esistente — aggiornamento..."
    cd "${INSTALL_DIR}"
    git fetch origin "${BRANCH}"
    git reset --hard "origin/${BRANCH}"
elif [ -n "${REPO_URL}" ]; then
    log "Clone repository da ${REPO_URL}..."
    git clone --branch "${BRANCH}" "${REPO_URL}" "${INSTALL_DIR}"
else
    log "Nessun REPO_URL — uso directory corrente"
    INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

cd "${INSTALL_DIR}"

# ── Python Virtual Environment ────────────────────────────────────────────────
log "Creazione virtual environment Python..."
PYTHON_BIN=$(command -v python3.12 || command -v python3)
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

log "Installazione dipendenze Python..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ── Directory di lavoro ───────────────────────────────────────────────────────
log "Creazione directory di lavoro..."
mkdir -p "${INSTALL_DIR}"/{data,reports,backups,snapshots,logs}
mkdir -p "${INSTALL_DIR}/data/rdp_screenshots"
mkdir -p "${LOG_DIR}"

# ── .env file ─────────────────────────────────────────────────────────────────
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    log "Copio .env.example → .env (da configurare manualmente)"
    cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
    chmod 600 "${INSTALL_DIR}/.env"
fi

# ── company.yaml ──────────────────────────────────────────────────────────────
if [ ! -f "${INSTALL_DIR}/config/company.yaml" ]; then
    log "Copio company.yaml.example → company.yaml (da configurare manualmente)"
    cp "${INSTALL_DIR}/config/company.yaml.example" "${INSTALL_DIR}/config/company.yaml"
fi

# ── Permessi ──────────────────────────────────────────────────────────────────
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${LOG_DIR}"
chmod 700 "${INSTALL_DIR}/.env"

# ── Systemd service ──────────────────────────────────────────────────────────
log "Creazione servizio systemd..."
cat > /etc/systemd/system/workmind.service <<UNIT
[Unit]
Description=WorkMind Operational Assistant
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${VENV_DIR}/bin/python main.py
Restart=on-failure
RestartSec=30
StartLimitBurst=5
StartLimitIntervalSec=300
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR} ${LOG_DIR}
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable workmind.service

# ── Logrotate ─────────────────────────────────────────────────────────────────
log "Configurazione logrotate..."
cat > /etc/logrotate.d/workmind <<LOGROTATE
${INSTALL_DIR}/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}

${LOG_DIR}/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

# ── Cron: auto-update orario ──────────────────────────────────────────────────
log "Configurazione cron per auto-update..."
CRON_LINE="0 * * * * ${SERVICE_USER} cd ${INSTALL_DIR} && ${VENV_DIR}/bin/python -c 'from updater import AutoUpdater; AutoUpdater().check_and_update()' >> ${LOG_DIR}/auto_update.log 2>&1"
echo "${CRON_LINE}" > /etc/cron.d/workmind-update
chmod 644 /etc/cron.d/workmind-update

# ── Xvfb per RDP headless ────────────────────────────────────────────────────
log "Configurazione Xvfb (display virtuale per RDP)..."
cat > /etc/systemd/system/xvfb.service <<XVFB
[Unit]
Description=Xvfb Virtual Framebuffer
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
User=nobody

[Install]
WantedBy=multi-user.target
XVFB

systemctl daemon-reload
systemctl enable xvfb.service
systemctl start xvfb.service 2>/dev/null || true

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
log "======================================"
log "  WorkMind installato con successo!"
log "======================================"
echo ""
log "Prossimi passi:"
log "  1. Configura ${INSTALL_DIR}/.env con le API key"
log "  2. Configura ${INSTALL_DIR}/config/company.yaml con i dati aziendali"
log "  3. Avvia: sudo systemctl start workmind"
log "  4. Verifica: sudo systemctl status workmind"
log "  5. Chat supervisore: http://$(hostname -I | awk '{print $1}'):7860"
log "  6. Dashboard: http://$(hostname -I | awk '{print $1}'):7861"
echo ""
log "Per Tailscale: sudo tailscale up"
log "Log: journalctl -u workmind -f"
echo ""

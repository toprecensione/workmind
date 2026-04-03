#!/usr/bin/env bash
# =============================================================================
# WorkMind — Ubuntu Node Setup Script
# CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
# =============================================================================
# Usage:
#   chmod +x scripts/setup_ubuntu.sh
#   sudo ./scripts/setup_ubuntu.sh
#
# Environment variables (set before running or in .env):
#   WORKMIND_REPO_URL   — private GitHub HTTPS clone URL (required)
#   WORKMIND_NODE_ID    — unique identifier for this node (required)
#   WORKMIND_NODE_LABEL — human-readable label (optional)
#   GITHUB_TOKEN        — GitHub PAT with repo:read scope (required)
#   WORKMIND_ENV        — production | staging  (default: production)
# =============================================================================

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Validate environment ─────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "Run this script as root (sudo)."
[[ -n "${WORKMIND_REPO_URL:-}" ]] || error "WORKMIND_REPO_URL must be set."
[[ -n "${WORKMIND_NODE_ID:-}"  ]] || error "WORKMIND_NODE_ID must be set."
[[ -n "${GITHUB_TOKEN:-}"      ]] || error "GITHUB_TOKEN must be set."

INSTALL_DIR="${INSTALL_DIR:-/opt/workmind}"
WORKMIND_USER="workmind"
WORKMIND_ENV="${WORKMIND_ENV:-production}"
PYTHON_MIN="3.10"

info "WorkMind Ubuntu Node Setup"
info "Node ID    : ${WORKMIND_NODE_ID}"
info "Install dir: ${INSTALL_DIR}"
info "Environment: ${WORKMIND_ENV}"

# ─── System packages ──────────────────────────────────────────────────────────
info "Updating apt and installing system dependencies…"
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    git curl wget jq \
    build-essential libssl-dev \
    2>/dev/null

PYTHON=$(command -v python3)
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: ${PY_VERSION}"

# ─── Create system user ───────────────────────────────────────────────────────
if ! id "${WORKMIND_USER}" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "${INSTALL_DIR}" "${WORKMIND_USER}"
    info "System user '${WORKMIND_USER}' created."
fi

# ─── Clone repository ─────────────────────────────────────────────────────────
AUTHED_URL="${WORKMIND_REPO_URL/https:\/\//https:\/\/${GITHUB_TOKEN}@}"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Repository already cloned — pulling latest…"
    sudo -u "${WORKMIND_USER}" git -C "${INSTALL_DIR}" pull --ff-only
else
    info "Cloning repository to ${INSTALL_DIR}…"
    git clone "${AUTHED_URL}" "${INSTALL_DIR}"
    chown -R "${WORKMIND_USER}:${WORKMIND_USER}" "${INSTALL_DIR}"
fi

# ─── Python virtual environment ───────────────────────────────────────────────
VENV_DIR="${INSTALL_DIR}/.venv"
info "Creating Python virtual environment…"
sudo -u "${WORKMIND_USER}" $PYTHON -m venv "${VENV_DIR}"
PIP="${VENV_DIR}/bin/pip"

info "Installing Python dependencies…"
sudo -u "${WORKMIND_USER}" "${PIP}" install --upgrade pip -q
sudo -u "${WORKMIND_USER}" "${PIP}" install -r "${INSTALL_DIR}/requirements.txt" -q

# ─── Directory structure ──────────────────────────────────────────────────────
for dir in logs data reports backups snapshots; do
    mkdir -p "${INSTALL_DIR}/${dir}"
    chown "${WORKMIND_USER}:${WORKMIND_USER}" "${INSTALL_DIR}/${dir}"
done

# ─── Environment file ─────────────────────────────────────────────────────────
ENV_FILE="${INSTALL_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    info "Writing environment configuration to ${ENV_FILE}…"
    cat > "${ENV_FILE}" <<EOF
# WorkMind Node Environment — CONFIDENTIAL
WORKMIND_NODE_ID=${WORKMIND_NODE_ID}
WORKMIND_NODE_LABEL=${WORKMIND_NODE_LABEL:-WorkerNode}
WORKMIND_REPO_URL=${WORKMIND_REPO_URL}
WORKMIND_BRANCH=main
WORKMIND_ENV=${WORKMIND_ENV}
GITHUB_TOKEN=${GITHUB_TOKEN}
LOG_LEVEL=INFO
EOF
    chmod 600 "${ENV_FILE}"
    chown "${WORKMIND_USER}:${WORKMIND_USER}" "${ENV_FILE}"
else
    warn "${ENV_FILE} already exists — skipping (edit manually if needed)."
fi

# ─── systemd service ──────────────────────────────────────────────────────────
SYSTEMD_FILE="/etc/systemd/system/workmind.service"
info "Installing systemd service…"
cat > "${SYSTEMD_FILE}" <<EOF
[Unit]
Description=WorkMind AI Operational Assistant
Documentation=https://github.com/private/workmind
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=simple
User=${WORKMIND_USER}
Group=${WORKMIND_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/main.py
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=15s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=workmind

# Hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${INSTALL_DIR}/logs ${INSTALL_DIR}/data ${INSTALL_DIR}/reports ${INSTALL_DIR}/backups ${INSTALL_DIR}/snapshots
CapabilityBoundingSet=
AmbientCapabilities=

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable workmind.service
info "systemd service 'workmind' enabled."

# ─── Cron: hourly update check ────────────────────────────────────────────────
CRON_FILE="/etc/cron.d/workmind-updater"
info "Installing cron job for automatic updates…"
cat > "${CRON_FILE}" <<EOF
# WorkMind auto-updater — checks GitHub every hour
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
0 * * * * ${WORKMIND_USER} cd ${INSTALL_DIR} && ${VENV_DIR}/bin/python -c "from updater import AutoUpdater; AutoUpdater().check_and_update()" >> ${INSTALL_DIR}/logs/cron_update.log 2>&1
EOF
chmod 644 "${CRON_FILE}"

# ─── Log rotation ─────────────────────────────────────────────────────────────
cat > "/etc/logrotate.d/workmind" <<EOF
${INSTALL_DIR}/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
    su ${WORKMIND_USER} ${WORKMIND_USER}
}
EOF

# ─── Start service ────────────────────────────────────────────────────────────
info "Starting WorkMind service…"
systemctl start workmind.service

sleep 3
if systemctl is-active --quiet workmind.service; then
    info "✅ WorkMind is running successfully."
    info "   Logs: journalctl -u workmind -f"
    info "   Status: systemctl status workmind"
else
    warn "⚠️  WorkMind may not have started correctly."
    warn "   Check: journalctl -u workmind -n 50 --no-pager"
fi

info "Setup complete for node '${WORKMIND_NODE_ID}'."

#!/bin/bash
# ============================================================
# WorkMind Client Setup — Ubuntu 22.04/24.04
# ============================================================
# Installa WorkMind + Tailscale su un nuovo server Ubuntu.
# Esegui con:
#   curl -fsSL https://raw.githubusercontent.com/toprecensione/workmind/main/scripts/setup_client.sh | bash
#   oppure: sudo bash setup_client.sh
#
# Al termine il client e' raggiungibile via Tailscale SSH
# e l'hub puo' gestirlo con: python hub/hub_manager.py status
# ============================================================

set -e
export DEBIAN_FRONTEND=noninteractive

# ── Colori ──────────────────────────────────────────────────
G="\033[32m"; R="\033[31m"; Y="\033[33m"; B="\033[34m"; W="\033[1m"; X="\033[0m"
ok()   { echo -e "${G}[OK]${X} $1"; }
info() { echo -e "${B}[..]${X} $1"; }
warn() { echo -e "${Y}[!!]${X} $1"; }
err()  { echo -e "${R}[ERR]${X} $1"; exit 1; }

echo -e "\n${W}========================================${X}"
echo -e "${W}  WorkMind Client Setup                ${X}"
echo -e "${W}========================================${X}\n"

# ── Config ──────────────────────────────────────────────────
WM_USER="${WM_USER:-$(whoami)}"
WM_DIR="${WM_DIR:-/home/$WM_USER/workmind}"
WM_PORT="${WM_PORT:-7860}"
WM_REPO="${WM_REPO:-https://github.com/toprecensione/workmind.git}"
WM_BRANCH="${WM_BRANCH:-main}"
TAILSCALE_AUTH_KEY="${TAILSCALE_AUTH_KEY:-}"  # Opzionale: imposta per auth automatica

info "Utente: $WM_USER"
info "Directory: $WM_DIR"
info "Porta: $WM_PORT"
info "Repo: $WM_REPO"

# ── 1. Sistema base ─────────────────────────────────────────
info "Aggiornamento sistema..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    git curl wget python3 python3-pip python3-venv \
    ffmpeg build-essential libssl-dev \
    ca-certificates gnupg lsb-release \
    htop nano ufw fail2ban

ok "Pacchetti installati"

# ── 2. Tailscale ────────────────────────────────────────────
info "Installazione Tailscale..."
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    ok "Tailscale installato"
else
    ok "Tailscale gia' presente ($(tailscale --version | head -1))"
fi

# Avvia e connetti a Tailscale
sudo systemctl enable tailscaled
sudo systemctl start tailscaled
sleep 2

if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    info "Autenticazione Tailscale con auth key..."
    sudo tailscale up --authkey="$TAILSCALE_AUTH_KEY" --hostname="workmind-$(hostname)" 2>/dev/null || true
    ok "Tailscale connesso"
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "N/A")
    echo -e "\n  ${G}Tailscale IP: $TS_IP${X}\n"
else
    warn "Tailscale non autenticato. Dopo l'installazione esegui:"
    echo -e "  ${Y}sudo tailscale up --hostname=workmind-$(hostname)${X}"
    echo -e "  Poi copia il link nel browser per autenticarti.\n"
fi

# ── 3. Python 3.11+ ─────────────────────────────────────────
PYTHON_BIN=$(command -v python3.11 || command -v python3.12 || command -v python3)
info "Python: $($PYTHON_BIN --version)"

# ── 4. Clone o aggiornamento WorkMind ───────────────────────
if [ -d "$WM_DIR/.git" ]; then
    info "Aggiornamento WorkMind esistente..."
    cd "$WM_DIR"
    git fetch origin
    git checkout "$WM_BRANCH"
    git pull origin "$WM_BRANCH"
    ok "WorkMind aggiornato"
elif [ -d "$WM_DIR" ]; then
    info "Directory esistente senza git, clono in backup..."
    mv "$WM_DIR" "${WM_DIR}.bak.$(date +%s)"
    git clone -b "$WM_BRANCH" "$WM_REPO" "$WM_DIR"
    ok "WorkMind clonato"
else
    info "Clonazione WorkMind..."
    mkdir -p "$(dirname "$WM_DIR")"
    git clone -b "$WM_BRANCH" "$WM_REPO" "$WM_DIR"
    ok "WorkMind clonato in $WM_DIR"
fi

cd "$WM_DIR"

# ── 5. Virtual environment ──────────────────────────────────
info "Creazione virtual environment..."
$PYTHON_BIN -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel -q
ok "Venv creato"

# ── 6. Dipendenze ───────────────────────────────────────────
info "Installazione dipendenze Python..."
pip install -r requirements.txt -q
ok "Dipendenze installate"

# Dipendenze opzionali per plugin
info "Installazione dipendenze plugin opzionali..."
pip install -q \
    SpeechRecognition pydub \
    mem0ai qdrant-client sentence-transformers \
    chromadb \
    httpx paramiko 2>/dev/null || true
ok "Dipendenze plugin installate"

# ── 7. File .env ────────────────────────────────────────────
if [ ! -f "$WM_DIR/.env" ]; then
    info "Creazione .env da esempio..."
    cp "$WM_DIR/.env.example" "$WM_DIR/.env"
    # Genera secret key random
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/wm-secret-change-me-2026/$SECRET/" "$WM_DIR/.env" 2>/dev/null || true
    warn "IMPORTANTE: Modifica $WM_DIR/.env con le tue API keys"
fi

# ── 8. Directory dati ───────────────────────────────────────
mkdir -p "$WM_DIR/data" "$WM_DIR/logs" "$WM_DIR/backups" "$WM_DIR/reports"
ok "Directory dati create"

# ── 9. Systemd service ──────────────────────────────────────
info "Configurazione systemd service..."
sudo tee /etc/systemd/system/workmind.service > /dev/null <<EOF
[Unit]
Description=WorkMind Operational Assistant
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
User=$WM_USER
WorkingDirectory=$WM_DIR
EnvironmentFile=$WM_DIR/.env
ExecStart=$WM_DIR/venv/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=workmind

# Risorse
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable workmind
ok "Service systemd configurato"

# ── 10. Firewall ─────────────────────────────────────────────
info "Configurazione firewall..."
sudo ufw --force enable 2>/dev/null || true
sudo ufw allow ssh 2>/dev/null || true
sudo ufw allow "$WM_PORT/tcp" comment "WorkMind UI" 2>/dev/null || true
# Tailscale usa la sua rete, non serve aprire porte extra
ok "Firewall configurato"

# ── 11. SSH hardening base ──────────────────────────────────
info "SSH: abilita autenticazione a chiave..."
sudo sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config 2>/dev/null || true
sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd 2>/dev/null || true
ok "SSH configurato"

# ── 12. Avvio WorkMind ──────────────────────────────────────
info "Avvio WorkMind..."
sudo systemctl start workmind
sleep 5

if systemctl is-active --quiet workmind; then
    ok "WorkMind avviato con successo"
    HTTP=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$WM_PORT/login" 2>/dev/null)
    ok "Web UI risponde: HTTP $HTTP"
else
    warn "WorkMind non avviato. Controlla: journalctl -u workmind -n 30"
fi

# ── Riepilogo ────────────────────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')
TS_IP=$(tailscale ip -4 2>/dev/null || echo "non connesso")

echo ""
echo -e "${W}========================================${X}"
echo -e "${W}  Setup Completato!                    ${X}"
echo -e "${W}========================================${X}"
echo -e ""
echo -e "  ${G}WorkMind UI:${X}     http://$LOCAL_IP:$WM_PORT"
echo -e "  ${G}Tailscale IP:${X}    $TS_IP"
echo -e "  ${G}Directory:${X}       $WM_DIR"
echo -e "  ${G}Service:${X}         sudo systemctl status workmind"
echo -e "  ${G}Log:${X}             journalctl -u workmind -f"
echo ""
echo -e "  ${Y}Credenziali default:${X}"
echo -e "  Email:    toprecensione@gmail.com"
echo -e "  Password: WorkMind2026!"
echo ""
if [ "$TS_IP" = "non connesso" ]; then
    echo -e "  ${Y}Per connettere a Tailscale:${X}"
    echo -e "  sudo tailscale up --hostname=workmind-$(hostname)"
fi
echo -e ""
echo -e "  ${B}Aggiungi al Hub:${X}"
echo -e "  python hub/hub_manager.py add-client"
echo ""

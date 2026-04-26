#!/usr/bin/env bash
# WorkMind 3 — Production server setup
# Run once as: sudo bash deploy/install.sh
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$DEPLOY_DIR")"
USER="emanuele"
VENV="$PROJECT_DIR/.venv"

echo "==> WorkMind 3 production install"
echo "    Project: $PROJECT_DIR"

# 1. System packages
apt-get update -q
apt-get install -y -q nginx redis-server postgresql postgresql-contrib python3.12 python3.12-venv python3-pip

# 2. Python venv
if [ ! -d "$VENV" ]; then
    python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "$PROJECT_DIR/workmind-api[dev]"

# 3. Ollama
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.ai/install.sh | sh
fi
# Pull required models
sudo -u "$USER" ollama pull nomic-embed-text &
sudo -u "$USER" ollama pull qwen2.5:14b &
wait

# 4. Tailscale cert for HTTPS
tailscale cert "$(tailscale status --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Self']['DNSName'].rstrip('.'))")" || true

# 5. Nginx
ln -sf "$DEPLOY_DIR/nginx.conf" /etc/nginx/sites-enabled/workmind
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# 6. Systemd services
for svc in workmind-api workmind-celery workmind-celery-beat; do
    ln -sf "$DEPLOY_DIR/$svc.service" /etc/systemd/system/
done
systemctl daemon-reload
systemctl enable workmind-api workmind-celery workmind-celery-beat
systemctl start workmind-api workmind-celery workmind-celery-beat

# 7. Create required dirs
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data" "$PROJECT_DIR/backups"
chown -R "$USER:$USER" "$PROJECT_DIR/logs" "$PROJECT_DIR/data" "$PROJECT_DIR/backups"

echo "==> Install complete."
echo "    API:    https://$(tailscale status --json | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['Self']['DNSName'].rstrip('.'))\")/"
echo "    Status: systemctl status workmind-api"

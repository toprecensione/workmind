#!/bin/bash
# Fallback startup — runs @reboot via cron if systemd services are down
# Systemd services (workmind-api, workmind-celery, workmind-celery-beat) start automatically.
# This script covers edge cases only.
set -a
source /home/emanuele/workmind-v2/.env
set +a

LOGS=/home/emanuele/workmind-v2/logs
mkdir -p "$LOGS" /home/emanuele/workmind-v2/uploads

cd /home/emanuele/workmind-v2/workmind-api

if ! systemctl is-active --quiet workmind-api 2>/dev/null; then
  nohup /home/emanuele/workmind-v2/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --workers 2 \
    --loop uvloop --http httptools \
    --proxy-headers --forwarded-allow-ips=127.0.0.1 \
    >> "$LOGS/uvicorn.log" 2>&1 &
  echo "$(date) Started uvicorn fallback PID $!" >> "$LOGS/reboot.log"
fi

if ! pgrep -f 'celery.*worker' > /dev/null; then
  nohup /home/emanuele/workmind-v2/.venv/bin/celery \
    -A app.tasks.celery_app worker --loglevel=info --concurrency=2 \
    >> "$LOGS/celery.log" 2>&1 &
  echo "$(date) Started celery-worker fallback PID $!" >> "$LOGS/reboot.log"
fi

if ! pgrep -f 'celery.*beat' > /dev/null; then
  nohup /home/emanuele/workmind-v2/.venv/bin/celery \
    -A app.tasks.celery_app beat --loglevel=info \
    --schedule=/home/emanuele/workmind-v2/data/celerybeat-schedule \
    >> "$LOGS/celery-beat.log" 2>&1 &
  echo "$(date) Started celery-beat fallback PID $!" >> "$LOGS/reboot.log"
fi

# Re-enable Tailscale Funnel if not active
if ! tailscale funnel status 2>/dev/null | grep -q 'Funnel on'; then
  tailscale serve --bg http://localhost:8000 2>/dev/null || true
  tailscale funnel --bg http://localhost:8000 2>/dev/null || true
  echo "$(date) Re-enabled Tailscale Funnel" >> "$LOGS/reboot.log"
fi

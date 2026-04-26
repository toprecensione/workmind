#!/bin/bash
# WorkMind v2 API autostart script
set -a
source /home/emanuele/workmind-v2/.env
set +a

LOG=/home/emanuele/workmind-v2/api.log
PID_FILE=/home/emanuele/workmind-v2/api.pid

echo "[$(date)] Starting workmind-v2 API..." >> "$LOG"

cd /home/emanuele/workmind-v2

exec /home/emanuele/workmind-v2/.venv/bin/uvicorn app.main:app     --app-dir workmind-api     --host 0.0.0.0     --port 8000     --workers 2     >> "$LOG" 2>&1

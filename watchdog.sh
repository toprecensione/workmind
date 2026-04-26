#!/bin/bash
# Watchdog: restart workmind-v2 if down
LOG=/home/emanuele/workmind-v2/api.log
while true; do
    if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[$(date)] API down, restarting..." >> "$LOG"
        pkill -f 'uvicorn.*8000' 2>/dev/null
        sleep 2
        /home/emanuele/workmind-v2/start_api.sh &
        sleep 15  # wait before next check
    fi
    sleep 30
done

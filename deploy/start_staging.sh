#!/bin/bash
set -a
source /home/emanuele/workmind-v2/.env.staging
set +a

cd /home/emanuele/workmind-v2/workmind-api
exec /home/emanuele/workmind-v2/.venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8001 \
    --workers 1 \
    --log-level debug

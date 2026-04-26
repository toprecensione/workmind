# WorkMind v2 — Deployment Guide

**Audience:** DevOps engineers, SREs, technical operators
**Target:** Linux server (Ubuntu 22.04+ or 24.04 LTS)

---

## Table of Contents

1. [Architecture Recap](#1-architecture-recap)
2. [Prerequisites](#2-prerequisites)
3. [Initial Server Setup](#3-initial-server-setup)
4. [Application Deployment](#4-application-deployment)
5. [systemd Service Configuration](#5-systemd-service-configuration)
6. [Network Exposure (Tailscale)](#6-network-exposure-tailscale)
7. [Observability Stack](#7-observability-stack)
8. [Continuous Deployment](#8-continuous-deployment)
9. [Rollback Procedures](#9-rollback-procedures)

---

## 1. Architecture Recap

WorkMind is deployed as a single-node application:

```
                 [Tailscale Funnel]
                       │ :443
                       ▼
                 ┌─────────────────────┐
                 │  Linux server       │
                 │  ┌───────────────┐  │
                 │  │ uvicorn :8000 │  │
                 │  │ (production) │  │
                 │  └───────┬───────┘  │
                 │          │          │
                 │  ┌───────▼───────┐  │
                 │  │ PostgreSQL 16 │  │
                 │  │ + pgvector    │  │
                 │  └───────────────┘  │
                 │  ┌───────────────┐  │
                 │  │ Redis 7       │  │
                 │  └───────────────┘  │
                 │  ┌───────────────┐  │
                 │  │ Ollama        │  │
                 │  │ (embeddings)  │  │
                 │  └───────────────┘  │
                 └─────────────────────┘
```

---

## 2. Prerequisites

### 2.1 Server requirements

- **OS:** Ubuntu 22.04 LTS or 24.04 LTS (Debian 12 also supported)
- **CPU:** 4 cores minimum (8 recommended for Ollama embedding throughput)
- **RAM:** 8 GB minimum (16 GB recommended)
- **Disk:** 100 GB SSD (separate volume for `/var/lib/postgresql` recommended)
- **Network:** outbound HTTPS to api.anthropic.com, api.deepseek.com, api.telegram.org, graph.facebook.com (WhatsApp); inbound 443 via Tailscale

### 2.2 Software dependencies

Installed via apt:
- `postgresql-16` + `postgresql-16-pgvector`
- `redis-server`
- `python3.13` + `python3.13-venv`
- `nodejs` 20.x + `npm`
- `nginx` (optional reverse proxy)
- `git`, `curl`, `build-essential`
- `tailscale` (from official repo)

Installed separately:
- `ollama` (from https://ollama.com/install.sh)

### 2.3 External services

- **Anthropic API key** (for Claude)
- **DeepSeek API key** (preferred for cost)
- **Tailscale account** (free for personal use)
- **SMTP credentials** (for password reset emails)

---

## 3. Initial Server Setup

### 3.1 User & SSH

```bash
# Create deployment user
sudo useradd -m -s /bin/bash emanuele
sudo usermod -aG sudo emanuele

# Set up SSH key auth
sudo -u emanuele mkdir -p /home/emanuele/.ssh
echo "<your_public_key>" | sudo -u emanuele tee /home/emanuele/.ssh/authorized_keys
sudo -u emanuele chmod 700 /home/emanuele/.ssh
sudo -u emanuele chmod 600 /home/emanuele/.ssh/authorized_keys

# Disable password SSH (in /etc/ssh/sshd_config)
PasswordAuthentication no
sudo systemctl restart ssh
```

### 3.2 PostgreSQL with pgvector

```bash
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-pgvector

# Create user and database
sudo -u postgres psql <<EOF
CREATE USER workmind WITH PASSWORD 'Wm2026Bender!Pg';
CREATE DATABASE workmind OWNER workmind;
\\c workmind
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
EOF
```

Tune `postgresql.conf` for the workload (typical 16GB server):

```
shared_buffers = 4GB
effective_cache_size = 12GB
maintenance_work_mem = 1GB
work_mem = 32MB
max_connections = 100
```

### 3.3 Redis

```bash
sudo apt install -y redis-server
sudo systemctl enable --now redis-server
```

Default config (localhost-only) is fine. No tuning needed for current scale.

### 3.4 Python 3.13

Ubuntu 24.04 ships with Python 3.12; install 3.13 from deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv python3.13-dev
```

### 3.5 Node.js & npm

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs
```

### 3.6 Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text     # Embedding model (137MB)
# Optional, for local fallback chat:
ollama pull llama3.2:3b
```

Verify:
```bash
curl http://localhost:11434/api/tags
```

### 3.7 Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Approve in admin console
sudo tailscale set --advertise-tags=tag:workmind
```

### 3.8 Enable systemd user lingering

This allows user services to start at boot without being logged in:

```bash
sudo loginctl enable-linger emanuele
```

---

## 4. Application Deployment

### 4.1 Clone Repository

The platform repo is private:

```bash
ssh -i ~/.ssh/github_workmind -T git@github-platform   # verify SSH access
cd ~
git clone git@github-platform:toprecensione/workmind-platform.git workmind-v2
cd workmind-v2
```

### 4.2 Python Virtualenv

```bash
cd ~/workmind-v2
python3.13 -m venv .venv
source .venv/bin/activate
cd workmind-api
pip install --upgrade pip
pip install -e ".[dev]"
```

### 4.3 Environment Configuration

Create `.env`:

```bash
cat > ~/workmind-v2/.env <<'EOF'
# Application
WORKMIND_ENV=production
WORKMIND_SECRET_KEY=<generate via: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
WORKMIND_API_KEYS=<comma-separated-keys>

# Database
DATABASE_URL=postgresql+asyncpg://workmind:Wm2026Bender!Pg@localhost:5432/workmind

# Redis
REDIS_URL=redis://localhost:6379/0

# AI Providers
WORKMIND_DEEPSEEK_API_KEY=sk-...
WORKMIND_ANTHROPIC_API_KEY=sk-ant-...
WORKMIND_OLLAMA_BASE_URL=http://localhost:11434

# Cost limits
WORKMIND_MAX_DAILY_COST_USD=20.0

# Email (for password reset)
WORKMIND_SMTP_HOST=smtp.example.com
WORKMIND_SMTP_PORT=465
WORKMIND_SMTP_SSL=true
WORKMIND_SMTP_USER=...
WORKMIND_SMTP_PASSWORD=...
WORKMIND_SMTP_FROM=workmind@example.com

# CORS
WORKMIND_ALLOWED_ORIGINS=https://workmind-bender.tail898ef4.ts.net
EOF

chmod 600 ~/workmind-v2/.env
```

Save the secrets to KDBX immediately.

### 4.4 Database Migrations

```bash
cd ~/workmind-v2/workmind-api
source ../.venv/bin/activate
alembic upgrade head
```

Verify:
```bash
alembic current
# Should show: e620428 (head)
```

### 4.5 Frontend Build

```bash
cd ~/workmind-v2/workmind-frontend
npm ci
npm run build
```

Build artifacts go to `~/workmind-v2/workmind-frontend/build/`.

For MEDIC-branded build:
```bash
VITE_CLIENT=medic npm run build
```

The API mounts the frontend build at `/static` and serves it as the SPA root.

### 4.6 Initial Smoke Test

Run the API in foreground to verify:

```bash
cd ~/workmind-v2/workmind-api
source ../.venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell:
```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok",...}`

Stop with Ctrl+C and proceed to systemd setup.

---

## 5. systemd Service Configuration

All services run as user-level systemd units (no root for app processes).

### 5.1 Production API

`~/.config/systemd/user/workmind-api.service`:

```ini
[Unit]
Description=WorkMind API (Production)
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
WorkingDirectory=/home/emanuele/workmind-v2/workmind-api
EnvironmentFile=/home/emanuele/workmind-v2/.env
ExecStart=/home/emanuele/workmind-v2/.venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 \
  --log-config /home/emanuele/workmind-v2/deploy/uvicorn-log.json
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

### 5.2 Staging API

Identical except port 8001 and different EnvironmentFile (`.env.staging`).

### 5.3 Celery Worker

`~/.config/systemd/user/workmind-celery.service`:

```ini
[Unit]
Description=WorkMind Celery Worker
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
WorkingDirectory=/home/emanuele/workmind-v2/workmind-api
EnvironmentFile=/home/emanuele/workmind-v2/.env
ExecStart=/home/emanuele/workmind-v2/.venv/bin/celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### 5.4 Celery Beat

```ini
[Unit]
Description=WorkMind Celery Beat (scheduler)
After=network.target redis-server.service

[Service]
Type=simple
WorkingDirectory=/home/emanuele/workmind-v2/workmind-api
EnvironmentFile=/home/emanuele/workmind-v2/.env
ExecStart=/home/emanuele/workmind-v2/.venv/bin/celery -A app.tasks.celery_app beat --loglevel=info
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### 5.5 Enable & Start

```bash
systemctl --user daemon-reload
systemctl --user enable workmind-api workmind-staging workmind-celery workmind-celery-beat
systemctl --user start workmind-api workmind-staging workmind-celery workmind-celery-beat

# Verify
systemctl --user status workmind-api
```

---

## 6. Network Exposure (Tailscale)

### 6.1 Public Production via Funnel

Tailscale Funnel exposes a service to the internet via Tailscale's edge:

```bash
sudo tailscale funnel --bg 8000
# This proxies https://workmind-bender.tail898ef4.ts.net → 127.0.0.1:8000
```

Verify:
```bash
tailscale funnel status
```

### 6.2 Tailnet-only Services

Staging, Grafana, Prometheus exposed to tailnet only (no public access):

```bash
sudo tailscale serve --bg --https=8001 8001        # staging
sudo tailscale serve --bg --https=3001 3001        # Grafana
sudo tailscale serve --bg --https=9090 9090        # Prometheus
```

URLs:
- `https://workmind-bender.tail898ef4.ts.net:8001`
- `https://workmind-bender.tail898ef4.ts.net:3001`

### 6.3 Optional Nginx Reverse Proxy

For more sophisticated routing (e.g., custom domain, multiple sites), add nginx in front of uvicorn. See `deploy/nginx.conf` for example.

Generally **not needed** with Tailscale Funnel.

---

## 7. Observability Stack

### 7.1 Prometheus

`~/.config/systemd/user/prometheus.service`:

```ini
[Unit]
Description=Prometheus
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/emanuele/prometheus
ExecStart=/home/emanuele/prometheus/prometheus --config.file=/home/emanuele/prometheus/prometheus.yml
Restart=on-failure

[Install]
WantedBy=default.target
```

`prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'workmind-api'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['localhost:8000']
        labels: {env: 'production'}
      - targets: ['localhost:8001']
        labels: {env: 'staging'}

  - job_name: 'node_exporter'
    static_configs:
      - targets: ['localhost:9100']
```

Install Prometheus binary from https://prometheus.io/download/ (extract to `~/prometheus/`).

### 7.2 Grafana

```bash
# Install via apt
sudo apt-get install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt-get update && sudo apt-get install -y grafana

# Override systemd unit to bind only localhost
sudo mkdir -p /etc/systemd/system/grafana-server.service.d/
sudo tee /etc/systemd/system/grafana-server.service.d/override.conf <<EOF
[Service]
Environment="GF_SERVER_HTTP_PORT=3001"
Environment="GF_SERVER_HTTP_ADDR=127.0.0.1"
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now grafana-server
```

Access: `http://localhost:3001` or via Tailscale serve.

Add Prometheus as datasource: `http://localhost:9090`.

Import recommended dashboards from `docs/operations/grafana-dashboards/` (when available).

### 7.3 Backup Cron

```bash
crontab -e
```

Add:
```
30 2 * * * bash /home/emanuele/workmind-v2/deploy/backup.sh >> /home/emanuele/backups/backup.log 2>&1
```

---

## 8. Continuous Deployment

### 8.1 Manual Deploy Script

`deploy/update.sh` (run on bender):

```bash
#!/bin/bash
set -euo pipefail

cd ~/workmind-v2
git pull origin master

source .venv/bin/activate

# API
cd workmind-api
pip install -e ".[dev]" -q
alembic upgrade head

# Frontend
cd ../workmind-frontend
npm ci --silent
npm run build

# Restart
systemctl --user restart workmind-api

# Smoke test
sleep 5
curl -sf http://localhost:8000/health || (echo "Health check failed!" && exit 1)

echo "Deploy successful at $(date)"
```

### 8.2 Future: GitHub Actions Auto-Deploy

When CI confidence is high, add a deploy job that:
1. Runs after CI passes on master
2. SSH to bender via deploy key
3. Runs `bash ~/workmind-v2/deploy/update.sh`

Currently disabled because CI is still being stabilized.

### 8.3 Blue/Green Strategy (future)

For zero-downtime deploys:
1. Deploy to staging (port 8001) first
2. Run smoke tests against staging
3. Swap Tailscale Funnel to point staging port
4. Production becomes new staging
5. Repeat next cycle

---

## 9. Rollback Procedures

### 9.1 Code Rollback

```bash
cd ~/workmind-v2
git log --oneline -10           # Identify last good commit
git checkout <good_commit_sha>
cd workmind-api && pip install -e ".[dev]" -q
cd ../workmind-frontend && npm run build
systemctl --user restart workmind-api
```

### 9.2 Database Rollback

⚠️ **Migrations may not be reversible.** Always test downgrades on staging first.

```bash
cd workmind-api
alembic downgrade -1            # One step back
# OR
alembic downgrade <revision>    # Specific revision
```

If downgrade fails, restore from `pg_dump`:

```bash
systemctl --user stop workmind-api workmind-celery
sudo -u postgres dropdb workmind
sudo -u postgres createdb workmind -O workmind
sudo -u postgres pg_restore -d workmind ~/backups/postgres/workmind-<DATE>.dump
systemctl --user start workmind-api workmind-celery
```

### 9.3 Configuration Rollback

`.env` files are not version controlled but can be backed up:

```bash
cp ~/workmind-v2/.env ~/workmind-v2/.env.backup-$(date +%F)
```

Maintain a `.env.template` in git so the structure is documented.

---

## 10. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| API returns 503 on /ready | DB or Redis down | Check `systemctl status postgresql redis-server` |
| `/api/chat` returns 500 | AI provider key invalid | Check `.env` and `journalctl --user -u workmind-api` |
| Frontend shows blank page | Build artifacts missing | `cd workmind-frontend && npm run build` |
| Login slow (>5s) | bcrypt cost too high | Verify `bcrypt.gensalt(12)` not higher |
| Migrations fail | DB schema drift | Compare `\d <table>` to `models.py` |

---

**End of Deployment Guide**

# WorkMind v2 — Operations Runbook

**Last Updated:** 2026-04-26
**On-call rotation:** emanuele (single SRE for now)
**Escalation:** none defined
**SLA target:** 99.5% monthly availability

---

## Table of Contents

1. [Production Environment Overview](#1-production-environment-overview)
2. [Daily Operations](#2-daily-operations)
3. [Common Tasks](#3-common-tasks)
4. [Incident Playbooks](#4-incident-playbooks)
5. [Backup & Recovery](#5-backup--recovery)
6. [Capacity Planning](#6-capacity-planning)
7. [Monitoring & Alerts](#7-monitoring--alerts)
8. [Useful Commands](#8-useful-commands)

---

## 1. Production Environment Overview

### 1.1 Server: bender

| Property | Value |
|---|---|
| OS | Ubuntu 24.04 LTS |
| Hostname | bender |
| Tailscale FQDN | workmind-bender.tail898ef4.ts.net |
| User | emanuele |
| SSH key | `~/.ssh/workmind_hub` (on operator's workstation) |
| Sudo password | stored in KDBX (`Servers / bender sudo`) |

### 1.2 Services Running on bender

All managed via systemd user units (no root required, persists via `loginctl enable-linger emanuele`).

| Service | Port | Type | Source |
|---|---|---|---|
| `workmind-api.service` | 8000 | uvicorn (single worker, async) | Production API |
| `workmind-staging.service` | 8001 | uvicorn (single worker) | Staging API |
| `workmind-celery.service` | — | Celery worker | Background jobs |
| `workmind-celery-beat.service` | — | Celery beat | Scheduled jobs |
| `prometheus.service` | 9090 | Prometheus | Metrics scraping |
| `grafana.service` | 3001 | Grafana | Dashboards |
| `postgresql@16-main` | 5432 | apt-installed | Main DB |
| `redis-server` | 6379 | apt-installed | Cache + queue |
| `ollama.service` | 11434 | systemd system | Local AI |
| `tailscaled` | 41641/udp | system | VPN tunnel |

### 1.3 File Locations

| Path | Purpose |
|---|---|
| `~/workmind-v2/` | Code repository (git, master branch) |
| `~/workmind-v2/.venv/` | Python virtualenv |
| `~/workmind-v2/workmind-api/uploads/` | KB file storage |
| `~/workmind-v2/.env` | Production config (mode 600) |
| `~/workmind-v2/.env.staging` | Staging config |
| `~/.config/systemd/user/` | systemd unit files |
| `~/backups/postgres/` | Local DB backup directory |
| `/var/log/journal/` | systemd journal logs |

### 1.4 Network Exposure

| Service | External | Tailnet | Local |
|---|---|---|---|
| Production API | ✅ via Funnel | ✅ | ✅ |
| Staging API | ❌ | ✅ | ✅ |
| Grafana | ❌ | ✅ | ✅ |
| Prometheus | ❌ | ✅ | ✅ |
| Postgres | ❌ | ❌ | ✅ |
| Redis | ❌ | ❌ | ✅ |

---

## 2. Daily Operations

### 2.1 Morning Health Check (5 min)

```bash
ssh -i ~/.ssh/workmind_hub emanuele@bender '
  echo "== Services =="
  systemctl --user is-active workmind-api workmind-staging workmind-celery prometheus grafana
  echo ""
  echo "== Health =="
  curl -sf https://workmind-bender.tail898ef4.ts.net/health
  echo ""
  echo "== Disk =="
  df -h / /home
  echo ""
  echo "== Memory =="
  free -h
  echo ""
  echo "== Last backup =="
  ls -lh ~/backups/postgres/ | tail -3
'
```

Expected:
- All services `active`
- Health returns `{"status":"ok"}`
- Disk free >20%
- Last backup within last 24h

### 2.2 Weekly Tasks

Monday morning:
- Check Grafana dashboards for slow queries, error rate spikes
- Review last week's audit log for unusual activity (`SELECT event_type, COUNT(*) FROM audit_logs WHERE created_at > now() - interval '7 days' GROUP BY 1`)
- Verify backup retention (should have 30 days of dumps)

### 2.3 Monthly Tasks

First weekday of month:
- Run a backup restore test (procedure in §5.4)
- Review `apt list --upgradable` and apply security updates (within maintenance window)
- Run `pip-audit` against pinned deps; create issues for vulns
- Rotate Tailscale Funnel cert if approaching expiry (auto-renews — verify)

---

## 3. Common Tasks

### 3.1 Deploy New Code (Production)

Standard deploy:

```bash
ssh -i ~/.ssh/workmind_hub emanuele@bender '
  cd ~/workmind-v2 &&
  git fetch origin master &&
  git pull origin master &&
  source .venv/bin/activate &&
  cd workmind-api &&
  pip install -e ".[dev]" -q &&
  alembic upgrade head &&
  cd ../workmind-frontend &&
  npm ci && npm run build &&
  cd ~/workmind-v2 &&
  systemctl --user restart workmind-api &&
  sleep 3 &&
  curl -sf https://workmind-bender.tail898ef4.ts.net/health
'
```

If this fails partway, see §4.1 (Deploy Rollback).

### 3.2 Deploy to Staging First

Strongly recommended for major changes:

```bash
# Same as above but:
systemctl --user restart workmind-staging
curl -sf http://localhost:8001/health
# Test manually via tailnet, then deploy to prod
```

### 3.3 View Logs

Production API live:
```bash
ssh emanuele@bender 'journalctl --user -u workmind-api -f'
```

Last 1000 lines of staging:
```bash
journalctl --user -u workmind-staging -n 1000 --no-pager
```

Filter by error level:
```bash
journalctl --user -u workmind-api --since "1 hour ago" -p err
```

### 3.4 Restart a Service

```bash
systemctl --user restart workmind-api
# Or specific:
systemctl --user restart workmind-celery
systemctl --user restart prometheus grafana
```

### 3.5 Run a Database Query

```bash
sudo -u postgres psql workmind
```

Common queries:

```sql
-- Active users in last 24h
SELECT COUNT(DISTINCT user_id) FROM messages
WHERE created_at > now() - interval '24 hours';

-- AI cost yesterday
SELECT provider, SUM(cost_usd) AS cost
FROM model_usage
WHERE created_at::date = current_date - 1
GROUP BY provider;

-- Documents pending indexing
SELECT id, title, status, error_msg FROM documents
WHERE status IN ('pending', 'processing', 'failed')
ORDER BY created_at DESC;

-- Slow recent queries (requires pg_stat_statements)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;
```

### 3.6 Trigger a Manual Backup

```bash
# Via API (recommended — logs to backup_logs table):
curl -X POST -H "Authorization: Bearer <admin-jwt>" \
  https://workmind-bender.tail898ef4.ts.net/api/admin/backup/trigger

# Via shell directly:
ssh emanuele@bender 'bash ~/workmind-v2/deploy/backup.sh'
```

### 3.7 Add a New User

Either via the admin UI (`/admin/users`) or via API:

```bash
curl -X POST -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  https://workmind-bender.tail898ef4.ts.net/api/admin/users \
  -d '{"email":"new@example.com","display_name":"New User","role":"user"}'
```

The response includes `temp_password` if no password was provided.

### 3.8 Reset a User Password (Admin)

```bash
curl -X POST -H "Authorization: Bearer <admin-jwt>" \
  https://workmind-bender.tail898ef4.ts.net/api/admin/users/<user_id>/reset-password
```

Returns a temporary password. Communicate to user via secure channel.

### 3.9 Rotate JWT Secret

⚠️ **Logs out ALL users.** Use only for incident response.

```bash
ssh emanuele@bender '
  # Generate new key
  NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  # Update .env
  sed -i "s|^WORKMIND_SECRET_KEY=.*|WORKMIND_SECRET_KEY=$NEW_KEY|" ~/workmind-v2/.env
  systemctl --user restart workmind-api workmind-celery
  echo "Done. Save new key:"
  echo "$NEW_KEY"
'
```

Save new key to KDBX immediately.

---

## 4. Incident Playbooks

### 4.1 API Returns 500 Errors

**Symptoms:** Health endpoint returns 200, but most other endpoints fail.

```bash
# 1. Check logs for stack traces
journalctl --user -u workmind-api --since "10 minutes ago" -p err

# 2. Check DB connectivity from API
ssh emanuele@bender '
  source ~/workmind-v2/.venv/bin/activate
  python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
async def main():
    e = create_async_engine(\"postgresql+asyncpg://workmind:Wm2026Bender!Pg@localhost:5432/workmind\")
    async with e.connect() as c:
        r = await c.execute(__import__(\"sqlalchemy\").text(\"SELECT 1\"))
        print(r.scalar())
asyncio.run(main())
"'

# 3. If DB OK, restart API
systemctl --user restart workmind-api

# 4. If still failing, deploy rollback
cd ~/workmind-v2 && git log --oneline -5
git reset --hard HEAD~1   # ⚠️ Be careful — last good commit
systemctl --user restart workmind-api
```

### 4.2 Database Down

```bash
# 1. Status
systemctl status postgresql@16-main

# 2. Logs
sudo tail -100 /var/log/postgresql/postgresql-16-main.log

# 3. Restart
sudo systemctl restart postgresql@16-main

# 4. Verify connectivity
sudo -u postgres psql -c "SELECT 1"

# 5. If corrupted: restore from latest dump
sudo -u postgres pg_restore -d workmind /home/emanuele/backups/postgres/<latest>.dump
```

### 4.3 Disk Full

```bash
# Find offenders
df -h
sudo du -sh /var/log/* | sort -h | tail -20
du -sh ~/workmind-v2/* | sort -h | tail -10
du -sh ~/backups/* | sort -h | tail -10

# Common cleanup:
# - Old systemd journals
sudo journalctl --vacuum-time=7d

# - Old backups (keep last 30 days, monthly for 12)
find ~/backups/postgres -name "*.dump" -mtime +30 ! -name "*-01.dump" -delete

# - npm cache
npm cache clean --force

# - apt cache
sudo apt clean
```

### 4.4 High AI Cost / Suspected Abuse

```bash
# 1. Check today's AI cost by user
sudo -u postgres psql workmind -c "
SELECT u.email, SUM(mu.cost_usd) AS cost, COUNT(*) AS calls
FROM model_usage mu
JOIN users u ON u.id = mu.user_id
WHERE mu.created_at::date = current_date
GROUP BY u.email
ORDER BY cost DESC LIMIT 10;
"

# 2. If a single user is excessive: rate limit or disable
# Disable user:
curl -X POST -H "Authorization: Bearer <admin-jwt>" \
  https://workmind-bender.tail898ef4.ts.net/api/admin/users/<user_id>/deactivate

# 3. Lower daily budget temporarily in .env:
sed -i 's/^WORKMIND_MAX_DAILY_COST_USD=.*/WORKMIND_MAX_DAILY_COST_USD=10.0/' ~/workmind-v2/.env
systemctl --user restart workmind-api
```

### 4.5 Security Incident: Suspected Breach

1. **Don't panic.** Document timeline as you go.
2. **Preserve evidence**:
   ```bash
   # Snapshot logs immediately
   journalctl --user --since "24 hours ago" > /tmp/incident_$(date +%F).log
   sudo -u postgres pg_dump workmind | gzip > ~/incident_db_$(date +%F).sql.gz
   ```
3. **Block the threat**:
   - If specific user compromised: deactivate via API
   - If specific IP: add to firewall (`sudo iptables -A INPUT -s <IP> -j DROP`)
   - If unknown scope: rotate JWT secret (§3.9) → forces all logouts
4. **Investigate** via audit log:
   ```sql
   SELECT * FROM audit_logs
   WHERE created_at > now() - interval '7 days'
     AND event_type IN ('login_failed', '2fa_challenge_failed', 'permission_changed')
   ORDER BY created_at DESC;
   ```
5. **Document** post-mortem in `docs/incidents/<date>.md`

### 4.6 Tailscale Funnel Down

Production API not reachable externally but tailnet works:

```bash
# Check funnel status
tailscale funnel status

# Re-enable (if disabled)
tailscale funnel --bg 8000

# If port 443 conflict
sudo lsof -i :443    # Identify offending process
```

### 4.7 Out-of-Memory (OOM)

```bash
# Check OOM killer activity
sudo dmesg | grep -i "killed process"

# Identify memory hogs
ps aux --sort=-%mem | head -10

# If celery workers are bloated, restart
systemctl --user restart workmind-celery

# If postgres is exceeding: tune postgresql.conf
# - shared_buffers (default ~25% RAM)
# - work_mem (per-query)
# - max_connections
```

---

## 5. Backup & Recovery

### 5.1 Backup Schedule

| Type | Frequency | Time | Retention | Location |
|---|---|---|---|---|
| pg_dump | Daily | 02:30 UTC | 30 days | `~/backups/postgres/` |
| Monthly dump | 1st of month | 02:30 UTC | 12 months | same |
| Files (uploads/) | Daily | 03:00 UTC | 7 days | rsync to `/var/backups/files/` |
| Off-site | Weekly | Sunday | 4 weeks | rclone to S3 (planned) |

### 5.2 Backup Script

`deploy/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail

DEST=~/backups/postgres
mkdir -p $DEST
TODAY=$(date +%F)
DAY=$(date +%d)

# Daily dump
sudo -u postgres pg_dump --format=custom workmind > $DEST/workmind-$TODAY.dump

# Monthly: copy to perma directory if 1st
if [ "$DAY" = "01" ]; then
  cp $DEST/workmind-$TODAY.dump $DEST/monthly/workmind-$(date +%Y-%m).dump
fi

# Retention: delete > 30 days
find $DEST -maxdepth 1 -name "workmind-*.dump" -mtime +30 -delete
```

Scheduled via cron:
```
30 2 * * * bash /home/emanuele/workmind-v2/deploy/backup.sh
```

### 5.3 Restore Procedure

```bash
# 1. Stop services
systemctl --user stop workmind-api workmind-staging workmind-celery

# 2. Drop and recreate database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS workmind"
sudo -u postgres psql -c "CREATE DATABASE workmind OWNER workmind"

# 3. Restore
sudo -u postgres pg_restore -d workmind ~/backups/postgres/workmind-2026-04-26.dump

# 4. Verify
sudo -u postgres psql workmind -c "SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM messages;"

# 5. Start services
systemctl --user start workmind-api workmind-staging workmind-celery

# 6. Verify health
curl https://workmind-bender.tail898ef4.ts.net/health
```

### 5.4 Quarterly Restore Test

Procedure to verify backup integrity:

```bash
# 1. Create test database
sudo -u postgres psql -c "CREATE DATABASE workmind_restore_test"

# 2. Restore latest dump
sudo -u postgres pg_restore -d workmind_restore_test ~/backups/postgres/workmind-$(date +%F).dump

# 3. Sanity checks
sudo -u postgres psql workmind_restore_test -c "
SELECT
  (SELECT COUNT(*) FROM organizations) AS orgs,
  (SELECT COUNT(*) FROM users) AS users,
  (SELECT COUNT(*) FROM messages) AS msgs,
  (SELECT COUNT(*) FROM document_chunks) AS chunks
;"

# 4. Compare counts to production
sudo -u postgres psql workmind -c "
SELECT
  (SELECT COUNT(*) FROM organizations) AS orgs,
  (SELECT COUNT(*) FROM users) AS users,
  (SELECT COUNT(*) FROM messages) AS msgs,
  (SELECT COUNT(*) FROM document_chunks) AS chunks
;"

# 5. Cleanup
sudo -u postgres psql -c "DROP DATABASE workmind_restore_test"
```

Document results in `docs/operations/restore-tests.log`.

---

## 6. Capacity Planning

### 6.1 Current Resource Utilization (April 2026)

| Resource | Current | Capacity | Headroom |
|---|---|---|---|
| CPU (1m avg) | 5% | 8 cores | 95% |
| Memory | 4 GB | 16 GB | 75% |
| Disk (/home) | 12 GB | 200 GB | 94% |
| DB size | 800 MB | — | — |
| Postgres conn | 8 | 100 | 92% |
| Redis memory | 50 MB | 4 GB | 99% |

### 6.2 Growth Triggers

| Metric | Action when reached |
|---|---|
| Disk >70% | Plan storage expansion |
| API p95 latency >2s sustained | Investigate slow queries; add caching |
| DB conn pool >80% | Increase pool size or add read replica |
| Daily AI cost approaching budget | Adjust per-user rate limits |
| Concurrent SSE streams >50 | Scale to multiple uvicorn workers |
| KB chunks >500K | Tune HNSW index parameters |

### 6.3 Scale-Up Plan

When Bender alone is insufficient:

1. **Phase 1: Vertical scaling** — Larger Bender VPS (more CPU/RAM)
2. **Phase 2: Multi-process** — Gunicorn with multiple uvicorn workers, sticky session for SSE
3. **Phase 3: Read replica** — Add Postgres replica; route read-heavy admin queries
4. **Phase 4: Multi-node** — Move web tier to dedicated nodes; Celery to separate workers; Postgres + Redis on managed services

---

## 7. Monitoring & Alerts

### 7.1 Prometheus Metrics

Key metrics scraped from `/metrics`:

| Metric | Purpose |
|---|---|
| `workmind_http_requests_total` | Request count by route/method/status |
| `workmind_http_request_duration_seconds` | Latency histogram |
| `workmind_ai_cost_usd_total` | Cumulative AI spend |
| `workmind_ai_tokens_total` | Token usage by provider |
| `workmind_db_pool_used` | DB connection pool utilization |
| `workmind_active_users_5m` | Recent active users |

### 7.2 Grafana Dashboards

Available at https://grafana-bender.tail898ef4.ts.net (tailnet only):

1. **API Performance** — request rate, latency, error rate
2. **AI Usage** — cost per provider, token rate, user breakdown
3. **System Health** — CPU, memory, disk, network
4. **Database** — pool, slow queries, replication lag
5. **Skills & Jobs** — job success rate, queue depth

### 7.3 Alerts (Planned)

| Alert | Threshold | Channel |
|---|---|---|
| API down | health probe fails 2 consecutive | email + Telegram |
| High error rate | >5% errors over 5min | Telegram |
| AI cost spike | >$50/day | email |
| DB pool exhausted | >90% for 5min | Telegram |
| Disk >85% | sustained 1h | email |
| Backup failed | last backup >30h old | email + Telegram |

Currently using Grafana alerting (manual configuration). Alertmanager planned for stricter routing.

---

## 8. Useful Commands

### 8.1 SSH Shortcut

Add to `~/.ssh/config`:

```
Host bender
  HostName bender.tail898ef4.ts.net
  User emanuele
  IdentityFile ~/.ssh/workmind_hub
```

Then: `ssh bender`.

### 8.2 Quick Operations

```bash
# Tail prod API logs from anywhere
ssh bender 'journalctl --user -u workmind-api -f --no-pager'

# Run tests on bender
ssh bender 'cd ~/workmind-v2/workmind-api && source ../.venv/bin/activate && pytest tests/ -q'

# Open Postgres CLI
ssh -t bender 'sudo -u postgres psql workmind'

# Check Tailscale Funnel status
ssh bender 'tailscale funnel status'

# Force re-pull a Docker image (when Docker is used in future)
ssh bender 'docker compose pull && docker compose up -d --force-recreate'
```

### 8.3 Service Health (One-liner)

```bash
ssh bender 'systemctl --user is-active workmind-api workmind-staging workmind-celery prometheus grafana'
```

Output: `active active active active active` if all healthy.

---

**End of Runbook**

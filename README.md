# WorkMind 3 — v2.0.0

**AI-powered business assistant for MEDIC (aesthetic medicine).**

Self-hosted, privacy-first platform with multi-channel AI support (chat, Telegram, WhatsApp), knowledge base with semantic search, and a full admin panel.

> Internal platform only. Not for public distribution.
> Access restricted to Tailscale VPN: `workmind-bender.tail898ef4.ts.net`

---

## Architecture

```
[Browser / Telegram / WhatsApp]
            │
     [Nginx TLS :443]          ← Tailscale interface only
            │
   [FastAPI / uvicorn :8000]
            │
   ┌────────┴────────┐
   │                 │
[PostgreSQL 16    [Redis 7]
 + pgvector]       (broker + cache + sessions)
                   │
            [Celery Worker]
            [Celery Beat]
                   │
       ┌───────────┼───────────┐
  [Ollama]   [Claude API]  [DeepSeek API]
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115 + uvicorn (Python 3.12) |
| Frontend | SvelteKit (static build served by Nginx) |
| Database | PostgreSQL 16 + pgvector extension |
| Cache / Broker | Redis 7 |
| Background tasks | Celery + Celery Beat |
| AI — cloud | Anthropic Claude (Sonnet/Haiku), DeepSeek Chat |
| AI — local (PRO) | Ollama + Qwen 2.5 14B |
| Reverse proxy | Nginx (TLS, Tailscale only) |
| VPN | Tailscale |

---

## Model Profiles

### START (default — no GPU required)

```env
WORKMIND_PROFILE=start
LOCAL_LLM=false
```

| Task type | Primary | Fallback |
|---|---|---|
| FAST | DeepSeek Chat API | Claude Haiku |
| RELIABLE | Claude Haiku 4.5 | — |
| ANALYSE / CHAT | Claude Sonnet 4.6 | — |

### PRO (GPU node required)

```env
WORKMIND_PROFILE=pro
LOCAL_LLM=true
OLLAMA_BASE_URL=http://<gpu-node>:11434
```

| Task type | Primary | Fallback |
|---|---|---|
| FAST / CHAT | Ollama (Qwen 2.5) | Claude API |
| ANALYSE / RELIABLE | Claude API | — |

---

## Quick Start (Development)

```bash
# 1. Clone and enter
git clone <repo> workmind-v2
cd workmind-v2

# 2. Backend — create virtualenv and install
cd workmind-api
python3.12 -m venv ../.venv
../.venv/bin/pip install -e ".[dev]"

# 3. Configure environment
cp ../.env.example ../.env
# Edit .env — fill POSTGRES_PASSWORD, ANTHROPIC_API_KEY, etc.

# 4. Database
createdb workmind_db
../.venv/bin/alembic upgrade head

# 5. Frontend
cd ../workmind-frontend
npm install
npm run build

# 6. Start API (development)
cd ../workmind-api
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

Check: `curl http://localhost:8000/health`

---

## Production Setup

### Requirements

- Ubuntu 22.04+ (bare metal or VM)
- Python 3.12
- PostgreSQL 16 with pgvector
- Redis 7
- Nginx
- Tailscale (node already enrolled)

### Install

```bash
sudo bash deploy/install.sh
```

The script installs all system dependencies, creates the `workmind` user, sets up the virtualenv, runs migrations, builds the frontend, configures Nginx (Tailscale interface only), and installs three systemd services.

### Post-install

1. Copy and fill `.env`:
   ```bash
   cp .env.example .env
   nano .env   # fill required values
   ```

2. Start services:
   ```bash
   sudo systemctl enable --now workmind-api workmind-celery workmind-celery-beat
   ```

3. Check status:
   ```bash
   systemctl status workmind-api workmind-celery workmind-celery-beat
   ```

---

## Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `WORKMIND_ENV` | `production` | yes | `production` or `development` |
| `WORKMIND_PROFILE` | `start` | yes | `start` or `pro` |
| `WORKMIND_SECRET_KEY` | — | **yes** | 64-char random secret |
| `NODE_ID` | `bender` | yes | Node identifier |
| `DATABASE_URL` | — | **yes** | asyncpg DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | `redis://localhost:6379/0` | yes | Redis connection URL |
| `ANTHROPIC_API_KEY` | — | **yes** | Claude API key (`sk-ant-...`) |
| `DEEPSEEK_API_KEY` | — | yes (START) | DeepSeek API key |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | PRO only | Ollama endpoint |
| `JWT_EXPIRE_MINUTES` | `1440` | no | Session duration (24h) |
| `TELEGRAM_BOT_TOKEN` | — | optional | Telegram Bot token |
| `TELEGRAM_WEBHOOK_SECRET` | — | optional | Webhook validation secret |
| `WHATSAPP_TOKEN` | — | optional | WhatsApp Business API token |
| `WHATSAPP_PHONE_ID` | — | optional | WhatsApp sender phone ID |
| `WHATSAPP_VERIFY_TOKEN` | — | optional | Meta webhook verify token |
| `LOCAL_LLM` | `false` | no | Enable Ollama routing |
| `GPU_INFERENCE` | `false` | no | GPU inference flag |
| `MULTIORG` | `false` | no | Multi-organisation mode |
| `AUDIT_EXPORT` | `true` | no | Enable audit log export |
| `VECTOR_REINDEX` | `false` | no | Trigger reindex on startup |

Generate secrets:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## API Overview

### Health

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/health` | Liveness probe | none |
| GET | `/health/ready` | Readiness (checks PostgreSQL) | none |

### Chat & Conversations

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/chat` | Send message, get AI response | JWT |
| GET | `/api/conversations` | List conversations | JWT |
| GET | `/api/conversations/{id}` | Get conversation + messages | JWT |
| DELETE | `/api/conversations/{id}` | Soft-delete conversation | JWT |

### Knowledge Base

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/teach` | Inject knowledge (supervisor) | JWT |
| GET | `/api/kb` | List KB documents | JWT |
| POST | `/api/kb/upload` | Upload document | JWT |

### Admin

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/api/admin/usage` | AI model usage summary | Internal key |
| GET | `/api/admin/jobs` | Background job status | Internal key |
| POST | `/api/admin/reindex` | Trigger vector reindex | Internal key |
| GET | `/api/admin/users` | List users | Internal key |
| GET | `/api/admin/audit` | Audit log | Internal key |

### Channels

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/channels/telegram/webhook` | Telegram incoming update | HMAC |
| GET/POST | `/api/channels/whatsapp/webhook` | WhatsApp incoming message | Verify token |

---

## Admin Panel

Access at: `https://workmind-bender.tail898ef4.ts.net/admin`

| Page | URL | Description |
|---|---|---|
| Dashboard | `/admin` | Overview and quick stats |
| Users | `/admin/users` | Manage users and roles |
| Knowledge Base | `/admin/kb` | Upload and manage KB documents |
| AI Actions | `/admin/ai-actions` | Configure AI action templates |
| AI Usage | `/admin/ai-usage` | Token and cost tracking per model |
| Skills | `/admin/skills` | Manage agent skills |
| Connectors | `/admin/connectors` | External integration settings |
| Audit Log | `/admin/audit` | Append-only operation log |
| System | `/admin/system` | Node info, feature flags, health |

---

## Channels Setup

### Telegram

```bash
# Register webhook (run once after deploy)
curl "https://workmind-bender.tail898ef4.ts.net/api/channels/telegram/set-webhook?webhook_url=https://workmind-bender.tail898ef4.ts.net/api/channels/telegram/webhook"
```

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` in `.env` before registering.

### WhatsApp Business

1. In Meta Developer Dashboard → Webhooks, set:
   - Webhook URL: `https://workmind-bender.tail898ef4.ts.net/api/channels/whatsapp/webhook`
   - Verify Token: value of `WHATSAPP_VERIFY_TOKEN` in `.env`
2. Subscribe to `messages` field.
3. Set `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_ID` in `.env`.

---

## Knowledge Base

Documents are chunked, embedded (pgvector), and retrieved at query time.

**Add documents via Admin UI:**

1. Go to `/admin/kb`
2. Click **Upload** — supports PDF, DOCX, TXT, MD
3. Documents are processed asynchronously by the Celery worker

**Trigger manual reindex:**

```bash
curl -X POST https://workmind-bender.tail898ef4.ts.net/api/admin/reindex \
  -H "X-WorkMind-Key: $INTERNAL_API_KEY" \
  -d '{"scope": "documents", "force": false}'
```

---

## Updates

```bash
bash deploy/update.sh
```

The script runs: `git pull` → `pip install` → `alembic upgrade head` → `npm run build` → `systemctl reload` for all three services.

---

## Backup

```bash
# Manual
bash scripts/backup_pg.sh

# Automated — add to crontab (daily at 02:00)
0 2 * * * /path/to/workmind-v2/scripts/backup_pg.sh >> /var/log/workmind-backup.log 2>&1
```

---

## Security

- All traffic via Tailscale VPN only — no public internet exposure
- Nginx binds TLS exclusively on the Tailscale network interface
- UFW default-deny on all non-Tailscale interfaces
- PII stripped from all external AI calls (reversible anonymization)
- Audit log is append-only (no `UPDATE`/`DELETE` permissions in PostgreSQL)
- Secrets in `.env` only — `.env` is gitignored

---

## Project Structure

```
workmind-v2/
├── workmind-api/           # FastAPI backend
│   ├── app/
│   │   ├── api/routes/     # All HTTP route handlers
│   │   ├── agents/         # AI agent logic and model router
│   │   ├── db/             # SQLAlchemy models and migrations
│   │   ├── services/       # Business logic layer
│   │   ├── tasks/          # Celery tasks
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   └── main.py         # App factory and lifespan
│   ├── alembic/            # Database migrations
│   └── pyproject.toml      # Dependencies and build config
├── workmind-frontend/      # SvelteKit frontend
│   └── src/
│       ├── routes/(app)/   # Authenticated app pages
│       │   ├── admin/      # Admin panel pages
│       │   ├── chat/       # Chat interface
│       │   ├── products/   # Product catalogue
│       │   └── sales/      # Sales dashboard
│       └── lib/            # Shared components and stores
├── deploy/                 # Production deployment scripts
│   ├── install.sh          # One-shot server setup
│   ├── update.sh           # Zero-downtime update
│   ├── nginx.conf          # Nginx config (Tailscale TLS)
│   └── *.service           # systemd unit files
├── scripts/                # Maintenance scripts
│   └── backup_pg.sh        # PostgreSQL backup
├── .env.example            # Environment variable template
└── docker-compose.yml      # Docker Compose (alternative setup)
```

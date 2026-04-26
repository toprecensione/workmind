# WorkMind v2 — Software Architecture Document (SAD)

**Document Status:** Approved
**Version:** 2.0.0
**Last Updated:** 2026-04-26
**Authors:** WorkMind Engineering
**Audience:** Engineering, DevOps, Solutions Architects

---

## 1. Introduction

### 1.1 Purpose

This Software Architecture Document (SAD) provides a comprehensive architectural overview of the WorkMind v2 platform. It describes the system using multiple architectural views to capture the major architectural decisions which have been made on the system. WorkMind v2 is a multi-tenant, AI-augmented business assistant platform designed to integrate with multiple communication channels and provide domain-specific intelligence through pluggable client modules.

### 1.2 Scope

This document covers:
- The runtime architecture (process structure, communication, scaling)
- The logical architecture (module decomposition, layering)
- The data architecture (schema, persistence, vector storage)
- The deployment architecture (target environments)
- The cross-cutting concerns (security, logging, monitoring)

It does **not** cover:
- Detailed API contracts (see `docs/api/API_REFERENCE.md`)
- Database schema details (see `docs/architecture/DATABASE_SCHEMA.md`)
- Specific deployment procedures (see `docs/operations/DEPLOYMENT.md`)

### 1.3 Definitions and Acronyms

| Term | Definition |
|---|---|
| **Org** | Organization — top-level multi-tenant boundary |
| **Connector** | Pluggable integration with an external service (Telegram, SMTP, etc.) |
| **Skill** | Scheduled or event-driven automated capability |
| **Client (in this context)** | Domain-specific extension package, e.g. `clients/medic/` |
| **RAG** | Retrieval-Augmented Generation — LLM responses grounded in indexed docs |
| **TOTP** | Time-based One-Time Password (RFC 6238) |
| **SSE** | Server-Sent Events — unidirectional streaming over HTTP |
| **Sector** | Vertical/industry served by a Client (e.g. "medic", "retail") |

### 1.4 References

- Pydantic v2 docs: https://docs.pydantic.dev/2.0/
- SQLAlchemy 2.x async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- pgvector: https://github.com/pgvector/pgvector
- Anthropic API: https://docs.anthropic.com
- DeepSeek API: https://api-docs.deepseek.com

---

## 2. Architectural Goals and Constraints

### 2.1 Goals

| ID | Goal | Priority |
|---|---|---|
| G-1 | **Multi-tenancy by design** — every entity scoped by `org_id` | Must |
| G-2 | **Pluggable AI providers** — Claude/DeepSeek/Ollama swappable per request | Must |
| G-3 | **Pluggable client modules** — domain extensions without core changes | Must |
| G-4 | **Async-first I/O** — handle 100+ concurrent chat streams | Must |
| G-5 | **Privacy-preserving** — anonymization before external AI calls | Should |
| G-6 | **Observable** — structured logs + Prometheus metrics + audit trail | Must |
| G-7 | **Cost-aware** — daily budget per provider, automatic fallback | Should |
| G-8 | **Resilient** — graceful degradation when providers/services unavailable | Must |

### 2.2 Constraints

| ID | Constraint | Origin |
|---|---|---|
| C-1 | Python 3.13 minimum | Modern async features required |
| C-2 | PostgreSQL 16 + pgvector | Vector search performance |
| C-3 | Single-region deployment (Bender) | Current scale doesn't require global distribution |
| C-4 | Italian language primary; multilingual UI deferred | Target market = Italy |
| C-5 | Open-source publishable core | Public GitHub presence required |
| C-6 | GDPR compliance | EU user base |

### 2.3 Quality Attributes

| Attribute | Target |
|---|---|
| **Availability** | 99.5% (3.6h/month allowable downtime) |
| **Throughput** | 50 concurrent users, 200 RPS sustained |
| **Latency** | p95 < 500ms for non-AI endpoints; p95 < 8s for AI responses (first token) |
| **Durability** | RPO ≤ 24h (daily backup), RTO ≤ 2h |
| **Security** | OWASP Top 10 mitigated; SOC 2 readiness on roadmap |

---

## 3. Architectural Representation

This document uses the **4+1 view model** (Kruchten):

1. **Logical View** — module decomposition, classes
2. **Process View** — runtime processes, threading, communication
3. **Development View** — code organization, packaging
4. **Physical View** — deployment topology
5. **Scenarios** — key use cases that exercise the architecture

---

## 4. Logical View

### 4.1 Layered Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Presentation Layer                       │
│  SvelteKit SPA    │   Telegram Bot   │  WhatsApp Webhook   │
└─────────┬───────────────────┬───────────────────┬───────────┘
          │                   │                   │
┌─────────▼───────────────────▼───────────────────▼───────────┐
│                    API Gateway Layer                        │
│   FastAPI Routers (auth, chat, kb, conversations,           │
│   admin_*, channels/*, clients/*/routes.py)                 │
└─────────┬───────────────────────────────────────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────┐
│                    Service Layer                            │
│  ModelRouter │ Embedder │ Anonymizer │ FileParser           │
│  ConnectorRegistry │ SkillScheduler │ ChannelRouter         │
└─────────┬───────────────────────────────────────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────┐
│                    Data Access Layer                        │
│  SQLAlchemy 2.x async ORM │ asyncpg driver │ Redis client   │
└─────────┬───────────────────────────────────────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────┐
│                    Persistence Layer                        │
│   PostgreSQL 16 + pgvector  │  Redis 7  │  Local filesystem │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Module Decomposition

#### Core Platform (`workmind-api/app/`)

| Module | Responsibility | Key Files |
|---|---|---|
| `api/routes/` | HTTP endpoint definitions, request validation | 17 routers |
| `api/deps/` | Cross-cutting dependencies (rate limiter) | `limiter.py` |
| `services/` | Domain-agnostic business logic | `model_router.py`, `embedder.py`, `anonymizer.py` |
| `services/connectors/` | External integration adapters | `__init__.py` (registry), `catalog.py` |
| `services/skills/` | Scheduled capabilities | `__init__.py` (scheduler), `implementations/` |
| `db/` | ORM models, engine, CRUD helpers | `models.py`, `engine.py`, `crud/` |
| `tasks/` | Celery workers (long-running jobs) | `kb.py`, `maintenance.py`, `telegram_poll.py` |
| `agents/` | Multi-step AI agents (RAG, file analysis) | `orchestrator.py`, `data_agent.py` |
| `schemas/` | Pydantic DTOs separate from ORM | `chat.py`, `documents.py`, `admin.py` |

#### Client Extensions (`workmind-api/clients/<name>/`)

Each client follows this structure:

```
clients/medic/
├── __init__.py         # Empty - package marker
├── models.py           # SQLAlchemy models (use shared Base from app.db.base)
├── routes.py           # FastAPI router; exposes ROUTE_PREFIX + SECTOR
├── tasks.py            # Celery tasks (optional)
└── skills/             # Custom skills (optional)
    └── low_stock_alert.py
```

The dynamic loader in `app/main.py` discovers clients at startup:

```python
for _cpkg in sorted(_clients_dir.iterdir()):
    if not _cpkg.is_dir() or _cpkg.name.startswith("_"):
        continue
    _cmod = importlib.import_module(f"clients.{_cpkg.name}.routes")
    _prefix = getattr(_cmod, "ROUTE_PREFIX", f"/api/{_cpkg.name}")
    app.include_router(_cmod.router, prefix=_prefix, tags=[_cpkg.name])
```

This enables zero-touch addition of new clients: drop a directory, restart, done.

### 4.3 Key Design Patterns

| Pattern | Usage |
|---|---|
| **Dependency Injection** | FastAPI `Depends()` for auth, DB session, settings |
| **Singleton** | Engine, session factory, scheduler — module-level state |
| **Strategy** | `ModelRouter` selects provider based on config + budget |
| **Adapter** | Connector registry wraps Telegram/WhatsApp/SMTP APIs |
| **Observer** | Audit log entries written from all admin routes |
| **Repository** | `db/crud/` modules abstract SQLAlchemy queries |
| **Plugin** | Dynamic client loader at startup |

---

## 5. Process View

### 5.1 Runtime Components

```
┌──────────────────────────────────────────────────────────────────┐
│                      Bender Server (Linux)                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  systemd user services                                   │   │
│  │  ┌─────────────────┐  ┌─────────────────┐               │   │
│  │  │ workmind-api    │  │ workmind-staging│               │   │
│  │  │ (uvicorn :8000) │  │ (uvicorn :8001) │               │   │
│  │  └────────┬────────┘  └────────┬────────┘               │   │
│  │           │                    │                         │   │
│  │  ┌────────▼────────┐  ┌────────▼────────┐               │   │
│  │  │ workmind-celery │  │ workmind-beat   │               │   │
│  │  │ (Celery worker) │  │ (Celery beat)   │               │   │
│  │  └────────┬────────┘  └────────┬────────┘               │   │
│  │           │                    │                         │   │
│  │  ┌────────▼────────┐  ┌────────▼────────┐               │   │
│  │  │ prometheus :9090│  │ grafana   :3001 │               │   │
│  │  └─────────────────┘  └─────────────────┘               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Native services (apt-installed)                         │   │
│  │  postgresql-16 :5432  │  redis :6379  │  ollama :11434  │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Inter-process Communication

| From | To | Protocol | Notes |
|---|---|---|---|
| Browser | API | HTTPS (Tailscale Funnel) | JWT bearer auth |
| API | PostgreSQL | TCP | asyncpg, connection pool 20–40 |
| API | Redis | TCP | aioredis, connection pool 10 |
| API | Ollama | HTTP | localhost:11434, embeddings + local LLM |
| API | Anthropic | HTTPS | api.anthropic.com |
| API | DeepSeek | HTTPS | api.deepseek.com |
| API | Telegram | HTTPS (long-poll) | Bot API |
| Celery Worker | API DB/Redis | (same as API) | Shares config |
| Celery Beat | Redis | TCP | Schedule storage |
| Prometheus | API `/metrics` | HTTP | Pull every 15s |

### 5.3 Concurrency Model

- **Web tier**: Single uvicorn process, single worker, asyncio event loop. ~1000 concurrent connections supported.
- **Background tier**: Celery worker, prefork pool, 4 processes by default.
- **Scheduler tier**: APScheduler in-process within API. Dedicated worker for I/O-bound skills.

**Why single-process API?** Current scale (50 users) doesn't justify horizontal scaling. When needed, switch to gunicorn with multiple uvicorn workers + sticky sessions for SSE.

### 5.4 Lifespan Sequence

```
[startup]
  1. Load Settings (Pydantic, validates env vars)
  2. Initialize DB engine + session factory (engine.init_engine)
  3. Configure encryption (load Fernet key from settings.workmind_secret_key)
  4. Initialize ConnectorRegistry (caches loaded from DB on demand)
  5. Start SkillScheduler (APScheduler, AsyncIOScheduler)
  6. Reload skill jobs from DB
  7. Start Celery beat (separate process, reads same DB)
  8. Mount static SPA (build artifacts from SvelteKit)
  9. Register Prometheus metrics
 10. Begin accepting requests

[shutdown — SIGTERM]
  1. Stop accepting new connections
  2. Wait for in-flight requests (drain timeout = 30s)
  3. Stop SkillScheduler
  4. Close DB engine
  5. Close Redis pool
  6. Flush logs
```

---

## 6. Development View

### 6.1 Repository Structure

```
workmind-v2/
├── workmind-api/           # FastAPI backend
│   ├── app/                # Core platform code
│   ├── clients/            # Domain extensions (private repo only)
│   ├── tests/              # Pytest test suite
│   ├── alembic/            # Database migrations
│   └── pyproject.toml      # Dependencies + tooling config
├── workmind-frontend/      # SvelteKit SPA
│   ├── src/
│   │   ├── lib/           # Shared components, stores, API client
│   │   ├── routes/        # Page components (file-based routing)
│   │   │   ├── (app)/     # Authenticated pages, shared layout
│   │   │   └── (medic)/   # MEDIC-specific pages (private repo only)
│   │   └── app.html       # HTML shell
│   └── vite.config.js
├── workmind-worker/        # Reserved for separate worker images
├── deploy/                 # Deployment scripts + systemd units
├── scripts/                # Operational utilities (migrate, backup, seed)
├── docs/                   # Documentation (this directory)
└── docker-compose.yml      # Local dev environment
```

### 6.2 Two-Repository Strategy

| Repo | Visibility | Contents |
|---|---|---|
| `github.com/toprecensione/workmind` | Public | Core platform only (clients/* stripped) |
| `github.com/toprecensione/workmind-platform` | Private | Full platform with clients/medic/, deploy artifacts |

The `deploy/publish-core.sh` script automates publishing core to the public repo via orphan branch (clean history, no secrets).

### 6.3 Dependency Management

- **Backend**: `pyproject.toml` with PEP 621 metadata, `setuptools.build_meta` backend
- **Frontend**: `package.json` with npm; SvelteKit 2.x, Vite 5.x
- **Versioning**: SemVer applied to platform releases (v2.0.0 = current)

### 6.4 Tooling

| Tool | Purpose |
|---|---|
| `ruff` | Linting + formatting (single tool, replaces flake8 + isort + black) |
| `mypy` | Type checking (config in pyproject.toml: `strict = false`) |
| `pytest` + `pytest-asyncio` | Test runner |
| `alembic` | Schema migrations (autogenerate disabled — handcrafted only) |
| `pre-commit` | Git hooks (planned) |
| GitHub Actions | CI: test + lint on every PR |

---

## 7. Physical View (Deployment)

### 7.1 Deployment Topology

```
                    ┌─────────────────────────┐
                    │  Tailscale Funnel       │
                    │  (public HTTPS gateway) │
                    │  workmind-bender.tail.. │
                    └────────────┬────────────┘
                                 │ :443
                    ┌────────────▼────────────┐
                    │   Bender (Linux server) │
                    │   - Native Postgres     │
                    │   - Native Redis        │
                    │   - Native Ollama       │
                    │   - systemd user units  │
                    │     for API, Celery,    │
                    │     Prometheus, Grafana │
                    └─────────────────────────┘
```

Staging is exposed only on the Tailscale tailnet (not Funnel). Grafana likewise.

### 7.2 Environments

| Env | URL | Branch | Purpose |
|---|---|---|---|
| **Production** | https://workmind-bender.tail898ef4.ts.net | `master` | Customer-facing |
| **Staging** | https://staging.workmind-bender.tail898ef4.ts.net | `master` (separate DB) | Pre-production validation |
| **Dev** | http://localhost:8000 | feature branches | Local development |

### 7.3 Persistence

| Service | Path | Backup Strategy |
|---|---|---|
| PostgreSQL | `/var/lib/postgresql/16/main` | `pg_dump` daily 02:30, 30-day retention, monthly copy on 1st |
| Redis | `/var/lib/redis` | RDB snapshots (in-memory, ephemeral) |
| Uploads | `~/workmind-v2/workmind-api/uploads/` | rsync to backup volume daily |
| Ollama models | `~/.ollama/models/` | Not backed up (re-pullable) |

### 7.4 Network Architecture

- **Public**: Tailscale Funnel exposes API only (port 443 → 8000)
- **Tailnet-only**: Staging API (8001), Grafana (3001), Prometheus (9090)
- **Localhost-only**: Postgres (5432), Redis (6379), Ollama (11434)

---

## 8. Scenarios (Key Use Cases)

### 8.1 Scenario: User sends a chat message with RAG

```
Browser → POST /api/chat/stream {message, conversation_id}
  ↓
FastAPI router (chat.py)
  ↓ verify JWT, load org/user
  ↓ load conversation (org-scoped)
  ↓ persist user message
  ↓ anonymize message → AnonymizationSession
  ↓ embed query (Ollama via embedder.py)
  ↓ similarity_search top-K chunks (pgvector)
  ↓ build prompt with context + history
  ↓ ModelRouter.complete_stream(messages)
  ↓   choose provider: Claude (if budget OK) → DeepSeek (fallback) → Ollama (last resort)
  ↓   open SSE stream to provider
  ↓ relay tokens to browser via SSE
  ↓ on end: persist final assistant message + cost
  ↓ deanonymize tokens before sending to browser
```

**Key architectural decisions:**
- Anonymization happens *before* external API calls
- Vector search is sync within a single async call (no separate worker)
- Streaming uses SSE (not WebSockets) to allow simple HTTP/2 multiplexing
- Cost tracking is per-message via `Message.cost_usd` field

### 8.2 Scenario: Admin enables a connector

```
Browser → PUT /api/admin/connectors/telegram {config: {bot_token, ...}}
  ↓
FastAPI (admin_connectors.py)
  ↓ require_admin()
  ↓ encrypt config dict (Fernet, key from settings)
  ↓ upsert Connector row (config_enc field)
  ↓
Browser → POST /api/admin/connectors/telegram/enable
  ↓ set Connector.is_enabled = True
  ↓
Browser → POST /api/admin/connectors/telegram/test
  ↓ ConnectorRegistry.test_connector() — live ping
  ↓ update status + tested_at in DB
```

The connector is now available for skills (e.g., `telegram_notifications` skill reads from this connector).

### 8.3 Scenario: Skill execution (low-stock alert)

```
APScheduler fires (every 4 hours)
  ↓
make_low_stock_job(org_id, cfg)() coroutine runs
  ↓ open DB session
  ↓ SELECT products WHERE stock_qty <= low_stock_threshold AND org_id = :org
  ↓ if any found:
  ↓   ConnectorRegistry.get_config(db, org, "telegram")
  ↓   call Telegram API to send alert
  ↓ log skill_execution row in audit_log
```

If skill fails, exception is logged but doesn't crash scheduler. Next scheduled run still happens.

### 8.4 Scenario: New client onboarding (e.g. "retail")

```
1. Developer creates clients/retail/ directory:
     models.py    → RetailProduct, RetailOrder, ...
     routes.py    → router with ROUTE_PREFIX="/api/retail" + SECTOR="retail"
     skills/      → custom retail skills

2. Developer creates Alembic migration for retail tables.

3. Developer creates SvelteKit (retail) route group with retail-specific pages.

4. Build with VITE_CLIENT=retail to enable retail nav in Sidebar.

5. Restart API → main.py auto-discovers clients/retail/routes.py and mounts it.

6. No core changes required.
```

---

## 9. Cross-Cutting Concerns

### 9.1 Security Architecture

See `docs/security/SECURITY.md` for full details.

Summary:
- **Authentication**: Multi-layered (API key → JWT → 2FA TOTP)
- **Authorization**: RBAC with roles {user, admin, owner, supervisor}
- **Encryption at rest**: Fernet for connector configs; bcrypt for passwords
- **Encryption in transit**: TLS via Tailscale Funnel; localhost-only for internal services
- **Audit**: All admin actions logged to `audit_log` table

### 9.2 Logging Strategy

- **Structured**: structlog produces JSON logs with `request_id`, `user_id`, `org_id` context
- **Levels**: DEBUG (dev only), INFO (default), WARNING, ERROR
- **Sinks**: stdout (captured by systemd journal); file rotation handled by journald

### 9.3 Monitoring

- **Metrics**: Prometheus scrapes `/metrics` every 15s
- **Dashboards**: Grafana with custom dashboards for API, AI cost, DB pool, system
- **Alerting**: Planned (Alertmanager or Grafana alerting)

### 9.4 Configuration

- **Source of truth**: environment variables (Pydantic Settings)
- **Hierarchy**: `.env` (local dev) → `.env.staging` → `.env.production` → `.env.bender`
- **Secrets**: Never committed; loaded from systemd `EnvironmentFile=`
- **Hot reload**: Settings cached via `@lru_cache`; restart API to apply changes

### 9.5 Internationalization

- **Backend**: Italian primary; English log messages
- **Frontend**: Italian UI strings hardcoded for now; i18n framework planned

---

## 10. Architectural Decisions (ADRs Summary)

| ADR | Decision | Rationale |
|---|---|---|
| ADR-001 | Use FastAPI instead of Flask/Django | Async-first; auto OpenAPI; Pydantic integration |
| ADR-002 | Async SQLAlchemy with asyncpg | Required for asyncio web tier; mature in 2.x |
| ADR-003 | pgvector instead of separate vector DB (Pinecone, Weaviate) | Simplicity; co-located with relational data |
| ADR-004 | APScheduler in-process | Avoid extra ops surface for cron-style jobs; Celery beat reserved for queue jobs |
| ADR-005 | Multi-client via dynamic loader | Zero-touch onboarding; clients are independent dirs |
| ADR-006 | SSE for chat streaming, not WebSockets | HTTP/2 multiplexing; simpler proxying |
| ADR-007 | Tailscale Funnel instead of public LB + ACME | Faster setup; better access control for staging |
| ADR-008 | Ollama for embeddings (768-dim nomic-embed-text) | Free, fast, runs on Bender CPU |
| ADR-009 | bcrypt for passwords (work factor 12) | Industry standard; Python implementation maintained |
| ADR-010 | systemd user units for services | No root required; per-user isolation; `loginctl enable-linger` for persistence |

---

## 11. Risks and Open Questions

### 11.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Single-region deployment fails | Low | High | Document RTO/RPO; restore from `pg_dump` to alt host |
| Bender hardware failure | Medium | High | Daily backups offsite (planned: rclone to S3) |
| AI provider API changes | High | Medium | Version-pinned models; integration tests would help |
| pgvector index slow at >1M chunks | Medium | Medium | Switch to HNSW (already in 0007 migration); tune `m`, `ef_construction` |
| Skill scheduler crashes | Low | High | Validation needed (see code review SKL-1) |

### 11.2 Open Questions

- Should we add OpenTelemetry distributed tracing in 2026 H2?
- Should `clients/*` directory be moved out of `workmind-api/` to better signal it's a separate concern?
- Should we adopt PostgreSQL logical replication for read scaling?
- Should encrypted secrets migrate from Fernet to a vault (HashiCorp Vault, AWS KMS)?

---

## 12. Appendices

### 12.1 Component Catalog

#### A. Routers (FastAPI)

| Router | Path Prefix | Purpose | Auth |
|---|---|---|---|
| `auth` | `/api/auth` | Login, refresh, logout | None |
| `auth_2fa` | `/api/auth/2fa` | TOTP setup/confirm/challenge/disable | JWT (or temp_token) |
| `auth_reset` | `/api/auth` | Password reset flow | None |
| `chat` | `/api/chat` | Send messages, stream responses | JWT |
| `conversations` | `/api/conversations` | CRUD on conversations | JWT |
| `kb` | `/api/kb` | Document upload, search | JWT |
| `teach` | `/api/teach` | Train memories from text | JWT |
| `health` | `/health`, `/ready`, `/metrics` | Liveness/readiness/Prometheus | None |
| `channels/telegram` | `/api/channels/telegram` | Telegram webhook | Webhook secret |
| `channels/whatsapp` | `/api/channels/whatsapp` | WhatsApp webhook | Verify token |
| `admin` | `/api/admin` | Admin dashboard data | JWT + admin role |
| `admin_users` | `/api/admin/users` | User management | JWT + admin role |
| `admin_connectors` | `/api/admin/connectors` | Connector config | JWT + admin role |
| `admin_skills` | `/api/admin/skills` | Skill enable/disable | JWT + admin role |
| `admin_kb` | `/api/admin/kb` | KB document management | JWT + admin role |
| `admin_audit` | `/api/admin/audit` | Audit log viewer | JWT + admin role |
| `admin_system` | `/api/admin/system` | System health, AI usage | JWT + admin role |
| `admin_backup` | `/api/admin/backup` | Backup trigger, list | JWT + admin role |
| `admin_ai_actions` | `/api/admin/ai-actions` | AI action config | JWT + admin role |
| `clients/medic/routes` | `/api/medic` | MEDIC inventory, sales, agents | JWT |

#### B. Services

| Service | Module | Responsibility |
|---|---|---|
| **ModelRouter** | `services/model_router.py` | Provider selection, retry, streaming |
| **Embedder** | `services/embedder.py` | Embeddings via Ollama |
| **Anonymizer** | `services/anonymizer.py` | PII anonymization with reversible session |
| **FileParser** | `services/file_parser.py` | PDF, DOCX, XLSX, DXF text extraction |
| **Chunker** | `services/chunker.py` | Document chunking for embeddings |
| **EncryptionService** | `services/encryption.py` | Fernet encrypt/decrypt for connector configs |
| **EmailService** | `services/email.py` | SMTP send (password reset, alerts) |
| **ConnectorRegistry** | `services/connectors/__init__.py` | Live test, get config, dispatch |
| **SkillScheduler** | `services/skills/__init__.py` | APScheduler wrapper |
| **ChannelRouter** | `services/channel_router.py` | Route incoming messages from any channel |

---

**End of Document**

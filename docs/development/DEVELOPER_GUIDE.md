# WorkMind v2 — Developer Guide

**Audience:** Backend, frontend, and full-stack engineers contributing to WorkMind
**Skill prerequisite:** Python 3.13, async/await, FastAPI, SQLAlchemy 2.x, basic SvelteKit

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Project Layout](#2-project-layout)
3. [Local Development](#3-local-development)
4. [Coding Standards](#4-coding-standards)
5. [Database Workflow](#5-database-workflow)
6. [Adding New Features](#6-adding-new-features)
7. [Adding a New Client](#7-adding-a-new-client)
8. [Frontend Development](#8-frontend-development)
9. [Working with AI Providers](#9-working-with-ai-providers)
10. [Pull Request Process](#10-pull-request-process)

---

## 1. Getting Started

### 1.1 Clone & Setup

```bash
# Public core
git clone https://github.com/toprecensione/workmind.git
# or full platform (private)
git clone git@github-platform:toprecensione/workmind-platform.git workmind-v2

cd workmind-v2
```

### 1.2 Python Environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate     # Linux/Mac
# or
.venv\Scripts\activate        # Windows PowerShell

cd workmind-api
pip install -e ".[dev]"
```

### 1.3 Required Services

You need running locally:
- **PostgreSQL 16** with `pgvector` extension
- **Redis 7+**
- **Ollama** with `nomic-embed-text` model

Quick setup via Docker Compose:

```bash
docker compose -f docker-compose.yml up -d
```

This starts Postgres, Redis, and Ollama (the application itself runs natively for hot-reload).

### 1.4 Environment Variables

```bash
cp .env.example .env
# Edit .env with your credentials
```

Minimum required:
- `DATABASE_URL`
- `REDIS_URL`
- `WORKMIND_SECRET_KEY` (any 32+ char random string)
- `WORKMIND_DEEPSEEK_API_KEY` or `WORKMIND_ANTHROPIC_API_KEY`

### 1.5 First Run

```bash
# Apply migrations
cd workmind-api
alembic upgrade head

# Seed test data (optional)
python ../scripts/seed_medic.py

# Run dev server
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the OpenAPI Swagger UI.

### 1.6 Frontend Dev Server

```bash
cd workmind-frontend
npm install
npm run dev
# Opens http://localhost:5173 (proxies API to localhost:8000)
```

---

## 2. Project Layout

```
workmind-v2/
├── workmind-api/                # FastAPI backend
│   ├── app/
│   │   ├── main.py              # App factory, middleware, lifespan
│   │   ├── config.py            # Pydantic Settings
│   │   ├── dependencies.py      # Auth, current_user
│   │   ├── api/
│   │   │   └── routes/          # FastAPI routers (one file per resource)
│   │   ├── services/            # Business logic, external integrations
│   │   ├── db/
│   │   │   ├── base.py          # SQLAlchemy Base
│   │   │   ├── engine.py        # Session factory
│   │   │   ├── models.py        # ORM models
│   │   │   └── crud/            # Query helpers
│   │   ├── tasks/               # Celery tasks
│   │   ├── agents/              # Multi-step AI agents
│   │   └── schemas/             # Pydantic DTOs
│   ├── clients/                 # Client extensions (private repo only)
│   │   └── medic/
│   │       ├── models.py        # MEDIC-specific tables
│   │       ├── routes.py        # /api/medic/* endpoints
│   │       └── ...
│   ├── tests/                   # Pytest test suite
│   ├── alembic/                 # Database migrations
│   └── pyproject.toml
│
├── workmind-frontend/           # SvelteKit SPA
│   ├── src/
│   │   ├── routes/              # File-based routing
│   │   │   ├── (app)/           # Auth-protected pages
│   │   │   └── (medic)/         # MEDIC-only pages
│   │   ├── lib/                 # Components, stores, API client
│   │   └── app.html             # HTML shell
│   └── package.json
│
├── deploy/                      # systemd units, scripts
├── scripts/                     # Operational utilities
├── docs/                        # Documentation
└── docker-compose.yml
```

---

## 3. Local Development

### 3.1 Hot Reload

```bash
# Backend (auto-reloads on file change)
uvicorn app.main:app --reload --port 8000

# Frontend (HMR via Vite)
cd workmind-frontend && npm run dev
```

### 3.2 Running Tests

```bash
cd workmind-api
pytest tests/ -v                           # All tests
pytest tests/test_auth.py -v               # Single file
pytest tests/test_2fa.py::TestTotpSetup -v # Single class
pytest -k "totp" -v                        # Match by name
pytest --cov=app --cov-report=html         # Coverage report
```

The test suite uses a **separate database** (`workmind_test`) — never the dev DB.

### 3.3 Linting & Formatting

```bash
ruff check app/ clients/ tests/   # Lint
ruff check --fix .                # Auto-fix
ruff format app/ clients/         # Format
```

CI runs `ruff check app/ clients/ --select E,W,F --ignore E501` and fails on errors.

### 3.4 Type Checking

```bash
mypy app/
```

mypy is configured with `strict = false`; gradually adopt stricter typing in new modules.

### 3.5 Database Inspection

```bash
psql postgresql://workmind:Wm2026Bender!Pg@localhost:5432/workmind
```

Useful queries:

```sql
\dt                                  -- list tables
\d users                             -- describe table
SELECT * FROM alembic_version;       -- current migration
SELECT * FROM users LIMIT 5;
```

### 3.6 Celery Worker (when needed)

For tasks that use Celery (KB indexing, scheduled jobs):

```bash
celery -A app.tasks.celery_app worker --loglevel=info
celery -A app.tasks.celery_app beat --loglevel=info
```

---

## 4. Coding Standards

### 4.1 Python

- **Type hints everywhere.** Use `from __future__ import annotations` for cleaner forward refs.
- **Async by default** for I/O. Use sync only when calling sync libraries.
- **Pydantic v2** for all DTOs. Use `model_config = {"from_attributes": True}` (not `class Config:`).
- **f-strings** for string formatting.
- **Pathlib** for paths, not `os.path`.
- **logging via structlog**, not `print()`.

### 4.2 Naming

| Element | Convention | Example |
|---|---|---|
| Variable | `snake_case` | `user_id`, `created_at` |
| Function | `snake_case` | `create_user()`, `get_user_by_id()` |
| Class | `PascalCase` | `UserOut`, `ConnectorRegistry` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_FILE_SIZE`, `JWT_ALGORITHM` |
| Module | `snake_case` | `model_router.py`, `auth_2fa.py` |
| Private | `_leading_underscore` | `_hash_password()`, `_settings_cache` |

Avoid single-letter variables except in lambdas or comprehensions where context is clear.

### 4.3 File Structure (Python module)

```python
"""Module docstring (one line summary)."""
from __future__ import annotations

# 1. Standard library
import os
from datetime import datetime
from typing import Optional
from uuid import UUID

# 2. Third-party
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 3. Local
from app.db.engine import get_db_session
from app.db.models import User
from app.dependencies import get_current_user, CurrentUser

log = structlog.get_logger()
router = APIRouter()

# Constants
MAX_PAGE_SIZE = 100

# ── Schemas ───────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: UUID
    email: str

# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_email(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()

# ── Routes / Public API ───────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(...):
    ...
```

### 4.4 Error Handling

- **HTTPException** for client-facing errors (400, 401, 403, 404, 409, 422)
- **structlog.error()** before raising 500s, with context (`user_id`, `org_id`, exception)
- **Catch-and-rethrow** is OK if you add useful context; never silently swallow
- **Validation errors** should rely on Pydantic; don't reinvent

### 4.5 Database Access Patterns

✅ **Good — use ORM:**
```python
result = await db.execute(
    select(User).where(User.org_id == org_id, User.is_active.is_(True))
)
users = result.scalars().all()
```

❌ **Bad — string interpolation:**
```python
result = await db.execute(text(f"SELECT * FROM users WHERE org_id = '{org_id}'"))  # SQL injection!
```

✅ **Good — bound parameters in raw SQL:**
```python
result = await db.execute(
    text("SELECT * FROM users WHERE org_id = :org"),
    {"org": org_id},
)
```

**Always commit explicitly:**
```python
db.add(new_user)
await db.commit()
await db.refresh(new_user)  # reload from DB
```

**Multi-tenancy:** Always filter by `org_id`. Add a comment if it seems redundant.

### 4.6 Logging

```python
log.info("user_created", user_id=str(user.id), org_id=str(user.org_id))
log.warning("ai_provider_failed", provider="claude", error=str(exc))
log.error("payment_failed", user_id=str(user.id), reason="invalid_card")
```

Keys are snake_case. Values must be JSON-serializable (str, int, bool, dict, list).

**Never log:**
- Passwords, tokens, API keys
- Full message contents (could contain PII)
- Email addresses (use `email_hash` instead)

### 4.7 Comments

- Code explains *what*. Comments explain *why* (when not obvious).
- TODO/FIXME comments include a name and date: `# TODO(emanuele 2026-04): fix N+1 query`
- No commented-out code in commits — use git history.

### 4.8 Italian vs. English

Current convention:
- **Code** (variables, functions, comments) → English
- **API error messages** → Italian (user-facing in EU market)
- **Docstrings** → Italian for now; English encouraged for OSS contributions

This may change as the codebase becomes more public.

---

## 5. Database Workflow

### 5.1 Creating a Migration

Migrations are **handcrafted**, not autogenerated.

```bash
cd workmind-api
alembic revision -m "add foo table"
```

Edit the generated file in `alembic/versions/`:

```python
def upgrade() -> None:
    op.create_table(
        "foos",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    )
    op.create_index("idx_foos_org", "foos", ["org_id"])

def downgrade() -> None:
    op.drop_index("idx_foos_org")
    op.drop_table("foos")
```

### 5.2 Adding the Model

In `app/db/models.py`:

```python
class Foo(Base):
    __tablename__ = "foos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 5.3 Apply & Test

```bash
alembic upgrade head
pytest tests/ -v             # Tests should still pass
```

### 5.4 Rolling Back

```bash
alembic downgrade -1
```

If a migration cannot be downgraded cleanly, document this in the migration file:

```python
def downgrade() -> None:
    raise NotImplementedError("Forward-only migration; restore from backup if needed")
```

---

## 6. Adding New Features

### 6.1 Adding an Endpoint

1. **Pick or create a router** in `app/api/routes/`
2. **Define Pydantic schemas** for request/response (in `app/schemas/` or inline)
3. **Implement the handler** with auth + DB session deps
4. **Add tests** in `tests/test_<module>.py`
5. **Update `docs/api/API_REFERENCE.md`** if user-facing

Example minimal endpoint:

```python
class FooCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)

class FooOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    model_config = {"from_attributes": True}

@router.post("/foos", response_model=FooOut, status_code=201)
async def create_foo(
    body: FooCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    foo = Foo(org_id=user.org_id, name=body.name)
    db.add(foo)
    await db.commit()
    await db.refresh(foo)
    log.info("foo_created", user_id=str(user.user_id), foo_id=str(foo.id))
    return foo
```

### 6.2 Adding a Service

A service is a class or set of functions in `app/services/`. Examples: `embedder.py`, `anonymizer.py`.

Guidelines:
- Single responsibility
- Stateless or with explicit lifecycle (start/close)
- Async if it does I/O
- Doesn't import from `api/routes/` (one-way dependency: routes → services → db)

### 6.3 Adding a Skill

1. Create `app/services/skills/implementations/<name>.py`
2. Implement `make_<name>_job(org_id: str, cfg: dict) -> Coroutine`
3. Register in `app/services/skills/implementations/__init__.py` `get_skill_jobs()` with a case
4. Add to `app/services/skills/catalog.py` (id, name, description, default config)
5. Add tests

### 6.4 Adding a Connector

1. Add `ConnectorDef` entry to `app/services/connectors/catalog.py`
2. Add a `_test_<type>()` function in `app/services/connectors/__init__.py`
3. Add a case in `_test_dispatch()`
4. Document fields in API reference

---

## 7. Adding a New Client

Client = domain extension package (e.g., `medic`, `retail`, `legal`).

### 7.1 Backend

```bash
mkdir -p workmind-api/clients/<name>/skills
touch workmind-api/clients/<name>/{__init__,models,routes,tasks}.py
```

`models.py`:
```python
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base   # SHARED Base — critical

class RetailProduct(Base):
    __tablename__ = "retail_products"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # ...
```

`routes.py`:
```python
from fastapi import APIRouter

router = APIRouter()
ROUTE_PREFIX = "/api/retail"   # required for dynamic loader
SECTOR = "retail"              # required for dynamic loader

@router.get("/products")
async def list_products(...):
    ...
```

The dynamic loader in `main.py` will pick this up at startup. No core changes needed.

### 7.2 Migration

Create migration for the client tables. Mark them clearly:

```python
def upgrade():
    # MEDIC-specific tables
    op.create_table("medic_products", ...)
```

### 7.3 Frontend

```bash
mkdir -p workmind-frontend/src/routes/\(<name>\)
```

Add `+layout.svelte` (copy from `(app)/+layout.svelte`) and pages.

In `Sidebar.svelte`, conditionally show the client's nav items:

```javascript
const CLIENT = import.meta.env.VITE_CLIENT || 'core';
const isRetail = CLIENT === 'retail';

const navItems = [
    ...(isRetail ? [
        { href: '/products', label: 'Prodotti', icon: 'archive' },
        // ...
    ] : []),
];
```

### 7.4 Build

```bash
VITE_CLIENT=retail npm run build
```

The build artifact contains the retail nav and pages.

---

## 8. Frontend Development

### 8.1 Stack

- **SvelteKit 2.x** — file-based routing, layouts
- **Vite** — dev server, HMR
- **No CSS framework** — vanilla CSS in components (small footprint)
- **Stores** — Svelte built-in stores in `lib/stores.js`

### 8.2 API Client

`src/lib/api.js` is a thin wrapper around `fetch`:

```javascript
export async function api(path, options = {}) {
    const res = await fetch(`/api${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getToken()}`,
            ...options.headers,
        },
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
    }
    return res.json();
}
```

### 8.3 Routing Conventions

| Route | Auth | Layout |
|---|---|---|
| `/login`, `/forgot-password`, `/reset-password` | No | base |
| `(app)/*` | Yes | sidebar |
| `(medic)/*` | Yes + medic role | sidebar |
| `(app)/admin/*` | Yes + admin role | sidebar |

The `+layout.svelte` in `(app)/` checks auth and redirects to `/login` if missing.

### 8.4 Streaming Chat (SSE)

```javascript
async function sendStream(message) {
    const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { /* ... */ },
        body: JSON.stringify({ message }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Parse SSE events: "event: token\ndata: {...}\n\n"
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';
        for (const ev of events) {
            const data = parseSSE(ev);
            if (data?.text) appendToLast(data.text);
        }
    }
}
```

### 8.5 Building

```bash
npm run build            # Production build (static)
npm run preview          # Preview production build
```

Output goes to `build/` and is served by the FastAPI app at `/`.

---

## 9. Working with AI Providers

### 9.1 Calling the Model Router

```python
from app.services.model_router import get_model_router

router = get_model_router(settings, db_factory)
response = await router.complete(
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ],
    org_id=str(user.org_id),
    user_id=str(user.user_id),
    model_preference="claude-sonnet",  # optional
)
print(response.content, response.cost_usd)
```

### 9.2 Streaming

```python
async for chunk in router.complete_stream(messages, ...):
    if chunk.kind == "token":
        yield chunk.text
    elif chunk.kind == "done":
        cost = chunk.cost_usd
```

### 9.3 Cost Awareness

Each call is recorded in `model_usage` table with:
- provider, model
- tokens_in, tokens_out
- cost_usd (computed from pricing table)

Daily budget enforced: if today's cumulative cost > `WORKMIND_MAX_DAILY_COST_USD`, request fails with 429.

### 9.4 Adding a New Provider

1. Add config fields to `Settings` (`api_key`, `base_url`)
2. Add pricing entries to `_PRICING` dict in `model_router.py`
3. Implement `_call_<provider>_complete()` and `_stream_<provider>()`
4. Register provider name in router selection logic

---

## 10. Pull Request Process

### 10.1 Branch Naming

- `feat/<short-name>` — new feature
- `fix/<short-name>` — bug fix
- `chore/<short-name>` — non-functional changes
- `docs/<short-name>` — documentation only

### 10.2 Commit Messages

Follow Conventional Commits:

```
feat(chat): add SSE streaming endpoint

Implement /api/chat/stream that returns text/event-stream.
Frontend updated with sendStream() in stores.

Closes #42
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `perf`.

Subject ≤72 chars, imperative mood, no trailing period.

### 10.3 PR Checklist

- [ ] Tests added/updated
- [ ] `pytest tests/` passes locally
- [ ] `ruff check` passes
- [ ] Migrations included if schema changed
- [ ] API reference updated if endpoint added/changed
- [ ] No secrets in commits (`git diff` review)
- [ ] PR description explains the **why**, not just the **what**

### 10.4 Code Review

- Self-review your diff before requesting review
- Reviewers focus on:
  - Correctness (does the code work?)
  - Security (injection, auth, data leaks?)
  - Performance (N+1 queries, blocking calls?)
  - Maintainability (naming, structure, comments?)
- Resolve all comments or explicitly defer with a follow-up issue

### 10.5 Merging

- **Squash and merge** for feature branches (clean history)
- **Rebase and merge** for chains of related commits
- **Never merge commit messages** — they pollute history

After merge:
- Delete the branch
- Verify CI passes on master
- Watch for any post-deploy errors

---

## Appendix A: Common Pitfalls

| Pitfall | Fix |
|---|---|
| Forgetting `await` on async call | Will return a coroutine object; tests should catch |
| Not committing the session | Changes lost; always `await db.commit()` |
| Mixing sync & async | Sync functions in async routes block the event loop |
| Forgetting `org_id` filter | Multi-tenant leak; review every query |
| Hardcoding strings (org IDs, API keys) | Use Settings or DB lookups |
| Catching too broadly | `except Exception:` hides bugs; catch specific types |
| Long-running tasks in HTTP handlers | Use Celery; HTTP requests should be <30s |

---

## Appendix B: Useful Resources

- [FastAPI docs](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.x async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Pydantic v2 migration](https://docs.pydantic.dev/2.0/migration/)
- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [pgvector usage](https://github.com/pgvector/pgvector)
- [SvelteKit docs](https://kit.svelte.dev/docs)
- [Anthropic API](https://docs.anthropic.com/)

---

**Welcome to the WorkMind team. Build well.**

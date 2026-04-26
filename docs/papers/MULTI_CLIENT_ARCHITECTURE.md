# Multi-Client Architecture in WorkMind v2

**Type:** Technical Whitepaper
**Audience:** Architects, technical leadership, prospective integrators
**Date:** 2026-04-26
**Authors:** WorkMind Engineering

---

## Abstract

WorkMind v2 is built around a core platform that serves diverse industries through pluggable, domain-specific extensions called **Clients**. This paper describes the architectural approach that allows WorkMind to:

- Maintain a single, cohesive core codebase published as open source
- Support proprietary, customer-specific extensions without forking
- Enable rapid onboarding of new vertical markets (medical, legal, retail, manufacturing, etc.)
- Deploy a single binary that adapts behavior at runtime based on which Clients are present
- Keep operational complexity flat regardless of Client count

The result is a platform that scales **horizontally across verticals** without scaling complexity proportionally.

---

## 1. The Problem

Most vertical SaaS solutions face a tension between three competing demands:

1. **Domain depth** — Each industry has unique workflows, terminology, and regulations. A medical SaaS must understand drug lots, expiry dates, and prescription regulations. A legal SaaS must handle case management, billable hours, and bar associations.

2. **Engineering economy** — Building a separate platform for each industry multiplies development cost, infrastructure overhead, and maintenance burden.

3. **Open ecosystem** — Customers increasingly want transparency (open core) and the ability to contribute or audit code.

Traditional approaches:

| Approach | Problem |
|---|---|
| **One platform, all features built in** | Codebase bloats; UI complexity; users see irrelevant features |
| **Per-industry forks** | Diverging codebases; security patches duplicated; can't share improvements |
| **Whitelabel with feature flags** | Flag explosion; runtime branching everywhere; hard to test combinations |
| **Microservices per domain** | Operational overhead; integration complexity |

WorkMind takes a different approach: **Pluggable Clients**.

---

## 2. The Concept of a Client

In WorkMind terminology, a **Client** is a self-contained domain extension package that lives alongside the core platform but extends it with vertical-specific:

- Database tables
- API endpoints
- Background tasks (Celery)
- Scheduled skills
- Frontend pages and navigation

A Client is **not**:

- A separate microservice (it runs in-process with the core)
- A plugin in the traditional sense (no dynamic loading from .so/.dll)
- A theme or branding skin (Clients have full backend logic)

A Client **is**:

- A directory of code (Python + Svelte) following a contract
- Loaded at process startup via Python `importlib`
- Free to use the core's services (DB, AI, connectors, skills) but doesn't modify them
- Subject to the same multi-tenancy, security, and observability rules as the core

---

## 3. Architectural Decision Record

### ADR-005: Adopt the Pluggable Clients Pattern

**Status:** Accepted (2026-04)

**Context:**
WorkMind's first customer is MEDIC, a medical/pharmaceutical distribution company with detailed inventory management needs (lots, expiry dates, FIFO consumption, agent warehouses). We anticipate adding other verticals (retail, legal, manufacturing) without rewriting the core.

**Decision:**
We will introduce a `clients/` package directory at the same level as the core `app/` package. Each subdirectory is a Client. The core's `main.py` discovers and loads Clients at startup using Python's `importlib`.

**Consequences:**

✅ Positive:
- Adding a new Client requires no core changes
- Clients can be developed in isolation by separate teams
- Public open-source release strips Clients via build script (`publish-core.sh`)
- Each Client owns its data model, fully testable in isolation

⚠️ Negative:
- Clients share the same database (multi-Client deployments need careful naming)
- Clients can in principle introduce conflicts (e.g., two Clients defining the same SQLAlchemy table name)
- Frontend must be built per-Client (`VITE_CLIENT=<name>`) for client-specific UI

🔮 Future considerations:
- Could evolve to load Clients dynamically (drop-in plugin) in 3.x
- May require Client compatibility checks (declared core API version)

---

## 4. The Client Contract

### 4.1 Required Structure

Every Client must have this layout:

```
clients/<client_name>/
├── __init__.py            # Empty marker
├── routes.py              # FastAPI router (REQUIRED)
└── models.py              # SQLAlchemy models (OPTIONAL)
```

Optional:

```
├── tasks.py               # Celery tasks
├── skills/                # Custom scheduled skills
├── prompts/               # Domain-specific AI prompts
└── README.md              # Client documentation
```

### 4.2 Required Constants in `routes.py`

```python
from fastapi import APIRouter

router = APIRouter()
ROUTE_PREFIX = "/api/<client_name>"   # e.g., "/api/medic"
SECTOR = "<client_name>"              # e.g., "medic"

@router.get("/something")
async def something(...):
    ...
```

The core's main.py uses `ROUTE_PREFIX` to mount the router and `SECTOR` as the OpenAPI tag.

### 4.3 Database Models

Client models share the **same SQLAlchemy `Base`** as the core to enable Alembic to manage them:

```python
# clients/<name>/models.py
from app.db.base import Base   # ← Shared Base, NOT redefined

class RetailProduct(Base):
    __tablename__ = "retail_products"   # Convention: prefix with client name
    ...
```

Benefits:
- Single Alembic migration history
- Foreign keys can reference core tables (e.g., `users.id`)
- Single connection pool

Downsides:
- All Client tables are visible in `\dt` even if Client is not in use
- Naming collisions possible (mitigation: prefix tables with client name)

### 4.4 Migrations

Alembic migrations for Client tables live in `workmind-api/alembic/versions/` like core migrations. Convention: filename includes Client name.

```
0002_medic_schema.py        # MEDIC tables
0010_retail_schema.py       # (future) Retail tables
```

When MEDIC is removed (e.g., for a Retail-only deployment), we don't drop MEDIC migration files — the tables exist but are unused. They consume zero performance overhead.

### 4.5 Frontend Conventions

Frontend uses SvelteKit's **route groups** for Client-specific pages:

```
workmind-frontend/src/routes/
├── (app)/                  # Auth-protected core pages
│   ├── chat/
│   ├── conversations/
│   └── admin/
└── (medic)/                # MEDIC-only pages (excluded in core build)
    ├── products/
    ├── sales/
    └── stats/
```

### 4.6 Build-time Client Selection

Vite environment variable selects the Client at build time:

```bash
VITE_CLIENT=medic npm run build
```

The Sidebar component reads this:

```javascript
const CLIENT = import.meta.env.VITE_CLIENT || 'core';
const isMedic = CLIENT === 'medic';

const navItems = [
    { href: '/', label: 'Chat', icon: 'message' },
    ...(isMedic ? [
        { href: '/products', label: 'Prodotti', icon: 'archive' },
        { href: '/sales', label: 'Vendite', icon: 'cart' },
    ] : []),
    { href: '/admin', label: 'Admin', icon: 'gear' },
];
```

This produces a Client-specific build artifact while keeping a single source tree.

---

## 5. The Dynamic Loader

The core's `main.py` includes this discovery logic:

```python
import importlib
from pathlib import Path

_clients_dir = Path(__file__).parent.parent / "clients"

if _clients_dir.is_dir():
    for _cpkg in sorted(_clients_dir.iterdir()):
        if not _cpkg.is_dir() or _cpkg.name.startswith("_"):
            continue
        try:
            _cmod = importlib.import_module(f"clients.{_cpkg.name}.routes")
            _prefix = getattr(_cmod, "ROUTE_PREFIX", f"/api/{_cpkg.name}")
            _sector = getattr(_cmod, "SECTOR", _cpkg.name)
            app.include_router(_cmod.router, prefix=_prefix, tags=[_sector])
            log.info("client_router_loaded", client=_cpkg.name, prefix=_prefix)
        except (ImportError, AttributeError) as exc:
            log.warning("client_router_skip", client=_cpkg.name, reason=str(exc))
```

Key properties:
- **Idempotent** — running twice produces same result
- **Fault-tolerant** — broken Client logs warning, doesn't crash core
- **Order-deterministic** — `sorted()` ensures consistent route ordering

---

## 6. Public/Private Repository Strategy

WorkMind's source code is published in two repositories:

### 6.1 Public Repository: `workmind`

Contains:
- Full core (everything in `app/`)
- Empty `clients/` directory with a README explaining the extension contract
- Generic SvelteKit frontend (no Client route groups)
- Documentation
- Deploy infrastructure

Visibility: Public on GitHub. MIT or Apache 2.0 license (TBD).

### 6.2 Private Repository: `workmind-platform`

Contains:
- Everything in the public repo
- All Client packages (`clients/medic/`, etc.)
- Customer-specific frontend route groups
- Production environment files (.env.staging, .env.production)
- Customer-specific deploy scripts

Visibility: Private; access restricted to operator + customer-authorized engineers.

### 6.3 Synchronization Strategy

The `deploy/publish-core.sh` script generates a clean, history-less snapshot of the core and force-pushes it to the public repo:

```bash
git checkout-index -a --prefix="$WORK_DIR/"   # Clean export
cd "$WORK_DIR"
rm -rf workmind-api/clients/medic/
rm -rf workmind-frontend/src/routes/\(medic\)/
# ... (other Client-specific paths)

git init && git checkout -b main
git add -A && git commit -m "feat: WorkMind v2..."
git push origin main --force
```

Result: the public repo always reflects the current core, no Client leakage, no commit history that could expose old secrets.

---

## 7. Use Case: MEDIC Client

The MEDIC Client demonstrates the architecture in production.

### 7.1 What MEDIC Adds

| Component | Description |
|---|---|
| **Models** | 6 tables: `medic_products`, `medic_inventory_lots`, `medic_sales`, `medic_stock_corrections`, `agent_warehouse_allocations`, `agent_warehouse_movements` |
| **Routes** | 25+ endpoints under `/api/medic/*` |
| **Skill** | `low_stock_alert` — periodic check for products below threshold |
| **Frontend pages** | Products, Lots, Sales, Statistics, Agent Warehouse |
| **Domain logic** | FIFO lot consumption, multi-agent inventory tracking, expiry alerts |

### 7.2 Lines of Code

```
clients/medic/
├── models.py        ~200 LOC
├── routes.py        ~2100 LOC
├── tasks.py         ~150 LOC
└── skills/          ~80 LOC
              Total: ~2530 LOC
```

This is ~15% of the total backend codebase, fully isolated.

### 7.3 Frontend pages

```
workmind-frontend/src/routes/(medic)/
├── products/+page.svelte       ~400 LOC
├── sales/+page.svelte          ~600 LOC
├── stats/+page.svelte          ~250 LOC
└── agent-warehouse/+page.svelte ~300 LOC
                          Total: ~1550 LOC
```

### 7.4 What MEDIC Reuses from Core

- **Authentication**: same login, JWT, 2FA
- **Multi-tenancy**: same `org_id` scoping
- **AI Chat**: same chat endpoint; AI is aware of MEDIC tables via custom prompts
- **Knowledge Base**: same upload/search/RAG; MEDIC uploads protocols, regulations
- **Audit Log**: MEDIC actions logged to same `audit_logs` table
- **Skills framework**: `low_stock_alert` runs in same scheduler
- **Connectors**: Telegram, email, etc. — all available
- **Observability**: same Prometheus metrics

### 7.5 The Cost-of-Adding-a-Client

For a customer like a similar-scale vertical (e.g., a different medical product distributor):

| Activity | Effort |
|---|---|
| Define schema (5–10 tables) | 1 week |
| Build routes (CRUD + business logic) | 2–3 weeks |
| Frontend pages | 2 weeks |
| Skills (1–2 vertical-specific) | 1 week |
| Testing & deployment | 1 week |
| **Total** | **6–8 weeks** |

Compare to building from scratch: 6+ months minimum for an MVP.

---

## 8. Multi-Client Deployments

A single WorkMind instance can host multiple Clients simultaneously. Considerations:

### 8.1 Database

All Clients share one database. Tables are namespaced by prefix (`medic_*`, `retail_*`, etc.). The unused tables in a customer's instance are inert — no performance impact.

### 8.2 Frontend

A single frontend build can support only one Client's UI today (via `VITE_CLIENT`). For multi-Client UI in a single deployment, future evolution could:

- Lazy-load route groups per org's `sector`
- Use SvelteKit's runtime route guards to show/hide Clients

For now, separate deployments per customer are the norm.

### 8.3 Tenancy

Each org has one `sector` field. Routes can check this:

```python
@router.post("/products")
async def create_product(...):
    org = await db.get(Organization, user.org_id)
    if org.sector != "medic":
        raise HTTPException(403, "MEDIC features only")
    ...
```

This prevents users in non-MEDIC orgs from using MEDIC endpoints even though the routes are mounted.

---

## 9. Comparison to Alternatives

### 9.1 Plugin Architectures (e.g., WordPress, Shopify Apps)

| Aspect | WordPress Plugins | WorkMind Clients |
|---|---|---|
| Loading | Runtime (admin enables/disables) | Build-time (developer adds dir) |
| Isolation | Sandbox-ish | Full Python access |
| Schema | Custom tables via WPDB | First-class SQLAlchemy + Alembic |
| Discovery | Plugin registry | Directory scan |
| Trust model | Untrusted | Vendor-controlled |

WordPress favors low-trust, dynamic discovery. WorkMind favors high-trust, vendor-controlled extensions.

### 9.2 Microservices per Domain

| Aspect | Microservices | WorkMind Clients |
|---|---|---|
| Process | Separate process per domain | Single process |
| Communication | Network (REST/gRPC) | In-memory function calls |
| Database | Per-service or shared | Shared schema |
| Operational complexity | High | Low |
| Latency | Network hops | Negligible |
| Deployment | Independent | Coupled |

Microservices win at scale (1000s of users, multiple teams). WorkMind Clients win at moderate scale (10s of customers, small team).

### 9.3 Module Federation (frontend)

The frontend approach (route groups + VITE_CLIENT) is a static analog of "module federation" in micro-frontend architecture. Future versions could adopt true micro-frontends if Client diversity increases.

---

## 10. Roadmap

### 10.1 Near-term (2026)

- [ ] **Compatibility version** declared by Clients (`MIN_CORE_VERSION = "2.0.0"`)
- [ ] **Client manifest** (`client.toml`) describing capabilities, dependencies
- [ ] **Health check** endpoint per Client (`/api/<client>/health`)
- [ ] **Client-specific docs** auto-discovered and linked in admin UI
- [ ] **Schema namespace** enforced (Clients must prefix tables)

### 10.2 Mid-term (2026 H2)

- [ ] **Per-org Client enable/disable** (today: build-time)
- [ ] **Multi-Client frontend** (single build, dynamic nav based on org sector)
- [ ] **Client SDK** to scaffold new Clients (`workmind new-client legal`)
- [ ] **Marketplace concept** for sharing Client templates between developers

### 10.3 Long-term (2027+)

- [ ] **Dynamic loading** of Clients (truly drop-in plugins)
- [ ] **Sandboxed Clients** (WASM or restricted subprocess) for untrusted Clients
- [ ] **Cross-Client interop** standards (e.g., shared "contact" or "asset" abstractions)

---

## 11. Conclusion

WorkMind's pluggable Client architecture solves a real-world problem: how to serve diverse verticals from a single, well-maintained, open-source-friendly platform.

By treating Clients as first-class but **vendor-controlled** extensions, we get:

- **Clean separation** between core platform and domain logic
- **Predictable extension points** with a documented contract
- **Fast onboarding** of new verticals (~6-8 weeks)
- **Single binary deploy** with low operational complexity
- **Open-source story** that doesn't compromise customer privacy

This pattern is a deliberate choice between extremes: not as flexible as runtime plugins, not as monolithic as a single codebase. The middle ground delivers what most B2B SaaS products actually need: structured extensibility with sensible boundaries.

---

## Appendix A: Client Skeleton Template

```
clients/example/
├── __init__.py              # Empty
├── README.md                # Client docs
├── models.py                # See template below
├── routes.py                # See template below
├── tasks.py                 # Optional Celery tasks
└── skills/
    └── __init__.py
```

### `models.py` template

```python
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExampleEntity(Base):
    __tablename__ = "example_entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default="uuid_generate_v4()",
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
```

### `routes.py` template

```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.dependencies import get_current_user, CurrentUser
from clients.example.models import ExampleEntity

router = APIRouter()
ROUTE_PREFIX = "/api/example"
SECTOR = "example"


@router.get("/entities")
async def list_entities(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    # Always filter by org_id
    result = await db.execute(
        select(ExampleEntity).where(ExampleEntity.org_id == user.org_id)
    )
    return result.scalars().all()
```

### Migration template

```python
"""<NN>_example_schema

Revision ID: <hash>
Revises: <previous>
Create Date: ...
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    op.create_table(
        "example_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    )
    op.create_index("idx_example_org", "example_entities", ["org_id"])


def downgrade():
    op.drop_index("idx_example_org")
    op.drop_table("example_entities")
```

---

**End of Whitepaper**

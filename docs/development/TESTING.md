# WorkMind v2 — Testing Strategy

**Owner:** Engineering
**Last Updated:** 2026-04-26

---

## 1. Goals

- Provide confidence that production is **correct**, **secure**, and **performant**
- Catch regressions before they ship
- Enable refactoring without fear
- Keep test runtime under 60s for the full suite

---

## 2. Test Pyramid

```
         ╱╲
        ╱  ╲     E2E (5%)
       ╱────╲    Browser-level: full stack via Playwright (planned)
      ╱      ╲
     ╱────────╲  Integration (20%)
    ╱          ╲ Real DB + Redis; API routes; AI mocked
   ╱────────────╲
  ╱──────────────╲ Unit (75%)
 ╱                ╲ Pure functions, services with mocked deps
```

Current status: ~95% unit + integration mix; no E2E yet.

---

## 3. Test Suite Overview

```
workmind-api/tests/
├── conftest.py              # Shared fixtures (test DB, client, users)
├── test_health.py           # Health & readiness probes
├── test_auth.py             # Login, refresh, logout, /me
├── test_2fa.py              # TOTP setup, confirm, challenge, disable
├── test_chat.py             # Chat endpoints (with mocked AI)
├── test_kb.py                # KB upload, search, deletion
├── test_medic.py            # MEDIC inventory, sales, agent warehouse
└── test_admin_system.py     # System metrics, audit
```

**Counts (current):**
- 7 test modules
- 69 tests total
- ~22 seconds runtime
- ~95% pass rate (2 known flaky tests in test_chat.py — TODO)

---

## 4. Fixtures

### 4.1 Database Fixtures

`conftest.py` provides:

| Fixture | Scope | Purpose |
|---|---|---|
| `test_engine` | session | Async SQLAlchemy engine on `workmind_test` DB |
| `test_session_factory` | session | `async_sessionmaker` for creating sessions |
| `seed_base_orgs` (autouse) | session | Pre-creates `test-org` and `medic-org` |
| `db_session` | function | Fresh session per test, rolled back at end |
| `client` | function | `httpx.AsyncClient` with ASGI transport |
| `test_org` | session | The default `test-org` Organization object |
| `test_user` | session | A user in `test-org` with role=user |
| `admin_user` | session | A user in `test-org` with role=admin |
| `auth_headers` | function | `{"Authorization": "Bearer <jwt>"}` for `test_user` |
| `admin_auth_headers` | function | Same for `admin_user` |

### 4.2 Test Database Setup

```python
# At session start:
1. Connect to workmind_test DB
2. CREATE EXTENSION uuid-ossp, vector
3. Base.metadata.create_all() — creates all tables
4. Apply idempotent ALTER TABLE statements for any new columns
5. Seed orgs

# At each test:
1. Open new AsyncSession
2. Yield to test
3. Roll back any uncommitted changes
4. Close session
```

### 4.3 Auth Fixtures Pattern

```python
async def test_endpoint_requires_auth(client):
    resp = await client.get("/api/conversations")
    assert resp.status_code == 401

async def test_endpoint_with_user(client, auth_headers):
    resp = await client.get("/api/conversations", headers=auth_headers)
    assert resp.status_code == 200

async def test_admin_endpoint(client, admin_auth_headers):
    resp = await client.get("/api/admin/users", headers=admin_auth_headers)
    assert resp.status_code == 200
```

---

## 5. Writing Tests

### 5.1 Test File Structure

```python
"""Tests for <module>."""
import pytest
from httpx import AsyncClient


class TestFooEndpoints:
    @pytest.mark.asyncio
    async def test_create_foo(self, client: AsyncClient, auth_headers):
        resp = await client.post("/api/foos", json={"name": "x"}, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "x"

    @pytest.mark.asyncio
    async def test_list_foos_filters_by_org(self, client, auth_headers):
        # Setup, exercise, assert
        ...

class TestFooValidation:
    @pytest.mark.asyncio
    async def test_create_foo_empty_name_returns_422(self, client, auth_headers):
        resp = await client.post("/api/foos", json={"name": ""}, headers=auth_headers)
        assert resp.status_code == 422
```

### 5.2 Naming

`test_<what>_<expected_outcome>` — describe behavior, not implementation:

✅ `test_login_with_invalid_password_returns_401`
✅ `test_create_user_generates_temp_password_when_not_provided`

❌ `test_login_works`
❌ `test_password_validation`

### 5.3 Arrange — Act — Assert

```python
async def test_create_user(client, admin_auth_headers, test_session_factory):
    # Arrange
    payload = {"email": "new@test.com", "display_name": "New", "role": "user"}

    # Act
    resp = await client.post("/api/admin/users", json=payload, headers=admin_auth_headers)

    # Assert
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == payload["email"]
    assert "temp_password" in data

    # Verify DB state
    async with test_session_factory() as session:
        from app.db.models import User
        user = await session.get(User, uuid.UUID(data["id"]))
        assert user is not None
        assert user.role == "user"
```

### 5.4 Mocking External Services

For AI provider calls, network operations, etc.:

```python
from unittest.mock import AsyncMock, patch

async def test_chat_uses_ai_router(client, auth_headers):
    mock_response = AsyncMock(return_value=AIResponse(content="Hello", cost_usd=0.001))
    with patch("app.services.model_router.ModelRouter.complete", mock_response):
        resp = await client.post("/api/chat", json={"message": "Hi"}, headers=auth_headers)
        assert resp.status_code == 200
        mock_response.assert_called_once()
```

### 5.5 Async Considerations

- All HTTP tests are `@pytest.mark.asyncio`
- `pytest-asyncio` configured with `mode = "auto"` so the marker is implicit
- Use `await` for all async calls; missing `await` is the most common test bug
- Each test gets a fresh event loop (configurable via `event_loop_policy`)

---

## 6. Test Categories

### 6.1 Health & Readiness

```python
async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

async def test_ready_includes_db_check(client):
    resp = await client.get("/health/ready")
    assert "checks" in resp.json()
    assert resp.json()["checks"]["db"] == "ok"
```

### 6.2 Auth Tests

Coverage:
- Login success/failure
- Refresh with valid/invalid/expired token
- Logout
- /me endpoint
- 2FA flow (setup → confirm → challenge)
- Password reset flow

### 6.3 Multi-tenancy Tests (CRITICAL)

Verify org-level isolation:

```python
async def test_user_cannot_see_other_org_conversations(
    client, auth_headers, test_session_factory
):
    # Create a conversation in org A (current user's org)
    # Create a conversation in org B (different org)
    # Verify GET /api/conversations only returns org A's

    # ...
```

This pattern should exist for every entity with `org_id`.

### 6.4 Validation Tests

Use Pydantic to your advantage:

```python
async def test_invalid_email_returns_422(client, admin_auth_headers):
    resp = await client.post(
        "/api/admin/users",
        json={"email": "not-an-email", "role": "user"},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 422
```

### 6.5 Integration Tests with Real DB

The test DB is real Postgres + pgvector. Tests can:
- Create data via API, verify via direct DB query
- Test cascading deletes
- Verify constraint violations return 409

### 6.6 Performance Smoke Tests (planned)

Use `pytest-benchmark` to track key endpoint latency:

```python
def test_list_conversations_is_fast(benchmark, client, auth_headers):
    result = benchmark(lambda: asyncio.run(
        client.get("/api/conversations", headers=auth_headers)
    ))
    assert result.status_code == 200
```

Fail if regression >50% from baseline.

---

## 7. Coverage Goals

| Module | Current | Target |
|---|---|---|
| `app/api/routes/auth.py` | 90% | 95% |
| `app/api/routes/auth_2fa.py` | 95% | 95% |
| `app/api/routes/chat.py` | 60% | 85% |
| `app/api/routes/kb.py` | 70% | 90% |
| `app/services/model_router.py` | 50% | 80% |
| `app/services/embedder.py` | 40% | 80% |
| `app/services/anonymizer.py` | 30% | 90% |
| `app/services/encryption.py` | 60% | 95% |
| `clients/medic/routes.py` | 45% | 75% |
| **Total** | **~58%** | **80%** |

Run coverage:

```bash
pytest --cov=app --cov=clients --cov-report=html
open htmlcov/index.html
```

---

## 8. Continuous Integration

GitHub Actions runs on every push and PR:

1. **Lint** — `ruff check app/ clients/` (must pass)
2. **Test** — `pytest tests/` (must pass)
3. **Security** — `pip-audit` (planned)

Workflow file: `.github/workflows/ci.yml`

CI uses:
- Ubuntu 24.04
- Python 3.13
- Postgres 16 + pgvector (service container)
- Redis 7 (service container)

Failure modes to fix:
- **Setup error** → check `pyproject.toml` deps
- **DB connection** → check `DATABASE_URL` env var matches service container
- **Test timeout** → add `timeout` env var or fix flaky tests

---

## 9. Test Maintenance

### 9.1 Flaky Tests

If a test is flaky:

1. Reproduce locally with `pytest --count=20`
2. Identify the source: timing, ordering, state leakage, external service
3. Fix the root cause; don't add `time.sleep()`
4. If unfixable in current PR, mark `@pytest.mark.flaky` and create issue

### 9.2 Slow Tests

Use `pytest --durations=10` to find the slowest 10 tests.

Common offenders:
- Tests that rebuild the database
- Tests with real network calls (should be mocked)
- Tests with `time.sleep()` waiting for state

### 9.3 Test Data Hygiene

- Each test should be independent
- Use unique identifiers (UUIDs) per test, not shared constants
- Clean up resources created (or rely on session rollback)
- Avoid relying on test execution order

---

## 10. What's Missing (Future Work)

Per code review, these areas need test coverage:

### 10.1 Integration

- [ ] AI provider failover scenarios (Claude timeout → DeepSeek)
- [ ] Concurrent chat messages on same conversation
- [ ] Concurrent sales on same MEDIC lot (race condition)
- [ ] Multi-org isolation (every entity)

### 10.2 End-to-End

- [ ] User registration → 2FA setup → first chat
- [ ] Document upload → embedding → RAG search → chat answer
- [ ] Connector setup → skill enable → scheduled execution

### 10.3 Performance

- [ ] Vector search at 10K, 100K, 1M chunks
- [ ] Concurrent SSE streams (load test with 50 simulated users)
- [ ] DB pool saturation behavior

### 10.4 Security

- [ ] SQL injection attempts on all user-controlled inputs
- [ ] Rate limit enforcement (login, 2FA, chat)
- [ ] CSRF token verification (when applicable)
- [ ] Webhook signature validation

### 10.5 Frontend (planned with Playwright)

- [ ] Login flow
- [ ] Chat streaming UI
- [ ] Admin user management UI
- [ ] MEDIC sales workflow

---

## 11. Test Data Builders (planned)

To reduce test boilerplate, plan to introduce factories using `factory_boy`:

```python
class UserFactory(SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session = ...

    org_id = factory.SubFactory(OrganizationFactory)
    email = factory.Faker("email")
    display_name = factory.Faker("name")
    role = "user"
    password_hash = factory.LazyFunction(lambda: bcrypt.hashpw(b"test", ...).decode())
```

Usage:

```python
async def test_thing(db_session):
    user = UserFactory(role="admin")
    conv = ConversationFactory(user=user, message_count=5)
    ...
```

---

## 12. Manual Test Checklists

Some flows are too complex/expensive to fully automate. Maintain manual checklists for releases:

### Pre-release smoke test

- [ ] Login (with and without 2FA)
- [ ] Send a chat message; verify streaming
- [ ] Upload a document; verify it appears in KB
- [ ] Search KB; verify relevant results
- [ ] Admin: create a user; activate/deactivate
- [ ] Admin: configure a connector; test it
- [ ] Admin: enable a skill; verify it runs (check logs)
- [ ] MEDIC: create product, lot, sale; verify stock decremented
- [ ] Forgot password → reset → login with new password

### After deploy

- [ ] /health returns 200
- [ ] /metrics returns Prometheus output
- [ ] Send test message; verify AI response
- [ ] Check Grafana for unusual error rate
- [ ] Audit log shows recent activity

---

**End of Testing Strategy**

# WorkMind v2 — Security Architecture

**Classification:** Internal
**Document Status:** Approved
**Last Reviewed:** 2026-04-26
**Next Review:** 2026-10-26

---

## Table of Contents

1. [Security Principles](#1-security-principles)
2. [Threat Model](#2-threat-model)
3. [Authentication](#3-authentication)
4. [Authorization](#4-authorization)
5. [Data Protection](#5-data-protection)
6. [Network Security](#6-network-security)
7. [Application Security](#7-application-security)
8. [Audit & Compliance](#8-audit--compliance)
9. [Incident Response](#9-incident-response)
10. [Security Roadmap](#10-security-roadmap)

---

## 1. Security Principles

WorkMind v2 follows these core principles:

1. **Defense in depth** — multiple layers (auth, encryption, network, application)
2. **Least privilege** — users get the minimum role needed; service accounts narrowly scoped
3. **Secure by default** — secure configurations are the defaults; opt-out for special cases
4. **Privacy by design** — anonymization before external AI; data minimization
5. **Auditability** — every admin action and security event logged immutably
6. **Fail closed** — on auth/permission errors, deny access; never default to allow
7. **Encryption everywhere** — at rest (Fernet, bcrypt) and in transit (TLS)

---

## 2. Threat Model

### 2.1 Attack Surface

| Surface | Exposure | Primary Threats |
|---|---|---|
| **Public HTTPS API** | Internet (via Tailscale Funnel) | Brute force, credential stuffing, injection, DoS |
| **Tailnet APIs** (staging, Grafana) | Tailscale users only | Lateral movement, insider threat |
| **Webhooks** (Telegram, WhatsApp) | Public POST endpoints | Forged requests, replay attacks |
| **Database** | Localhost only | Data exfiltration via app vuln, backup compromise |
| **AI provider APIs** (egress) | Outbound | Data leakage, key compromise |
| **Local filesystem** | Server-side code | Path traversal, KB file injection |

### 2.2 Threat Actors

| Actor | Motivation | Capability |
|---|---|---|
| **External attacker** | Data theft, ransomware, disruption | Low to medium (no insider info) |
| **Authenticated user (curious)** | Access other org's data | Medium (knows API shape) |
| **Authenticated user (malicious admin)** | Privilege escalation, data theft | High (privileged within own org) |
| **Compromised AI provider** | Data harvesting | High (legitimate egress channel) |
| **Compromised dependency** | Supply chain attack | High (code execution in app) |

### 2.3 STRIDE Analysis

| Threat | Mitigation |
|---|---|
| **Spoofing** | JWT signing with HMAC-SHA256; bcrypt password hashing; TOTP 2FA |
| **Tampering** | All data validation via Pydantic; HTTPS prevents MITM; audit log with HMAC chain (planned) |
| **Repudiation** | Audit log records actor + timestamp for all admin actions |
| **Information Disclosure** | Per-org data isolation; sensitive fields masked in API responses; logs scrub PII |
| **Denial of Service** | Rate limiting (slowapi); body size limits; request timeouts; daily AI budget cap |
| **Elevation of Privilege** | Role hierarchy enforced in `dependencies.py`; admin actions audited; non-prod fallback flagged |

---

## 3. Authentication

### 3.1 Authentication Mechanisms

| Mechanism | Purpose | Lifetime | Rotation |
|---|---|---|---|
| **API Key** | Server-to-server (Celery, internal) | Permanent until revoked | Manual via env var update |
| **JWT Access Token** | Web/mobile client | 24 hours (configurable) | On every login |
| **JWT Refresh Token** | Renewal | 30 days | Rotated (planned — see code review AUTH-1) |
| **TOTP (RFC 6238)** | Second factor | 30s window, ±1 tolerance | Per code |
| **Password Reset Token** | Email-based reset | 1 hour | Single-use (used_at timestamp) |
| **Temp Token (2FA challenge)** | Bridges login → 2FA | 5 minutes | Single-use |

### 3.2 Password Policy

- **Minimum length:** 8 characters
- **Hashing:** bcrypt with work factor 12 (~250ms per hash)
- **Storage:** `password_hash` field, never stored plaintext or recoverable
- **Reset:** Email-based with single-use token (no security questions)
- **No password reuse history** (planned)
- **No complexity requirements** by design (length > complexity per NIST 800-63B)

### 3.3 Two-Factor Authentication

- **Algorithm:** TOTP-SHA1, 6 digits, 30-second window
- **Standard:** RFC 6238
- **Compatible with:** Google Authenticator, Authy, 1Password, Bitwarden
- **Backup codes:** Not yet implemented (planned, see code review 2FA-2)
- **Mandatory for:** admin/owner roles (recommendation — not yet enforced server-side)

### 3.4 JWT Implementation

**Algorithm:** HS256 (symmetric, suits single-deployment topology)

**Claims:**
```json
{
  "sub": "user_uuid",
  "org_id": "org_uuid",
  "role": "admin",
  "type": "access" | "refresh" | "totp_challenge",
  "iat": 1714000000,
  "exp": 1714086400
}
```

**Secret:** `WORKMIND_SECRET_KEY` env var, minimum 32 bytes random.

**Validation order:**
1. Signature verification (constant-time)
2. Expiration check
3. `type` claim matches expected
4. User still exists and is active
5. Role from token compared to required role for endpoint

### 3.5 Session Management

- **Stateless tokens** — no server-side session store except for refresh token hashes
- **Logout:** Revokes refresh token (best-effort) and clears client storage
- **Token rotation:** Refresh exchange should issue new refresh token (planned — currently old token remains valid)
- **Concurrent sessions:** Allowed (no single-session enforcement)

---

## 4. Authorization

### 4.1 Role Hierarchy

```
owner    > admin   > supervisor  > user
(super)  (admin)   (read-only)   (basic)
```

**owner** — Full access including org config, billing.
**admin** — Manage users, connectors, skills, KB, audit.
**supervisor** — Read-only access to admin views.
**user** — Use chat, conversations, KB search; no admin capabilities.

### 4.2 Authorization Enforcement

Centralized in `app/dependencies.py`:

```python
def require_admin(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("admin", "owner"):
        raise HTTPException(403, "Accesso riservato agli amministratori")
    return user
```

Every admin route uses `Depends(require_admin)` (or equivalent inline check).

### 4.3 Multi-Tenant Isolation

**Critical invariant:** Every database query MUST filter by `org_id` matching the authenticated user's org.

Pattern in CRUD modules:

```python
result = await db.execute(
    select(Conversation).where(
        Conversation.org_id == user.org_id,
        Conversation.id == conversation_id,
    )
)
```

**Risks:**
- UUID enumeration not yet prevented at user level (see code review CHAT-3)
- No row-level security in PostgreSQL (relies on app correctness)

**Future hardening:**
- Enable PostgreSQL RLS with `org_id` policy
- Set `current_setting('app.org_id')` per session
- Reduces blast radius of accidental query bug

### 4.4 Per-Resource Permissions

| Resource | Owner | Admin | Supervisor | User |
|---|---|---|---|---|
| User CRUD | ✅ | ✅ | ❌ | own profile only |
| Org config | ✅ | ❌ | ❌ | ❌ |
| Connectors | ✅ | ✅ | read | ❌ |
| Skills | ✅ | ✅ | read | ❌ |
| KB documents | ✅ | ✅ | read | search only |
| Audit log | ✅ | ✅ | read | ❌ |
| Backup | ✅ | ✅ | read | ❌ |
| Conversations | ✅ | own + admin | read all | own only |
| Chat | ✅ | ✅ | ✅ | ✅ |
| MEDIC sales | ✅ | ✅ | read | own only (agent) |

---

## 5. Data Protection

### 5.1 Encryption at Rest

| Data Class | Mechanism | Key Source |
|---|---|---|
| Passwords | bcrypt cost 12 | N/A (one-way) |
| Connector configs | Fernet (AES-128-CBC + HMAC-SHA256) | SHA-256 of `WORKMIND_SECRET_KEY` |
| TOTP secrets | Plain (Postgres at-rest encryption assumed) | N/A |
| JWT secret | Env var | `WORKMIND_SECRET_KEY` |
| KB document content | Plain (in DB) | N/A |
| Database | Postgres data dir on encrypted disk (recommended) | OS-level (LUKS) |

**Current limitations:**
- TOTP secrets are not field-level encrypted (relies on DB at-rest)
- KB documents not encrypted (sensitive docs would benefit from this)

### 5.2 Encryption in Transit

- **External**: TLS 1.2+ via Tailscale Funnel (auto-provisioned cert)
- **Internal**: localhost connections (Postgres, Redis, Ollama) — not encrypted; relies on host isolation

### 5.3 Secrets Management

**Current:**
- `.env.production`, `.env.staging` files on Bender
- Loaded via systemd `EnvironmentFile=`
- File permissions `600`, owned by `emanuele` user
- KDBX (KeePass) database for human-readable backup of credentials (`workmind_credentials.kdbx`)

**Roadmap:**
- Migrate to HashiCorp Vault or AWS Secrets Manager when scaling beyond Bender
- Implement automatic rotation for AI API keys

### 5.4 Privacy & Anonymization

Before sending user messages to external AI providers (Anthropic, DeepSeek):

1. **Anonymizer service** scans the message for PII patterns:
   - Italian fiscal codes (CF)
   - IBAN
   - Phone numbers
   - Email addresses
   - Credit card numbers
   - Person names (heuristic + capitalized words)

2. PII is replaced with placeholders: `[PII_001]`, `[PII_002]`, etc.

3. Mapping stored in Redis with conversation-scoped key, TTL 1 hour.

4. After AI response, **deanonymize** the placeholders back to original values for the user.

**Risks:**
- Heuristic detection misses non-standard formats
- Conversation key collision (see code review CHAT-1)
- Placeholders in AI training data could leak patterns (mitigated by AI provider terms)

---

## 6. Network Security

### 6.1 Network Topology

```
Public Internet
       │
       ▼
[Tailscale Funnel]  (TLS termination, automatic cert)
       │
       ▼
[Bender :443] ─→ uvicorn :8000 (production API)
                ─→ uvicorn :8001 (staging, tailnet only)

Tailnet only:
       Grafana :3001
       Prometheus :9090

Localhost only:
       Postgres :5432
       Redis :6379
       Ollama :11434
```

### 6.2 Firewall Rules

Bender iptables policy (default deny inbound):

```
ALLOW 22/tcp  (SSH, key-only auth)
ALLOW 41641/udp (Tailscale)
ALLOW lo (loopback)
DENY all others
```

Tailscale handles all external HTTPS routing.

### 6.3 CORS

Configured in `main.py`:

```python
allow_origins = [
    "https://workmind-bender.tail898ef4.ts.net",
    "http://localhost:5173",  # SvelteKit dev
]
allow_credentials = True
allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
allow_headers = ["*"]
```

### 6.4 Security Headers

Set by middleware in `main.py`:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
```

**Missing (planned):**
- `Strict-Transport-Security` (HSTS) — should be `max-age=31536000; includeSubDomains; preload`
- `Content-Security-Policy` — needs careful tuning for SvelteKit assets
- `Permissions-Policy` — to disable unused browser APIs

---

## 7. Application Security

### 7.1 Input Validation

- **Pydantic v2** validates all request bodies, query params, path params
- **Type coercion** prevents type confusion (e.g., `str` to `int` mismatches)
- **Constraints** via Pydantic `Field()`: min/max length, regex patterns, enums

### 7.2 SQL Injection Prevention

- **SQLAlchemy ORM** uses parameterized queries by default
- **Raw SQL** is rare and uses bound parameters via `text(...).bindparams(...)`

**Known issue (P0 in code review):**
- `documents.py:107` constructs vector search SQL with `str(query_embedding)` — must validate as `list[float]` before use.

### 7.3 Cross-Site Scripting (XSS)

- **API only** — no server-rendered HTML except SPA shell
- **JSON responses** — Content-Type prevents XSS in API responses
- **SPA escapes by default** — Svelte auto-escapes interpolated values
- **User-generated content in chat** — rendered as plain text, not HTML

### 7.4 Cross-Site Request Forgery (CSRF)

- **Bearer token in Authorization header** — not in cookies — eliminates traditional CSRF
- **Webhook endpoints** verify signatures (Telegram, WhatsApp) — not vulnerable to CSRF

### 7.5 Path Traversal

- **File uploads** validated for filename pattern; stored under content hash, not user-supplied name
- **KB watch paths** restricted to admin-configured roots; no `..` traversal

### 7.6 Server-Side Request Forgery (SSRF)

- **Outbound HTTP** is restricted to known providers (Anthropic, DeepSeek, Telegram, Meta, Ollama localhost)
- **No user-supplied URLs** are fetched server-side currently
- **Egress proxy** could be added for stricter control (planned)

### 7.7 Dependency Security

- **Pinned major versions** in `pyproject.toml` (e.g. `fastapi>=0.111.0`)
- **CI lint** flags unused imports (could miss vulnerable transitive deps)
- **Dependabot** not yet configured (recommended)
- **`pip-audit`** can be run manually; should be in CI (TODO)

### 7.8 Rate Limiting

Implemented via `slowapi`:

| Endpoint | Limit | Rationale |
|---|---|---|
| Login | 10/min | Prevent password brute force |
| Refresh | 10/min | Prevent token harvesting |
| Forgot password | 5/min | Prevent email spam |
| Chat | 30/min | Prevent AI cost abuse |
| 2FA challenge | **None (P1)** | Brute force vulnerability — must add |

**Backend:** Redis (shared across processes if multiple workers)

### 7.9 AI-Specific Security

- **Daily budget cap** per provider (`max_daily_cost_usd`) — prevents runaway costs
- **Provider failover** — if one fails, fallback (Claude → DeepSeek → Ollama)
- **Anonymization** before sending to external providers
- **Cost recorded per message** for audit
- **No tools / function calling** in current chat (limits LLM-driven actions)

---

## 8. Audit & Compliance

### 8.1 Audit Log

Every action that modifies state or involves authentication writes to `audit_logs`:

```
INSERT INTO audit_logs (event_type, actor, summary, details_json, ip_address, user_agent, created_at)
```

**Retention:** Indefinite (DB grows ~1MB per 10K events).

**Export:** CSV via `GET /api/admin/audit/logs/export`.

**Tamper detection (planned):** HMAC chain — each log entry references the hash of the previous, making in-place modification detectable.

### 8.2 GDPR Compliance

See `docs/security/PRIVACY_GDPR.md` for full details.

Summary:
- **Data subject access**: Users can view their own data via `/api/auth/me`, conversations, and admin can export
- **Right to deletion**: Soft delete on user (preserves audit log), hard delete of conversations available
- **Data portability**: Conversation export as JSON, KB documents downloadable
- **Lawful basis**: Contract (service provision); explicit consent for AI processing
- **Data Processing Agreement (DPA)**: Required with AI providers (Anthropic + DeepSeek)
- **Sub-processors disclosed**: Anthropic, DeepSeek, Tailscale, Meta (WhatsApp), Telegram

### 8.3 SOC 2 Readiness

Not yet certified. Gap analysis:

| Control | Status |
|---|---|
| Access control | ✅ Implemented |
| Audit logging | ✅ Implemented |
| Encryption | ⚠️ Partial (no TOTP encryption) |
| Backup | ✅ Daily |
| Incident response plan | ⚠️ Documented but untested |
| Vulnerability management | ⚠️ No formal program |
| Change management | ⚠️ Git-based, no formal review process |
| Vendor management | ⚠️ Informal |

---

## 9. Incident Response

### 9.1 Detection

| Source | Signal | Action |
|---|---|---|
| Audit log | Repeated `login_failed` from same IP | Manual review; consider IP block |
| Audit log | `2fa_challenge_failed` >5 in 5min | Auto-lock account (planned) |
| Prometheus alert | API error rate >5% | Page on-call |
| Prometheus alert | DB connection failures | Page on-call |
| Manual report | User reports anomalous activity | Investigate; preserve logs |

### 9.2 Response Procedure

1. **Triage** — Determine severity (P0=active breach, P1=potential, P2=false alarm)
2. **Contain** — If P0:
   - Revoke all active JWTs (rotate `WORKMIND_SECRET_KEY`)
   - Disable affected user accounts
   - Block source IP at Tailscale level
3. **Investigate** — Read audit log + structured logs (journalctl)
4. **Recover** — Restore from backup if data was tampered
5. **Post-mortem** — Document timeline, root cause, action items

### 9.3 Backup & Recovery

- **Daily**: `pg_dump` at 02:30 UTC, retained 30 days
- **Monthly**: Copy of 1st-of-month dump retained 12 months
- **Files**: rsync `~/uploads/` to backup volume daily
- **Test restore**: Quarterly (manual, document procedure)

**RPO:** ≤24 hours
**RTO:** ≤2 hours (assuming Bender hardware available)

### 9.4 Disaster Recovery

If Bender is permanently unavailable:

1. Provision new Linux server
2. Install dependencies (Postgres 16, Redis, Python 3.13, Tailscale)
3. Restore latest `pg_dump`
4. Apply Alembic migrations (idempotent — should be no-op)
5. Configure systemd services (from `deploy/`)
6. Update Tailscale Funnel to point to new node
7. Update DNS if changed

---

## 10. Security Roadmap

### Q2 2026 (immediate)

- [P0] Fix vector search SQL injection (validate embedding type)
- [P1] Add rate limit on 2FA challenge endpoint
- [P1] Implement refresh token rotation with revocation
- [P1] Add per-conversation user access check
- [P1] Validate skill job config schema on load

### Q3 2026

- [P2] Implement TOTP backup codes
- [P2] Add HSTS, CSP, Permissions-Policy headers
- [P2] PostgreSQL row-level security on org_id
- [P2] HMAC chain for audit log
- [P2] Dependabot + pip-audit in CI
- [P2] Encrypt TOTP secrets at field level

### Q4 2026

- [P3] Migrate secrets to HashiCorp Vault
- [P3] Add OpenTelemetry distributed tracing
- [P3] Penetration test (external)
- [P3] Tabletop incident response exercise
- [P3] SOC 2 Type 1 audit prep

---

**Document classification:** Internal — share with engineering, security, and select stakeholders only.

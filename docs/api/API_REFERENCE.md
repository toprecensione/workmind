# WorkMind v2 — API Reference

**Version:** 2.0.0
**Base URL (prod):** `https://workmind-bender.tail898ef4.ts.net`
**Base URL (staging):** `https://staging.workmind-bender.tail898ef4.ts.net` (tailnet only)
**OpenAPI:** `/docs` (Swagger UI), `/redoc` (ReDoc), `/openapi.json` (raw spec)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication](#2-authentication)
3. [Conventions](#3-conventions)
4. [Errors](#4-errors)
5. [Rate Limiting](#5-rate-limiting)
6. [Endpoints](#6-endpoints)
   - [Health](#61-health--observability)
   - [Auth](#62-auth)
   - [2FA](#63-two-factor-authentication-2fa)
   - [Password Reset](#64-password-reset)
   - [Conversations](#65-conversations)
   - [Chat](#66-chat)
   - [Knowledge Base](#67-knowledge-base-kb)
   - [Teach](#68-teach)
   - [Channels](#69-channels-webhooks)
   - [Admin: Users & Org](#610-admin--users--org)
   - [Admin: Connectors](#611-admin--connectors)
   - [Admin: Skills](#612-admin--skills)
   - [Admin: Knowledge Base](#613-admin--knowledge-base)
   - [Admin: Audit](#614-admin--audit)
   - [Admin: Backup](#615-admin--backup)
   - [Admin: System](#616-admin--system)
   - [Admin: AI Actions](#617-admin--ai-actions)
   - [MEDIC Client](#618-medic-client)
7. [Server-Sent Events (SSE)](#7-server-sent-events-sse)
8. [Webhooks](#8-webhooks)

---

## 1. Overview

The WorkMind v2 API is a RESTful HTTP API exposing JSON over HTTPS. It supports both regular request/response and streaming responses (SSE) for chat. Multi-tenancy is enforced server-side: every authenticated request is scoped to the user's `org_id` and access to other orgs is impossible.

### Versioning Policy

The API is currently at version 2 and is mounted at `/api`. Breaking changes will introduce `/api/v3` while maintaining `/api` (= v2) for at least 6 months.

### Content Type

All endpoints accept and return `application/json` unless explicitly documented (e.g., file uploads use `multipart/form-data`, streaming endpoints use `text/event-stream`).

---

## 2. Authentication

WorkMind supports three authentication mechanisms:

### 2.1 API Key (server-to-server)

```http
X-API-Key: <your-key>
```

Used for internal service-to-service calls (Celery workers, scheduled jobs). Configured via `WORKMIND_API_KEYS` env var (comma-separated).

### 2.2 Bearer Token (web/mobile clients)

```http
Authorization: Bearer <jwt>
```

JWT obtained via `POST /api/auth/login`. Lifetime 24h (configurable).

### 2.3 Refresh Token

JWT with `type=refresh` and longer lifetime (30 days). Used to obtain new access tokens via `POST /api/auth/refresh`.

### 2.4 Two-Factor Authentication (TOTP)

If `totp_enabled=true` for the user, login returns a `temp_token` instead of access/refresh tokens. The client must complete the 2FA challenge via `POST /api/auth/2fa/challenge` with a valid TOTP code.

---

## 3. Conventions

### 3.1 Pagination

Most list endpoints accept:

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 100 | Max items per page |
| `offset` | int | 0 | Skip first N items |

Responses include the array directly; total counts via `?include_total=true` where supported.

### 3.2 Identifiers

All IDs are UUIDs (v4) unless documented otherwise. Email hashes (SHA-256) are used as alternate identifiers in user records.

### 3.3 Timestamps

ISO 8601 with timezone (UTC) — e.g., `"2026-04-26T14:30:00.000Z"`.

### 3.4 Currency

USD, stored as `Numeric(12, 8)` for AI cost; EUR as `Numeric(10, 2)` for MEDIC sales.

---

## 4. Errors

Standard FastAPI error format:

```json
{
  "detail": "Error description"
}
```

### 4.1 HTTP Status Codes

| Code | Meaning |
|---|---|
| 200 | OK |
| 201 | Created |
| 202 | Accepted (async job started) |
| 204 | No Content |
| 400 | Bad Request — validation error or malformed input |
| 401 | Unauthorized — invalid/missing token |
| 403 | Forbidden — authenticated but insufficient role |
| 404 | Not Found |
| 409 | Conflict — duplicate resource or state issue |
| 422 | Unprocessable Entity — Pydantic validation failure |
| 429 | Too Many Requests — rate limited |
| 500 | Internal Server Error |
| 502 | Bad Gateway — upstream AI provider error |
| 503 | Service Unavailable |

### 4.2 Validation Errors (422)

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```

---

## 5. Rate Limiting

Implemented via `slowapi` (Redis-backed). Limits applied per IP and per endpoint:

| Endpoint | Limit |
|---|---|
| `POST /api/auth/login` | 10/minute |
| `POST /api/auth/refresh` | 10/minute |
| `POST /api/auth/forgot-password` | 5/minute |
| `POST /api/chat/*` | 30/minute |
| Default | 60/minute |

Rate limit headers (response):

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1714134000
```

---

## 6. Endpoints

### 6.1 Health & Observability

#### `GET /health`

Liveness probe. Always returns 200 if the process is up.

**Response:**
```json
{"status": "ok", "uptime_seconds": 5347.3}
```

#### `GET /health/ready`

Readiness probe. Verifies DB connectivity, Redis, and required services.

**Response (200):**
```json
{
  "status": "ready",
  "checks": {
    "db": "ok",
    "redis": "ok",
    "ollama": "ok"
  }
}
```

**Response (503):** Same shape but `status: "not_ready"` and one or more checks `"failed"`.

#### `GET /metrics`

Prometheus metrics in text exposition format. Scraped by Prometheus every 15s.

---

### 6.2 Auth

#### `POST /api/auth/login`

Authenticate with email + password.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "••••••••"
}
```

**Response (200, no 2FA):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "Mario Rossi",
    "role": "admin",
    "org_id": "uuid"
  }
}
```

**Response (200, 2FA required):**
```json
{
  "totp_required": true,
  "temp_token": "eyJ...",
  "expires_in": 300
}
```

#### `POST /api/auth/refresh`

Exchange a refresh token for a new access token.

**Request:**
```json
{"refresh_token": "eyJ..."}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "expires_in": 86400
}
```

#### `POST /api/auth/logout`

Invalidate the current refresh token (best-effort). Returns 204.

#### `GET /api/auth/me`

Get the authenticated user's profile.

**Response (200):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "Mario Rossi",
  "role": "admin",
  "is_active": true,
  "totp_enabled": true,
  "org": {
    "id": "uuid",
    "name": "MEDIC SRL",
    "sector": "medic"
  }
}
```

#### `PATCH /api/auth/me`

Update own profile or change password.

**Request:**
```json
{
  "display_name": "New Name",
  "current_password": "••••",
  "new_password": "••••"
}
```

---

### 6.3 Two-Factor Authentication (2FA)

#### `POST /api/auth/2fa/setup`

Begin TOTP enrollment. Generates a secret and QR code.

**Response (200):**
```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "uri": "otpauth://totp/WorkMind:user@example.com?secret=...&issuer=WorkMind",
  "qr_base64": "iVBORw0KGgoAAAANSUhE..."
}
```

**Errors:**
- `409` — 2FA already active

#### `POST /api/auth/2fa/confirm`

Confirm enrollment with a code from the authenticator app.

**Request:**
```json
{"code": "123456"}
```

**Response (200):**
```json
{"detail": "2FA attivato"}
```

#### `POST /api/auth/2fa/challenge`

Complete the 2FA challenge during login.

**Request:**
```json
{"temp_token": "eyJ...", "code": "123456"}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "expires_in": 86400
}
```

**Errors:**
- `401` — invalid temp_token, expired, or wrong code

#### `DELETE /api/auth/2fa`

Disable 2FA. Requires a valid TOTP code (no master override).

**Request:**
```json
{"code": "123456"}
```

---

### 6.4 Password Reset

#### `POST /api/auth/forgot-password`

Request a password reset email.

**Request:**
```json
{"email": "user@example.com"}
```

**Response (200):**
```json
{"detail": "Se l'email esiste, riceverai un link di reset"}
```

(Same response whether the email exists or not, to prevent enumeration.)

#### `POST /api/auth/reset-password`

Complete the password reset with a token from the email.

**Request:**
```json
{
  "token": "reset-token-from-email",
  "new_password": "••••"
}
```

---

### 6.5 Conversations

#### `GET /api/conversations`

List conversations for the authenticated user.

**Query params:**
- `limit` (int, default 50)
- `offset` (int, default 0)
- `archived` (bool, default false)

**Response (200):**
```json
[
  {
    "id": "uuid",
    "title": "Domanda inventario",
    "created_at": "2026-04-26T...",
    "updated_at": "2026-04-26T...",
    "message_count": 12,
    "last_message_preview": "..."
  }
]
```

#### `GET /api/conversations/{id}`

Get a conversation with its messages.

#### `POST /api/conversations`

Create a new (empty) conversation.

#### `PATCH /api/conversations/{id}`

Update title or archive status.

#### `DELETE /api/conversations/{id}`

Delete a conversation and all messages (cascade).

---

### 6.6 Chat

#### `POST /api/chat/stream`

Send a message and receive a streaming SSE response.

**Headers:**
```
Authorization: Bearer <jwt>
Content-Type: application/json
Accept: text/event-stream
```

**Request:**
```json
{
  "conversation_id": "uuid (optional)",
  "message": "...",
  "use_kb": true,
  "model_preference": "claude-sonnet" 
}
```

**Response (`text/event-stream`):**
```
event: token
data: {"text": "Hello"}

event: token
data: {"text": " world"}

event: done
data: {"message_id": "uuid", "total_tokens": 45, "cost_usd": 0.000123}
```

#### `POST /api/chat`

Non-streaming variant. Returns full response after generation completes.

**Response (200):**
```json
{
  "conversation_id": "uuid",
  "message_id": "uuid",
  "role": "assistant",
  "content": "...",
  "model_used": "claude-sonnet-4-5",
  "tokens_in": 100,
  "tokens_out": 200,
  "cost_usd": 0.000123,
  "latency_ms": 1234
}
```

---

### 6.7 Knowledge Base (KB)

#### `POST /api/kb/upload`

Upload a document (PDF, DOCX, XLSX, DXF, TXT).

**Request (multipart):**
```
file: <binary>
title: "Manuale procedura"
description: "Procedura standard per..."
```

**Response (201):**
```json
{
  "document_id": "uuid",
  "filename": "manuale.pdf",
  "size_bytes": 124582,
  "status": "pending",
  "celery_task_id": "..."
}
```

The document is processed asynchronously: parsed, chunked, embedded, and indexed.

#### `POST /api/kb/scan-directory`

Trigger a rescan of all watched directories.

#### `GET /api/kb/documents`

List documents.

**Query:** `status`, `search`, `limit`, `offset`

#### `GET /api/kb/documents/{id}`

Get document metadata + status.

#### `DELETE /api/kb/documents/{id}`

Delete document and all chunks.

---

### 6.8 Teach

#### `POST /api/teach`

Manually train the assistant on a piece of text (creates a Memory).

**Request:**
```json
{
  "content": "...",
  "category": "policy"
}
```

---

### 6.9 Channels (Webhooks)

These are inbound webhook endpoints used by external services:

#### `POST /api/channels/telegram/webhook`

Telegram Bot API webhook. Verifies via `X-Telegram-Bot-Api-Secret-Token` header.

#### `GET /api/channels/whatsapp/webhook`

WhatsApp webhook verification (Meta GET). Returns hub.challenge.

#### `POST /api/channels/whatsapp/webhook`

WhatsApp inbound message webhook. Validates signature via `X-Hub-Signature-256`.

---

### 6.10 Admin — Users & Org

All `/api/admin/*` endpoints require `role = admin` or `role = owner`.

#### `GET /api/admin/users`

List users in the org.

**Query:** `role`, `is_active`, `search`

#### `POST /api/admin/users`

Create a new user. If no password provided, generates a temporary one and returns it.

**Request:**
```json
{
  "email": "new@example.com",
  "display_name": "New User",
  "role": "user",
  "password": "optional"
}
```

#### `GET /api/admin/users/{id}`

User detail with stats (message count, conversation count, recent activity).

#### `PUT /api/admin/users/{id}`

Update user (name, role, active).

#### `DELETE /api/admin/users/{id}`

Soft delete (email becomes `__deleted__<original>`).

#### `POST /api/admin/users/{id}/reset-password`

Generate new temp password.

#### `POST /api/admin/users/{id}/activate`
#### `POST /api/admin/users/{id}/deactivate`
#### `GET /api/admin/users/{id}/activity`

#### `GET /api/admin/org` / `PUT /api/admin/org`

Get/update organization settings.

---

### 6.11 Admin — Connectors

#### `GET /api/admin/connectors`

List all connectors with current status (configured, enabled, last test).

**Response:**
```json
[
  {
    "type": "telegram",
    "name": "Telegram Bot",
    "icon": "telegram",
    "category": "messaging",
    "is_enabled": true,
    "status": "ok",
    "tested_at": "2026-04-26T...",
    "fields": [
      {"key": "bot_token", "label": "Bot Token", "type": "password", "required": true},
      ...
    ],
    "config": {"bot_token": "••••••••", "webhook_secret": "••••••••"}
  }
]
```

Sensitive values are masked.

#### `PUT /api/admin/connectors/{type}`

Save/update connector config. Existing masked values (`••••••••`) preserved.

#### `POST /api/admin/connectors/{type}/enable`
#### `POST /api/admin/connectors/{type}/disable`
#### `POST /api/admin/connectors/{type}/test`

Live connection test. Returns `{ok: bool, message: str}`.

#### `PATCH /api/admin/connectors/{type}/roles`

Set which roles can use this connector.

#### `DELETE /api/admin/connectors/{type}`

Delete config (preserves type, just clears credentials).

**Available connector types:**
- `telegram` — Telegram Bot
- `whatsapp` — WhatsApp Business
- `smtp` — Outgoing email
- `imap` — Incoming email
- `github` — GitHub Issues integration
- `anthropic` — Claude API
- `deepseek` — DeepSeek API
- `ollama` — Local Ollama instance
- `backup` — Backup destination

---

### 6.12 Admin — Skills

#### `GET /api/admin/skills`

List available skills with current state.

**Response:**
```json
[
  {
    "skill_id": "low_stock_alert",
    "name": "Avviso scorte basse",
    "description": "...",
    "is_enabled": true,
    "config": {"check_interval_hours": 4},
    "allowed_roles": ["admin", "owner"]
  }
]
```

#### `POST /api/admin/skills/{id}/enable`
#### `POST /api/admin/skills/{id}/disable`
#### `PATCH /api/admin/skills/{id}/roles`
#### `PUT /api/admin/skills/{id}/config`

**Available skills:**
- `low_stock_alert` (MEDIC) — alerts on low product stock
- `daily_report` — daily summary email
- `backup_auto` — scheduled backup
- `telegram_notifications` — proactive Telegram alerts
- `email_reader` — IMAP polling for ticket creation
- `telegram_commands` — bot command handler (webhook)
- `telegram_voice` — voice message transcription (webhook)
- `email_alerts` — email-based alerts
- `whatsapp_chat` — WhatsApp inbound chat (webhook)
- `github_issues` — GitHub issue sync

---

### 6.13 Admin — Knowledge Base

#### `GET /api/admin/kb/documents`

List all documents in the org KB.

#### `DELETE /api/admin/kb/documents/{id}`

Delete document and chunks.

#### `GET /api/admin/kb/search?q=...`

Vector search across the org's KB.

**Response:**
```json
{
  "results": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "title": "Manuale...",
      "snippet": "...",
      "similarity": 0.873
    }
  ]
}
```

#### `POST /api/admin/kb/reindex`

Reindex pending/failed documents.

#### `GET /api/admin/kb/watch-paths`
#### `POST /api/admin/kb/watch-paths`
#### `PUT /api/admin/kb/watch-paths/{id}`
#### `DELETE /api/admin/kb/watch-paths/{id}`
#### `POST /api/admin/kb/watch-paths/{id}/scan`

Manage filesystem watch paths for auto-ingestion.

#### `GET /api/admin/kb/stats`

Document/chunk counts, by-status breakdown.

---

### 6.14 Admin — Audit

#### `GET /api/admin/audit/logs`

Retrieve audit log entries.

**Query:** `event_type`, `actor`, `from`, `to`, `limit`, `offset`

**Response:**
```json
[
  {
    "id": "uuid",
    "event_type": "admin_action",
    "actor": "uuid",
    "summary": "Updated user role to admin",
    "details_json": {...},
    "created_at": "2026-04-26T..."
  }
]
```

#### `GET /api/admin/audit/logs/export`

CSV export of audit log.

---

### 6.15 Admin — Backup

#### `GET /api/admin/backup`

List recent backups.

#### `POST /api/admin/backup/trigger`

Trigger a backup now (returns 202 Accepted with task id).

#### `GET /api/admin/backup/{id}/status`

Check backup status.

---

### 6.16 Admin — System

#### `GET /api/admin/system/status`

System health snapshot: CPU, memory, disk, DB pool, Redis, Ollama.

#### `GET /api/admin/system/metrics`

Time-series metrics for the last hour (used by overview page).

#### `GET /api/admin/system/overview`

Aggregate AI usage, message counts, top users.

---

### 6.17 Admin — AI Actions

Manage which user/role/connector combinations are allowed for which AI actions.

#### `GET /api/admin/ai-actions`
#### `GET /api/admin/ai-actions/users`
#### `PATCH /api/admin/ai-actions/{action_key}`

---

### 6.18 MEDIC Client

All `/api/medic/*` endpoints require role `user` minimum (org must be MEDIC sector).

#### Products

- `GET /api/medic/products` — list products
- `POST /api/medic/products` — create product
- `GET /api/medic/products/{id}`
- `PUT /api/medic/products/{id}`
- `DELETE /api/medic/products/{id}`

#### Lots

- `GET /api/medic/products/{id}/lots` — list lots for product
- `POST /api/medic/products/{id}/lots` — add stock lot

#### Inventory

- `GET /api/medic/inventory` — inventory snapshot with expiring lots
- `GET /api/medic/stock/alerts` — low stock alerts

#### Sales

- `POST /api/medic/sales` — record a sale (deducts from stock)
- `GET /api/medic/sales` — list sales
- `GET /api/medic/sales/{id}`
- `PUT /api/medic/sales/{id}`
- `DELETE /api/medic/sales/{id}` — reverses stock deduction

#### Stock corrections

- `POST /api/medic/products/{id}/stock-correction` — manual adjustment

#### Agent Warehouse

- `GET /api/medic/agent-warehouse/allocations` — admin view: all agents
- `GET /api/medic/agent-warehouse/my` — current user's allocations
- `POST /api/medic/agent-warehouse/allocate` — allocate stock to agent
- `POST /api/medic/agent-warehouse/return` — return stock from agent
- `GET /api/medic/agent-warehouse/movements` — full movement history

#### Stats

- `GET /api/medic/stats/summary` — sales summary by period

---

## 7. Server-Sent Events (SSE)

Used for streaming chat responses. The client opens an HTTP/1.1 or HTTP/2 connection with `Accept: text/event-stream` and reads events as they arrive.

### 7.1 Event Format

```
event: <event_name>
data: <JSON payload>

```

(Note: blank line between events.)

### 7.2 Chat Stream Events

| Event | Payload | When |
|---|---|---|
| `token` | `{"text": "..."}` | Each token (or chunk of tokens) from the model |
| `usage` | `{"tokens_in": N, "tokens_out": N}` | After model completes (mid-stream possible) |
| `error` | `{"detail": "..."}` | Error during generation |
| `done` | `{"message_id": "uuid", "total_tokens": N, "cost_usd": F}` | Final event |

### 7.3 Client Example (JavaScript)

```javascript
const response = await fetch('/api/chat/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({message: '...'}),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const {value, done} = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value);
  // Parse SSE events from chunk...
}
```

---

## 8. Webhooks

### 8.1 Telegram Webhook

Inbound webhook from Telegram Bot API. Set via:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://workmind-bender.tail898ef4.ts.net/api/channels/telegram/webhook" \
  -d "secret_token=<SECRET>"
```

The API verifies `X-Telegram-Bot-Api-Secret-Token` matches the configured secret.

### 8.2 WhatsApp Webhook

Two endpoints:

1. `GET /api/channels/whatsapp/webhook` — for verification handshake from Meta
2. `POST /api/channels/whatsapp/webhook` — for inbound messages

Signature verified via `X-Hub-Signature-256` (HMAC-SHA256 of body using app_secret).

---

**End of API Reference**

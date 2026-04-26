# WorkMind v2 — Administrator Manual

**Audience:** Organization administrators (role = admin or owner)
**Prerequisite:** Familiarity with the platform (see User Manual first)

---

## Table of Contents

1. [Admin Overview](#1-admin-overview)
2. [User Management](#2-user-management)
3. [Connectors](#3-connectors)
4. [Skills](#4-skills)
5. [Knowledge Base](#5-knowledge-base)
6. [AI Settings & Costs](#6-ai-settings--costs)
7. [Audit Log](#7-audit-log)
8. [System Status](#8-system-status)
9. [Backup](#9-backup)
10. [Troubleshooting Common Issues](#10-troubleshooting-common-issues)

---

## 1. Admin Overview

As an administrator, you have access to the **Admin** section in the sidebar. This is where you manage:

- Users
- External integrations (connectors)
- Automated capabilities (skills)
- Knowledge base content
- AI configuration
- System monitoring
- Audit history
- Backups

You can perform anything a regular user can, plus admin-specific actions.

**Roles overview:**

| Role | Capabilities |
|---|---|
| `owner` | Everything; can change org settings; promote/demote admins |
| `admin` | Manage users (except owner), connectors, skills, KB, audit |
| `supervisor` | Read-only access to admin views |
| `user` | Standard user; no admin access |

---

## 2. User Management

**Admin → Utenti**

### 2.1 Listing Users

The user list shows all users in your organization with:
- Name and email
- Role
- Active status
- Last seen timestamp

Filters:
- By role
- By status (active/inactive)
- Search by name or email

### 2.2 Creating a User

1. Click **+ Nuovo Utente**
2. Fill in:
   - **Email** (required)
   - **Display name** (optional, defaults to email prefix)
   - **Role** (default: user)
   - **Password** (optional; if empty, system generates a temporary one)
3. Click **Crea**

If a temp password was generated, the system shows it once. **Copy it and share securely** with the user (e.g., 1Password, Signal). They should change it on first login.

### 2.3 Editing a User

Click on a user → opens detail view.

You can update:
- Display name
- Role
- Active status

### 2.4 Resetting a Password

In the user detail view: **Reset Password**.

This generates a new temp password. Communicate to the user via secure channel.

### 2.5 Deactivating vs Deleting

**Deactivate** (`POST /admin/users/{id}/deactivate`):
- User cannot log in
- Data is preserved
- Reversible (reactivate any time)
- **Use this for** vacationing employees, temporary holds

**Delete** (`DELETE /admin/users/{id}`):
- Soft delete: email becomes `__deleted__<original>`, account inactive
- After 30 days, hard delete option (operator-level)
- **Use this for** permanent departures

### 2.6 Viewing User Activity

**User detail** → **Attività**:
- Recent conversations
- Recent messages
- Login history
- Total AI cost incurred

Useful for understanding usage patterns and investigating anomalies.

### 2.7 Best Practices

- **Promote sparingly.** Most users should be `user` role. Only promote to `admin` when needed.
- **Review inactive users monthly.** Deactivate accounts unused for 90+ days.
- **Use display names consistently.** "Mario Rossi" not "mario", "MRossi", etc.
- **Audit login_failed events** weekly to spot password attacks.

---

## 3. Connectors

**Admin → Connettori**

Connectors are integrations with external services. WorkMind ships with these:

| Type | Purpose |
|---|---|
| Telegram | Bot for chat, voice transcription, notifications |
| WhatsApp | Customer chat via WhatsApp Business |
| SMTP | Outgoing email (alerts, password reset) |
| IMAP | Incoming email (auto-ticket creation) |
| GitHub | Issue tracking integration |
| Anthropic | Claude AI |
| DeepSeek | DeepSeek AI |
| Ollama | Local AI |
| Backup | Backup destination configuration |

### 3.1 Configuring a Connector

1. Find the connector card
2. Click **Configura**
3. Fill in the fields (passwords/tokens are masked after save)
4. Click **Salva**

The state changes to **configurato** but **disabilitato**. To activate, click **Abilita**.

### 3.2 Testing a Connector

Click **Test** to verify the configuration is correct (e.g., Telegram bot reachable, SMTP login successful).

If the test fails:
- Check the credentials
- Verify network access (some services need outbound HTTPS)
- See error message for specifics

### 3.3 Role Restrictions

**Admin → Connettori → ⚙️**

You can restrict which roles can use a connector. Example: only admins can use the GitHub Issues connector. Useful when:
- A connector exposes sensitive data
- A connector incurs costs (e.g., Anthropic)

### 3.4 Disabling/Deleting

**Disable** keeps the config but stops using it. Quick on/off.

**Delete** removes the encrypted config from the database. Use this when:
- You're rotating credentials and want to start fresh
- You're decommissioning the integration

### 3.5 Telegram Setup Walkthrough

1. **Create bot:** Open Telegram, message @BotFather, `/newbot`, follow prompts
2. **Get token:** BotFather gives you a token like `1234:AAAA...`
3. **In WorkMind:** Connectors → Telegram → Configura
4. **Paste bot_token**
5. **Webhook secret:** generate a random string (e.g., 32 chars)
6. **Save**, then **Abilita**, then **Test** — should say "Bot @YourBot raggiunto"
7. **Set webhook URL:**
   ```bash
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://workmind-bender.tail898ef4.ts.net/api/channels/telegram/webhook" \
     -d "secret_token=<YOUR_SECRET>"
   ```
8. **Verify** by sending a message to your bot

---

## 4. Skills

**Admin → Skill**

Skills are automated capabilities that run on a schedule or webhook. WorkMind ships with:

| Skill | Type | Purpose |
|---|---|---|
| `low_stock_alert` (MEDIC) | Scheduled | Alert when products below threshold |
| `daily_report` | Scheduled | Daily summary email |
| `backup_auto` | Scheduled | Automated backups |
| `telegram_notifications` | Scheduled | Proactive Telegram alerts |
| `email_reader` | Scheduled | IMAP polling, ticket creation |
| `email_alerts` | Scheduled | Email-based alerts |
| `telegram_commands` | Webhook | Bot command handler |
| `telegram_voice` | Webhook | Voice message transcription |
| `whatsapp_chat` | Webhook | WhatsApp inbound chat |
| `github_issues` | Scheduled | GitHub issue sync |

### 4.1 Enabling a Skill

1. Find the skill card
2. Click **Abilita**
3. Configure parameters (e.g., check interval, recipients)
4. Click **Salva configurazione**

The skill runs at the configured time (or on webhook trigger). Logs visible in the Audit section.

### 4.2 Skill Dependencies

Many skills require connectors:
- `telegram_*` → Telegram connector enabled
- `email_*` → SMTP and/or IMAP connector enabled
- `low_stock_alert` → Telegram or SMTP connector for delivery
- `backup_auto` → Backup connector configured

If you enable a skill without its dependencies, you'll see a warning. The skill won't run until deps are met.

### 4.3 Configuring Skill Parameters

Each skill has its own config fields. Examples:

**low_stock_alert:**
- `check_interval_hours` (default 4) — how often to check
- `notify_via` (telegram/email) — delivery channel

**daily_report:**
- `send_hour` (default 8) — local time
- `recipients` — list of emails

**telegram_notifications:**
- `daily_summary_enabled` (true/false)
- `daily_summary_hour`
- `notify_chat_ids` — comma-separated Telegram chat IDs

### 4.4 Disabling a Skill

Click **Disabilita**. The job is removed from the scheduler immediately. Webhook-triggered skills stop responding.

### 4.5 Skill Execution Logs

Currently, skill executions are logged to the system journal. For each run, you'll see:
- Skill ID
- Start time
- Success/failure
- Duration

Roadmap: dedicated UI panel for skill execution history.

---

## 5. Knowledge Base

**Admin → Knowledge Base**

Comprehensive view of all KB documents in your organization.

### 5.1 Document Statuses

| Status | Meaning |
|---|---|
| `pending` | Queued for processing |
| `processing` | Being parsed and embedded |
| `ready` | Indexed and searchable |
| `failed` | Processing failed; see error message |

### 5.2 Uploading Documents

Use the user interface (**Knowledge Base** in main sidebar) or:

**Admin → Knowledge Base → Upload**

Drag and drop multiple files. Supported formats:
- PDF (with OCR for scanned docs — slow)
- DOCX
- XLSX (treats sheets as separate documents)
- DXF (AutoCAD — extracts text annotations)
- TXT, MD

### 5.3 Watch Paths

Configure folders to be auto-monitored. New files appear → automatically processed.

**Admin → Knowledge Base → Watch Paths**

1. Add path: e.g., `/home/emanuele/shared-docs/manuals/`
2. Set patterns: e.g., `["*.pdf", "*.docx"]`
3. Enable recursive (subdirectories) if needed
4. Save

The watcher polls every 5 minutes (configurable). New files are queued for indexing.

### 5.4 Reindexing

If you change embedding settings or recover from a bad batch:

**Admin → Knowledge Base → Reindex**

This re-processes documents in `pending` or `failed` status. Successful documents are not touched.

For a **full re-index** of everything, contact your operator (it requires deleting existing chunks).

### 5.5 Searching the KB

**Admin → Knowledge Base → Cerca** — same as user search, but admins see all org docs (not just their own).

### 5.6 Best Practices

- **Use descriptive titles.** "Manuale procedure 2024" not "doc1"
- **Avoid duplicates.** WorkMind detects exact duplicates by hash, but near-duplicates pollute results
- **Update outdated docs.** Delete old versions when uploading replacements
- **Mind the limit.** Performance degrades past ~500K chunks. For larger KBs, talk to operator

---

## 6. AI Settings & Costs

**Admin → Sistema → AI Usage**

### 6.1 Daily/Monthly Costs

Dashboard shows:
- Total cost today, this week, this month
- Breakdown by provider (Claude, DeepSeek, Ollama)
- Top users by cost
- Cost per conversation (averages)

### 6.2 Cost Anomalies

Watch for:
- Sudden spikes (could indicate abuse)
- One user dominating (>30% of org cost) — investigate
- Unexpected provider usage (e.g., Claude when you intended DeepSeek)

### 6.3 Daily Budget

The system has a global daily budget (`WORKMIND_MAX_DAILY_COST_USD`, default $20). If exceeded:
- New AI requests fail with 429 (Too Many Requests)
- Users see "Budget giornaliero esaurito" message
- Resets at midnight UTC

To change: contact your operator (env var change).

### 6.4 Per-User Limits (planned)

Roadmap: per-user daily caps to prevent any single user from exhausting the org budget.

### 6.5 Provider Selection

Users can specify a preferred model:
- `claude-sonnet` — Anthropic's flagship; balanced quality/cost
- `claude-haiku` — Cheaper, faster
- `deepseek-chat` — Very cheap; good general quality
- `ollama-local` — Free; runs on local server; slower and lower quality

By default, the system tries:
1. User's `model_preference` (if set)
2. Claude Sonnet
3. DeepSeek (fallback if Claude fails or budget tight)
4. Ollama (last resort)

---

## 7. Audit Log

**Admin → Audit**

Every administrative action and security-relevant event is logged.

### 7.1 What's Logged

- Login successes and failures
- Logout
- Password changes
- 2FA enable/disable
- 2FA challenge failures
- User CRUD (create, update, delete, reset password)
- Connector configuration changes
- Skill enable/disable
- KB document uploads/deletions
- Permission changes

### 7.2 Filters

Filter by:
- Event type
- Actor (user)
- Date range

### 7.3 Exporting

**Esporta CSV** produces a CSV with all logs matching current filters. Import into Excel/spreadsheet for analysis.

### 7.4 Investigation Patterns

**Suspicious login attempts:**
```
Event: login_failed, repeated from same IP
Action: investigate, consider blocking IP
```

**Unauthorized admin attempt:**
```
Event: admin_action with role=user (unusual)
Action: review user's permissions
```

**Mass deletion:**
```
Event: kb_document_deleted, many in short window
Action: verify with the actor
```

### 7.5 Retention

Audit logs are kept indefinitely (per compliance requirements). They're stored in the `audit_logs` table and included in backups.

---

## 8. System Status

**Admin → Sistema**

### 8.1 Status Page

Real-time view of:
- API health
- Database (connections, slow queries)
- Redis
- Ollama (model availability)
- Disk usage
- Active users (last 5 min)

### 8.2 Metrics

Time-series view of:
- Request rate
- Error rate
- p95 latency
- AI cost rate

For deeper analysis, access **Grafana** (your operator can give you the link). Grafana has dashboards for trends over hours/days/weeks.

### 8.3 Overview

Aggregate stats:
- Total users, active users today
- Total messages today, this month
- AI cost today, this month
- KB document count, chunk count

---

## 9. Backup

**Admin → Sistema → Backup**

### 9.1 Automatic Backups

Daily at 02:30 UTC (configurable). Retained:
- 30 days for daily backups
- 12 months for monthly (1st of each month)

### 9.2 Manual Backup

Click **Trigger backup** to start one immediately. Returns a job ID; check status with **Refresh**.

### 9.3 Backup Status

For each backup, see:
- Type (database / files)
- Status
- Size
- Duration
- Path

### 9.4 Restore

Restoration requires operator-level access (via SSH). Contact your operator.

---

## 10. Troubleshooting Common Issues

### 10.1 User Can't Log In

**Symptom:** User reports invalid credentials.

**Steps:**
1. Verify the email is correct (typos, capitalization)
2. Check if user is active (Admin → Users → search)
3. Check audit log for `login_failed` events
4. If user forgot password, use **Reset Password** (Admin)
5. If 2FA issue, you may need to disable 2FA for that user (operator-level: directly in DB)

### 10.2 AI Responses Slow

**Symptom:** Chat takes >10s for first token.

**Steps:**
1. Check **System** dashboard for current load
2. Check AI cost — if budget exhausted, requests are rejected
3. Try changing model preference (Claude → DeepSeek)
4. If Ollama-only, expect slower responses (CPU inference)
5. Network latency between bender and AI providers can cause delays

### 10.3 KB Search Returns Irrelevant Results

**Symptom:** Search for X returns documents unrelated to X.

**Steps:**
1. Verify the document is `ready` status
2. Try a longer/more specific query
3. Check if KB has many duplicate or similar docs (cleanup needed)
4. If docs are very recent, indexing may not be complete

### 10.4 Connector Test Fails

**Symptom:** Test connector → "Errore: ..."

Common causes:
- Wrong credentials
- Outbound network blocked (rare, but check with operator)
- Service quota exhausted (e.g., AI provider monthly limit)
- API endpoint changed (provider deprecated, update needed)

### 10.5 Skill Doesn't Run

**Symptom:** Skill is enabled but never executes.

**Steps:**
1. Verify dependencies (connectors enabled?)
2. Check the skill's schedule (cron timing)
3. Look at audit log for skill execution events
4. Check the system journal (operator)
5. Try disabling and re-enabling the skill

### 10.6 Out of Disk Space

**Symptom:** Operations failing; disk warning in System dashboard.

**Steps:**
1. Check old backups — clean up or move offline
2. Check uploads directory for large files
3. Check Postgres growth — possibly need to vacuum
4. Contact operator for capacity expansion

---

## 11. Security Best Practices

- **Enforce 2FA** for all admin/owner roles (currently a recommendation; soon mandatory)
- **Rotate API keys** every 6 months
- **Review audit log** weekly for anomalies
- **Test backups** quarterly (operator)
- **Keep credentials secure** — use 1Password/Bitwarden, never email/Slack
- **Limit owner role** to 1-2 trusted people
- **Regular password resets** for service accounts (if any)
- **Notify your operator** of any suspected breach immediately

---

## 12. Operator Escalation

For tasks beyond admin scope, contact your operator. Include in your message:

- What you want to do
- Why (business reason)
- Any error messages
- Date/time of issue
- Affected users

Operator has SSH access and can:
- Modify environment configuration
- Restore from backup
- Run database queries
- Inspect logs in detail
- Update the platform

---

**End of Administrator Manual**

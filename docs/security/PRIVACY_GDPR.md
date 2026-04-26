# WorkMind v2 — Privacy & GDPR Compliance

**Last Reviewed:** 2026-04-26
**Data Protection Officer:** (to be designated)
**Lawful Basis:** Contract performance (Article 6(1)(b) GDPR) + consent for AI processing (Article 6(1)(a))

---

## Table of Contents

1. [Scope](#1-scope)
2. [Personal Data Inventory](#2-personal-data-inventory)
3. [Data Subjects' Rights](#3-data-subjects-rights)
4. [Lawful Bases](#4-lawful-bases)
5. [Data Retention](#5-data-retention)
6. [Sub-processors](#6-sub-processors)
7. [International Transfers](#7-international-transfers)
8. [Security Measures](#8-security-measures)
9. [Breach Notification](#9-breach-notification)
10. [Privacy by Design](#10-privacy-by-design)

---

## 1. Scope

This document describes how WorkMind v2 processes personal data in compliance with:

- **GDPR** — EU Regulation 2016/679 (primary)
- **Italian DPA** ("Garante per la Protezione dei Dati Personali") guidance
- **ePrivacy** — for cookie/tracking use (minimal in WorkMind)

The platform is operated by the data controller (WorkMind operator). Customers using the platform act as data controllers for their end-users' data; WorkMind acts as data processor in that relationship.

---

## 2. Personal Data Inventory

### 2.1 Data Categories Collected

| Category | Examples | Storage | Retention |
|---|---|---|---|
| **Identity** | Name, email, role | `users` table | Until account deletion |
| **Authentication** | Password hash (bcrypt), TOTP secret | `users` table | Until account deletion |
| **Activity** | Login times, last_seen | `users` table, `audit_logs` | 7 years (audit) |
| **Communication content** | Chat messages, KB documents | `messages`, `documents` | Until user deletes |
| **Communication metadata** | Conversation timestamps, models used | `conversations`, `messages` | Until user deletes |
| **AI usage** | Token counts, cost | `model_usage` | 7 years (financial) |
| **External IDs** | Telegram chat_id, WhatsApp number | `channels` | Until disconnected |
| **Audit trail** | IP, user-agent, action details | `audit_logs` | 7 years |
| **MEDIC-specific** | Sales records, customer names | `medic_sales` | 10 years (Italian fiscal law) |

### 2.2 Data Categories NOT Collected

- ❌ Browsing history outside WorkMind
- ❌ Biometric data
- ❌ Geolocation
- ❌ Special categories of personal data (Article 9 GDPR), unless explicitly entered by users into chat/KB

### 2.3 Special Categories (Article 9)

If a user uploads a medical document to KB, or types health information in chat, that data falls under Article 9. **Consent is required** at upload time. Currently, this is implicit in the EULA; we plan a more explicit toggle.

---

## 3. Data Subjects' Rights

GDPR grants individuals these rights. WorkMind implements them as follows:

### 3.1 Right of Access (Article 15)

Endpoint: `GET /api/auth/me` (own data)
For full export, contact the data controller (admin) who can produce a JSON export via:

```bash
# Admin command (planned API)
GET /api/admin/users/{id}/export
```

Returns: user record, all conversations, all messages, all uploaded documents, audit log entries.

### 3.2 Right to Rectification (Article 16)

Endpoint: `PATCH /api/auth/me` (own profile)
Admin: `PUT /api/admin/users/{id}` (any user in same org)

### 3.3 Right to Erasure / "Right to be Forgotten" (Article 17)

Endpoint: `DELETE /api/admin/users/{id}` (admin action)

**Implementation:** Soft delete — email becomes `__deleted__<original>`, `is_active=false`, but row preserved for audit log integrity.

For **full hard delete** (removing all data), the operator must run:

```sql
-- ⚠️ DESTRUCTIVE — use only after legal review
BEGIN;

-- 1. Verify user has been notified and provided export
-- 2. Delete in order due to foreign keys:
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = '<uuid>');
DELETE FROM conversations WHERE user_id = '<uuid>';
DELETE FROM memories WHERE user_id = '<uuid>';
DELETE FROM model_usage WHERE user_id = '<uuid>';
-- audit_logs: REPLACE user_id with NULL but keep summary (legitimate interest)
UPDATE audit_logs SET user_id = NULL, details_json = jsonb_set(details_json, '{user_deleted}', 'true') WHERE user_id = '<uuid>';
DELETE FROM password_reset_tokens WHERE user_id = '<uuid>';
DELETE FROM users WHERE id = '<uuid>';

COMMIT;
```

The soft-delete-then-hard-delete-after-30-days pattern is recommended.

### 3.4 Right to Data Portability (Article 20)

Same as 3.1 — export endpoint produces machine-readable JSON.

### 3.5 Right to Restriction (Article 18)

Endpoint: `POST /api/admin/users/{id}/deactivate` — disables login but preserves data.

### 3.6 Right to Object (Article 21)

User can object to processing for direct marketing (not applicable in WorkMind currently — no marketing emails) or other automated decisions. The AI features can be disabled per-user via admin.

### 3.7 Right Regarding Automated Decisions (Article 22)

WorkMind's AI does not make decisions with legal or significant effects on users without human oversight. Any AI-generated recommendations (e.g., low-stock alerts) are informational only.

### 3.8 Time to Respond

Per GDPR, requests must be answered within **30 days** (extendable to 90 days for complex cases).

WorkMind operator commits to **15 business days** for routine requests.

---

## 4. Lawful Bases

| Processing Activity | Lawful Basis | Justification |
|---|---|---|
| User account creation | Contract (6(1)(b)) | Necessary to provide service |
| Password authentication | Contract (6(1)(b)) | Necessary for security |
| Logging audit trail | Legitimate interest (6(1)(f)) | Security monitoring, fraud prevention |
| Sending password reset emails | Contract (6(1)(b)) | Necessary for account recovery |
| AI processing of chat | Contract (6(1)(b)) + consent | Service is AI-based; consent for external API usage |
| KB document indexing | Contract (6(1)(b)) | Core feature |
| MEDIC sales record retention | Legal obligation (6(1)(c)) | Italian fiscal law requires 10 years |
| Cookie usage | Strictly necessary | Session cookies only; no tracking |

---

## 5. Data Retention

### 5.1 Retention Schedule

| Data | Active Retention | Post-Deletion | Justification |
|---|---|---|---|
| User account | Until user deletes | 30 days soft, then hard delete | Right to be forgotten |
| Chat conversations | Until user deletes | Same | User-controlled |
| KB documents | Until user deletes | Same | User-controlled |
| Audit logs | 7 years | Hard delete | Legal & security |
| Model usage / AI cost | 7 years | Hard delete | Financial records |
| Password reset tokens | 1 hour | Auto-deleted | Security |
| Backup files | 30 days (daily), 12 months (monthly) | Auto-deleted | Disaster recovery |
| MEDIC sales | 10 years | Hard delete | Italian fiscal law (DPR 633/72) |
| MEDIC product catalog | Indefinite (active business records) | — | Operational |
| Telegram/WhatsApp conversations | Until user disconnects channel | 30 days then hard delete | Channel record |

### 5.2 Automated Cleanup

Currently manual via `app/tasks/maintenance.py` (Celery weekly job):

```python
@celery_app.task
def cleanup_expired_data():
    # Delete password reset tokens older than 1 hour
    # Delete soft-deleted users older than 30 days
    # Delete temp_tokens, expired sessions
    ...
```

Roadmap: extend with full retention policy enforcement.

---

## 6. Sub-processors

WorkMind uses these third-party services that may process personal data on our behalf:

| Sub-processor | Purpose | Data Processed | Location | DPA Status |
|---|---|---|---|---|
| **Anthropic, PBC** | Claude AI completions | Anonymized chat content | USA | DPA in place |
| **DeepSeek** | DeepSeek AI completions | Anonymized chat content | China | ⚠️ Limited transfer protections; consent required |
| **Tailscale, Inc.** | Network infrastructure (VPN) | IP addresses, traffic metadata | USA/Canada | DPA available |
| **Meta Platforms** (WhatsApp Business API) | WhatsApp messaging | Phone number, message content | Ireland (EU) | Standard DPA |
| **Telegram FZ-LLC** | Telegram bot platform | Telegram user_id, message content | UAE | ToS-based; limited GDPR alignment |
| **GitHub, Inc.** | Code hosting (private repo) | No production data | USA | DPA in place |
| **Cloud Provider (Bender host)** | Server infrastructure | All data | EU (recommended) | Provider DPA |

### 6.1 Sub-processor Changes

When we add or change sub-processors, we will:
- Update this document
- Notify customers at least 30 days in advance for material changes
- Obtain re-consent if processing scope changes

---

## 7. International Transfers

### 7.1 Transfers to USA

Anthropic, Tailscale, GitHub: covered by **Standard Contractual Clauses** (SCCs) and the EU-US Data Privacy Framework (where applicable).

### 7.2 Transfers to China

DeepSeek operates from China. **No adequacy decision exists** for China. Transfers rely on:
- User explicit consent at AI provider selection
- Data minimization (anonymization before transfer)
- Operator's risk acceptance (documented per request)

**Mitigation:** When DeepSeek is used, the user is informed and the system anonymizes PII before sending. For high-sensitivity orgs, DeepSeek can be disabled per-org via admin config.

### 7.3 Transfers to UAE (Telegram)

If Telegram is used for inbound messaging, message content is processed by Telegram. Operator must make this clear in the org's privacy policy.

---

## 8. Security Measures

See `docs/security/SECURITY.md` for full details. Summary of GDPR Article 32 controls:

### 8.1 Technical Measures

- Encryption in transit (TLS 1.2+)
- Encryption at rest for sensitive config (Fernet)
- Password hashing (bcrypt 12)
- Two-factor authentication (TOTP)
- Multi-tenant data isolation (org_id scoping)
- Audit logging
- Daily backups with off-site copy (planned)
- Network isolation (Tailscale VPN, localhost-only services)

### 8.2 Organizational Measures

- Access on need-to-know basis
- Operator NDA for any team members
- Incident response procedure documented
- Regular review of audit logs
- Quarterly backup restore tests
- Annual penetration test (planned)

---

## 9. Breach Notification

### 9.1 Internal Detection

Breach indicators monitored:
- Unusual login patterns (audit_logs)
- Rate limit triggers
- Unauthorized API access attempts
- Unexpected data exports

### 9.2 Response Timeline

Per GDPR Article 33:

- **Detect** → assess severity
- **Within 72 hours of awareness**: notify supervisory authority (Garante)
- **Without undue delay**: notify affected data subjects (if high risk)
- **Document everything** in `docs/incidents/<date>.md`

### 9.3 Notification Content

Must include:
- Nature of breach
- Categories and approximate number of data subjects affected
- Categories and approximate number of records affected
- Likely consequences
- Measures taken or proposed to mitigate

### 9.4 Notification Templates

`docs/templates/breach-notification-supervisory.md` — for Garante
`docs/templates/breach-notification-subject.md` — for affected users

(To be created.)

---

## 10. Privacy by Design

WorkMind incorporates privacy considerations into engineering decisions:

### 10.1 Data Minimization

- We collect only what's needed (e.g., email, name; not phone, address)
- Email hash stored alongside email for unique constraint without leaking via index
- Optional fields kept optional (display_name nullable)

### 10.2 Purpose Limitation

- Data collected for service operation is not repurposed for marketing
- AI training: we do not use customer data to train AI models

### 10.3 Anonymization Before AI

```python
# In app/services/anonymizer.py
PATTERNS = {
    "fiscal_code_it": r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b",
    "iban": r"\bIT\d{2}[A-Z]\d{22}\b",
    "phone": r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b",
    "email": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
}
```

Before sending text to external AI providers, PII matching these patterns is replaced with `[PII_NNN]` tokens. The mapping is stored server-side, allowing reversal of the AI response back into the original text for the user.

### 10.4 Storage Limitation

- Retention policies enforced (see §5)
- Soft-delete-then-hard-delete pattern
- Backup retention bounded

### 10.5 Transparency

- This document is public for customers
- Privacy policy linked from login page (planned)
- Audit log accessible to admins
- Sub-processors disclosed (§6)

---

## 11. Customer Responsibilities

When a customer (data controller) uses WorkMind to process their end-users' data:

1. **Inform end-users** about WorkMind being a data processor
2. **Obtain consent** for any AI processing of personal data
3. **Maintain their own privacy policy** including WorkMind sub-processors
4. **Configure connectors and skills** in line with their privacy commitments
5. **Use the soft-delete feature** when end-users request data removal
6. **Respond to data subject requests** through the platform's tools

WorkMind provides:
- A **Data Processing Agreement** (DPA) template for execution between operator and customer
- **Tooling** for data subject requests (export, delete)
- **Audit log** for accountability

---

## 12. Cookie & Tracking Policy

WorkMind uses **only strictly necessary cookies**:

| Cookie | Purpose | Lifetime |
|---|---|---|
| `wm_access_token` (localStorage, not actual cookie) | Auth bearer token | 24h or until logout |
| `wm_refresh_token` (localStorage) | Token renewal | 30 days or until logout |

**No third-party tracking, analytics, or advertising cookies.**

This means no cookie consent banner is required (per ePrivacy).

If the operator adds analytics in the future (e.g., self-hosted Plausible), this section will be updated and a banner introduced.

---

## 13. Children's Data

WorkMind is **not intended for users under 16**. The service does not knowingly collect data from children. If a customer wishes to use WorkMind for educational purposes with minors, parental consent procedures must be implemented separately.

---

## 14. Changes to This Document

Material changes to this privacy document will be:
- Communicated to active customers via email
- Published with 30 days advance notice for new processing activities
- Approved by the Data Protection Officer (when designated)

Version history maintained at the bottom.

---

## Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-04-26 | Initial document |

---

**Contact for privacy matters:** privacy@workmind.example.com (placeholder; to be configured)

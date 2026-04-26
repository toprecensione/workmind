# WorkMind v2 — Documentation

Welcome to the WorkMind documentation hub. This directory contains the complete technical, operational, and product documentation for the platform.

---

## Quick Links

| If you are... | Start with |
|---|---|
| **A new engineer** | [Developer Guide](development/DEVELOPER_GUIDE.md) |
| **Deploying or operating** | [Deployment Guide](operations/DEPLOYMENT.md) → [Operations Runbook](operations/RUNBOOK.md) |
| **An end user** | [User Manual](manuals/USER_MANUAL.md) |
| **An admin** | [Admin Manual](manuals/ADMIN_MANUAL.md) |
| **An architect** | [Software Architecture](architecture/SOFTWARE_ARCHITECTURE.md) |
| **A security reviewer** | [Security Document](security/SECURITY.md) → [Privacy/GDPR](security/PRIVACY_GDPR.md) |
| **Looking for an API endpoint** | [API Reference](api/API_REFERENCE.md) |

---

## Document Catalog

### 📐 Architecture

- **[Software Architecture Document (SAD)](architecture/SOFTWARE_ARCHITECTURE.md)** — High-level system design, 4+1 view model, ADRs, runtime/process/development/physical views
- **[Database Schema](architecture/DATABASE_SCHEMA.md)** — Tables, indexes, foreign keys, conventions, migration history

### 🔌 API

- **[API Reference](api/API_REFERENCE.md)** — Complete endpoint catalog with request/response examples, auth, errors, rate limits, SSE, webhooks

### 🛠️ Development

- **[Developer Guide](development/DEVELOPER_GUIDE.md)** — Onboarding, project layout, local dev, coding standards, PR process, adding features and clients
- **[Testing Strategy](development/TESTING.md)** — Pyramid, fixtures, conventions, CI integration, coverage goals, manual checklists

### 🚀 Operations

- **[Deployment Guide](operations/DEPLOYMENT.md)** — Step-by-step server setup, systemd, Tailscale, observability stack
- **[Operations Runbook](operations/RUNBOOK.md)** — Daily ops, common tasks, incident playbooks, backup/recovery, capacity planning

### 🔐 Security & Privacy

- **[Security Architecture](security/SECURITY.md)** — Threat model, auth, authorization, data protection, incident response, security roadmap
- **[Privacy & GDPR](security/PRIVACY_GDPR.md)** — Data inventory, subjects' rights, sub-processors, retention, breach notification

### 📋 Process

- **[Software Development Lifecycle](process/SDLC.md)** — Phases, branching, code review, testing gates, release process
- **[Change Management](process/CHANGE_MANAGEMENT.md)** — Change categories, risk assessment, rollback strategies, communication

### 📖 Manuals

- **[User Manual](manuals/USER_MANUAL.md)** — Login, chat, KB, conversations, MEDIC features (for end users)
- **[Admin Manual](manuals/ADMIN_MANUAL.md)** — User management, connectors, skills, KB, audit, system status (for org admins)

### 📄 Whitepapers

- **[Multi-Client Architecture](papers/MULTI_CLIENT_ARCHITECTURE.md)** — How WorkMind serves diverse verticals through pluggable Client extensions
- **[AI Integration Architecture](papers/AI_INTEGRATION.md)** — ModelRouter, RAG pipeline, anonymization, cost control, streaming

### 🔍 Reviews

- **[Code Review 2026-04](reviews/CODE_REVIEW_2026-04.md)** — Comprehensive automated code review covering all modules with prioritized findings

---

## Maintenance

These documents are **living documents**. When you make changes that affect them:

1. Update the relevant document(s) in the same PR as the code change
2. Bump the "Last Updated" date at the top
3. For substantial changes, add an entry to the document's version history (where present)
4. Cross-link related documents to keep the web of references fresh

---

## Conventions

- **Markdown** is the source format (renders nicely on GitHub, supports tables/code/links)
- **English** is the primary language (some user-facing strings are Italian; documented as such)
- **Diagrams** in ASCII or Mermaid where possible (rather than image files); Mermaid blocks render on GitHub
- **Examples** are concrete and runnable wherever possible
- **Cross-references** use relative paths (`../security/SECURITY.md`)

---

## Document Status Legend

When you see a status header in a document:

- **Draft** — Work in progress, not authoritative yet
- **Approved** — Reviewed and considered current
- **Deprecated** — Kept for reference; superseded by newer version
- **Archived** — Historical; no longer maintained

---

## Contributing to Docs

Documentation PRs follow the same process as code (see [SDLC](process/SDLC.md)).

Good doc PRs:
- Update existing docs rather than creating new ones, when the content fits
- Link to other docs to avoid duplication
- Provide concrete examples
- Are reviewed for accuracy by someone who didn't write the content

---

## Document Inventory Statistics

| Category | Documents | Total LOC (approx) |
|---|---|---|
| Architecture | 2 | 1,400 |
| API | 1 | 1,000 |
| Development | 2 | 1,400 |
| Operations | 2 | 1,200 |
| Security & Privacy | 2 | 1,300 |
| Process | 2 | 1,000 |
| Manuals | 2 | 1,200 |
| Whitepapers | 2 | 1,400 |
| Reviews | 1 | 600 |
| **Total** | **16** | **~10,500** |

(Counts approximate. Updated as documents evolve.)

---

**Last index update:** 2026-04-26

# WorkMind v2 — Change Management Policy

**Version:** 1.0
**Last Updated:** 2026-04-26

---

## 1. Purpose

This document defines how changes to the WorkMind production environment are proposed, reviewed, approved, implemented, and tracked. It complements `docs/process/SDLC.md` (development process) and `docs/operations/RUNBOOK.md` (operational runbook).

Goals:
- **Reduce production incidents** caused by uncoordinated changes
- **Maintain audit trail** for compliance and post-mortem
- **Enable fast, safe iteration** without unnecessary friction
- **Keep stakeholders informed** of changes affecting them

---

## 2. Scope

This policy applies to all changes to:

- Production application code (backend, frontend)
- Production database schema
- Production environment configuration (`.env`, systemd units)
- Production infrastructure (Tailscale, firewall, dependencies)
- Production data (manual updates, migrations, cleanups)

It does **not** apply to:
- Local development environments
- Staging-only changes (lower bar; see SDLC)
- Documentation updates that don't affect runtime

---

## 3. Change Categories

### 3.1 Standard Change

Routine, low-risk changes that follow well-defined procedures.

**Examples:**
- Deploying a tested PR after CI green
- Restarting a service for log rotation
- Applying minor dependency updates
- Adjusting non-critical config values (e.g., log verbosity)
- Running a documented backup

**Approval:** Implicit (operator's discretion within standard procedures)
**Notification:** Logged in deploy log; visible in audit log if applicable

### 3.2 Normal Change

Non-routine but non-emergency changes affecting users.

**Examples:**
- New feature deploy
- Schema migration
- Connector or integration changes
- Major dependency upgrades
- Configuration changes affecting behavior (e.g., AI provider routing)

**Approval:** Tech lead + operator
**Notification:** 24h advance to admins via email/Slack
**Implementation window:** Off-peak hours preferred

### 3.3 Emergency / Hotfix Change

Urgent changes to address active production issues.

**Examples:**
- Security vulnerability patch
- Critical bug fix (data loss, total outage)
- Hot-rollback of a bad deploy
- Emergency config change (e.g., disable a broken connector)

**Approval:** Operator + 1 reviewer (concurrent if needed)
**Notification:** Post-fact, within 24h
**Implementation:** Immediate

### 3.4 Major Change

Changes with broad scope, multi-day impact, or significant risk.

**Examples:**
- Major version upgrade (v2 → v3)
- Database engine upgrade (PG 16 → 17)
- Migration to new infrastructure (new server, new cloud)
- Architectural overhaul (e.g., split into microservices)

**Approval:** Tech lead + product owner + customer notification
**Notification:** 14 days advance
**Implementation:** Detailed runbook required; external testing recommended

---

## 4. Change Request Process

### 4.1 Standard Changes

No formal request needed. Changes flow through PRs, merge to master, deploy to production via `deploy/update.sh`.

### 4.2 Normal Changes

1. **Open a GitHub issue** with label `change-request`
2. **Document**:
   - What is being changed
   - Why (business or technical reason)
   - Risk assessment
   - Rollback plan
   - Implementation date proposed
3. **Tech lead reviews** within 1 business day
4. **Approval = comment "Approved" with implementation date**
5. **Implementation** by operator or designated engineer
6. **Confirmation** comment after success

### 4.3 Emergency Changes

1. **Operator initiates** (informally — phone, Slack, etc.)
2. **Implements with at least one peer aware**
3. **After resolution**: open a retroactive issue documenting:
   - What changed
   - Why it was urgent
   - Outcome
   - Any follow-ups needed
4. **Post-mortem** within 5 business days for any P0 emergency

### 4.4 Major Changes

1. **Design doc** in `docs/designs/<date>-<short-name>.md`
2. **Stakeholder review** (tech lead, product, operator, optionally customer rep)
3. **Implementation plan** with phases, rollback strategy, test plan
4. **Phased rollout** (e.g., staging → 10% prod → 100% prod)
5. **Communication plan** to affected users
6. **Retrospective** post-implementation

---

## 5. Change Calendar

### 5.1 Maintenance Windows

Default: **Tuesday/Thursday 06:00–07:00 UTC** (low-traffic).

For longer maintenance: scheduled in advance, communicated to admins.

Avoid:
- Friday afternoons (weekend if something breaks)
- Major holidays
- Known customer business-critical periods

### 5.2 Frozen Periods

We avoid changes during:
- Year-end (Dec 20 – Jan 5)
- Italian fiscal close (Mar 30 – Apr 5)
- Customer-specific blackout periods (TBD per contract)

Exceptions: emergency changes only (with extra scrutiny).

---

## 6. Risk Assessment Framework

Before any normal or major change, assess:

### 6.1 Probability of Failure

| Level | Description |
|---|---|
| Very low | Tested in staging; reversible; well-understood path |
| Low | Standard pattern; minor unknowns |
| Medium | New territory; some unknowns; partially tested |
| High | Significant unknowns; complex dependencies |
| Very high | First-time change; deep system impact |

### 6.2 Impact if Failure Occurs

| Level | Description |
|---|---|
| Negligible | Cosmetic; user-invisible |
| Minor | Single feature degraded; workaround available |
| Moderate | Multiple features degraded; user impact |
| Major | Service degraded for multiple users |
| Severe | Total outage or data loss risk |

### 6.3 Risk Score = Probability × Impact

| Score | Action |
|---|---|
| Very low | Standard change |
| Low | Standard change with extra testing |
| Medium | Normal change with formal review |
| High | Major change with phased rollout |
| Very high | Defer or redesign to reduce risk |

---

## 7. Rollback Strategy

Every non-trivial change must have a documented rollback procedure.

### 7.1 Code Rollback

```bash
# Identify last good commit
git log --oneline -10

# Roll back
git checkout <good_sha>
systemctl --user restart workmind-api
```

### 7.2 Schema Rollback

If migration is reversible:
```bash
alembic downgrade -1
```

If irreversible (column drop, type change):
- Restore from backup taken just before
- Document why irreversible was acceptable

### 7.3 Config Rollback

```bash
cp ~/workmind-v2/.env ~/workmind-v2/.env.backup-$(date +%F)
# Make change
# If broken:
cp ~/workmind-v2/.env.backup-<date> ~/workmind-v2/.env
systemctl --user restart workmind-api
```

### 7.4 Cannot Roll Back?

Some changes are forward-only (e.g., dropped a column, encrypted previously plaintext data). For these:

- Document the irreversibility in the change request
- Take a fresh backup just before
- Have a documented "restore from backup" procedure
- Get explicit sign-off from tech lead

---

## 8. Communication

### 8.1 Internal

| Audience | Channel | When |
|---|---|---|
| Engineering | GitHub PR/issue | All changes |
| Operator | Direct (DM/email) | Pre-change for normal+ |
| Tech lead | GitHub mentions | Approval requests |
| All team | Slack #deploys | Production deploy notifications |

### 8.2 External (Customer Admins)

| Type | Channel | Lead time |
|---|---|---|
| Routine deploy | None (silent) | — |
| New feature | Email + in-app banner | Day-of |
| Breaking change | Email | 30 days |
| Maintenance window | Email | 24 hours |
| Emergency | Email | Post-fact, ASAP |

Email distribution list maintained in operator's contacts (for now manual; future: CRM-driven).

### 8.3 Templates

`docs/templates/`:
- `change-notification-customers.md`
- `maintenance-window-notice.md`
- `emergency-incident-notice.md`
- `feature-announcement.md`

(Templates to be created.)

---

## 9. Change Tracking

### 9.1 Records Maintained

| Record | Where |
|---|---|
| Change requests | GitHub Issues with `change-request` label |
| Implementation steps | GitHub PR + deploy log |
| Approvals | Comments on issue/PR |
| Rollback plans | In change request body |
| Outcomes | Closing comment on issue |
| Post-mortems | `docs/incidents/<date>.md` |

### 9.2 Auditability

For compliance audits:
- Filter GitHub Issues by `change-request` label, date range
- Each issue shows: who proposed, who approved, when implemented, outcome
- Linked to PRs (code), audit log (DB events), and incident reports (where applicable)

### 9.3 Annual Review

End of each year:
- Total changes by category
- Failure rate (changes that required rollback)
- Mean time to deploy
- Mean time to recover (for emergencies)
- Trends and process improvements

---

## 10. Roles in Change Management

### 10.1 Operator

- Initiates standard changes
- Performs implementation for all changes
- Owns the runbook
- First line of defense for incidents

### 10.2 Tech Lead

- Approves normal/major changes
- Reviews high-risk changes
- Owns architectural standards
- Mentors engineers on change risk

### 10.3 Engineer

- Proposes code changes via PR
- Provides risk assessment in change request
- Implements at the operator's request
- Documents rollback procedure

### 10.4 Product Owner

- Approves major changes affecting product
- Communicates to customers
- Prioritizes change backlog

### 10.5 Security Reviewer

- Reviews changes touching auth, crypto, data handling
- Approves or blocks security-sensitive changes
- Owns security incident response

(Currently, in solo-developer mode, one person fills all roles. As team grows, split.)

---

## 11. Out-of-Process Changes

Sometimes changes happen without going through this process (e.g., emergency fix, ad-hoc tweak). When discovered:

- **Document retroactively** within 48 hours
- **Don't punish** good-faith deviations during emergencies
- **Use the deviation as a learning opportunity** — should the process be relaxed in such cases?

The goal is **safety**, not bureaucracy.

---

## 12. Process Improvement

This document is reviewed annually (or after any significant incident traceable to process gaps).

Proposed improvements go through the same review process: PR, approval, version bump.

---

## Appendix A: Sample Change Request

```markdown
## Change Request: Migrate model_router to async httpx

**Category:** Normal change
**Risk:** Medium

### What

Replace synchronous `httpx.Client` + `run_in_executor()` with `httpx.AsyncClient` directly in `app/services/model_router.py`.

### Why

- Current implementation blocks event loop momentarily during HTTP calls
- Connection pooling not utilized
- Simplifies code (no executor wrapper)
- Improves observability (async timeouts work cleanly)

### Risk Assessment

- **Probability:** Medium — async httpx behaves differently in some edge cases
- **Impact:** Moderate — affects all AI calls; failure breaks chat for everyone
- **Mitigation:** Tested on staging for 48 hours under load

### Rollback Plan

Revert the commit; redeploy. Sync httpx code preserved in git history.

### Implementation Window

Tuesday 2026-05-07 06:00 UTC

### Sign-off

- [ ] Tech lead approval
- [ ] Operator confirmation
```

---

## Appendix B: Templates

(In `docs/templates/` — to be created)

- `change-request.md` — for opening a change request
- `rollback-procedure.md` — checklist for rolling back
- `incident-report.md` — for post-mortems

---

**End of Change Management Policy**

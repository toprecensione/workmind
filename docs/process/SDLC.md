# WorkMind v2 — Software Development Lifecycle (SDLC)

**Document Status:** Approved
**Version:** 1.0
**Last Updated:** 2026-04-26

---

## Table of Contents

1. [Overview](#1-overview)
2. [Roles & Responsibilities](#2-roles--responsibilities)
3. [Development Phases](#3-development-phases)
4. [Branching & Versioning](#4-branching--versioning)
5. [Code Review](#5-code-review)
6. [Testing Gates](#6-testing-gates)
7. [Release Process](#7-release-process)
8. [Change Management](#8-change-management)
9. [Hotfix Procedure](#9-hotfix-procedure)
10. [Compliance Considerations](#10-compliance-considerations)

---

## 1. Overview

This document describes the SDLC followed for WorkMind v2. The process is intentionally lightweight (suitable for a small team) but provides the rigor needed for B2B production software.

The lifecycle has these phases:

```
[Discovery] → [Planning] → [Implementation] → [Review] → [Testing] → [Staging] → [Production] → [Monitoring]
                                  ↑                                                   │
                                  └────────────[Iteration / Hotfix]────────────────────┘
```

---

## 2. Roles & Responsibilities

In a small team, individuals wear multiple hats. The roles below are functional, not necessarily distinct people.

| Role | Responsibilities |
|---|---|
| **Product Owner** | Defines requirements, prioritizes backlog, accepts deliverables |
| **Tech Lead** | Architectural decisions, code review, mentorship |
| **Engineer** | Implements features, writes tests, performs self-review |
| **DevOps / SRE** | Deploys, monitors, maintains infrastructure |
| **Security Reviewer** | Performs security review on auth/cryptographic/data handling changes |
| **QA / Tester** | Manual testing of staging before prod release |
| **Operator** | Runs the production system day-to-day; handles backups, restores, incidents |

---

## 3. Development Phases

### 3.1 Discovery

**Triggered by:** Customer request, internal idea, security finding, dependency update

**Output:** A short brief or issue describing:
- Problem statement
- Stakeholders / users affected
- Success criteria
- Constraints (regulatory, performance, compatibility)
- Rough scope estimate

**Tooling:** GitHub Issues with labels:
- `priority/p0` (critical), `priority/p1`, `priority/p2`, `priority/p3`
- `type/feature`, `type/bug`, `type/security`, `type/chore`, `type/docs`
- `area/backend`, `area/frontend`, `area/db`, `area/ops`, `area/clients-medic`

### 3.2 Planning

For non-trivial features (>1 day of work):

1. **Design doc** — short document (1-3 pages) covering:
   - Goal & non-goals
   - Architectural sketch
   - Data model changes
   - API changes
   - Open questions
2. **Tech lead review** — async via PR comments on the design doc
3. **Approval** — design doc lives in `docs/designs/<date>-<short-name>.md`

For small fixes (≤1 day): proceed directly to implementation. Low-stakes work doesn't need ceremony.

### 3.3 Implementation

**Branch off `master`** with a descriptive name:
```bash
git checkout master && git pull
git checkout -b feat/2fa-totp
```

Follow conventions:
- Small, atomic commits with Conventional Commits messages
- Tests added for new code paths
- Docs updated where relevant (API reference, README)
- Migrations included for schema changes

**Time-box:** A feature branch should be merged within 1 week. If longer, it's likely too big — split it.

### 3.4 Self-Review

Before opening a PR:

- [ ] Run `pytest tests/` locally
- [ ] Run `ruff check` locally
- [ ] Review your own diff (`git diff master..HEAD`)
- [ ] Verify no secrets committed
- [ ] Check migrations roll back cleanly (where reversible)
- [ ] Verify the change works end-to-end (manual smoke test)

### 3.5 Review

Open a PR. CI runs automatically. Once green, request review.

See §5 (Code Review) for guidelines.

### 3.6 Merge

After approval:
- **Squash and merge** for feature branches (single commit on master)
- Conventional Commits format in the squash commit message
- Branch deleted after merge

### 3.7 Staging Deploy

Auto-deployed to staging on every merge to master (planned; currently manual).

### 3.8 Production Deploy

Manual approval after staging validation. See §7 (Release Process).

### 3.9 Monitoring

Post-deploy, the operator watches:
- API error rate (Grafana)
- AI cost rate
- New audit log events
- User support channels

Issues found → tracked as new bugs in GitHub Issues.

---

## 4. Branching & Versioning

### 4.1 Branch Model

We use **trunk-based development** with short-lived branches:

```
master ────●────●────●─────●────●────●────►
            \   /\   \    /\   /
             feat-A   feat-B  feat-C
                       (merged)
```

- `master` is always deployable
- Feature branches are short (hours to days)
- No long-lived release branches
- No `develop` branch

### 4.2 Versioning

WorkMind follows **Semantic Versioning** (semver):

- `MAJOR.MINOR.PATCH`
- `MAJOR` = breaking API change (incompatible)
- `MINOR` = new feature, backward compatible
- `PATCH` = bug fix, backward compatible

**Current version:** 2.0.0 (released early 2026)

Each release is tagged in git:
```bash
git tag -a v2.1.0 -m "Release 2.1.0"
git push origin v2.1.0
```

A `CHANGELOG.md` is maintained at the repo root with sections per version.

### 4.3 API Versioning

API is mounted at `/api`. Treated as version 2.

If a breaking change is needed:
- New API mounted at `/api/v3`
- Old `/api` continues to work for at least 6 months
- Deprecation notices added to OpenAPI descriptions
- Client libraries migrate at their pace

---

## 5. Code Review

### 5.1 Goals

- **Catch bugs** before they ship
- **Spread knowledge** — reviewers learn the code; authors get feedback
- **Maintain consistency** — naming, patterns, idioms
- **Surface security/perf concerns** before merge

### 5.2 Reviewer Checklist

| Area | Check |
|---|---|
| **Correctness** | Does the code do what the description says? Edge cases? |
| **Security** | SQL injection? Auth check missing? Secrets in logs? |
| **Performance** | N+1 queries? Blocking calls in async? Big payloads? |
| **Maintainability** | Naming clear? Functions small? Comments where needed? |
| **Testing** | Are new code paths tested? Tests meaningful (not cargo-cult)? |
| **API design** | Consistent with existing endpoints? Pydantic schemas defined? |
| **Multi-tenancy** | Every query filters by `org_id`? |
| **Logging** | Useful events logged? PII not in logs? |
| **Breaking change?** | Migration path? Documented? |

### 5.3 Reviewer Etiquette

- **Be specific.** "This could be cleaner" → not actionable. "Extract this 30-line block into a helper named `compute_discount()`" → actionable.
- **Explain why.** Not just "wrong"; explain the reasoning.
- **Suggest, don't dictate.** "Consider..." invites discussion. "You must..." shuts it down.
- **Approve when good enough.** Perfect is the enemy of done.
- **Block firmly when needed.** P0 security issues are non-negotiable.

### 5.4 Author Etiquette

- **Don't take it personally.** Critique is of the code, not you.
- **Reply to every comment.** Even just "Done" or "Will address in follow-up #123".
- **Push back when warranted.** Reviewers are sometimes wrong; explain your reasoning.
- **Iterate.** Multiple review rounds are normal.

### 5.5 Approval Requirements

| Change Type | Required Reviewers |
|---|---|
| Documentation only | 1 reviewer |
| Bug fix (low risk) | 1 reviewer |
| New feature | 1 reviewer + tech lead |
| Schema migration | 1 reviewer + tech lead |
| Auth/security code | 2 reviewers (one being security reviewer) |
| Public API breaking change | Tech lead approval required |

For solo contributor (current state), self-merge after 24-hour cool-off period for non-trivial changes. (When team grows, formal reviewers required.)

---

## 6. Testing Gates

### 6.1 CI Pipeline

Triggered on every push and PR to master:

1. **Setup**: Python 3.13, install deps via pyproject.toml
2. **Lint**: `ruff check app/ clients/`
3. **Test**: `pytest tests/`
4. **Coverage report** (planned): `pytest --cov=app`

CI must pass before merge. No exceptions.

### 6.2 Test Levels

See `docs/development/TESTING.md` for full strategy. Briefly:

| Level | When Run | Coverage Target |
|---|---|---|
| Unit | Every commit | 80%+ on new code |
| Integration | Every commit | All major user flows |
| E2E (planned) | Pre-release | Top 10 user journeys |
| Performance smoke | Pre-release | p95 latency budgets |
| Security scan | Weekly + pre-release | All deps via pip-audit |
| Manual smoke | Before prod deploy | See checklist in TESTING.md |

### 6.3 Acceptance Criteria

A feature is "done" when:

- [ ] All automated tests pass
- [ ] Code review approved
- [ ] Documentation updated (API ref, user manual where relevant)
- [ ] Manually verified on staging
- [ ] No new lint warnings or type errors
- [ ] Migrations apply cleanly (forward) and roll back cleanly (backward)
- [ ] No regression in existing functionality

---

## 7. Release Process

### 7.1 Cadence

- **Continuous deployment** to staging on every master merge
- **Production deploys**: as needed, typically 1–2x per week
- **Major version bumps**: ~quarterly, planned in advance

### 7.2 Pre-Release Checklist

For non-trivial production deploys:

- [ ] All staging smoke tests pass (see TESTING.md §12)
- [ ] CHANGELOG.md updated
- [ ] Migrations reviewed (especially destructive ones)
- [ ] Backup taken just before deploy
- [ ] Maintenance window communicated if downtime expected
- [ ] Rollback plan documented

### 7.3 Deploy Steps

See `docs/operations/RUNBOOK.md` §3.1 for the production deploy procedure.

Quick version:

```bash
ssh bender 'cd ~/workmind-v2 && bash deploy/update.sh'
```

### 7.4 Post-Release

- [ ] `curl /health` returns ok
- [ ] Sample user flow works (login, send chat, etc.)
- [ ] No spike in error rate (Grafana watch for 30 min)
- [ ] No spike in audit log anomalies
- [ ] Tag the release in git (`git tag v2.X.Y && git push --tags`)
- [ ] Update CHANGELOG.md if not already

### 7.5 Rollback Triggers

Roll back if any of:
- Error rate > 5% for >5 minutes
- API health check fails consistently
- Critical user flow broken (login, chat)
- Security regression discovered

Rollback procedure: see RUNBOOK.md §4.1 and §9.

---

## 8. Change Management

### 8.1 Risk Categorization

| Category | Examples | Process |
|---|---|---|
| **Low risk** | Doc updates, frontend cosmetic, single-test fix | Standard PR review |
| **Medium risk** | New endpoint, new connector, new skill | PR + design doc + staging validation |
| **High risk** | Auth changes, schema migrations, dep upgrades | PR + design doc + tech lead approval + staging soak |
| **Critical risk** | Cryptographic changes, multi-tenant boundary changes | PR + security review + 2 reviewers + canary deploy |

### 8.2 Schema Migration Risk

Migrations are particularly dangerous. Categories:

- **Safe**: Add nullable column, add index, add new table
- **Risky**: Change column type, add NOT NULL with default
- **Dangerous**: Drop column, rename column, foreign key changes

For risky/dangerous migrations:
1. Test on a copy of production data
2. Verify rollback works (or document why it doesn't)
3. Run during low-traffic window
4. Have backup just before

### 8.3 Dependency Updates

Quarterly process:
1. Run `pip list --outdated`
2. Review release notes for breaking changes
3. Update minor/patch versions in pyproject.toml
4. Run full test suite
5. Major version updates: separate PRs each, with thorough testing

For security updates: as soon as advisory is published, prioritize.

### 8.4 Configuration Changes

Production `.env` changes require:
- Documented in commit-equivalent (in private repo or operator log)
- Service restart immediately
- Verification that change took effect

---

## 9. Hotfix Procedure

For critical issues in production (data loss, security breach, total outage):

### 9.1 Classification

- **P0**: Immediate response (within 1 hour)
- **P1**: Same-day response (within 8 hours)

### 9.2 Hotfix Branch

```bash
git checkout master && git pull
git checkout -b hotfix/<short-name>
# ... fix ...
```

### 9.3 Streamlined Review

For P0:
- 1 reviewer minimum (waive normal 2-reviewer if waiting blocks resolution)
- Skip non-critical CI steps if needed (but always run tests)
- Hotfix PR explicit in title: "HOTFIX: ..."

### 9.4 Deploy

Direct to production (skip staging) if:
- The bug is in staging-incompatible code
- Time pressure is extreme (security incident)

Otherwise: staging → production within hours.

### 9.5 Post-Hotfix

- [ ] Post-mortem within 5 business days (`docs/incidents/<date>.md`)
- [ ] Add regression test for the bug
- [ ] Document root cause + fix in CHANGELOG
- [ ] Identify any process improvements

---

## 10. Compliance Considerations

### 10.1 Documentation Requirements

For SOC 2 / ISO 27001 readiness, we maintain:

- **This SDLC document** (process)
- **Code review records** (PR history in GitHub)
- **Testing evidence** (CI run logs)
- **Deployment logs** (`deploy/<date>.log` planned)
- **Backup logs** (`backup_logs` table)
- **Audit logs** (`audit_logs` table)
- **Incident reports** (`docs/incidents/`)
- **Change requests** (GitHub issues + PRs)

### 10.2 Separation of Duties

Currently single-operator (challenge for compliance). Mitigations:

- Manual approval gates for production deploys (planned: Slack/email)
- All deploys logged
- Automated tests + lint as objective gates
- Periodic external audit (planned)

### 10.3 Vendor Management

Sub-processors (AI providers, cloud) are documented in `docs/security/PRIVACY_GDPR.md`. Quarterly review:
- Are DPAs still in place?
- Have providers updated their terms?
- Any new sub-sub-processors?

### 10.4 Training

For team growth:
- New engineers complete the Developer Guide before first PR
- Security training annual (AWS Security Fundamentals or similar)
- GDPR refresher annual

---

## 11. Continuous Improvement

This SDLC is itself subject to iteration. Quarterly retrospective:

- What's working?
- What's slowing us down?
- Are processes proportional to risk?
- New tools to evaluate?

Updates to this document tracked in version history below.

---

## 12. Version History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-04-26 | Engineering | Initial document |

---

**End of SDLC**

# WorkMind

> ⚠️ **CONFIDENTIAL — PRIVATE REPOSITORY**
> This project and all its contents are proprietary and confidential.
> Do not distribute, fork, clone to public repositories, or share externally.

---

WorkMind is a distributed AI-powered operational assistant that runs as worker nodes on Ubuntu servers. It monitors directories, learns usage patterns over time, detects anomalies, and generates structured reports. All code is generated and updated from a Windows development machine using Claude Code and distributed automatically via a private GitHub repository.

---

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│         Windows Dev Machine                 │
│         Claude Code (code generation)       │
└───────────────────┬─────────────────────────┘
                    │ git push
                    ▼
         ┌──────────────────────┐
         │  GitHub (PRIVATE)    │
         │  workmind repository │
         └──────┬───────────────┘
                │ git pull (hourly auto-update)
       ┌────────┴────────┐
       ▼                 ▼
┌─────────────┐   ┌─────────────┐   ...
│  Ubuntu     │   │  Ubuntu     │
│  Node 001   │   │  Node 002   │
│             │   │             │
│ AgentMgr    │   │ AgentMgr    │
│  MindWork   │   │  MindWork   │
│  AutoUpdate │   │  AutoUpdate │
│  Logger     │   │  Logger     │
└─────────────┘   └─────────────┘
```

### Component Responsibilities

| Component | Role |
|---|---|
| **AgentManager** | Spawns/kills processes, enforces filesystem permissions, monitors CPU/memory, restarts on failure |
| **PermissionGuard** | Allow-list enforcement — MindWork has zero direct OS access |
| **ResourceMonitor** | Polls `psutil`, kills processes exceeding CPU/memory/fd limits |
| **MindWork Core** | `DirectoryScanner → PatternAnalyser → ReportEngine` cycle |
| **PatternAnalyser** | Statistical anomaly detection (z-score over historical series) |
| **ReportEngine** | Generates JSON + Markdown reports |
| **AutoUpdater** | `git fetch → validate → backup → pull → rollback on failure` |
| **StructuredLogger** | JSON log lines with fixed schema on every action |

---

## Production Cycle

```
1. Developer writes / updates Python code on Windows (Claude Code)
2. git push → private GitHub repository
3. Ubuntu nodes: hourly cron checks for new commits
4. AutoUpdater: validates syntax + structure in temp clone
5. Creates rolling backup of current code
6. git pull --ff-only applies the update
7. systemd restarts WorkMind with new code
8. On any failure: automatic git reset --hard rollback
```

---

## Ubuntu Node Setup

### Prerequisites
- Ubuntu 22.04 LTS
- Root access
- GitHub Personal Access Token (scope: `Contents: read`)

### Installation

```bash
# Set required environment variables
export WORKMIND_REPO_URL="https://github.com/YOUR_ORG/workmind.git"
export WORKMIND_NODE_ID="node-001"
export WORKMIND_NODE_LABEL="Production Worker 1"
export GITHUB_TOKEN="ghp_XXXXXXXXXXXXXXXX"
export WORKMIND_ENV="production"

# Run the installer
chmod +x scripts/setup_ubuntu.sh
sudo -E bash scripts/setup_ubuntu.sh
```

The script installs:
- Python virtual environment with all dependencies
- `workmind` system user (non-login, minimal privileges)
- `systemd` service with security hardening
- Hourly cron job for automatic updates
- `logrotate` configuration

### Post-install Commands

```bash
# Check status
systemctl status workmind

# Follow live logs
journalctl -u workmind -f

# Run diagnostics
sudo bash /opt/workmind/scripts/health_check.sh

# Manual rollback
sudo bash /opt/workmind/scripts/rollback.sh
```

---

## Docker Deployment (Alternative)

```bash
# Copy and configure environment
cp .env.example .env
nano .env  # fill in real values

# Build and start 2 nodes locally
docker compose up --build -d

# View logs
docker compose logs -f workmind-node-1
```

---

## Log Schema

Every log line is a JSON object with this fixed schema:

```json
{
  "timestamp":  "2026-04-03T10:00:00.123Z",
  "node_id":    "node-001",
  "level":      "INFO",
  "module":     "mindwork.scanner",
  "action":     "scan",
  "status":     "ok",
  "message":    "Scan complete: 1234 files in 2.1s",
  "suggestion": "Consider archiving logs older than 30 days.",
  "extra":      { "files": 1234, "elapsed_s": 2.1 }
}
```

Logs are written to `logs/workmind.log` (JSON, rotating) and to `journald`.

---

## Update & Rollback Strategy

| Step | Action |
|---|---|
| 1 | `git fetch origin main` |
| 2 | Compare local SHA with remote SHA |
| 3 | Clone remote to temp dir, run `UpdateValidator` |
| 4 | Validate: Python syntax, required dirs, `version.py` |
| 5 | Create timestamped backup (max 5 rolling) |
| 6 | `git pull --ff-only` |
| 7 | Write `version.json` with new SHA |
| 8 | **On failure**: `git reset --hard <previous_sha>` |

Manual rollback: `sudo bash /opt/workmind/scripts/rollback.sh`

---

## Security Considerations

### Filesystem Isolation
- MindWork has **zero direct filesystem access**
- All paths must pass through `PermissionGuard.check_path()`
- Allow-list based: only declared directories are accessible
- Hardcoded deny list: `/etc`, `/root`, `/sys`, `/proc`, `/boot`, `/bin`, `/sbin`

### Process Isolation
- Runs as `workmind` system user (non-login shell, no sudo)
- `systemd` hardening: `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `CapabilityBoundingSet=`
- Docker: runs as UID 1001 (non-root)

### Secrets Management
- `.env` file: `chmod 600`, owned by `workmind` user
- GitHub token: minimum scope (`Contents: read` only)
- `.env` is in `.gitignore` — never committed

### Audit Trail
- Every permission check, process event, file access, and update step produces a JSON log record
- Logs are immutable (append-only rotation via `logrotate`)

---

## Directory Structure

```
workmind/
├── main.py                    # Entry point
├── version.py                 # Semantic versioning
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example               # Template — never commit .env
├── .gitignore
│
├── config/
│   └── settings.py            # Typed dataclass configuration
│
├── agent_manager/
│   └── manager.py             # Orchestrator, PermissionGuard, ResourceMonitor
│
├── mindwork/
│   ├── __init__.py            # MindWork orchestrator
│   ├── scanner.py             # Directory walker
│   ├── analyser.py            # Pattern analysis + anomaly detection
│   └── reporter.py            # JSON + Markdown report generation
│
├── logging_system/
│   └── logger.py              # Structured JSON logger
│
├── updater/
│   └── auto_updater.py        # Git pull, validate, backup, rollback
│
├── scripts/
│   ├── setup_ubuntu.sh        # One-command node installer
│   ├── rollback.sh            # Manual rollback utility
│   └── health_check.sh        # Node diagnostics
│
├── tests/
│   ├── test_agent_manager.py
│   ├── test_logger.py
│   └── test_updater.py
│
├── .github/
│   └── workflows/
│       └── ci.yml             # CI: syntax check + tests + security scan
│
├── logs/          (runtime, gitignored)
├── data/          (runtime, gitignored)
├── reports/       (runtime, gitignored)
└── backups/       (runtime, gitignored)
```

---

## Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=term-missing
```

---

## Configuration Reference

All settings are driven by environment variables (see `.env.example`).

| Variable | Required | Description |
|---|---|---|
| `WORKMIND_NODE_ID` | ✅ | Unique node identifier |
| `WORKMIND_NODE_LABEL` | | Human-readable label |
| `WORKMIND_REPO_URL` | ✅ | Private GitHub HTTPS URL |
| `WORKMIND_BRANCH` | | Branch to track (default: `main`) |
| `GITHUB_TOKEN` | ✅ | PAT with `Contents: read` |
| `WORKMIND_ENV` | | `production` / `staging` |
| `LOG_LEVEL` | | `INFO` (default) |

---

## Version History

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-04-03 | Initial release — all phases |

---

*WorkMind — Internal Operational Intelligence System*
*CONFIDENTIAL — Not for public distribution*

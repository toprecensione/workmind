#!/usr/bin/env bash
# =============================================================================
# WorkMind — GitHub Repository Initialization Script
# Run this ONCE from your Windows machine (Git Bash / WSL / PowerShell)
# CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
# =============================================================================
#
# Before running:
#   1. Create a NEW PRIVATE repository on GitHub (no README, no .gitignore)
#      → https://github.com/new
#   2. Copy the HTTPS clone URL
#   3. Set GITHUB_REPO_URL below or export it as an env var
#
# Usage:
#   bash scripts/init_github.sh
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

GITHUB_REPO_URL="${GITHUB_REPO_URL:-}"

if [[ -z "${GITHUB_REPO_URL}" ]]; then
    echo -e "${CYAN}Enter the HTTPS URL of your PRIVATE GitHub repository:${NC}"
    read -rp "  URL: " GITHUB_REPO_URL
fi

[[ "${GITHUB_REPO_URL}" == https://github.com/* ]] \
    || error "URL must start with https://github.com/"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

cd "${PROJECT_DIR}"
info "Working directory: ${PROJECT_DIR}"

# ─── Git init ─────────────────────────────────────────────────────────────────
if [[ ! -d ".git" ]]; then
    info "Initializing Git repository…"
    git init
    git branch -M main
else
    info "Git repository already initialized."
fi

# ─── Configure remote ─────────────────────────────────────────────────────────
if git remote get-url origin &>/dev/null; then
    warn "Remote 'origin' already set — updating to: ${GITHUB_REPO_URL}"
    git remote set-url origin "${GITHUB_REPO_URL}"
else
    git remote add origin "${GITHUB_REPO_URL}"
    info "Remote 'origin' added."
fi

# ─── Initial commit ───────────────────────────────────────────────────────────
info "Staging all files…"
git add .

if git diff --cached --quiet; then
    warn "Nothing to commit — repository may already be initialized."
else
    git commit -m "feat: initial WorkMind system — all phases

- AgentManager: process orchestration, PermissionGuard, ResourceMonitor
- MindWork: DirectoryScanner, PatternAnalyser, ReportEngine
- AutoUpdater: git pull, validate, backup, rollback
- Structured JSON logging system
- Ubuntu node setup script (systemd + cron + logrotate)
- Docker + Docker Compose support
- Full test suite
- GitHub Actions CI workflow

CONFIDENTIAL — Private repository"
    info "Initial commit created."
fi

# ─── Push ─────────────────────────────────────────────────────────────────────
echo ""
warn "About to push to: ${GITHUB_REPO_URL}"
warn "Ensure this is a PRIVATE repository before proceeding."
read -rp "Confirm push? (yes/no): " CONFIRM
[[ "${CONFIRM}" == "yes" ]] || { info "Push cancelled."; exit 0; }

info "Pushing to origin/main…"
git push -u origin main

echo ""
info "✅ Repository initialized and pushed successfully."
info "   URL: ${GITHUB_REPO_URL}"
info ""
info "Next steps:"
info "  1. On each Ubuntu node, run: sudo -E bash scripts/setup_ubuntu.sh"
info "  2. Set WORKMIND_REPO_URL, WORKMIND_NODE_ID, GITHUB_TOKEN in environment"
info "  3. Monitor: journalctl -u workmind -f"

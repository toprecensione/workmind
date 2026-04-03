#!/usr/bin/env bash
# =============================================================================
# WorkMind — Health Check & Diagnostics
# CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
# =============================================================================
# Usage:  ./scripts/health_check.sh
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; FAILED=$((FAILED+1)); }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }
FAILED=0

INSTALL_DIR="${INSTALL_DIR:-/opt/workmind}"
ENV_FILE="${INSTALL_DIR}/.env"
VENV="${INSTALL_DIR}/.venv/bin/python"
LOG_FILE="${INSTALL_DIR}/logs/workmind.log"

echo -e "\n${BOLD}${CYAN}═══ WorkMind Health Check ═══${NC}\n"

# ─── systemd service ──────────────────────────────────────────────────────────
echo -e "${BOLD}Service Status${NC}"
if systemctl is-active --quiet workmind.service 2>/dev/null; then
    ok "workmind.service is active"
else
    fail "workmind.service is NOT active"
fi

if systemctl is-enabled --quiet workmind.service 2>/dev/null; then
    ok "workmind.service is enabled (auto-start)"
else
    warn "workmind.service is not enabled"
fi

# ─── Python & venv ───────────────────────────────────────────────────────────
echo -e "\n${BOLD}Python Environment${NC}"
if [[ -x "${VENV}" ]]; then
    PY_VER=$("${VENV}" --version 2>&1)
    ok "Virtual env present: ${PY_VER}"
else
    fail "Virtual environment not found at ${VENV}"
fi

# ─── Key files ────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}File System${NC}"
for f in main.py version.py requirements.txt config/settings.py agent_manager/manager.py; do
    if [[ -f "${INSTALL_DIR}/${f}" ]]; then
        ok "${f}"
    else
        fail "${f} MISSING"
    fi
done

[[ -f "${ENV_FILE}" ]] && ok ".env present" || fail ".env MISSING"

# ─── Directories ─────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Runtime Directories${NC}"
for d in logs data reports backups; do
    if [[ -d "${INSTALL_DIR}/${d}" ]]; then
        SIZE=$(du -sh "${INSTALL_DIR}/${d}" 2>/dev/null | cut -f1)
        ok "${d}/  (${SIZE})"
    else
        fail "${d}/ MISSING"
    fi
done

# ─── Disk space ───────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Disk & Memory${NC}"
DISK_FREE=$(df -h "${INSTALL_DIR}" | awk 'NR==2{print $4}')
DISK_PCT=$(df "${INSTALL_DIR}" | awk 'NR==2{print $5}' | tr -d '%')
if (( DISK_PCT < 80 )); then
    ok "Disk usage: ${DISK_PCT}%  (free: ${DISK_FREE})"
elif (( DISK_PCT < 90 )); then
    warn "Disk usage: ${DISK_PCT}%  (free: ${DISK_FREE}) — getting full"
else
    fail "Disk usage: ${DISK_PCT}%  (free: ${DISK_FREE}) — CRITICAL"
fi

MEM_FREE=$(free -m | awk '/^Mem/{print $7}')
if (( MEM_FREE > 256 )); then
    ok "Available RAM: ${MEM_FREE} MB"
else
    warn "Available RAM: ${MEM_FREE} MB — low"
fi

# ─── Recent log activity ─────────────────────────────────────────────────────
echo -e "\n${BOLD}Recent Logs (last 5 lines)${NC}"
if [[ -f "${LOG_FILE}" ]]; then
    tail -5 "${LOG_FILE}" | while IFS= read -r line; do
        # Pretty print key JSON fields
        TS=$(echo "${line}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('timestamp','?')[:19])" 2>/dev/null || echo "?")
        LVL=$(echo "${line}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('level','?'))" 2>/dev/null || echo "?")
        MSG=$(echo "${line}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('message','?')[:80])" 2>/dev/null || echo "${line:0:80}")
        echo "    ${TS}  [${LVL}]  ${MSG}"
    done
else
    warn "No log file found yet at ${LOG_FILE}"
fi

# ─── Backup inventory ────────────────────────────────────────────────────────
echo -e "\n${BOLD}Backup Inventory${NC}"
BACKUP_COUNT=$(ls -1 "${INSTALL_DIR}/backups/" 2>/dev/null | wc -l)
if (( BACKUP_COUNT > 0 )); then
    ok "${BACKUP_COUNT} backup(s) available"
    ls -1t "${INSTALL_DIR}/backups/" | head -3 | while read -r b; do
        echo "    → ${b}"
    done
else
    warn "No backups found"
fi

# ─── Version ─────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Version Info${NC}"
if [[ -f "${INSTALL_DIR}/version.json" ]]; then
    cat "${INSTALL_DIR}/version.json" | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(f\"  Version : {d.get('version','?')}\n  SHA     : {d.get('git_sha','?')[:12]}\n  Deployed: {d.get('deployed_at','?')[:19]}\")" 2>/dev/null \
        || warn "Could not parse version.json"
else
    warn "version.json not found"
fi

GIT_SHA=$(git -C "${INSTALL_DIR}" rev-parse --short HEAD 2>/dev/null || echo "unknown")
ok "Git HEAD: ${GIT_SHA}"

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
if (( FAILED == 0 )); then
    echo -e "${GREEN}${BOLD}All checks passed. WorkMind is healthy.${NC}\n"
    exit 0
else
    echo -e "${RED}${BOLD}${FAILED} check(s) failed. Review the output above.${NC}\n"
    exit 1
fi

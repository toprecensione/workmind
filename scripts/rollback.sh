#!/usr/bin/env bash
# =============================================================================
# WorkMind — Manual Rollback Script
# CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
# =============================================================================
# Usage:
#   ./scripts/rollback.sh                  → rolls back to latest backup
#   ./scripts/rollback.sh backup_20260403  → rolls back to specific backup
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

INSTALL_DIR="${INSTALL_DIR:-/opt/workmind}"
BACKUP_DIR="${INSTALL_DIR}/backups"
TARGET_BACKUP="${1:-}"

[[ -d "${BACKUP_DIR}" ]] || error "Backup directory not found: ${BACKUP_DIR}"

# ─── List available backups ───────────────────────────────────────────────────
echo -e "\n${CYAN}Available backups:${NC}"
mapfile -t BACKUPS < <(ls -1t "${BACKUP_DIR}" 2>/dev/null || true)

if [[ ${#BACKUPS[@]} -eq 0 ]]; then
    error "No backups found in ${BACKUP_DIR}"
fi

for i in "${!BACKUPS[@]}"; do
    echo "  [$i] ${BACKUPS[$i]}"
done

# ─── Select backup ────────────────────────────────────────────────────────────
if [[ -n "${TARGET_BACKUP}" ]]; then
    SELECTED="${TARGET_BACKUP}"
else
    SELECTED="${BACKUPS[0]}"
    warn "No backup specified — using latest: ${SELECTED}"
fi

BACKUP_PATH="${BACKUP_DIR}/${SELECTED}"
[[ -d "${BACKUP_PATH}" ]] || error "Backup not found: ${BACKUP_PATH}"

# ─── Confirm ──────────────────────────────────────────────────────────────────
echo ""
warn "This will STOP WorkMind and restore from: ${SELECTED}"
read -rp "Are you sure? (yes/no): " CONFIRM
[[ "${CONFIRM}" == "yes" ]] || { info "Rollback cancelled."; exit 0; }

# ─── Stop service ────────────────────────────────────────────────────────────
info "Stopping WorkMind service…"
systemctl stop workmind.service 2>/dev/null || true

# ─── Restore files ────────────────────────────────────────────────────────────
info "Restoring from backup…"
PRESERVE_DIRS=("logs" "data" "reports" "backups" ".env")

# Copy backup contents, skip runtime dirs
rsync -a --delete \
    $(for d in "${PRESERVE_DIRS[@]}"; do echo "--exclude=${d}"; done) \
    "${BACKUP_PATH}/" \
    "${INSTALL_DIR}/" \
    2>/dev/null || {
    # Fallback without rsync
    for item in "${BACKUP_PATH}"/*; do
        base=$(basename "${item}")
        skip=false
        for excl in "${PRESERVE_DIRS[@]}"; do
            [[ "${base}" == "${excl}" ]] && skip=true && break
        done
        $skip || cp -r "${item}" "${INSTALL_DIR}/"
    done
}

chown -R workmind:workmind "${INSTALL_DIR}" 2>/dev/null || true

# ─── Restart ──────────────────────────────────────────────────────────────────
info "Restarting WorkMind service…"
systemctl start workmind.service

sleep 3
if systemctl is-active --quiet workmind.service; then
    info "✅ Rollback successful. WorkMind is running."
    info "   Restored from: ${SELECTED}"
else
    error "WorkMind failed to start after rollback. Check: journalctl -u workmind -n 50"
fi

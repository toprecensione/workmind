"""
WorkMind Backup Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Backup automatico periodico di knowledge base, audit trail, settings, chromadb.
"""

from __future__ import annotations

import shutil
import tarfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR, BACKUP_DIR, BASE_DIR
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("storage.backup")

_BACKUP_SOURCES = [
    DATA_DIR / "knowledge_base.json",
    DATA_DIR / "audit_trail.jsonl",
    DATA_DIR / "ui_settings.json",
    DATA_DIR / "budget_usage.json",
    DATA_DIR / "chromadb",
    BASE_DIR / "config" / "company.yaml",
]


class BackupManager:
    def __init__(self, keep: int = 30, interval_hours: int = 24) -> None:
        self._keep = keep
        self._interval = interval_hours * 3600
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def create_backup(self) -> str:
        """Crea un backup tar.gz. Ritorna il percorso del file."""
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = BACKUP_DIR / f"backup_{ts}.tar.gz"

        with tarfile.open(str(archive_path), "w:gz") as tar:
            for src in _BACKUP_SOURCES:
                if src.exists():
                    arcname = src.name if src.is_file() else src.name
                    tar.add(str(src), arcname=arcname)

        size_mb = archive_path.stat().st_size / (1024 * 1024)
        log.info(
            f"Backup creato: {archive_path.name} ({size_mb:.2f} MB)",
            action=LogAction.CONFIG, status=LogStatus.OK,
        )
        self.cleanup_old()
        return str(archive_path)

    def list_backups(self) -> list[dict]:
        """Lista tutti i backup esistenti."""
        if not BACKUP_DIR.exists():
            return []
        backups = []
        for f in sorted(BACKUP_DIR.glob("backup_*.tar.gz"), reverse=True):
            stat = f.stat()
            backups.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return backups

    def restore_backup(self, backup_name: str) -> bool:
        """Ripristina da un backup specifico."""
        archive = BACKUP_DIR / backup_name
        if not archive.exists():
            log.error(f"Backup non trovato: {backup_name}", action=LogAction.CONFIG)
            return False

        try:
            with tarfile.open(str(archive), "r:gz") as tar:
                # Safety: only extract known file names
                safe_members = []
                for m in tar.getmembers():
                    if ".." in m.name or m.name.startswith("/"):
                        continue
                    safe_members.append(m)
                tar.extractall(path=str(DATA_DIR), members=safe_members)

            log.info(f"Backup ripristinato: {backup_name}", action=LogAction.CONFIG, status=LogStatus.OK)
            return True
        except Exception as exc:
            log.error(f"Errore ripristino backup: {exc}", action=LogAction.CONFIG)
            return False

    def cleanup_old(self, keep: int | None = None) -> int:
        """Rimuove backup vecchi, mantiene gli ultimi N. Ritorna il numero rimosso."""
        keep = keep or self._keep
        files = sorted(BACKUP_DIR.glob("backup_*.tar.gz"), reverse=True)
        removed = 0
        for f in files[keep:]:
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
        return removed

    def start(self, interval_hours: int | None = None) -> None:
        """Avvia backup periodico in background."""
        if interval_hours:
            self._interval = interval_hours * 3600
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BackupManager")
        self._thread.start()
        log.info(
            f"Backup scheduler avviato (ogni {self._interval // 3600}h)",
            action=LogAction.STARTUP, status=LogStatus.OK,
        )

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        # Prima attesa: calcola tempo fino alle 03:00
        while self._running:
            try:
                self.create_backup()
            except Exception as exc:
                log.error(f"Errore backup periodico: {exc}", action=LogAction.CONFIG)
            # Attendi intervallo
            for _ in range(int(self._interval)):
                if not self._running:
                    return
                time.sleep(1)


# ─── Singleton ────────────────────────────────────────────────────────────────

_mgr: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    global _mgr
    if _mgr is None:
        _mgr = BackupManager()
    return _mgr

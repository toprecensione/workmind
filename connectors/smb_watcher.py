"""
WorkMind SMB File Watcher
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Monitora cartelle condivise SMB (mount points Linux) per nuovi file
o modifiche. Quando rileva un cambiamento, accoda il file per il parsing.

Usa inotify su Linux (watchdog come fallback) per notifiche in tempo reale.
In alternativa, polling periodico per compatibilità.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from config.company import CompanyConfig, get_company_config
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("connectors.smb_watcher")


@dataclass
class FileEvent:
    path: str
    event_type: str    # created | modified | deleted
    timestamp: float
    extension: str = ""
    size: int = 0


class SmbWatcher:
    """
    Monitora mount points SMB per nuovi/modificati file.
    I file rilevanti vengono segnalati al callback on_file_changed.
    """

    def __init__(
        self,
        company_cfg: Optional[CompanyConfig] = None,
        on_file_changed: Optional[Callable[[FileEvent], None]] = None,
    ) -> None:
        self._cfg = (company_cfg or get_company_config()).smb
        self._callback = on_file_changed
        self._running = False
        self._threads: list[threading.Thread] = []
        self._known_files: dict[str, float] = {}  # path → mtime

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled and bool(self._cfg.shares)

    @property
    def watch_dirs(self) -> list[str]:
        return [s.get("mount_point", "") for s in self._cfg.shares if s.get("mount_point")]

    @property
    def monitored_extensions(self) -> set[str]:
        return set(self._cfg.extensions_monitor)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled:
            log.info("SMB watcher disabilitato", action=LogAction.CONFIG)
            return

        self._running = True

        # Tenta watchdog per eventi real-time, fallback su polling
        if self._try_watchdog():
            return

        # Fallback: polling ogni 30 secondi
        log.info(
            "watchdog non disponibile, uso polling (30s)",
            action=LogAction.STARTUP, status=LogStatus.WARNING,
            suggestion="Installa watchdog: pip install watchdog",
        )
        for mount_dir in self.watch_dirs:
            t = threading.Thread(
                target=self._poll_loop,
                args=(mount_dir,),
                daemon=True,
                name=f"SMBPoll-{Path(mount_dir).name}",
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._running = False
        log.info("SMB watcher fermato", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)

    # ── Watchdog (inotify) ────────────────────────────────────────────────────

    def _try_watchdog(self) -> bool:
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

            watcher = self

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory:
                        watcher._handle_event(event.src_path, "created")

                def on_modified(self, event):
                    if not event.is_directory:
                        watcher._handle_event(event.src_path, "modified")

            observer = Observer()
            for mount_dir in self.watch_dirs:
                if Path(mount_dir).exists():
                    observer.schedule(
                        _Handler(),
                        mount_dir,
                        recursive=self._cfg.recursive_watch,
                    )
                    log.info(
                        f"Watchdog attivo su {mount_dir}",
                        action=LogAction.STARTUP, status=LogStatus.OK,
                    )
                else:
                    log.warning(
                        f"Mount point non trovato: {mount_dir}",
                        action=LogAction.STARTUP, status=LogStatus.WARNING,
                        suggestion=f"Monta la share SMB: sudo mount -t cifs //server/share {mount_dir}",
                    )

            observer.start()
            return True
        except ImportError:
            return False

    # ── Polling fallback ──────────────────────────────────────────────────────

    def _poll_loop(self, directory: str, interval: int = 30) -> None:
        root = Path(directory)
        if not root.exists():
            log.warning(f"Directory non trovata per polling: {directory}", action=LogAction.SCAN)
            return

        # Build initial snapshot
        self._known_files.update(self._scan_directory(root))
        log.info(
            f"Polling avviato su {directory} ({len(self._known_files)} file noti)",
            action=LogAction.STARTUP, status=LogStatus.OK,
        )

        while self._running:
            time.sleep(interval)
            try:
                current = self._scan_directory(root)
                # Nuovi file
                for path, mtime in current.items():
                    if path not in self._known_files:
                        self._handle_event(path, "created")
                    elif mtime > self._known_files[path]:
                        self._handle_event(path, "modified")
                # File eliminati
                for path in set(self._known_files) - set(current):
                    self._handle_event(path, "deleted")
                self._known_files = current
            except Exception as exc:
                log.error(f"Errore polling {directory}: {exc}", action=LogAction.SCAN)

    def _scan_directory(self, root: Path) -> dict[str, float]:
        """Scansione completa di directory con filtro estensioni."""
        files = {}
        exts = self.monitored_extensions
        try:
            for dirpath, _, filenames in os.walk(root):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in exts:
                        try:
                            files[fpath] = os.path.getmtime(fpath)
                        except OSError:
                            pass
        except Exception:
            pass
        return files

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle_event(self, filepath: str, event_type: str) -> None:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self.monitored_extensions:
            return

        size = 0
        try:
            size = os.path.getsize(filepath)
        except OSError:
            pass

        event = FileEvent(
            path=filepath,
            event_type=event_type,
            timestamp=time.time(),
            extension=ext,
            size=size,
        )

        log.info(
            f"File {event_type}: {filepath}",
            action=LogAction.SCAN, status=LogStatus.OK,
            extra={"extension": ext, "size": size},
        )

        if self._callback:
            try:
                self._callback(event)
            except Exception as exc:
                log.error(f"Errore callback file event: {exc}", action=LogAction.SCAN)

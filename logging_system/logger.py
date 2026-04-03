"""
WorkMind Structured JSON Logging System
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

All log records are emitted as JSON with a fixed schema:
  timestamp | node_id | module | action | status | message | suggestion | extra
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import traceback
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from config.settings import config


# ─── Status / Action Enums ────────────────────────────────────────────────────

class LogStatus(str, Enum):
    OK      = "ok"
    WARNING = "warning"
    ERROR   = "error"
    STARTED = "started"
    STOPPED = "stopped"
    SKIPPED = "skipped"
    PENDING = "pending"


class LogAction(str, Enum):
    SCAN        = "scan"
    ANALYSE     = "analyse"
    REPORT      = "report"
    UPDATE      = "update"
    ROLLBACK    = "rollback"
    VALIDATE    = "validate"
    SPAWN       = "spawn"
    KILL        = "kill"
    MONITOR     = "monitor"
    AUTH        = "auth"
    PERMISSION  = "permission"
    HEARTBEAT   = "heartbeat"
    CONFIG      = "config"
    STARTUP     = "startup"
    SHUTDOWN    = "shutdown"


# ─── JSON Formatter ───────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Converts LogRecord → JSON line with WorkMind schema."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id":   config.node.node_id,
            "level":     record.levelname,
            "module":    getattr(record, "wm_module",  record.name),
            "action":    getattr(record, "wm_action",  "generic"),
            "status":    getattr(record, "wm_status",  "ok"),
            "message":   record.getMessage(),
            "suggestion": getattr(record, "wm_suggestion", None),
        }
        # Attach any extra k/v passed via the adapter
        extra = getattr(record, "wm_extra", None)
        if extra:
            payload["extra"] = extra
        # Attach exception info if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


# ─── Logging Adapter ──────────────────────────────────────────────────────────

class WorkMindLogger:
    """
    Thin adapter around stdlib Logger that enforces WorkMind log schema.

    Usage:
        log = get_logger("mindwork.scanner")
        log.info("Scan complete", action=LogAction.SCAN, status=LogStatus.OK,
                 suggestion="Consider archiving logs older than 30 days.",
                 extra={"files_scanned": 1234})
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(
        self,
        level: int,
        message: str,
        *,
        action: str  = LogAction.MONITOR,
        status: str  = LogStatus.OK,
        suggestion: Optional[str] = None,
        extra: Optional[dict] = None,
        exc_info: bool = False,
    ) -> None:
        self._log.log(
            level,
            message,
            exc_info=exc_info,
            extra={
                "wm_module":     self._log.name,
                "wm_action":     str(action),
                "wm_status":     str(status),
                "wm_suggestion": suggestion,
                "wm_extra":      extra,
            },
        )

    def debug(self, message: str, **kwargs) -> None:
        self._emit(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._emit(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        kwargs.setdefault("status", LogStatus.WARNING)
        self._emit(logging.WARNING, message, **kwargs)

    def error(self, message: str, exc_info: bool = False, **kwargs) -> None:
        kwargs.setdefault("status", LogStatus.ERROR)
        self._emit(logging.ERROR, message, exc_info=exc_info, **kwargs)

    def critical(self, message: str, exc_info: bool = True, **kwargs) -> None:
        kwargs.setdefault("status", LogStatus.ERROR)
        self._emit(logging.CRITICAL, message, exc_info=exc_info, **kwargs)


# ─── Bootstrap ────────────────────────────────────────────────────────────────

def _bootstrap_logging() -> None:
    """Configure root logger once at import time."""
    cfg     = config.logging
    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:          # already configured (e.g. in tests)
        return

    root.setLevel(cfg.log_level)
    formatter = JsonFormatter()

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        filename    = log_dir / "workmind.log",
        maxBytes    = cfg.max_log_size_mb * 1024 * 1024,
        backupCount = cfg.backup_count,
        encoding    = "utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Optional stdout handler
    if cfg.emit_to_stdout:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)


_bootstrap_logging()


def get_logger(name: str) -> WorkMindLogger:
    """Factory — returns a WorkMindLogger bound to *name*."""
    return WorkMindLogger(name)

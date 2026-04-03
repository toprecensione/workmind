"""
WorkMind Audit Trail Immutabile
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Registra ogni decisione AI, correzione del supervisore e evento rilevante
in un log append-only (JSONL) con hash di integrità concatenato.
Non è possibile modificare o eliminare voci passate senza rompere la chain.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from config.settings import DATA_DIR
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("storage.audit")

_AUDIT_FILE = DATA_DIR / "audit_trail.jsonl"
_LOCK = threading.Lock()


class AuditEventType(str, Enum):
    AI_DECISION      = "ai_decision"       # il bot ha preso una decisione AI
    SUPERVISOR_TEACH = "supervisor_teach"  # il supervisore ha insegnato qualcosa
    CORRECTION       = "correction"        # il supervisore ha corretto il bot
    ANOMALY          = "anomaly"           # rilevata anomalia
    REPORT_GENERATED = "report_generated"  # report generato
    FEEDBACK         = "feedback"          # feedback su un suggerimento
    SYSTEM           = "system"            # evento di sistema


class AuditTrail:
    """
    Log immutabile append-only.

    Ogni record contiene:
    - timestamp, event_type, actor, summary, details
    - prev_hash: hash SHA-256 del record precedente (chain)
    - hash: SHA-256 di questo record + prev_hash

    Verificare l'integrità con verify_chain().
    """

    def __init__(self) -> None:
        self._last_hash = self._get_last_hash()

    # ── Public API ────────────────────────────────────────────────────────────

    def record(
        self,
        event_type: AuditEventType,
        summary: str,
        actor: str = "system",
        details: Optional[dict] = None,
    ) -> str:
        """Aggiunge un evento all'audit trail. Ritorna l'hash del record."""
        record = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "event_type": str(event_type),
            "actor":      actor,
            "summary":    summary,
            "details":    details or {},
            "prev_hash":  self._last_hash,
        }
        record_hash = self._hash(record)
        record["hash"] = record_hash

        with _LOCK:
            with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._last_hash = record_hash

        return record_hash

    def record_ai_decision(
        self,
        model: str,
        prompt_summary: str,
        output_summary: str,
        confidence: float = 0.0,
        document_ref: str = "",
    ) -> str:
        return self.record(
            AuditEventType.AI_DECISION,
            summary=f"AI ({model}): {output_summary[:100]}",
            actor=model,
            details={
                "prompt_summary": prompt_summary,
                "output_summary": output_summary,
                "confidence": confidence,
                "document_ref": document_ref,
            },
        )

    def record_correction(
        self,
        wrong: str,
        correct: str,
        supervisor: str = "supervisor",
        context: str = "",
    ) -> str:
        return self.record(
            AuditEventType.CORRECTION,
            summary=f"Correzione: '{wrong}' → '{correct}'",
            actor=supervisor,
            details={"wrong": wrong, "correct": correct, "context": context},
        )

    def verify_chain(self) -> tuple[bool, int, str]:
        """
        Verifica l'integrità di tutta la chain.
        Ritorna (ok, records_count, error_message).
        """
        if not _AUDIT_FILE.exists():
            return True, 0, ""

        prev_hash = ""
        count = 0
        try:
            for line in _AUDIT_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                stored_hash = record.pop("hash", "")
                if record.get("prev_hash") != prev_hash:
                    return False, count, f"Record {count}: prev_hash non corrisponde"
                computed = self._hash(record)
                if computed != stored_hash:
                    return False, count, f"Record {count}: hash manomesso"
                prev_hash = stored_hash
                count += 1
        except Exception as exc:
            return False, count, str(exc)

        return True, count, ""

    def recent(self, n: int = 50) -> list[dict]:
        """Ritorna gli ultimi n eventi."""
        if not _AUDIT_FILE.exists():
            return []
        lines = _AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        result = []
        for line in reversed(lines[-n * 2:]):
            if line.strip():
                try:
                    result.append(json.loads(line))
                except Exception:
                    pass
            if len(result) >= n:
                break
        return result

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_last_hash(self) -> str:
        if not _AUDIT_FILE.exists():
            return ""
        last_line = ""
        try:
            for line in _AUDIT_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    last_line = line
        except Exception:
            return ""
        if not last_line:
            return ""
        try:
            return json.loads(last_line).get("hash", "")
        except Exception:
            return ""

    @staticmethod
    def _hash(record: dict) -> str:
        content = json.dumps(record, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ─── Singleton ────────────────────────────────────────────────────────────────

_audit: Optional[AuditTrail] = None


def get_audit() -> AuditTrail:
    global _audit
    if _audit is None:
        _audit = AuditTrail()
    return _audit

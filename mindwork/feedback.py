"""
WorkMind Feedback Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Gestisce il ciclo di feedback del supervisore sui suggerimenti e output AI:
- Conferma: il suggerimento è corretto → rafforza il modello
- Correggi: il suggerimento è sbagliato → salva correzione in KB
- Rifiuta: il suggerimento non è rilevante → abbassa priorità future simili

Ogni feedback viene registrato nell'audit trail.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit, AuditEventType
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("mindwork.feedback")

_FEEDBACK_FILE = DATA_DIR / "feedback_history.json"
_LOCK = threading.Lock()


@dataclass
class FeedbackEntry:
    suggestion_id: str
    action: str              # confirmed | corrected | rejected
    supervisor_comment: str = ""
    correction: str = ""     # per action=corrected: il valore corretto
    timestamp: str = ""
    original_title: str = ""
    original_description: str = ""


class FeedbackManager:
    """
    Gestisce feedback sui suggerimenti e aggiorna KnowledgeBase di conseguenza.
    """

    def __init__(self) -> None:
        self._kb = get_kb()
        self._audit = get_audit()
        self._history = self._load()

    # ── Azioni del supervisore ────────────────────────────────────────────────

    def confirm(
        self,
        suggestion_id: str,
        comment: str = "",
        title: str = "",
        description: str = "",
    ) -> FeedbackEntry:
        """Il supervisore conferma un suggerimento come corretto e utile."""
        entry = FeedbackEntry(
            suggestion_id=suggestion_id,
            action="confirmed",
            supervisor_comment=comment,
            timestamp=_now(),
            original_title=title,
            original_description=description,
        )
        self._save_entry(entry)

        # Registra come fatto positivo nella KB
        if title:
            self._kb.teach_fact(
                f"Il supervisore ha confermato il suggerimento: {title}. "
                f"{'Commento: ' + comment if comment else ''}",
                taught_by="feedback_system",
            )

        self._audit.record(
            AuditEventType.FEEDBACK,
            summary=f"Confermato: {title or suggestion_id}",
            actor="supervisor",
            details={"action": "confirmed", "comment": comment},
        )

        log.info(f"Feedback: confermato {suggestion_id}", action=LogAction.ANALYSE, status=LogStatus.OK)
        return entry

    def correct(
        self,
        suggestion_id: str,
        correction: str,
        comment: str = "",
        title: str = "",
        description: str = "",
    ) -> FeedbackEntry:
        """Il supervisore corregge un suggerimento sbagliato."""
        entry = FeedbackEntry(
            suggestion_id=suggestion_id,
            action="corrected",
            correction=correction,
            supervisor_comment=comment,
            timestamp=_now(),
            original_title=title,
            original_description=description,
        )
        self._save_entry(entry)

        # Salva la correzione nella KB
        self._kb.teach_correction(
            wrong=description or title or suggestion_id,
            correct=correction,
            context=comment,
            taught_by="supervisor",
        )

        self._audit.record(
            AuditEventType.CORRECTION,
            summary=f"Corretto: {title or suggestion_id} → {correction[:100]}",
            actor="supervisor",
            details={"action": "corrected", "correction": correction, "comment": comment},
        )

        log.info(f"Feedback: corretto {suggestion_id}", action=LogAction.ANALYSE, status=LogStatus.OK)
        return entry

    def reject(
        self,
        suggestion_id: str,
        reason: str = "",
        title: str = "",
        description: str = "",
    ) -> FeedbackEntry:
        """Il supervisore rifiuta un suggerimento non rilevante."""
        entry = FeedbackEntry(
            suggestion_id=suggestion_id,
            action="rejected",
            supervisor_comment=reason,
            timestamp=_now(),
            original_title=title,
            original_description=description,
        )
        self._save_entry(entry)

        if title or description:
            self._kb.teach_fact(
                f"Il supervisore ha rifiutato il suggerimento: {title}. "
                f"{'Motivo: ' + reason if reason else 'Nessun motivo specificato.'}",
                taught_by="feedback_system",
            )

        self._audit.record(
            AuditEventType.FEEDBACK,
            summary=f"Rifiutato: {title or suggestion_id}",
            actor="supervisor",
            details={"action": "rejected", "reason": reason},
        )

        log.info(f"Feedback: rifiutato {suggestion_id}", action=LogAction.ANALYSE, status=LogStatus.OK)
        return entry

    # ── Statistiche ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        confirmed = sum(1 for e in self._history if e["action"] == "confirmed")
        corrected = sum(1 for e in self._history if e["action"] == "corrected")
        rejected  = sum(1 for e in self._history if e["action"] == "rejected")
        total = len(self._history)
        return {
            "total": total,
            "confirmed": confirmed,
            "corrected": corrected,
            "rejected": rejected,
            "accuracy_rate": confirmed / total if total else 0.0,
        }

    def recent(self, n: int = 20) -> list[dict]:
        return self._history[-n:]

    # ── Persistenza ───────────────────────────────────────────────────────────

    def _save_entry(self, entry: FeedbackEntry) -> None:
        data = {
            "suggestion_id": entry.suggestion_id,
            "action": entry.action,
            "correction": entry.correction,
            "supervisor_comment": entry.supervisor_comment,
            "timestamp": entry.timestamp,
            "original_title": entry.original_title,
        }
        with _LOCK:
            self._history.append(data)
            _FEEDBACK_FILE.write_text(
                json.dumps(self._history, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def _load(self) -> list[dict]:
        if _FEEDBACK_FILE.exists():
            try:
                return json.loads(_FEEDBACK_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Singleton ────────────────────────────────────────────────────────────────

_feedback: Optional[FeedbackManager] = None


def get_feedback() -> FeedbackManager:
    global _feedback
    if _feedback is None:
        _feedback = FeedbackManager()
    return _feedback

"""
WorkMind Knowledge Base
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Memoria persistente del bot: raccoglie tutto ciò che il supervisore insegna
via il comando /teach nella chat. Usata da NLP Engine per contestualizzare
le analisi con conoscenza specifica dell'azienda.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.settings import DATA_DIR
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("storage.knowledge_base")

_KB_FILE = DATA_DIR / "knowledge_base.json"
_LOCK = threading.RLock()


class KnowledgeBase:
    """
    Storage strutturato delle conoscenze aziendali insegnate dal supervisore.

    Struttura interna:
    {
        "facts": [         # fatti generali sull'azienda
            {"text": "...", "taught_at": "...", "taught_by": "..."}
        ],
        "corrections": [   # correzioni a classificazioni sbagliate
            {"wrong": "...", "correct": "...", "context": "...", "taught_at": "..."}
        ],
        "processes": [     # processi aziendali descritti dal supervisore
            {"name": "...", "description": "...", "steps": [...], "taught_at": "..."}
        ],
        "glossary": {      # terminologia aziendale specifica
            "termine": "definizione"
        }
    }
    """

    def __init__(self) -> None:
        self._data = self._load()

    # ── Insegnamento ──────────────────────────────────────────────────────────

    def teach_fact(self, text: str, taught_by: str = "supervisor") -> None:
        """Aggiunge un fatto generico (es. 'Il nostro cliente principale è Fiat')."""
        entry = {
            "text": text,
            "taught_at": _now(),
            "taught_by": taught_by,
        }
        with _LOCK:
            self._data.setdefault("facts", []).append(entry)
            self._save()
        log.info(f"Fatto insegnato: {text[:80]}", action=LogAction.CONFIG, status=LogStatus.OK)

    def teach_correction(
        self,
        wrong: str,
        correct: str,
        context: str = "",
        taught_by: str = "supervisor",
    ) -> None:
        """Corregge una classificazione sbagliata del bot."""
        entry = {
            "wrong": wrong,
            "correct": correct,
            "context": context,
            "taught_at": _now(),
            "taught_by": taught_by,
        }
        with _LOCK:
            self._data.setdefault("corrections", []).append(entry)
            self._save()
        log.info(f"Correzione: '{wrong}' → '{correct}'", action=LogAction.CONFIG, status=LogStatus.OK)

    def teach_process(
        self,
        name: str,
        description: str,
        steps: list[str] | None = None,
        taught_by: str = "supervisor",
    ) -> None:
        """Insegna al bot un processo aziendale."""
        entry = {
            "name": name,
            "description": description,
            "steps": steps or [],
            "taught_at": _now(),
            "taught_by": taught_by,
        }
        with _LOCK:
            self._data.setdefault("processes", []).append(entry)
            self._save()
        log.info(f"Processo insegnato: {name}", action=LogAction.CONFIG, status=LogStatus.OK)

    def add_glossary_term(self, term: str, definition: str) -> None:
        """Aggiunge un termine al glossario aziendale."""
        with _LOCK:
            self._data.setdefault("glossary", {})[term.lower()] = definition
            self._save()

    # ── Lettura ───────────────────────────────────────────────────────────────

    def get_facts(self) -> list[dict]:
        return self._data.get("facts", [])

    def get_corrections(self) -> list[dict]:
        return self._data.get("corrections", [])

    def get_processes(self) -> list[dict]:
        return self._data.get("processes", [])

    def get_glossary(self) -> dict[str, str]:
        return self._data.get("glossary", {})

    def build_context_prompt(self) -> str:
        """
        Costruisce un testo di contesto da iniettare nei prompt AI
        con tutto ciò che il supervisore ha insegnato al bot.
        """
        parts: list[str] = []

        facts = self.get_facts()
        if facts:
            parts.append("=== CONOSCENZE AZIENDALI ===")
            for f in facts[-20:]:  # ultime 20 per non gonfiare il contesto
                parts.append(f"- {f['text']}")

        corrections = self.get_corrections()
        if corrections:
            parts.append("\n=== CORREZIONI APPRESE ===")
            for c in corrections[-10:]:
                parts.append(f"- '{c['wrong']}' deve essere classificato come '{c['correct']}'")
                if c.get("context"):
                    parts.append(f"  Contesto: {c['context']}")

        processes = self.get_processes()
        if processes:
            parts.append("\n=== PROCESSI AZIENDALI ===")
            for p in processes:
                parts.append(f"- {p['name']}: {p['description']}")
                if p.get("steps"):
                    for i, step in enumerate(p["steps"], 1):
                        parts.append(f"  {i}. {step}")

        glossary = self.get_glossary()
        if glossary:
            parts.append("\n=== GLOSSARIO ===")
            for term, definition in list(glossary.items())[:20]:
                parts.append(f"- {term}: {definition}")

        return "\n".join(parts)

    def summary(self) -> dict:
        return {
            "facts": len(self.get_facts()),
            "corrections": len(self.get_corrections()),
            "processes": len(self.get_processes()),
            "glossary_terms": len(self.get_glossary()),
        }

    # ── Persistenza ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if _KB_FILE.exists():
            try:
                return json.loads(_KB_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                log.error(f"Errore caricamento knowledge base: {exc}", action=LogAction.CONFIG)
        return {}

    def _save(self) -> None:
        _KB_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Singleton ────────────────────────────────────────────────────────────────

_kb: Optional[KnowledgeBase] = None


def get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb

"""
WorkMind Mem0 Integration — Memoria AI Locale
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Layer di memoria avanzata per agenti AI, 100% self-hosted.
Usa Mem0 con:
- DeepSeek API come LLM (estrazione fatti, gestione contraddizioni)
- HuggingFace sentence-transformers per embeddings (locale, no cloud)
- Qdrant embedded per vector storage (persistente su disco)

Funzionalita':
- Profili utente con fatti estratti automaticamente dalle conversazioni
- Ricerca semantica nelle memorie
- Gestione automatica contraddizioni e aggiornamenti
- Organizzazione per user_id (supervisor, telegram users, etc.)
- Zero dipendenze cloud (tranne DeepSeek API che gia' usi)
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("storage.mem0")

_MEM0_DIR = DATA_DIR / "mem0_qdrant"

try:
    from mem0 import Memory
    _HAS_MEM0 = True
except ImportError:
    _HAS_MEM0 = False
    Memory = None


def _build_config() -> dict:
    """
    Configurazione Mem0:
    - LLM: DeepSeek (OpenAI-compatible) per estrazione fatti
    - Embedder: HuggingFace locale (sentence-transformers, nessun cloud)
    - Vector Store: Qdrant on-disk (embedded, nessun Docker)
    """
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")

    config = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": "deepseek-chat",
                "api_key": deepseek_key,
                "openai_base_url": "https://api.deepseek.com",
                "temperature": 0.1,
                "max_tokens": 1500,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "model_kwargs": {"device": "cpu"},
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "workmind_memories",
                "path": str(_MEM0_DIR),
                "on_disk": True,
            },
        },
        "version": "v1.1",
    }

    return config


class Mem0Store:
    """
    Wrapper attorno a Mem0 per gestione memoria AI locale.

    User IDs usati:
    - "supervisor": supervisore principale (web UI)
    - "tg_{chat_id}": utenti Telegram
    - "system": memoria di sistema (fatti aziendali)
    """

    def __init__(self) -> None:
        self._memory: Optional[Memory] = None
        self._lock = threading.Lock()

        if not _HAS_MEM0:
            log.warning(
                "mem0ai non installato — pip install mem0ai. "
                "Memoria avanzata disabilitata.",
                action=LogAction.STARTUP,
            )
            return

        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not deepseek_key:
            log.warning(
                "DEEPSEEK_API_KEY non configurata — Mem0 richiede un LLM. "
                "Memoria avanzata disabilitata.",
                action=LogAction.STARTUP,
            )
            return

        try:
            _MEM0_DIR.mkdir(parents=True, exist_ok=True)
            config = _build_config()
            self._memory = Memory.from_config(config_dict=config)
            log.info(
                "Mem0 inizializzato — memoria AI locale attiva "
                f"(LLM: DeepSeek, Embedder: HuggingFace, Store: Qdrant @ {_MEM0_DIR})",
                action=LogAction.STARTUP, status=LogStatus.OK,
            )
        except Exception as exc:
            log.warning(f"Mem0 non disponibile: {exc}", action=LogAction.STARTUP)
            self._memory = None

    @property
    def available(self) -> bool:
        return self._memory is not None

    # ── Memorizzazione ────────────────────────────────────────────────────

    def add_conversation(
        self,
        user_message: str,
        bot_response: str,
        user_id: str = "supervisor",
        metadata: dict | None = None,
    ) -> bool:
        """
        Memorizza una conversazione. Mem0 estrae automaticamente
        i fatti rilevanti e gestisce contraddizioni.
        """
        if not self._memory or not user_message:
            return False
        try:
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": bot_response},
            ]
            with self._lock:
                self._memory.add(
                    messages=messages,
                    user_id=user_id,
                    metadata={"source": "conversation", **(metadata or {})},
                )
            return True
        except Exception as exc:
            log.warning(f"Errore add conversation: {exc}", action=LogAction.MONITOR)
            return False

    def add_fact(self, fact: str, user_id: str = "system", source: str = "teach") -> bool:
        """Aggiunge un fatto esplicito alla memoria."""
        if not self._memory or not fact:
            return False
        try:
            messages = [{"role": "user", "content": fact}]
            with self._lock:
                self._memory.add(
                    messages=messages,
                    user_id=user_id,
                    metadata={"type": "fact", "source": source},
                )
            return True
        except Exception as exc:
            log.warning(f"Errore add fact: {exc}", action=LogAction.MONITOR)
            return False

    def add_document(self, doc_name: str, content: str, user_id: str = "system") -> bool:
        """Indicizza il contenuto di un documento nella memoria."""
        if not self._memory or not content:
            return False
        try:
            # Tronca se troppo lungo
            if len(content) > 30000:
                content = content[:30000] + "\n[...troncato...]"
            messages = [
                {"role": "user", "content": f"Documento '{doc_name}':\n\n{content}"},
            ]
            with self._lock:
                self._memory.add(
                    messages=messages,
                    user_id=user_id,
                    metadata={"type": "document", "doc_name": doc_name},
                )
            return True
        except Exception as exc:
            log.warning(f"Errore add document: {exc}", action=LogAction.MONITOR)
            return False

    # ── Ricerca ───────────────────────────────────────────────────────────

    def search(self, query: str, user_id: str = "system", limit: int = 5) -> list[dict]:
        """Ricerca semantica nelle memorie."""
        if not self._memory or not query:
            return []
        try:
            with self._lock:
                results = self._memory.search(query=query, user_id=user_id, limit=limit)

            items = []
            # results puo' essere dict con 'results' key o lista diretta
            memories = results if isinstance(results, list) else results.get("results", [])
            for mem in memories:
                if isinstance(mem, dict):
                    items.append({
                        "id": mem.get("id", ""),
                        "memory": mem.get("memory", ""),
                        "score": mem.get("score", 0),
                    })
                else:
                    items.append({
                        "id": getattr(mem, "id", ""),
                        "memory": getattr(mem, "memory", str(mem)),
                        "score": getattr(mem, "score", 0),
                    })
            return items
        except Exception as exc:
            log.warning(f"Errore search: {exc}", action=LogAction.MONITOR)
            return []

    def get_all(self, user_id: str = "system") -> list[dict]:
        """Ritorna tutte le memorie di un utente."""
        if not self._memory:
            return []
        try:
            with self._lock:
                results = self._memory.get_all(user_id=user_id)
            memories = results if isinstance(results, list) else results.get("results", [])
            items = []
            for mem in memories:
                if isinstance(mem, dict):
                    items.append({"id": mem.get("id", ""), "memory": mem.get("memory", "")})
                else:
                    items.append({"id": getattr(mem, "id", ""), "memory": getattr(mem, "memory", str(mem))})
            return items
        except Exception as exc:
            log.warning(f"Errore get_all: {exc}", action=LogAction.MONITOR)
            return []

    # ── Contesto per prompt AI ────────────────────────────────────────────

    def build_memory_context(
        self,
        query: str,
        user_id: str = "supervisor",
        max_chars: int = 2000,
    ) -> str:
        """
        Costruisce contesto combinato dalle memorie dell'utente
        e dalle memorie di sistema per il prompt AI.
        """
        if not self._memory:
            return ""

        parts = []

        # Memorie specifiche dell'utente
        user_memories = self.search(query, user_id=user_id, limit=5)
        if user_memories:
            parts.append("=== MEMORIE UTENTE ===")
            for m in user_memories:
                mem_text = m.get("memory", "")
                if mem_text:
                    parts.append(f"- {mem_text}")

        # Memorie di sistema (fatti aziendali)
        if user_id != "system":
            sys_memories = self.search(query, user_id="system", limit=3)
            if sys_memories:
                parts.append("=== CONOSCENZE AZIENDALI (memoria) ===")
                for m in sys_memories:
                    mem_text = m.get("memory", "")
                    if mem_text:
                        parts.append(f"- {mem_text}")

        context = "\n".join(parts)
        if len(context) > max_chars:
            context = context[:max_chars] + "\n[...troncato...]"
        return context

    # ── Sincronizzazione KB ───────────────────────────────────────────────

    def sync_from_kb(self) -> dict:
        """Sincronizza tutti i fatti dalla Knowledge Base locale a Mem0."""
        if not self._memory:
            return {"synced": 0, "available": False}

        synced = 0
        try:
            from storage.knowledge_base import get_kb
            kb = get_kb()

            for fact in kb.get_facts():
                if self.add_fact(fact["text"], source="kb_sync"):
                    synced += 1

            for proc in kb.get_processes():
                desc = f"Processo: {proc['name']} — {proc['description']}"
                if proc.get("steps"):
                    desc += ". Passaggi: " + ", ".join(proc["steps"])
                if self.add_fact(desc, source="kb_sync"):
                    synced += 1

            for term, definition in kb.get_glossary().items():
                if self.add_fact(f"{term}: {definition}", source="kb_sync"):
                    synced += 1

            log.info(f"Sincronizzati {synced} elementi da KB a Mem0",
                     action=LogAction.CONFIG, status=LogStatus.OK)
        except Exception as exc:
            log.warning(f"Errore sync KB: {exc}", action=LogAction.MONITOR)

        return {"synced": synced, "available": True}

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        info = {
            "available": self.available,
            "has_sdk": _HAS_MEM0,
            "backend": "local (DeepSeek LLM + HuggingFace embeddings + Qdrant on-disk)",
            "storage_path": str(_MEM0_DIR),
        }
        if self._memory:
            try:
                sys_mems = self.get_all(user_id="system")
                info["system_memories"] = len(sys_mems)
            except Exception:
                info["system_memories"] = -1
        return info


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[Mem0Store] = None


def get_mem0() -> Mem0Store:
    global _store
    if _store is None:
        _store = Mem0Store()
    return _store

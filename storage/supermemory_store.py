"""
WorkMind Supermemory Integration
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Integra supermemory.ai come layer di memoria avanzata per gli agenti AI.
Gestisce automaticamente:
- Profili utente con fatti statici e contesto dinamico
- Memorizzazione conversazioni con estrazione fatti automatica
- Ricerca semantica ibrida (memories + documents)
- Gestione contraddizioni e aggiornamenti automatici
- Scadenza automatica informazioni obsolete

Se SUPERMEMORY_API_KEY non è configurata, fallback silenzioso alla KB locale.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Optional

from logging_system import get_logger, LogAction, LogStatus

log = get_logger("storage.supermemory")

try:
    from supermemory import Supermemory
    _HAS_SUPERMEMORY = True
except ImportError:
    _HAS_SUPERMEMORY = False


class SupermemoryStore:
    """
    Wrapper attorno a supermemory.ai SDK.

    Container tags usati:
    - "workmind": contesto globale del sistema
    - "company:{name}": fatti specifici dell'azienda
    - "user:{id}": profilo per utente (supervisore, telegram user, etc.)
    - "docs": documenti indicizzati
    """

    def __init__(self) -> None:
        self._client: Optional[Supermemory] = None
        self._lock = threading.Lock()
        self._api_key = os.getenv("SUPERMEMORY_API_KEY", "")

        if not _HAS_SUPERMEMORY:
            log.warning(
                "supermemory non installato — pip install supermemory. "
                "Usando solo KB locale.",
                action=LogAction.STARTUP,
            )
            return

        if not self._api_key:
            log.info(
                "SUPERMEMORY_API_KEY non configurata — memoria avanzata disabilitata. "
                "Configura da Settings per attivare.",
                action=LogAction.STARTUP,
            )
            return

        try:
            self._client = Supermemory(api_key=self._api_key)
            log.info(
                "Supermemory connesso — memoria avanzata attiva",
                action=LogAction.STARTUP, status=LogStatus.OK,
            )
        except Exception as exc:
            log.warning(f"Supermemory non disponibile: {exc}", action=LogAction.STARTUP)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    # ── Memorizzazione ────────────────────────────────────────────────────

    def add_memory(
        self,
        content: str,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> bool:
        """Aggiunge un ricordo/fatto alla memoria."""
        if not self._client or not content:
            return False
        try:
            with self._lock:
                self._client.add(
                    content=content,
                    container_tags=tags or ["workmind"],
                    metadata={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        **(metadata or {}),
                    },
                )
            return True
        except Exception as exc:
            log.warning(f"Errore add memory: {exc}", action=LogAction.MONITOR)
            return False

    def add_conversation(
        self,
        user_message: str,
        bot_response: str,
        user_id: str = "supervisor",
        source: str = "web",
    ) -> bool:
        """Memorizza una conversazione completa — supermemory estrae fatti automaticamente."""
        if not self._client:
            return False
        content = (
            f"[{source}] Conversazione con {user_id}:\n"
            f"Utente: {user_message}\n"
            f"WorkMind: {bot_response}"
        )
        return self.add_memory(
            content=content,
            tags=["workmind", f"user:{user_id}"],
            metadata={"type": "conversation", "source": source},
        )

    def add_fact(self, fact: str, source: str = "teach") -> bool:
        """Aggiunge un fatto esplicito insegnato dal supervisore."""
        return self.add_memory(
            content=fact,
            tags=["workmind", "company"],
            metadata={"type": "fact", "source": source},
        )

    def add_document(
        self,
        doc_name: str,
        content: str,
        doc_type: str = "",
    ) -> bool:
        """Indicizza un documento nella memoria."""
        if not self._client or not content:
            return False
        # Tronca se troppo lungo (supermemory gestisce il chunking)
        if len(content) > 50000:
            content = content[:50000] + "\n[...troncato...]"
        return self.add_memory(
            content=f"Documento: {doc_name}\n\n{content}",
            tags=["workmind", "docs"],
            metadata={"type": "document", "doc_name": doc_name, "doc_type": doc_type},
        )

    # ── Ricerca ───────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Ricerca semantica nella memoria."""
        if not self._client or not query:
            return []
        try:
            with self._lock:
                results = self._client.search.memories(
                    q=query,
                    container_tags=tags or ["workmind"],
                )
            items = []
            for mem in getattr(results, "results", [])[:limit]:
                items.append({
                    "content": getattr(mem, "content", str(mem)),
                    "score": getattr(mem, "score", 0),
                })
            return items
        except Exception as exc:
            log.warning(f"Errore search memory: {exc}", action=LogAction.MONITOR)
            return []

    def search_documents(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """Ricerca semantica nei documenti indicizzati."""
        if not self._client or not query:
            return []
        try:
            with self._lock:
                results = self._client.search.documents(
                    q=query,
                    container_tags=["workmind", "docs"],
                )
            items = []
            for doc in getattr(results, "results", [])[:limit]:
                items.append({
                    "content": getattr(doc, "content", str(doc)),
                    "metadata": getattr(doc, "metadata", {}),
                })
            return items
        except Exception as exc:
            log.warning(f"Errore search documents: {exc}", action=LogAction.MONITOR)
            return []

    # ── Profilo utente ────────────────────────────────────────────────────

    def get_user_profile(
        self,
        user_id: str = "supervisor",
        query: str = "",
    ) -> dict:
        """
        Ritorna il profilo utente con fatti statici e contesto dinamico.
        Supermemory costruisce automaticamente il profilo dalle conversazioni.
        """
        if not self._client:
            return {"static": "", "dynamic": ""}
        try:
            with self._lock:
                result = self._client.profile(
                    container_tag=f"user:{user_id}",
                    q=query or None,
                )
            profile = getattr(result, "profile", None)
            if profile:
                return {
                    "static": getattr(profile, "static", ""),
                    "dynamic": getattr(profile, "dynamic", ""),
                }
            return {"static": "", "dynamic": ""}
        except Exception as exc:
            log.warning(f"Errore get profile: {exc}", action=LogAction.MONITOR)
            return {"static": "", "dynamic": ""}

    # ── Contesto per prompt AI ────────────────────────────────────────────

    def build_memory_context(
        self,
        query: str,
        user_id: str = "supervisor",
        max_chars: int = 2000,
    ) -> str:
        """
        Costruisce contesto combinato da memoria + profilo utente
        da iniettare nel prompt AI.
        """
        if not self._client:
            return ""

        parts = []

        # Profilo utente
        profile = self.get_user_profile(user_id, query)
        if profile["static"]:
            parts.append(f"=== PROFILO UTENTE ===\n{profile['static']}")
        if profile["dynamic"]:
            parts.append(f"=== CONTESTO RECENTE ===\n{profile['dynamic']}")

        # Ricerca memories rilevanti
        memories = self.search(query, limit=5)
        if memories:
            mem_texts = []
            for m in memories:
                c = m.get("content", "")
                if c:
                    mem_texts.append(f"- {c[:300]}")
            if mem_texts:
                parts.append("=== MEMORIE RILEVANTI ===\n" + "\n".join(mem_texts))

        context = "\n\n".join(parts)
        if len(context) > max_chars:
            context = context[:max_chars] + "\n[...troncato...]"
        return context

    # ── Sincronizzazione KB ───────────────────────────────────────────────

    def sync_from_kb(self) -> dict:
        """Sincronizza tutti i fatti dalla Knowledge Base locale a supermemory."""
        if not self._client:
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
                    desc += "\nPassaggi: " + ", ".join(proc["steps"])
                if self.add_fact(desc, source="kb_sync"):
                    synced += 1

            for term, definition in kb.get_glossary().items():
                if self.add_fact(f"Glossario: {term} = {definition}", source="kb_sync"):
                    synced += 1

            log.info(f"Sincronizzati {synced} elementi da KB a supermemory",
                     action=LogAction.CONFIG, status=LogStatus.OK)
        except Exception as exc:
            log.warning(f"Errore sync KB: {exc}", action=LogAction.MONITOR)

        return {"synced": synced, "available": True}

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "available": self.available,
            "has_sdk": _HAS_SUPERMEMORY,
            "api_key_set": bool(self._api_key),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[SupermemoryStore] = None


def get_supermemory() -> SupermemoryStore:
    global _store
    if _store is None:
        _store = SupermemoryStore()
    return _store

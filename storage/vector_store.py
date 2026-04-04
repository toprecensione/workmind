"""
WorkMind Vector Store — RAG (Retrieval Augmented Generation)
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Indicizza documenti e fatti in ChromaDB per ricerca semantica.
Usato dalla chat per contestualizzare le risposte AI con i documenti aziendali.
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("storage.vector_store")

_CHROMA_DIR = DATA_DIR / "chromadb"

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _HAS_CHROMA = True
except ImportError:
    _HAS_CHROMA = False


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into chunks at sentence boundaries."""
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    # Split on sentence-ending punctuation
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            # Keep overlap from end of current chunk
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:] + " " + sentence
            else:
                current = sentence
        else:
            current = (current + " " + sentence).strip() if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks


class VectorStore:
    """ChromaDB-backed vector store for RAG."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client = None
        self._collection = None
        if _HAS_CHROMA:
            try:
                _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(_CHROMA_DIR),
                )
                self._collection = self._client.get_or_create_collection(
                    name="workmind_docs",
                    metadata={"hnsw:space": "cosine"},
                )
                log.info(
                    f"VectorStore inizializzato ({self._collection.count()} documenti)",
                    action=LogAction.STARTUP, status=LogStatus.OK,
                )
            except Exception as exc:
                log.warning(f"ChromaDB non disponibile: {exc}", action=LogAction.STARTUP)
                self._client = None
                self._collection = None
        else:
            log.warning(
                "chromadb non installato — RAG disabilitato. pip install chromadb",
                action=LogAction.STARTUP,
            )

    def index_document(self, doc_path: str, text: str, metadata: dict | None = None) -> int:
        """Indicizza un documento, ritorna il numero di chunk aggiunti."""
        if not self._collection or not text:
            return 0

        chunks = _chunk_text(text)
        if not chunks:
            return 0

        ids = []
        documents = []
        metadatas = []
        base_meta = {"source": doc_path, **(metadata or {})}

        for i, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{doc_path}::{i}::{chunk[:50]}".encode()).hexdigest()
            ids.append(doc_id)
            documents.append(chunk)
            metadatas.append({**base_meta, "chunk_index": i})

        with self._lock:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        log.info(f"Indicizzato '{doc_path}': {len(chunks)} chunk", action=LogAction.SCAN)
        return len(chunks)

    def index_fact(self, fact_text: str, source: str = "kb") -> None:
        """Indicizza un fatto dalla Knowledge Base."""
        if not self._collection or not fact_text:
            return
        doc_id = hashlib.md5(f"fact::{fact_text}".encode()).hexdigest()
        with self._lock:
            self._collection.upsert(
                ids=[doc_id],
                documents=[fact_text],
                metadatas=[{"source": source, "type": "fact"}],
            )

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Ricerca semantica, ritorna lista di {text, source, score}."""
        if not self._collection or not query:
            return []
        try:
            with self._lock:
                results = self._collection.query(
                    query_texts=[query],
                    n_results=min(n_results, self._collection.count() or 1),
                )
            items = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                items.append({
                    "text": doc,
                    "source": meta.get("source", ""),
                    "score": round(1.0 - dist, 4),  # cosine similarity
                })
            return items
        except Exception as exc:
            log.warning(f"Errore ricerca vettoriale: {exc}", action=LogAction.MONITOR)
            return []

    def build_rag_context(self, query: str, max_chars: int = 3000) -> str:
        """Cerca e formatta risultati come contesto per il prompt AI."""
        results = self.search(query, n_results=8)
        if not results:
            return ""

        parts = ["=== DOCUMENTI RILEVANTI ==="]
        total = 0
        for r in results:
            if r["score"] < 0.3:
                continue
            text = r["text"]
            if total + len(text) > max_chars:
                break
            src = r["source"]
            parts.append(f"[{src}] {text}")
            total += len(text)

        return "\n".join(parts) if len(parts) > 1 else ""

    def reindex_all(self) -> dict:
        """Reindicizza tutti i fatti KB e documenti in DATA_DIR."""
        stats = {"facts": 0, "documents": 0, "chunks": 0}
        if not self._collection:
            return stats

        # Reindex KB facts
        try:
            from storage.knowledge_base import get_kb
            kb = get_kb()
            for fact in kb.get_facts():
                self.index_fact(fact["text"], source="kb")
                stats["facts"] += 1
        except Exception as exc:
            log.warning(f"Errore reindex fatti: {exc}")

        # Reindex documents in DATA_DIR
        try:
            from connectors.document_parser import parse_document
            for ext in ["*.pdf", "*.docx", "*.xlsx", "*.csv", "*.txt", "*.eml"]:
                for fpath in DATA_DIR.glob(ext):
                    try:
                        text = parse_document(str(fpath))
                        if text:
                            n = self.index_document(str(fpath), text)
                            stats["documents"] += 1
                            stats["chunks"] += n
                    except Exception:
                        pass
        except ImportError:
            pass

        log.info(f"Reindex completato: {stats}", action=LogAction.SCAN, status=LogStatus.OK)
        return stats

    def stats(self) -> dict:
        if not self._collection:
            return {"available": False, "count": 0}
        return {
            "available": True,
            "count": self._collection.count(),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store

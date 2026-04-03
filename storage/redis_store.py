"""
WorkMind Redis Store
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Cache condivisa tra tutti i moduli.
Se Redis non è disponibile, fallback su dizionario in memoria
(non persistente, accettabile in dev).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

from logging_system import get_logger, LogStatus, LogAction

log = get_logger("storage.redis")

_REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
_REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
_REDIS_DB   = int(os.getenv("REDIS_DB", "0"))
_KEY_PREFIX = "workmind:"


class _MemoryFallback:
    """Dict in-memory con TTL, usato se Redis non è raggiungibile."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        expires_at = time.time() + ex if ex else float("inf")
        with self._lock:
            self._data[key] = (value, expires_at)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._data[key]
                return None
            return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self, pattern: str) -> list[str]:
        import fnmatch
        now = time.time()
        with self._lock:
            return [
                k for k, (_, exp) in self._data.items()
                if now <= exp and fnmatch.fnmatch(k, pattern)
            ]

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def lpush(self, key: str, *values) -> None:
        with self._lock:
            lst, exp = self._data.get(key, ([], float("inf")))
            if not isinstance(lst, list):
                lst = []
            lst[:0] = list(values)
            self._data[key] = (lst, exp)

    def lrange(self, key: str, start: int, end: int) -> list:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return []
            lst, exp = entry
            if time.time() > exp:
                del self._data[key]
                return []
            if not isinstance(lst, list):
                return []
            if end == -1:
                return lst[start:]
            return lst[start:end + 1]

    def ltrim(self, key: str, start: int, end: int) -> None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return
            lst, exp = entry
            if isinstance(lst, list):
                if end == -1:
                    self._data[key] = (lst[start:], exp)
                else:
                    self._data[key] = (lst[start:end + 1], exp)

    def ping(self) -> bool:
        return True


class RedisStore:
    """
    Wrapper su redis-py con fallback automatico su memoria.
    Tutte le chiavi sono prefissate con "workmind:" per namespace isolation.
    """

    def __init__(self) -> None:
        self._backend = self._connect()

    def _connect(self):
        try:
            import redis
            client = redis.Redis(
                host=_REDIS_HOST,
                port=_REDIS_PORT,
                db=_REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            client.ping()
            log.info(
                f"Redis connesso: {_REDIS_HOST}:{_REDIS_PORT}",
                action=LogAction.STARTUP, status=LogStatus.OK,
            )
            return client
        except Exception as exc:
            log.warning(
                f"Redis non raggiungibile ({exc}) — uso fallback in-memory",
                action=LogAction.STARTUP, status=LogStatus.WARNING,
                suggestion="Installa e avvia Redis: sudo systemctl start redis",
            )
            return _MemoryFallback()

    @property
    def is_redis(self) -> bool:
        try:
            import redis
            return isinstance(self._backend, redis.Redis)
        except ImportError:
            return False

    # ── Operazioni base ───────────────────────────────────────────────────────

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Salva un valore (serializzato in JSON)."""
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        k = _KEY_PREFIX + key
        if ttl_seconds:
            self._backend.set(k, serialized, ex=ttl_seconds)
        else:
            self._backend.set(k, serialized)

    def get(self, key: str, default: Any = None) -> Any:
        """Recupera un valore. Ritorna default se non esiste."""
        raw = self._backend.get(_KEY_PREFIX + key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def delete(self, key: str) -> None:
        self._backend.delete(_KEY_PREFIX + key)

    def exists(self, key: str) -> bool:
        return bool(self._backend.exists(_KEY_PREFIX + key))

    def keys(self, pattern: str = "*") -> list[str]:
        prefix = _KEY_PREFIX
        raw_keys = self._backend.keys(prefix + pattern)
        return [k[len(prefix):] for k in raw_keys]

    # ── Lista (usata per code e history) ─────────────────────────────────────

    def list_push(self, key: str, value: Any, max_len: int = 1000) -> None:
        """Aggiunge in testa alla lista, mantiene max max_len elementi."""
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        k = _KEY_PREFIX + key
        self._backend.lpush(k, serialized)
        self._backend.ltrim(k, 0, max_len - 1)

    def list_get(self, key: str, count: int = 100) -> list:
        """Recupera gli ultimi count elementi dalla lista."""
        k = _KEY_PREFIX + key
        raw = self._backend.lrange(k, 0, count - 1)
        result = []
        for item in raw:
            try:
                result.append(json.loads(item))
            except Exception:
                result.append(item)
        return result

    # ── Cache documentale ─────────────────────────────────────────────────────

    def cache_document(self, doc_hash: str, metadata: dict, ttl_days: int = 30) -> None:
        self.set(f"doc:{doc_hash}", metadata, ttl_seconds=ttl_days * 86400)

    def get_cached_document(self, doc_hash: str) -> Optional[dict]:
        return self.get(f"doc:{doc_hash}")

    # ── Pattern history (per anomaly detection) ────────────────────────────────

    def push_pattern_snapshot(self, target_dir: str, snapshot: dict) -> None:
        key = f"pattern:{target_dir.replace('/', '_')}"
        self.list_push(key, snapshot, max_len=90)  # ~3 mesi di storia

    def get_pattern_history(self, target_dir: str, days: int = 30) -> list[dict]:
        key = f"pattern:{target_dir.replace('/', '_')}"
        return self.list_get(key, count=days)


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[RedisStore] = None


def get_store() -> RedisStore:
    global _store
    if _store is None:
        _store = RedisStore()
    return _store

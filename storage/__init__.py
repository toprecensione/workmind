"""
WorkMind Storage Layer
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

- RedisStore: cache + code condiviso tra moduli
- KnowledgeBase: memoria persistente del bot (insegnamenti via /teach)
- AuditTrail: log immutabile di ogni decisione AI
"""

from storage.redis_store import RedisStore, get_store
from storage.knowledge_base import KnowledgeBase, get_kb
from storage.audit_trail import AuditTrail, get_audit

__all__ = [
    "RedisStore", "get_store",
    "KnowledgeBase", "get_kb",
    "AuditTrail", "get_audit",
]

"""
WorkMind Plugin Base
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Classe base per tutti i plugin WorkMind.
Ogni plugin eredita da PluginBase e implementa i hook necessari.
"""

from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


@dataclass
class PluginManifest:
    """Metadati di un plugin (manifest.json)."""
    id: str
    name: str
    version: str
    description: str = ""
    author: str = "WorkMind Dev"
    workmind_min_version: str = "1.0.0"
    hooks: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    enabled_by_default: bool = False
    category: str = "general"   # general, connector, interface, ai, storage

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class PluginBase(ABC):
    """
    Classe base per tutti i plugin WorkMind.

    Ogni plugin puo' implementare uno o piu' hook:
    - startup()              → eseguito all'avvio del sistema
    - shutdown()             → eseguito allo spegnimento
    - register_routes(app)  → registra route Flask
    - on_telegram_message(text, chat_id) → gestisce messaggi Telegram
    - on_whatsapp_message(text, phone)   → gestisce messaggi WhatsApp
    - on_schedule()          → eseguito ogni N minuti (se hooks contiene 'schedule')
    """

    # Sottoclassi devono definire MANIFEST
    MANIFEST: PluginManifest = None  # type: ignore

    def __init__(self) -> None:
        self._enabled = True
        self._error: Optional[str] = None

    @property
    def id(self) -> str:
        return self.MANIFEST.id if self.MANIFEST else "unknown"

    @property
    def name(self) -> str:
        return self.MANIFEST.name if self.MANIFEST else "Unknown Plugin"

    @property
    def version(self) -> str:
        return self.MANIFEST.version if self.MANIFEST else "0.0.0"

    def is_enabled(self) -> bool:
        return self._enabled

    # ── Hooks (opzionali, override in sottoclassi) ────────────────────

    def startup(self) -> None:
        """Chiamato all'avvio. Inizializza risorse del plugin."""
        pass

    def shutdown(self) -> None:
        """Chiamato allo spegnimento. Libera risorse."""
        pass

    def register_routes(self, app: "Flask") -> None:
        """Registra route Flask aggiuntive."""
        pass

    def register_web_ui(self) -> dict:
        """
        Ritorna dati per integrare il plugin nella Web UI.
        Formato:
        {
          "nav_label": "Ordini",
          "nav_icon": "📦",
          "page_id": "orders",
          "html": "<div>...</div>",
          "js": "function loadOrders() {...}",
          "api_routes": ["/api/orders"]
        }
        """
        return {}

    def on_telegram_message(self, text: str, chat_id: int) -> Optional[str]:
        """
        Gestisce un messaggio Telegram. Ritorna risposta o None
        (None = il messaggio non e' per questo plugin).
        """
        return None

    def on_whatsapp_message(self, text: str, phone: str) -> Optional[str]:
        """Gestisce un messaggio WhatsApp."""
        return None

    def on_schedule(self) -> None:
        """Eseguito periodicamente se 'schedule' e' in manifest.hooks."""
        pass

    def on_feature_request(self, request: dict) -> Optional[str]:
        """
        Intercetta una feature request prima della classificazione AI.
        Ritorna override del livello ('auto'/'review'/'block') o None.
        """
        return None

    # ── Info ──────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "enabled": self._enabled,
            "error": self._error,
        }

    def __repr__(self) -> str:
        return f"<Plugin {self.id} v{self.version}>"

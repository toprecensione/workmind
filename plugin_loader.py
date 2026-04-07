"""
WorkMind Plugin Loader
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Carica dinamicamente i plugin abilitati da data/plugins_enabled.json.
Ogni plugin registra i suoi hook (routes Flask, comandi Telegram, ecc.)
senza modificare il core.

plugins_enabled.json esempio:
{
  "whatsapp": "1.2.0",
  "feature_requests": "latest",
  "voice_telegram": "latest",
  "orders": "1.0.0"
}
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from config.settings import DATA_DIR
from logging_system import get_logger, LogAction, LogStatus

if TYPE_CHECKING:
    from flask import Flask
    from plugins.base import PluginBase

log = get_logger("plugin_loader")

_PLUGINS_CONFIG = DATA_DIR / "plugins_enabled.json"
_PLUGINS_DIR = Path(__file__).parent / "plugins"

# Registry globale plugin caricati
_loaded: dict[str, "PluginBase"] = {}


# ── Loader ───────────────────────────────────────────────────────────────────

def load_plugins() -> list["PluginBase"]:
    """
    Carica tutti i plugin abilitati. Da chiamare una sola volta all'avvio.
    Ritorna lista di plugin inizializzati.
    """
    global _loaded
    enabled = _read_enabled_list()

    for plugin_id, version in enabled.items():
        if plugin_id in _loaded:
            continue
        try:
            plugin = _load_single(plugin_id, version)
            if plugin:
                _loaded[plugin_id] = plugin
                log.info(f"Plugin caricato: {plugin_id} v{plugin.version}",
                         action=LogAction.STARTUP, status=LogStatus.OK)
        except Exception as exc:
            log.warning(f"Plugin {plugin_id} non caricato: {exc}",
                        action=LogAction.STARTUP)
            if log.isEnabledFor(10):  # DEBUG
                traceback.print_exc()

    log.info(f"Plugin attivi: {list(_loaded.keys())}",
             action=LogAction.STARTUP, status=LogStatus.OK)
    return list(_loaded.values())


def _load_single(plugin_id: str, version: str) -> Optional["PluginBase"]:
    """Carica un singolo plugin dal modulo corrispondente."""
    # Prova prima plugins.<id>.<id>_plugin, poi plugins.<id>
    candidates = [
        f"plugins.{plugin_id}.plugin",
        f"plugins.{plugin_id}",
    ]
    for module_path in candidates:
        try:
            mod = importlib.import_module(module_path)
            # Cerca classe Plugin<Id> o Plugin
            cls_name = f"Plugin{plugin_id.replace('_', ' ').title().replace(' ', '')}"
            cls = getattr(mod, cls_name, None) or getattr(mod, "Plugin", None)
            if cls:
                return cls()
        except ModuleNotFoundError:
            continue
        except Exception as exc:
            raise RuntimeError(f"Errore caricamento {module_path}: {exc}") from exc
    raise ModuleNotFoundError(f"Plugin '{plugin_id}' non trovato in {_PLUGINS_DIR}")


# ── Hooks ────────────────────────────────────────────────────────────────────

def startup_all() -> None:
    """Chiama startup() su tutti i plugin caricati."""
    for p in _loaded.values():
        try:
            p.startup()
        except Exception as exc:
            log.warning(f"Plugin {p.id} startup error: {exc}", action=LogAction.STARTUP)


def shutdown_all() -> None:
    """Chiama shutdown() su tutti i plugin."""
    for p in _loaded.values():
        try:
            p.shutdown()
        except Exception:
            pass


def register_routes_all(app: "Flask") -> None:
    """Registra le route Flask di tutti i plugin."""
    for p in _loaded.values():
        try:
            if "web_routes" in (p.MANIFEST.hooks if p.MANIFEST else []):
                p.register_routes(app)
        except Exception as exc:
            log.warning(f"Plugin {p.id} register_routes error: {exc}",
                        action=LogAction.STARTUP)


def dispatch_telegram(text: str, chat_id: int) -> Optional[str]:
    """
    Gira il messaggio Telegram a tutti i plugin.
    Ritorna la prima risposta non-None.
    """
    for p in _loaded.values():
        try:
            result = p.on_telegram_message(text, chat_id)
            if result is not None:
                return result
        except Exception:
            pass
    return None


def dispatch_whatsapp(text: str, phone: str) -> Optional[str]:
    """Gira il messaggio WhatsApp a tutti i plugin."""
    for p in _loaded.values():
        try:
            result = p.on_whatsapp_message(text, phone)
            if result is not None:
                return result
        except Exception:
            pass
    return None


def run_scheduled() -> None:
    """Chiama on_schedule() sui plugin che hanno hook 'schedule'."""
    for p in _loaded.values():
        if p.MANIFEST and "schedule" in p.MANIFEST.hooks:
            try:
                p.on_schedule()
            except Exception as exc:
                log.warning(f"Plugin {p.id} schedule error: {exc}",
                            action=LogAction.MONITOR)


def get_web_ui_extensions() -> list[dict]:
    """Raccoglie le estensioni Web UI da tutti i plugin."""
    extensions = []
    for p in _loaded.values():
        try:
            ext = p.register_web_ui()
            if ext:
                ext["plugin_id"] = p.id
                extensions.append(ext)
        except Exception:
            pass
    return extensions


# ── Plugin Management ────────────────────────────────────────────────────────

def get_loaded() -> dict[str, "PluginBase"]:
    return dict(_loaded)


def get_plugin(plugin_id: str) -> Optional["PluginBase"]:
    return _loaded.get(plugin_id)


def enable_plugin(plugin_id: str, version: str = "latest") -> bool:
    """Abilita un plugin (lo aggiunge a plugins_enabled.json)."""
    enabled = _read_enabled_list()
    enabled[plugin_id] = version
    _write_enabled_list(enabled)
    return True


def disable_plugin(plugin_id: str) -> bool:
    """Disabilita un plugin."""
    enabled = _read_enabled_list()
    if plugin_id in enabled:
        # Non si puo' disabilitare plugin core
        if plugin_id in ("feature_requests",):
            return False
        del enabled[plugin_id]
        _write_enabled_list(enabled)
        if plugin_id in _loaded:
            try:
                _loaded[plugin_id].shutdown()
            except Exception:
                pass
            del _loaded[plugin_id]
        return True
    return False


def list_available() -> list[dict]:
    """Elenca tutti i plugin disponibili nella cartella plugins/."""
    available = []
    for path in sorted(_PLUGINS_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        manifest_path = path / "manifest.json"
        if manifest_path.exists():
            try:
                from plugins.base import PluginManifest
                m = PluginManifest.from_file(manifest_path)
                enabled = _read_enabled_list()
                available.append({
                    "id": m.id,
                    "name": m.name,
                    "version": m.version,
                    "description": m.description,
                    "category": m.category,
                    "installed": m.id in _loaded,
                    "enabled": m.id in enabled,
                })
            except Exception:
                available.append({"id": path.name, "name": path.name,
                                  "installed": False, "enabled": False})
    return available


def status_all() -> list[dict]:
    """Stato di tutti i plugin caricati."""
    return [p.status() for p in _loaded.values()]


# ── Config Helpers ────────────────────────────────────────────────────────────

def _read_enabled_list() -> dict:
    """Legge plugins_enabled.json. Default: feature_requests e voice_telegram."""
    if _PLUGINS_CONFIG.exists():
        try:
            return json.loads(_PLUGINS_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Default: plugin fondamentali sempre attivi
    defaults = {
        "feature_requests": "latest",
        "voice_telegram": "latest",
        "whatsapp": "latest",
        "telegram_notifications": "latest",
        "backup": "latest",
    }
    _write_enabled_list(defaults)
    return defaults


def _write_enabled_list(data: dict) -> None:
    _PLUGINS_CONFIG.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

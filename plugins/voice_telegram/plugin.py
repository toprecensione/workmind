"""Voice Telegram Plugin — trascrizione vocali già integrata in telegram_bot.py."""
from __future__ import annotations
from plugins.base import PluginBase, PluginManifest
from pathlib import Path

class PluginVoiceTelegram(PluginBase):
    MANIFEST = PluginManifest.from_file(Path(__file__).parent / "manifest.json")
    # Funzionalita' gia' implementata direttamente in WorkMindTelegramBot._handle_voice()
    # Questo plugin serve come marker per abilitazione/disabilitazione via plugins_enabled.json

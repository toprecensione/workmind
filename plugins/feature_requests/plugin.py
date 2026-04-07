"""Feature Request Pipeline Plugin — wrapper del modulo mindwork.feature_requests."""
from __future__ import annotations
from plugins.base import PluginBase, PluginManifest
from pathlib import Path

class PluginFeatureRequests(PluginBase):
    MANIFEST = PluginManifest.from_file(Path(__file__).parent / "manifest.json")

    def startup(self):
        from mindwork.feature_requests import get_feature_manager
        get_feature_manager()  # inizializza singleton

    def on_telegram_message(self, text: str, chat_id: int):
        # I comandi /request /approve /reject /master /requests
        # sono gestiti direttamente in telegram_bot.py — nessun dispatch necessario
        return None

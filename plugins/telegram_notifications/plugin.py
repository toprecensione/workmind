"""Telegram Notifications Plugin."""
from __future__ import annotations
from plugins.base import PluginBase, PluginManifest
from pathlib import Path

class PluginTelegramNotifications(PluginBase):
    MANIFEST = PluginManifest.from_file(Path(__file__).parent / "manifest.json")

    def startup(self):
        from interface.telegram_notifications import get_notifier
        self._notifier = get_notifier()
        self._notifier.start()

    def shutdown(self):
        if hasattr(self, "_notifier"):
            self._notifier.stop()

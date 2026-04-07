"""WhatsApp Business Plugin — wrapper di interface.whatsapp_bot."""
from __future__ import annotations
from plugins.base import PluginBase, PluginManifest
from pathlib import Path

class PluginWhatsapp(PluginBase):
    MANIFEST = PluginManifest.from_file(Path(__file__).parent / "manifest.json")

    def startup(self):
        from interface.whatsapp_bot import get_whatsapp_bot
        self._bot = get_whatsapp_bot()

    def register_routes(self, app):
        from interface.whatsapp_bot import get_whatsapp_bot
        get_whatsapp_bot().register_routes(app)

    def on_whatsapp_message(self, text: str, phone: str):
        # Gestione delegata a WhatsAppBot._handle_incoming via webhook
        return None

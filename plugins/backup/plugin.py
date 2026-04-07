"""Automatic Backup Plugin."""
from __future__ import annotations
from plugins.base import PluginBase, PluginManifest
from pathlib import Path

class PluginBackup(PluginBase):
    MANIFEST = PluginManifest.from_file(Path(__file__).parent / "manifest.json")

    def startup(self):
        from storage.backup import get_backup_manager
        self._mgr = get_backup_manager()
        self._mgr.start(interval_hours=24)

    def shutdown(self):
        if hasattr(self, "_mgr"):
            self._mgr.stop()

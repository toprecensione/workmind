"""
WorkMind Telegram Notifications — Notifiche Proattive
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Invia notifiche push via Telegram quando rileva anomalie,
nuovi documenti, pattern o per il riepilogo giornaliero.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from config.settings import DATA_DIR
from storage.audit_trail import get_audit, AuditEventType
from ai_client.budget import get_budget
from storage.knowledge_base import get_kb
from mindwork.feedback import get_feedback
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("interface.telegram_notifications")

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_SUBSCRIBERS_FILE = DATA_DIR / "telegram_subscribers.json"
_CHECK_INTERVAL = 60  # secondi


class TelegramNotifier:
    def __init__(self) -> None:
        self._token = _TG_TOKEN
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_audit_hash = ""
        self._muted_chats: set[int] = set()
        self._subscribers = self._load_subscribers()
        self._last_daily_date = ""

    # ── Subscriber management ─────────────────────────────────────────────

    def _load_subscribers(self) -> list[int]:
        if _SUBSCRIBERS_FILE.exists():
            try:
                return json.loads(_SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_subscribers(self) -> None:
        _SUBSCRIBERS_FILE.write_text(
            json.dumps(list(set(self._subscribers)), indent=2),
            encoding="utf-8",
        )

    def subscribe(self, chat_id: int) -> str:
        if chat_id not in self._subscribers:
            self._subscribers.append(chat_id)
            self._save_subscribers()
            return "Iscritto alle notifiche!"
        return "Sei gia' iscritto."

    def unsubscribe(self, chat_id: int) -> str:
        if chat_id in self._subscribers:
            self._subscribers.remove(chat_id)
            self._save_subscribers()
            return "Disiscritto dalle notifiche."
        return "Non eri iscritto."

    def mute(self, chat_id: int) -> str:
        self._muted_chats.add(chat_id)
        return "Notifiche in pausa. Usa /unmute per riattivare."

    def unmute(self, chat_id: int) -> str:
        self._muted_chats.discard(chat_id)
        return "Notifiche riattivate!"

    # ── Sending ───────────────────────────────────────────────────────────

    def notify(self, message: str) -> None:
        """Invia messaggio a tutti i subscriber attivi."""
        if not self._token:
            return
        api = f"https://api.telegram.org/bot{self._token}"
        try:
            with httpx.Client(timeout=10) as client:
                for cid in self._subscribers:
                    if cid in self._muted_chats:
                        continue
                    try:
                        client.post(f"{api}/sendMessage", json={
                            "chat_id": cid, "text": message, "parse_mode": "Markdown",
                        })
                    except Exception:
                        pass
        except Exception as exc:
            log.warning(f"Errore invio notifica: {exc}", action=LogAction.MONITOR)

    def notify_anomaly(self, summary: str, details: dict | None = None) -> None:
        msg = f"*⚠ Anomalia rilevata*\n\n{summary}"
        if details:
            for k, v in list(details.items())[:5]:
                msg += f"\n- {k}: {v}"
        self.notify(msg)

    def notify_new_document(self, doc_name: str, doc_type: str = "") -> None:
        self.notify(f"*📄 Nuovo documento analizzato*\n\n`{doc_name}`\nTipo: {doc_type or 'N/D'}")

    def send_daily_summary(self) -> None:
        """Invia il riepilogo giornaliero."""
        try:
            kb = get_kb().summary()
            budget = get_budget().daily_summary()
            fb = get_feedback().stats()
            ds = budget.get("deepseek", {})
            cl = budget.get("claude", {})

            msg = (
                f"*📊 Riepilogo giornaliero WorkMind*\n"
                f"_{datetime.now(timezone.utc).strftime('%d/%m/%Y')}_\n\n"
                f"*Knowledge Base:* {kb['facts']} fatti, {kb['corrections']} correzioni\n"
                f"*Budget AI:* ${(ds.get('cost_usd', 0) + cl.get('cost_usd', 0)):.4f}\n"
                f"  DeepSeek: {ds.get('calls', 0)} calls\n"
                f"  Claude: {cl.get('calls', 0)} calls\n"
                f"*Feedback:* {fb['total']} totali, accuratezza {fb['accuracy_rate']:.0%}"
            )
            self.notify(msg)
        except Exception as exc:
            log.warning(f"Errore riepilogo giornaliero: {exc}", action=LogAction.MONITOR)

    # ── Background loop ───────────────────────────────────────────────────

    def start(self) -> None:
        if not self._token:
            log.warning("TELEGRAM_BOT_TOKEN non configurato — notifiche disabilitate",
                        action=LogAction.STARTUP)
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TGNotifier")
        self._thread.start()
        log.info("Telegram notifier avviato", action=LogAction.STARTUP, status=LogStatus.OK)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self._check_new_events()
                self._check_daily_summary()
            except Exception:
                pass
            for _ in range(_CHECK_INTERVAL):
                if not self._running:
                    return
                time.sleep(1)

    def _check_new_events(self) -> None:
        """Controlla audit trail per nuovi eventi da notificare."""
        audit = get_audit()
        recent = audit.recent(10)
        if not recent:
            return

        latest_hash = recent[0].get("hash", "")
        if latest_hash == self._last_audit_hash:
            return  # Nessun evento nuovo

        # Processa solo i nuovi
        new_events = []
        for event in recent:
            if event.get("hash") == self._last_audit_hash:
                break
            new_events.append(event)

        self._last_audit_hash = latest_hash

        for event in reversed(new_events):
            etype = event.get("event_type", "")
            if etype == str(AuditEventType.ANOMALY):
                self.notify_anomaly(event.get("summary", ""), event.get("details"))

    def _check_daily_summary(self) -> None:
        """Invia riepilogo alle 22:00."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if today != self._last_daily_date and now.hour >= 20:
            self._last_daily_date = today
            self.send_daily_summary()


# ─── Singleton ────────────────────────────────────────────────────────────────

_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier

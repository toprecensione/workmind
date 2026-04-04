"""
WorkMind Telegram Bot
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Bot Telegram che permette al supervisore di chattare con WorkMind
da qualsiasi luogo. Usa la stessa logica della chat web.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from typing import Optional

import httpx

from ai_client.client import get_ai_client, AIMessage, ModelRole
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit, AuditEventType
from ai_client.budget import get_budget
from config.company import get_company_config
from mindwork.feedback import get_feedback
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("interface.telegram")

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8349603082:AAH_-ks3h8xLPCu41T1-BXJGZU2w8Pde0_k")
_TG_API = f"https://api.telegram.org/bot{_TG_TOKEN}"


class WorkMindTelegramBot:
    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._kb = get_kb()
        self._budget = get_budget()
        self._company = get_company_config()
        self._feedback = get_feedback()
        self._audit = get_audit()
        self._running = False
        self._offset = 0
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not _TG_TOKEN:
            log.warning("TELEGRAM_BOT_TOKEN non configurato", action=LogAction.STARTUP)
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TelegramBot")
        self._thread.start()
        log.info("Telegram bot avviato", action=LogAction.STARTUP, status=LogStatus.OK)

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        while self._running:
            try:
                with httpx.Client(timeout=35) as client:
                    resp = client.get(f"{_TG_API}/getUpdates", params={
                        "offset": self._offset, "timeout": 30, "allowed_updates": '["message"]'
                    })
                    if resp.status_code != 200:
                        time.sleep(5)
                        continue
                    data = resp.json()
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")
                        chat_id = msg.get("chat", {}).get("id")
                        if text and chat_id:
                            reply = self._handle(text)
                            self._send(client, chat_id, reply)
            except Exception:
                time.sleep(5)

    def _send(self, client: httpx.Client, chat_id: int, text: str) -> None:
        try:
            client.post(f"{_TG_API}/sendMessage", json={
                "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
            })
        except Exception:
            pass

    def _handle(self, text: str) -> str:
        text = text.strip()
        if text.startswith("/start"):
            return f"Ciao! Sono WorkMind, l'assistente operativo di *{self._company.name}*.\n\nComandi:\n/status - Stato bot\n/budget - Spesa AI\n/teach <fatto> - Insegna\n/help - Aiuto\n\nOppure scrivimi una domanda!"

        if text.startswith("/status"):
            kb = self._kb.summary()
            fb = self._feedback.stats()
            return (
                f"*WorkMind - {self._company.name}*\n\n"
                f"KB: {kb['facts']} fatti, {kb['corrections']} correzioni\n"
                f"Feedback: {fb['total']} ({fb['confirmed']} ok, {fb['corrected']} corretti)\n"
                f"Accuratezza: {fb['accuracy_rate']:.0%}"
            )

        if text.startswith("/budget"):
            b = self._budget.daily_summary()
            ds = b.get("deepseek", {})
            cl = b.get("claude", {})
            return (
                f"*Budget AI oggi*\n"
                f"DeepSeek: ${ds.get('cost_usd', 0):.4f} ({ds.get('calls', 0)} calls)\n"
                f"Claude: ${cl.get('cost_usd', 0):.4f} ({cl.get('calls', 0)} calls)"
            )

        if text.startswith("/teach "):
            fact = text[7:].strip()
            if fact:
                self._kb.teach_fact(fact, taught_by="telegram")
                return f"Memorizzato: _{fact}_"
            return "Uso: /teach <fatto>"

        if text.startswith("/help"):
            return (
                "*Comandi WorkMind*\n\n"
                "/status - Stato del bot\n"
                "/budget - Spesa AI giornaliera\n"
                "/teach <fatto> - Insegna un fatto\n"
                "/help - Questo messaggio\n\n"
                "Oppure scrivi una domanda in linguaggio naturale!"
            )

        # Chat libera con DeepSeek
        try:
            context = self._kb.build_context_prompt()
            system = (
                f"Sei WorkMind, assistente operativo di {self._company.name}. "
                f"Rispondi in italiano, in modo conciso (max 500 caratteri). "
                f"Stai rispondendo via Telegram.\n"
            )
            if context:
                system += f"\n{context}\n"

            response = self._ai.complete_simple(
                text, system_prompt=system, role=ModelRole.FAST,
                max_tokens=300, temperature=0.3,
            )
            return response
        except Exception as exc:
            return f"Errore: {exc}"

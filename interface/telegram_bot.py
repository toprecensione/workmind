"""
WorkMind Telegram Bot
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Bot Telegram che permette al supervisore di chattare con WorkMind
da qualsiasi luogo. Usa la stessa logica della chat web.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
import traceback
from typing import Optional

import httpx

try:
    import speech_recognition as sr
    _HAS_SR = True
except ImportError:
    _HAS_SR = False

try:
    from pydub import AudioSegment
    _HAS_PYDUB = True
except ImportError:
    _HAS_PYDUB = False

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
        self._notifier = None

    def _get_notifier(self):
        if self._notifier is None:
            try:
                from interface.telegram_notifications import get_notifier
                self._notifier = get_notifier()
            except Exception:
                pass
        return self._notifier

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
                        chat_id = msg.get("chat", {}).get("id")
                        if not chat_id:
                            continue
                        # Voice messages (voice or video_note)
                        voice = msg.get("voice") or msg.get("voice_note")
                        if voice:
                            reply = self._handle_voice(client, voice)
                            self._send(client, chat_id, reply)
                            continue
                        # Text messages
                        text = msg.get("text", "")
                        if text:
                            reply = self._handle(text, chat_id)
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

    # ---- Voice message handling ------------------------------------------------

    def _handle_voice(self, client: httpx.Client, voice: dict) -> str:
        """Download a Telegram voice message, transcribe it via speech_recognition, then process as text."""
        if not _HAS_SR or not _HAS_PYDUB:
            return (
                "Non posso trascrivere messaggi vocali: librerie mancanti "
                "(speech_recognition e/o pydub). Installa con:\n"
                "`pip install SpeechRecognition pydub`\n"
                "e assicurati che ffmpeg sia nel PATH."
            )

        file_id = voice.get("file_id")
        if not file_id:
            return "Errore: messaggio vocale senza file_id."

        try:
            transcription = self._transcribe_voice(client, file_id)
        except Exception as exc:
            log.error(f"Trascrizione vocale fallita: {exc}", action=LogAction.STARTUP)
            return f"Non sono riuscito a trascrivere il messaggio vocale.\nErrore: {exc}"

        # Process transcribed text through the normal handler
        reply = self._handle(transcription)
        return f"🎤 _{transcription}_\n\n{reply}"

    def _transcribe_voice(self, client: httpx.Client, file_id: str) -> str:
        """Download .ogg from Telegram, convert to .wav, transcribe with Google STT."""
        # Step 1: get file path from Telegram
        resp = client.get(f"{_TG_API}/getFile", params={"file_id": file_id})
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        # Step 2: download the file bytes
        download_url = f"https://api.telegram.org/file/bot{_TG_TOKEN}/{file_path}"
        dl_resp = client.get(download_url)
        dl_resp.raise_for_status()
        ogg_bytes = dl_resp.content

        # Step 3: convert .ogg -> .wav using pydub (requires ffmpeg)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_f:
            ogg_f.write(ogg_bytes)
            ogg_path = ogg_f.name

        try:
            wav_path = ogg_path.replace(".ogg", ".wav")
            audio_seg = AudioSegment.from_ogg(ogg_path)
            audio_seg.export(wav_path, format="wav")
        finally:
            try:
                os.unlink(ogg_path)
            except OSError:
                pass

        # Step 4: transcribe with speech_recognition (Google free STT, Italian)
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="it-IT")
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

        if not text or not text.strip():
            raise ValueError("La trascrizione è vuota.")
        return text.strip()

    # ---- Text message handling -------------------------------------------------

    def _handle(self, text: str, chat_id: int = 0) -> str:
        text = text.strip()
        if text.startswith("/start"):
            # Auto-subscribe alle notifiche
            notifier = self._get_notifier()
            if notifier and chat_id:
                notifier.subscribe(chat_id)
            return (
                f"Ciao! Sono WorkMind, l'assistente operativo di *{self._company.name}*.\n\n"
                f"Comandi:\n/status - Stato bot\n/budget - Spesa AI\n"
                f"/teach <fatto> - Insegna\n/subscribe - Notifiche\n"
                f"/unsubscribe - Disattiva notifiche\n/mute - Pausa notifiche\n"
                f"/unmute - Riprendi notifiche\n/help - Aiuto\n\n"
                f"Oppure scrivimi una domanda o invia un vocale!"
            )

        if text.startswith("/subscribe"):
            notifier = self._get_notifier()
            return notifier.subscribe(chat_id) if notifier and chat_id else "Notifiche non disponibili."

        if text.startswith("/unsubscribe"):
            notifier = self._get_notifier()
            return notifier.unsubscribe(chat_id) if notifier and chat_id else "Notifiche non disponibili."

        if text.startswith("/mute"):
            notifier = self._get_notifier()
            return notifier.mute(chat_id) if notifier and chat_id else "Notifiche non disponibili."

        if text.startswith("/unmute"):
            notifier = self._get_notifier()
            return notifier.unmute(chat_id) if notifier and chat_id else "Notifiche non disponibili."

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
                try:
                    from storage.vector_store import get_vector_store
                    get_vector_store().index_fact(fact, source="telegram")
                except Exception:
                    pass
                try:
                    from storage.mem0_store import get_mem0
                    get_mem0().add_fact(fact, source="telegram")
                except Exception:
                    pass
                return f"Memorizzato: _{fact}_"
            return "Uso: /teach <fatto>"

        if text.startswith("/help"):
            return (
                "*Comandi WorkMind*\n\n"
                "/status - Stato del bot\n"
                "/budget - Spesa AI giornaliera\n"
                "/teach <fatto> - Insegna un fatto\n"
                "/subscribe - Attiva notifiche proattive\n"
                "/unsubscribe - Disattiva notifiche\n"
                "/mute / /unmute - Pausa notifiche\n"
                "/help - Questo messaggio\n\n"
                "Puoi anche inviare messaggi vocali!"
            )

        # Chat libera con DeepSeek (RAG + Supermemory enhanced)
        try:
            context = self._kb.build_context_prompt()
            rag_context = ""
            try:
                from storage.vector_store import get_vector_store
                rag_context = get_vector_store().build_rag_context(text)
            except Exception:
                pass

            # Mem0: memoria avanzata locale
            memory_context = ""
            try:
                from storage.mem0_store import get_mem0
                mem = get_mem0()
                if mem.available:
                    user_id = f"tg_{chat_id}" if chat_id else "telegram"
                    memory_context = mem.build_memory_context(text, user_id=user_id)
            except Exception:
                pass

            system = (
                f"Sei WorkMind, assistente operativo di {self._company.name}. "
                f"Rispondi in italiano, in modo conciso (max 500 caratteri). "
                f"Stai rispondendo via Telegram.\n"
            )
            if memory_context:
                system += f"\n{memory_context}\n"
            if rag_context:
                system += f"\n{rag_context}\n"
            if context:
                system += f"\n{context}\n"

            response = self._ai.complete_simple(
                text, system_prompt=system, role=ModelRole.FAST,
                max_tokens=300, temperature=0.3,
            )

            # Salva conversazione in Mem0 (background)
            try:
                from storage.mem0_store import get_mem0
                mem = get_mem0()
                if mem.available:
                    import threading as _t
                    _t.Thread(
                        target=mem.add_conversation,
                        args=(text, response),
                        kwargs={"user_id": f"tg_{chat_id}" if chat_id else "telegram"},
                        daemon=True,
                    ).start()
            except Exception:
                pass

            return response
        except Exception as exc:
            return f"Errore: {exc}"

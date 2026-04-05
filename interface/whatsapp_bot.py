"""
WorkMind WhatsApp Business Bot
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Integrazione WhatsApp Business Cloud API per:
- Comunicazione bidirezionale con clienti/terzi
- Gestione ordini con conferma
- Privacy e consenso GDPR (opt-in/opt-out)
- Stessi comandi del bot Telegram (/status, /teach, /request, ecc.)
- Rate limiting e policy configurabili

Richiede:
- WHATSAPP_TOKEN (token Meta Business API)
- WHATSAPP_PHONE_ID (ID del numero di telefono registrato)
- WHATSAPP_VERIFY_TOKEN (token verifica webhook)
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from ai_client.client import get_ai_client, ModelRole
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit, AuditEventType
from ai_client.budget import get_budget
from config.company import get_company_config
from config.settings import DATA_DIR
from mindwork.feedback import get_feedback
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("interface.whatsapp")

_WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
_WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
_WA_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "workmind_verify_2024")
_WA_API = "https://graph.facebook.com/v21.0"

# Contatti e conversazioni in corso
_CONVERSATIONS_FILE = DATA_DIR / "whatsapp_conversations.json"
_CONTACTS_FILE = DATA_DIR / "whatsapp_contacts.json"

# Ordini in attesa di conferma
_ORDERS_FILE = DATA_DIR / "whatsapp_orders.json"


class WorkMindWhatsAppBot:
    """Bot WhatsApp Business con gestione ordini e privacy."""

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._kb = get_kb()
        self._budget = get_budget()
        self._company = get_company_config()
        self._feedback = get_feedback()
        self._audit = get_audit()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._contacts = self._load_json(_CONTACTS_FILE, {})
        self._orders = self._load_json(_ORDERS_FILE, [])
        self._policy = None  # Lazy loaded

    def _get_policy(self):
        if self._policy is None:
            from interface.whatsapp_policy import get_wa_policy
            self._policy = get_wa_policy()
        return self._policy

    # ── Flask Webhook Routes (chiamato da web_ui) ────────────────────────

    def register_routes(self, app) -> None:
        """Registra le route webhook su Flask app."""
        from flask import request as flask_request, jsonify

        @app.route("/webhook/whatsapp", methods=["GET"])
        def wa_verify():
            """Verifica webhook Meta (challenge)."""
            mode = flask_request.args.get("hub.mode")
            token = flask_request.args.get("hub.verify_token")
            challenge = flask_request.args.get("hub.challenge")
            if mode == "subscribe" and token == _WA_VERIFY_TOKEN:
                log.info("WhatsApp webhook verificato", action=LogAction.STARTUP, status=LogStatus.OK)
                return challenge, 200
            return "Forbidden", 403

        @app.route("/webhook/whatsapp", methods=["POST"])
        def wa_webhook():
            """Riceve messaggi da WhatsApp."""
            data = flask_request.get_json(silent=True) or {}
            # Processa in background per rispondere entro 20s a Meta
            threading.Thread(
                target=self._process_webhook, args=(data,), daemon=True
            ).start()
            return "OK", 200

        # API per gestione WhatsApp dalla Web UI
        @app.route("/api/whatsapp/contacts")
        def wa_contacts():
            return jsonify({"contacts": list(self._contacts.values())})

        @app.route("/api/whatsapp/orders")
        def wa_orders():
            return jsonify({"orders": list(reversed(self._orders[-50:]))})

        @app.route("/api/whatsapp/send", methods=["POST"])
        def wa_send_api():
            d = flask_request.get_json(silent=True) or {}
            phone = d.get("phone", "")
            text = d.get("text", "")
            if not phone or not text:
                return jsonify({"ok": False, "error": "phone e text richiesti"})
            ok = self.send_message(phone, text)
            return jsonify({"ok": ok})

        @app.route("/api/whatsapp/policy")
        def wa_policy_get():
            return jsonify(self._get_policy().get_order_policy())

        @app.route("/api/whatsapp/policy", methods=["POST"])
        def wa_policy_update():
            d = flask_request.get_json(silent=True) or {}
            updated = self._get_policy().update_policy(d)
            return jsonify({"ok": True, "policy": updated})

        @app.route("/api/whatsapp/stats")
        def wa_stats():
            policy = self._get_policy()
            from interface.whatsapp_policy import ConsentType
            return jsonify({
                "total_contacts": len(self._contacts),
                "consented_chat": len(policy.get_all_consented(ConsentType.CHAT)),
                "consented_orders": len(policy.get_all_consented(ConsentType.ORDERS)),
                "total_orders": len(self._orders),
                "pending_orders": sum(1 for o in self._orders if o.get("status") == "pending"),
            })

    # ── Webhook Processing ───────────────────────────────────────────────

    def _process_webhook(self, data: dict) -> None:
        """Processa webhook da Meta (in background thread)."""
        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    contacts = value.get("contacts", [])

                    # Aggiorna contatti
                    for contact in contacts:
                        wa_id = contact.get("wa_id", "")
                        name = contact.get("profile", {}).get("name", "")
                        if wa_id:
                            self._update_contact(wa_id, name)

                    # Processa messaggi
                    for msg in messages:
                        self._handle_incoming(msg)

                    # Status updates (delivered, read, etc.)
                    statuses = value.get("statuses", [])
                    for status in statuses:
                        self._handle_status(status)

        except Exception as exc:
            log.error(f"Errore processing webhook WhatsApp: {exc}", action=LogAction.MONITOR)

    def _handle_incoming(self, msg: dict) -> None:
        """Gestisce un messaggio in arrivo."""
        msg_type = msg.get("type", "")
        phone = msg.get("from", "")
        if not phone:
            return

        policy = self._get_policy()

        # Testo del messaggio
        text = ""
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "interactive":
            # Bottoni interattivi
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("id", "")
            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("id", "")
        elif msg_type == "image":
            text = msg.get("image", {}).get("caption", "[immagine]")
        elif msg_type == "document":
            text = f"[documento: {msg.get('document', {}).get('filename', '?')}]"
        elif msg_type == "audio":
            text = "[messaggio vocale]"
        elif msg_type == "location":
            loc = msg.get("location", {})
            text = f"[posizione: {loc.get('latitude')}, {loc.get('longitude')}]"
        else:
            text = f"[{msg_type}]"

        if not text:
            return

        log.info(f"WA msg da {policy._mask_phone(phone)}: {text[:100]}",
                 action=LogAction.MONITOR, status=LogStatus.OK)

        # 1. Controlla opt-out keywords
        text_lower = text.strip().lower()
        if text_lower in policy.opt_out_keywords():
            policy.revoke_consent(phone)
            self.send_message(phone,
                "Hai revocato il consenso. Non riceverai piu' messaggi.\n"
                "Per riattivare, invia un messaggio qualsiasi."
            )
            self._audit.record(
                AuditEventType.FEEDBACK,
                f"WhatsApp opt-out: {policy._mask_phone(phone)}",
                actor=phone,
            )
            return

        # 2. Controlla se ha consenso CHAT, altrimenti chiedi
        from interface.whatsapp_policy import ConsentType
        if not policy.has_consent(phone, ConsentType.CHAT):
            # Risposte al messaggio di consenso
            if text_lower in ("si", "sì", "ok", "accetto", "yes"):
                policy.grant_consent(phone, ConsentType.CHAT)
                self.send_message(phone,
                    f"Grazie! Consenso registrato.\n\n"
                    f"Sono l'assistente di *{self._company.name}*.\n"
                    f"Scrivi /help per i comandi, oppure chiedimi qualcosa!"
                )
                return
            elif text_lower in ("ordini", "orders", "📦"):
                policy.grant_consent(phone, ConsentType.CHAT)
                policy.grant_consent(phone, ConsentType.ORDERS)
                self.send_message(phone,
                    f"Perfetto! Consenso per chat e ordini registrato.\n\n"
                    f"Sono l'assistente di *{self._company.name}*.\n"
                    f"Scrivi /ordine per iniziare un ordine, oppure chiedimi qualcosa!"
                )
                return
            elif text_lower in ("no", "non voglio", "rifiuto"):
                self.send_message(phone, "OK, non riceverai messaggi. Se cambi idea, scrivici di nuovo.")
                return
            else:
                # Primo contatto: invia messaggio di consenso
                policy.request_consent(phone, ConsentType.CHAT, context=f"Primo messaggio: {text[:100]}")
                welcome = self._get_policy()._policy.get("consent_message", "")
                self.send_message(phone, welcome)
                return

        # 3. Rate limiting
        if not policy.can_send(phone):
            self.send_message(phone, "Hai raggiunto il limite di messaggi per oggi. Riprova domani.")
            return

        # 4. Gestisci il messaggio
        reply = self._handle_message(text, phone)
        if reply:
            self.send_message(phone, reply)
            policy.record_send(phone)

    def _handle_status(self, status: dict) -> None:
        """Gestisce aggiornamenti di stato (delivered, read, failed)."""
        status_type = status.get("status", "")
        recipient = status.get("recipient_id", "")
        if status_type == "failed":
            errors = status.get("errors", [])
            err_msg = errors[0].get("message", "unknown") if errors else "unknown"
            log.warning(f"WA messaggio fallito per {recipient[:6]}***: {err_msg}",
                        action=LogAction.MONITOR)

    # ── Message Handling ─────────────────────────────────────────────────

    def _handle_message(self, text: str, phone: str) -> str:
        """Gestisce comandi e chat libera."""
        text = text.strip()
        from interface.whatsapp_policy import ConsentType

        # Comandi
        if text.startswith("/help"):
            return self._cmd_help(phone)
        if text.startswith("/status"):
            return self._cmd_status()
        if text.startswith("/ordine") or text.startswith("/order"):
            return self._cmd_new_order(text, phone)
        if text.startswith("/conferma") or text.startswith("/confirm"):
            return self._cmd_confirm_order(text, phone)
        if text.startswith("/annulla"):
            return self._cmd_cancel_order(text, phone)
        if text.startswith("/ordini") or text.startswith("/orders"):
            return self._cmd_list_orders(phone)
        if text.startswith("/consensi") or text.startswith("/privacy"):
            return self._cmd_privacy(phone)
        if text.startswith("/teach "):
            return self._cmd_teach(text)
        if text.startswith("/request "):
            return self._cmd_feature_request(text, phone)

        # Controlla se e' una risposta a un ordine in attesa
        pending = self._get_pending_order(phone)
        if pending:
            return self._process_order_reply(pending, text, phone)

        # Chat libera con AI
        return self._chat(text, phone)

    # ── Commands ─────────────────────────────────────────────────────────

    def _cmd_help(self, phone: str) -> str:
        policy = self._get_policy()
        from interface.whatsapp_policy import ConsentType
        has_orders = policy.has_consent(phone, ConsentType.ORDERS)
        help_text = (
            f"*{self._company.name} — Assistente WhatsApp*\n\n"
            f"*Comandi:*\n"
            f"/help — Questo messaggio\n"
            f"/status — Stato del servizio\n"
            f"/privacy — I tuoi consensi\n"
            f"/teach <fatto> — Insegna qualcosa\n"
            f"/request <idea> — Richiedi funzionalita'\n"
        )
        if has_orders:
            help_text += (
                f"\n*Ordini:*\n"
                f"/ordine <descrizione> — Nuovo ordine\n"
                f"/conferma <id> — Conferma ordine\n"
                f"/annulla <id> — Annulla ordine\n"
                f"/ordini — I tuoi ordini\n"
            )
        help_text += "\nOppure scrivimi una domanda qualsiasi!"
        return help_text

    def _cmd_status(self) -> str:
        kb = self._kb.summary()
        fb = self._feedback.stats()
        return (
            f"*{self._company.name} — Stato*\n\n"
            f"KB: {kb['facts']} fatti, {kb['corrections']} correzioni\n"
            f"Feedback: {fb['total']} ({fb['confirmed']} ok)\n"
            f"Accuratezza: {fb['accuracy_rate']:.0%}"
        )

    def _cmd_teach(self, text: str) -> str:
        fact = text[7:].strip()
        if not fact:
            return "Uso: /teach <fatto>"
        self._kb.teach_fact(fact, taught_by="whatsapp")
        try:
            from storage.vector_store import get_vector_store
            get_vector_store().index_fact(fact, source="whatsapp")
        except Exception:
            pass
        try:
            from storage.mem0_store import get_mem0
            get_mem0().add_fact(fact, source="whatsapp")
        except Exception:
            pass
        return f"Memorizzato: _{fact}_"

    def _cmd_feature_request(self, text: str, phone: str) -> str:
        desc = text[9:].strip()
        if not desc:
            return "Uso: /request <descrizione>"
        try:
            from mindwork.feature_requests import get_feature_manager
            fm = get_feature_manager()
            req = fm.submit_request(desc, submitted_by=f"wa_{phone[-4:]}", source="whatsapp")
            level = req["level"].upper()
            reply = f"*Richiesta #{req['id']}* — {level}\n{req['title']}"
            if req["status"] == "blocked":
                reply += f"\nBloccata: {req['reason']}"
            elif req["status"] == "auto_done":
                reply += "\nEseguita automaticamente!"
            else:
                reply += "\nIn attesa di approvazione."
            return reply
        except Exception as exc:
            return f"Errore: {exc}"

    def _cmd_privacy(self, phone: str) -> str:
        policy = self._get_policy()
        consents = policy.get_consents(phone)
        if not consents:
            return "Nessun consenso registrato."
        lines = ["*I tuoi consensi:*\n"]
        for c in consents:
            icon = "✅" if c["status"] == "granted" else "❌"
            lines.append(f"{icon} {c['type'].upper()} — {c['status']}")
        lines.append("\nInvia STOP per revocare tutti i consensi.")
        return "\n".join(lines)

    # ── Order Management ─────────────────────────────────────────────────

    def _cmd_new_order(self, text: str, phone: str) -> str:
        policy = self._get_policy()
        from interface.whatsapp_policy import ConsentType

        if not policy.has_consent(phone, ConsentType.ORDERS):
            policy.grant_consent(phone, ConsentType.ORDERS)

        if not policy.can_accept_orders(phone):
            return "Gli ordini non sono abilitati al momento."

        desc = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        if not desc:
            return (
                "Per effettuare un ordine, scrivi:\n"
                "/ordine <descrizione prodotto/servizio>\n\n"
                "Esempio:\n/ordine 2x Widget Premium + 1x Manuale"
            )

        order_id = self._next_order_id()
        order = {
            "id": order_id,
            "phone": phone,
            "description": desc,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "confirmed_at": None,
            "cancelled_at": None,
            "notes": "",
        }
        self._orders.append(order)
        self._save_json(_ORDERS_FILE, self._orders)

        self._audit.record(
            AuditEventType.SYSTEM,
            f"WhatsApp ordine #{order_id} creato da {policy._mask_phone(phone)}",
            actor=phone,
            details={"description": desc[:200]},
        )

        order_policy = policy.get_order_policy()
        if order_policy.get("require_confirmation"):
            return (
                f"*Ordine #{order_id}*\n\n"
                f"*Descrizione:* {desc}\n\n"
                f"Per confermare, invia:\n/conferma {order_id}\n\n"
                f"Per annullare:\n/annulla {order_id}"
            )
        else:
            order["status"] = "confirmed"
            order["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            self._save_json(_ORDERS_FILE, self._orders)
            return f"*Ordine #{order_id} confermato!*\n{desc}\n\nVerrai aggiornato sullo stato."

    def _cmd_confirm_order(self, text: str, phone: str) -> str:
        parts = text.split()
        if len(parts) < 2:
            return "Uso: /conferma <id ordine>"
        try:
            order_id = int(parts[1])
        except ValueError:
            return "ID ordine non valido."

        order = self._find_order(order_id)
        if not order:
            return f"Ordine #{order_id} non trovato."
        if order["phone"] != phone:
            return "Non puoi confermare ordini di altri."
        if order["status"] != "pending":
            return f"Ordine #{order_id} non e' in attesa (stato: {order['status']})."

        order["status"] = "confirmed"
        order["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        self._save_json(_ORDERS_FILE, self._orders)

        self._audit.record(
            AuditEventType.FEEDBACK,
            f"WhatsApp ordine #{order_id} confermato",
            actor=phone,
        )

        return (
            f"*Ordine #{order_id} CONFERMATO*\n\n"
            f"{order['description']}\n\n"
            f"Grazie! Riceverai aggiornamenti sullo stato."
        )

    def _cmd_cancel_order(self, text: str, phone: str) -> str:
        parts = text.split()
        if len(parts) < 2:
            return "Uso: /annulla <id ordine>"
        try:
            order_id = int(parts[1])
        except ValueError:
            return "ID ordine non valido."

        order = self._find_order(order_id)
        if not order:
            return f"Ordine #{order_id} non trovato."
        if order["phone"] != phone:
            return "Non puoi annullare ordini di altri."
        if order["status"] not in ("pending", "confirmed"):
            return f"Ordine #{order_id} non puo' essere annullato (stato: {order['status']})."

        order["status"] = "cancelled"
        order["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        self._save_json(_ORDERS_FILE, self._orders)

        self._audit.record(
            AuditEventType.FEEDBACK,
            f"WhatsApp ordine #{order_id} annullato",
            actor=phone,
        )
        return f"*Ordine #{order_id} annullato.*"

    def _cmd_list_orders(self, phone: str) -> str:
        my_orders = [o for o in self._orders if o["phone"] == phone]
        if not my_orders:
            return "Nessun ordine."
        lines = ["*I tuoi ordini:*\n"]
        icons = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌",
                 "shipped": "📦", "delivered": "🎉", "completed": "✓"}
        for o in my_orders[-10:]:
            icon = icons.get(o["status"], "❓")
            lines.append(f"{icon} *#{o['id']}* — {o['description'][:40]} — `{o['status']}`")
        return "\n".join(lines)

    def _get_pending_order(self, phone: str) -> dict | None:
        """Ritorna l'ordine in attesa piu' recente per il contatto."""
        for o in reversed(self._orders):
            if o["phone"] == phone and o["status"] == "pending":
                return o
        return None

    def _process_order_reply(self, order: dict, text: str, phone: str) -> str:
        """Processa risposte a ordini in attesa."""
        text_lower = text.strip().lower()
        if text_lower in ("si", "sì", "ok", "conferma", "confermo", "yes"):
            return self._cmd_confirm_order(f"/conferma {order['id']}", phone)
        elif text_lower in ("no", "annulla", "cancella"):
            return self._cmd_cancel_order(f"/annulla {order['id']}", phone)
        else:
            # Aggiunge nota all'ordine
            order["notes"] = (order.get("notes", "") + "\n" + text).strip()
            self._save_json(_ORDERS_FILE, self._orders)
            return (
                f"Nota aggiunta all'ordine #{order['id']}.\n\n"
                f"Rispondi *si* per confermare o *no* per annullare."
            )

    # ── AI Chat ──────────────────────────────────────────────────────────

    def _chat(self, text: str, phone: str) -> str:
        """Chat libera con AI (RAG + Mem0)."""
        try:
            context = self._kb.build_context_prompt()
            rag_context = ""
            try:
                from storage.vector_store import get_vector_store
                rag_context = get_vector_store().build_rag_context(text)
            except Exception:
                pass

            memory_context = ""
            try:
                from storage.mem0_store import get_mem0
                mem = get_mem0()
                if mem.available:
                    memory_context = mem.build_memory_context(text, user_id=f"wa_{phone[-4:]}")
            except Exception:
                pass

            system = (
                f"Sei l'assistente di {self._company.name} su WhatsApp. "
                f"Rispondi in italiano, conciso (max 400 caratteri). "
                f"Sei gentile e professionale. "
                f"NON condividere dati sensibili di altri clienti.\n"
            )
            if memory_context:
                system += f"\n{memory_context}\n"
            if rag_context:
                system += f"\n{rag_context}\n"
            if context:
                system += f"\n{context}\n"

            response = self._ai.complete_simple(
                text, system_prompt=system, role=ModelRole.FAST,
                max_tokens=250, temperature=0.3,
            )

            # Salva in Mem0 (background)
            try:
                from storage.mem0_store import get_mem0
                mem = get_mem0()
                if mem.available:
                    threading.Thread(
                        target=mem.add_conversation,
                        args=(text, response),
                        kwargs={"user_id": f"wa_{phone[-4:]}"},
                        daemon=True,
                    ).start()
            except Exception:
                pass

            return response
        except Exception as exc:
            return f"Mi scuso, c'e' un problema tecnico. Riprova tra poco."

    # ── Send Messages ────────────────────────────────────────────────────

    def send_message(self, phone: str, text: str) -> bool:
        """Invia messaggio di testo via WhatsApp Cloud API."""
        if not _WA_TOKEN or not _WA_PHONE_ID:
            log.warning("WhatsApp non configurato (token/phone_id mancanti)", action=LogAction.MONITOR)
            return False
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{_WA_API}/{_WA_PHONE_ID}/messages",
                    headers={
                        "Authorization": f"Bearer {_WA_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"body": text},
                    },
                )
                if resp.status_code in (200, 201):
                    self._get_policy().record_send(phone)
                    return True
                else:
                    log.warning(f"WA send failed: {resp.status_code} {resp.text[:200]}",
                                action=LogAction.MONITOR)
                    return False
        except Exception as exc:
            log.error(f"WA send error: {exc}", action=LogAction.MONITOR)
            return False

    def send_template(self, phone: str, template_name: str, language: str = "it",
                      components: list | None = None) -> bool:
        """Invia messaggio template approvato da Meta."""
        if not _WA_TOKEN or not _WA_PHONE_ID:
            return False
        try:
            payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language},
                },
            }
            if components:
                payload["template"]["components"] = components

            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{_WA_API}/{_WA_PHONE_ID}/messages",
                    headers={
                        "Authorization": f"Bearer {_WA_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                return resp.status_code in (200, 201)
        except Exception as exc:
            log.error(f"WA template send error: {exc}", action=LogAction.MONITOR)
            return False

    def send_interactive_buttons(self, phone: str, body: str, buttons: list[dict]) -> bool:
        """Invia messaggio con bottoni interattivi."""
        if not _WA_TOKEN or not _WA_PHONE_ID:
            return False
        try:
            btn_list = []
            for b in buttons[:3]:  # Max 3 bottoni
                btn_list.append({
                    "type": "reply",
                    "reply": {"id": b.get("id", ""), "title": b.get("title", "")[:20]}
                })
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{_WA_API}/{_WA_PHONE_ID}/messages",
                    headers={
                        "Authorization": f"Bearer {_WA_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": body},
                            "action": {"buttons": btn_list},
                        },
                    },
                )
                return resp.status_code in (200, 201)
        except Exception as exc:
            log.error(f"WA interactive send error: {exc}", action=LogAction.MONITOR)
            return False

    def notify_order_update(self, order_id: int, new_status: str, message: str = "") -> bool:
        """Notifica il cliente di un aggiornamento ordine."""
        order = self._find_order(order_id)
        if not order:
            return False
        phone = order["phone"]
        policy = self._get_policy()
        from interface.whatsapp_policy import ConsentType
        if not policy.has_consent(phone, ConsentType.NOTIFICATIONS):
            return False
        if not policy.can_send(phone, is_proactive=True):
            return False

        icons = {"shipped": "📦", "delivered": "🎉", "completed": "✓", "cancelled": "❌"}
        icon = icons.get(new_status, "📋")
        text = f"{icon} *Ordine #{order_id} — {new_status.upper()}*\n"
        if message:
            text += f"\n{message}"

        order["status"] = new_status
        self._save_json(_ORDERS_FILE, self._orders)

        return self.send_message(phone, text)

    # ── Contact Management ───────────────────────────────────────────────

    def _update_contact(self, phone: str, name: str) -> None:
        if phone not in self._contacts:
            self._contacts[phone] = {
                "phone": phone,
                "name": name,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "messages": 0,
            }
        contact = self._contacts[phone]
        if name:
            contact["name"] = name
        contact["last_seen"] = datetime.now(timezone.utc).isoformat()
        contact["messages"] = contact.get("messages", 0) + 1
        self._save_json(_CONTACTS_FILE, self._contacts)

    # ── Order Helpers ────────────────────────────────────────────────────

    def _find_order(self, order_id: int) -> dict | None:
        for o in self._orders:
            if o["id"] == order_id:
                return o
        return None

    def _next_order_id(self) -> int:
        if not self._orders:
            return 1
        return max(o["id"] for o in self._orders) + 1

    # ── Persistence ──────────────────────────────────────────────────────

    @staticmethod
    def _load_json(path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return default

    @staticmethod
    def _save_json(path, data):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Singleton ───────────────────────────────────────────────────────────────

_bot: Optional[WorkMindWhatsAppBot] = None


def get_whatsapp_bot() -> WorkMindWhatsAppBot:
    global _bot
    if _bot is None:
        _bot = WorkMindWhatsAppBot()
    return _bot

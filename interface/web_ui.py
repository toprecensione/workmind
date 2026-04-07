"""
WorkMind Web UI — Apple-Style
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Single-page app con:
- Dashboard status
- Chat con DeepSeek AI
- Settings panel (rete, email, cartelle, API)
- Tutto su porta 7860
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, redirect, request, render_template_string, send_from_directory, session, url_for

from config.settings import config, DATA_DIR
from config.company import get_company_config, load_company_config, CompanyConfig
from ai_client.client import get_ai_client, AIMessage, ModelRole
from ai_client.budget import get_budget
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit
from storage.user_manager import get_user_manager, UserRole
from mindwork.feedback import get_feedback
from nlp.hallucination_guard import HallucinationGuard
from mindwork.request_advisor import get_advisor
from logging_system import get_logger, LogAction, LogStatus

_STATIC_DIR = Path(__file__).parent.parent / "static"

_FACTUAL_KW = (
    "contatt", "telefono", "email", "mail", "indirizzo", "sito",
    "website", "url", "numero", "orari", "sede", "dove",
)

log = get_logger("interface.web_ui")

_SETTINGS_FILE = DATA_DIR / "ui_settings.json"


def _require_auth(f):
    """Decorator that redirects to /login if not authenticated."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


def _require_admin(f):
    """Decorator che richiede ruolo admin."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect("/login")
        if session.get("role") != "admin":
            return jsonify({"ok": False, "error": "Accesso riservato agli amministratori"}), 403
        return f(*args, **kwargs)
    return wrapper


class WorkMindUI:
    def __init__(self, port: int = 7860) -> None:
        self._port = port
        self._app = Flask("workmind")
        self._app.secret_key = os.getenv("WORKMIND_SECRET_KEY", "wm-secret-change-me-2026")
        self._ai = get_ai_client()
        self._kb = get_kb()
        self._budget = get_budget()
        self._audit = get_audit()
        self._feedback = get_feedback()
        self._company = get_company_config()
        self._guard = HallucinationGuard(self._ai)
        self._advisor = get_advisor()
        self._start_time = time.time()
        self._register_routes()
        # Registra route WhatsApp webhook e API
        try:
            from interface.whatsapp_bot import get_whatsapp_bot
            self._wa_bot = get_whatsapp_bot()
            self._wa_bot.register_routes(self._app)
            log.info("WhatsApp webhook routes registrate", action=LogAction.STARTUP, status=LogStatus.OK)
        except Exception as exc:
            log.warning(f"WhatsApp routes non registrate: {exc}", action=LogAction.STARTUP)

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True, name="WebUI")
        t.start()
        log.info(f"Web UI avviata su porta {self._port}", action=LogAction.STARTUP, status=LogStatus.OK)

    def _run(self) -> None:
        self._app.run(host="0.0.0.0", port=self._port, debug=False, use_reloader=False)

    def _register_routes(self):
        app = self._app

        @app.route("/login", methods=["GET", "POST"])
        def login():
            error = ""
            if request.method == "POST":
                email = request.form.get("email", "").strip().lower()
                password = request.form.get("password", "")
                um = get_user_manager()
                user = um.authenticate(email, password)
                if user:
                    session["authenticated"] = True
                    session["username"] = user["name"]
                    session["email"] = user["email"]
                    session["role"] = user["role"]
                    if user.get("must_change_password"):
                        return redirect("/change-password")
                    return redirect("/")
                error = "Email o password non validi"
            return render_template_string(_LOGIN_TEMPLATE, error=error)

        @app.route("/change-password", methods=["GET", "POST"])
        def change_password():
            if not session.get("authenticated"):
                return redirect("/login")
            error = ""
            success = ""
            if request.method == "POST":
                new_pw = request.form.get("new_password", "")
                confirm = request.form.get("confirm_password", "")
                if len(new_pw) < 8:
                    error = "La password deve essere di almeno 8 caratteri"
                elif new_pw != confirm:
                    error = "Le password non coincidono"
                else:
                    um = get_user_manager()
                    if um.change_password(session["email"], new_pw, changed_by=session["email"]):
                        success = "Password cambiata con successo!"
                        return redirect("/")
                    else:
                        error = "Errore nel cambio password"
            return render_template_string(_CHANGE_PW_TEMPLATE, error=error, success=success)

        @app.route("/forgot-password", methods=["GET", "POST"])
        def forgot_password():
            msg = ""
            if request.method == "POST":
                email = request.form.get("email", "").strip().lower()
                um = get_user_manager()
                base = request.host_url.rstrip("/")
                um.request_password_reset(email, base_url=base)
                msg = "Se l'email esiste, riceverai un link per il reset."
            return render_template_string(_FORGOT_PW_TEMPLATE, msg=msg)

        @app.route("/reset-password", methods=["GET", "POST"])
        def reset_password():
            token = request.args.get("token", "") or request.form.get("token", "")
            error = ""
            if request.method == "POST":
                new_pw = request.form.get("new_password", "")
                confirm = request.form.get("confirm_password", "")
                if len(new_pw) < 8:
                    error = "La password deve essere di almeno 8 caratteri"
                elif new_pw != confirm:
                    error = "Le password non coincidono"
                else:
                    um = get_user_manager()
                    if um.use_reset_token(token, new_pw):
                        return redirect("/login")
                    error = "Token non valido o scaduto"
            else:
                um = get_user_manager()
                if not um.verify_reset_token(token):
                    error = "Token non valido o scaduto"
            return render_template_string(_RESET_PW_TEMPLATE, error=error, token=token)

        @app.route("/logout")
        def logout():
            session.clear()
            return redirect("/login")

        @app.route("/manifest.json")
        def pwa_manifest():
            return send_from_directory(_STATIC_DIR, "manifest.json",
                                       mimetype="application/manifest+json")

        @app.route("/sw.js")
        def pwa_sw():
            resp = send_from_directory(_STATIC_DIR, "sw.js",
                                       mimetype="application/javascript")
            resp.headers["Service-Worker-Allowed"] = "/"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.route("/favicon.ico")
        def pwa_favicon():
            icons_dir = _STATIC_DIR / "icons"
            if (icons_dir / "favicon-32.png").exists():
                return send_from_directory(icons_dir, "favicon-32.png",
                                           mimetype="image/png")
            return send_from_directory(icons_dir, "icon.svg",
                                       mimetype="image/svg+xml")

        @app.route("/static/icons/<path:filename>")
        def pwa_icons(filename):
            return send_from_directory(_STATIC_DIR / "icons", filename)

        @app.route("/")
        @_require_auth
        def index():
            return render_template_string(_HTML_TEMPLATE, company=self._company.name)

        # ── API: Status ───────────────────────────────────────────────────
        @app.route("/api/status")
        @_require_auth
        def api_status():
            uptime = int(time.time() - self._start_time)
            h, m = divmod(uptime // 60, 60)
            return jsonify({
                "node_id": config.node.node_id,
                "company": self._company.name,
                "sector": self._company.sector,
                "environment": config.node.environment,
                "uptime": f"{h}h {m}m",
                "status": "online",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kb": self._kb.summary(),
                "feedback": self._feedback.stats(),
            })

        @app.route("/api/budget")
        @_require_auth
        def api_budget():
            return jsonify(self._budget.daily_summary())

        @app.route("/api/audit")
        @_require_auth
        def api_audit():
            return jsonify(self._audit.recent(30))

        @app.route("/api/kb")
        @_require_auth
        def api_kb():
            return jsonify(self._kb.summary())

        @app.route("/api/kb/full")
        @_require_auth
        def api_kb_full():
            """Restituisce tutti i contenuti della KB."""
            return jsonify({
                "facts":       self._kb.get_facts(),
                "corrections": self._kb.get_corrections(),
                "processes":   self._kb.get_processes(),
                "glossary":    self._kb.get_glossary(),
                "summary":     self._kb.summary(),
            })

        @app.route("/api/kb/search")
        @_require_auth
        def api_kb_search():
            q = request.args.get("q", "").strip()
            if not q:
                return jsonify({"result": None, "matches": []})
            result = self._kb.lookup_fact(q, threshold=0.15)
            # Ricerca testuale diretta
            matches = [f["text"] for f in self._kb.get_facts()
                       if q.lower() in f["text"].lower()]
            return jsonify({"result": result, "matches": matches[:20]})

        @app.route("/api/kb/fact", methods=["POST"])
        @_require_auth
        def api_kb_add_fact():
            d = request.get_json() or {}
            text = d.get("text", "").strip()
            if not text:
                return jsonify({"ok": False, "error": "Testo vuoto"})
            self._kb.teach_fact(text, taught_by=session.get("email", "web"))
            try:
                from storage.vector_store import get_vector_store
                get_vector_store().index_fact(text, source="web_kb")
            except Exception:
                pass
            return jsonify({"ok": True, "text": text})

        @app.route("/api/kb/fact/<int:idx>", methods=["DELETE"])
        @_require_auth
        def api_kb_delete_fact(idx):
            facts = self._kb.get_facts()
            if idx < 0 or idx >= len(facts):
                return jsonify({"ok": False, "error": "Indice non valido"})
            removed = facts.pop(idx)
            self._kb._data["facts"] = facts
            self._kb._save()
            return jsonify({"ok": True, "removed": removed["text"]})

        @app.route("/api/kb/glossary", methods=["POST"])
        @_require_auth
        def api_kb_add_glossary():
            d = request.get_json() or {}
            term = d.get("term", "").strip()
            defn = d.get("definition", "").strip()
            if not term or not defn:
                return jsonify({"ok": False, "error": "Termine e definizione richiesti"})
            self._kb.add_glossary_term(term, defn)
            return jsonify({"ok": True})

        @app.route("/api/kb/glossary/<term>", methods=["DELETE"])
        @_require_auth
        def api_kb_delete_glossary(term):
            gloss = self._kb.get_glossary()
            if term.lower() not in gloss:
                return jsonify({"ok": False, "error": "Termine non trovato"})
            del self._kb._data["glossary"][term.lower()]
            self._kb._save()
            return jsonify({"ok": True})

        @app.route("/api/kb/process", methods=["POST"])
        @_require_auth
        def api_kb_add_process():
            d = request.get_json() or {}
            name = d.get("name", "").strip()
            desc = d.get("description", "").strip()
            steps = d.get("steps", [])
            if not name or not desc:
                return jsonify({"ok": False, "error": "Nome e descrizione richiesti"})
            self._kb.teach_process(name, desc, steps,
                                   taught_by=session.get("email", "web"))
            return jsonify({"ok": True})

        @app.route("/api/kb/export")
        @_require_auth
        def api_kb_export():
            ctx = self._kb.build_context_prompt()
            summary = self._kb.summary()
            return jsonify({"export": ctx, "summary": summary})

        @app.route("/api/budget/models")
        @_require_auth
        def api_budget_models():
            """Spesa odierna per singolo modello AI."""
            return jsonify(self._budget.model_breakdown_today())

        # ── API: Chat ─────────────────────────────────────────────────────
        @app.route("/api/chat", methods=["POST"])
        @_require_auth
        def api_chat():
            data = request.get_json()
            message = data.get("message", "").strip()
            if not message:
                return jsonify({"reply": "Scrivi un messaggio."})

            # Utente ID per sessione advisor
            user_id = f"web_{session.get('email', 'anon').replace('@','_')}"

            # Annullamento advisor
            if message.lower() in ("annulla", "esci", "stop") and self._advisor.has_active_session(user_id):
                self._advisor.cancel(user_id)
                return jsonify({"reply": "Ok, lasciamo perdere! Dimmi se hai altre domande.", "source": "advisor"})

            # Sessione advisor attiva: continua raccolta requisiti
            if self._advisor.has_active_session(user_id):
                resp = self._advisor.process(user_id, message)
                return jsonify({
                    "reply": resp.message,
                    "source": "advisor",
                    "phase": resp.phase.value,
                    "request_submitted": resp.request_submitted,
                    "request_id": resp.request_id,
                })

            # Comandi slash
            if message.startswith("/"):
                # /idea e /voglio avviano advisor
                if any(message.startswith(cmd) for cmd in ("/idea", "/voglio", "/bisogno")):
                    text = message.split(maxsplit=1)[1].strip() if " " in message else ""
                    if text:
                        resp = self._advisor.start(user_id, "web", text)
                        return jsonify({"reply": resp.message, "source": "advisor", "phase": "clarifying"})
                    return jsonify({"reply": "Descrivimi cosa ti serve e ti guido!", "source": "advisor"})
                reply = self._handle_command(message)
                return jsonify({"reply": reply})

            # Trigger implicito advisor: l'utente esprime un bisogno
            if self._advisor.is_intent_trigger(message):
                resp = self._advisor.start(user_id, "web", message)
                return jsonify({"reply": resp.message, "source": "advisor", "phase": "clarifying"})

            # Intent routing: query fattuali → KB first, zero AI
            msg_lower = message.lower()
            if any(kw in msg_lower for kw in _FACTUAL_KW):
                kb_answer = self._kb.lookup_fact(message)
                if kb_answer:
                    return jsonify({
                        "reply": kb_answer,
                        "source": "kb",
                        "note": "Risposta dalla Knowledge Base aziendale (nessuna chiamata AI)"
                    })
                return jsonify({
                    "reply": (
                        "Non ho questa informazione nella Knowledge Base.\n\n"
                        "Aggiungila con `/teach <fatto>` oppure dalla pagina **Knowledge Base**.\n"
                        "Esempio: `/teach Email contatti: info@faberweb.it`"
                    ),
                    "source": "kb_miss"
                })

            # Chat con AI: grounding blindato + HallucinationGuard
            try:
                context = self._kb.build_context_prompt()
                rag_context = ""
                try:
                    from storage.vector_store import get_vector_store
                    rag_context = get_vector_store().build_rag_context(message)
                except Exception:
                    pass

                memory_context = ""
                try:
                    from storage.mem0_store import get_mem0
                    mem = get_mem0()
                    if mem.available:
                        user_id = session.get("username", "supervisor")
                        memory_context = mem.build_memory_context(message, user_id=user_id)
                except Exception:
                    pass

                system = (
                    f"Sei WorkMind, l'assistente operativo di {self._company.name} "
                    f"(settore: {self._company.sector}). "
                    f"Rispondi in italiano in modo conciso e professionale.\n\n"
                    f"REGOLE FONDAMENTALI:\n"
                    f"1. NON inventare URL, email, numeri di telefono, indirizzi.\n"
                    f"2. Se non sai: 'Non ho questa informazione. Aggiungila con /teach.'\n"
                    f"3. Usa SOLO fatti presenti nella Knowledge Base qui sotto.\n"
                    f"4. Non esiste il sito workmind.dev.\n"
                )
                if memory_context:
                    system += f"\n{memory_context}\n"
                if rag_context:
                    system += f"\n{rag_context}\n"
                if context:
                    system += f"\n--- KNOWLEDGE BASE ---\n{context}\n---\n"

                # Usa RELIABLE (Haiku) per risposte al supervisore: affidabile e veloce
                response = self._ai.complete_simple(
                    message, system_prompt=system,
                    role=ModelRole.RELIABLE, max_tokens=1024, temperature=0.2,
                )

                # HallucinationGuard
                guard_issues = []
                if context:
                    validation = self._guard.validate(response, context, context=message)
                    if not validation.is_valid:
                        guard_issues = validation.issues[:3]
                        log.warning(
                            f"Web UI hallucination guard: {len(validation.issues)} problemi",
                            action=LogAction.VALIDATE,
                            extra={"issues": guard_issues},
                        )

                # Salva in Mem0 (background)
                try:
                    from storage.mem0_store import get_mem0
                    mem = get_mem0()
                    if mem.available:
                        threading.Thread(
                            target=mem.add_conversation,
                            args=(message, response),
                            kwargs={"user_id": session.get("username", "supervisor")},
                            daemon=True,
                        ).start()
                except Exception:
                    pass

                result = {"reply": response, "source": "ai"}
                if guard_issues:
                    result["warning"] = f"Possibili imprecisioni rilevate: {'; '.join(guard_issues[:2])}"
                return jsonify(result)

            except Exception as exc:
                return jsonify({"reply": f"Errore AI: {exc}"})

        # ── API: Settings ─────────────────────────────────────────────────
        @app.route("/api/settings", methods=["GET"])
        @_require_auth
        def get_settings():
            return jsonify(self._load_settings())

        @app.route("/api/settings", methods=["POST"])
        @_require_admin
        def save_settings():
            data = request.get_json()
            self._save_settings(data)
            # Also update company.yaml
            self._apply_settings(data)
            return jsonify({"ok": True})

        @app.route("/api/teach", methods=["POST"])
        @_require_auth
        def api_teach():
            data = request.get_json()
            fact = data.get("fact", "").strip()
            if fact:
                self._kb.teach_fact(fact, taught_by="web_ui")
                # Index in vector store
                try:
                    from storage.vector_store import get_vector_store
                    get_vector_store().index_fact(fact, source="web_ui")
                except Exception:
                    pass
                # Sync to Mem0
                try:
                    from storage.mem0_store import get_mem0
                    get_mem0().add_fact(fact, source="web_ui")
                except Exception:
                    pass
                return jsonify({"ok": True, "message": f"Memorizzato: {fact}"})
            return jsonify({"ok": False, "message": "Nessun fatto specificato"})

        # ── API: Mem0 Memory ──────────────────────────────────────────────
        @app.route("/api/memory/stats")
        @_require_auth
        def api_mem_stats():
            try:
                from storage.mem0_store import get_mem0
                return jsonify(get_mem0().stats())
            except Exception:
                return jsonify({"available": False})

        @app.route("/api/memory/sync", methods=["POST"])
        @_require_auth
        def api_mem_sync():
            try:
                from storage.mem0_store import get_mem0
                result = get_mem0().sync_from_kb()
                return jsonify({"ok": True, **result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)})

        @app.route("/api/memory/search", methods=["POST"])
        @_require_auth
        def api_mem_search():
            data = request.get_json()
            query = data.get("query", "")
            user_id = data.get("user_id", "system")
            try:
                from storage.mem0_store import get_mem0
                results = get_mem0().search(query, user_id=user_id, limit=10)
                return jsonify({"results": results})
            except Exception as exc:
                return jsonify({"results": [], "error": str(exc)})

        @app.route("/api/memory/all")
        @_require_auth
        def api_mem_all():
            user_id = request.args.get("user_id", "system")
            try:
                from storage.mem0_store import get_mem0
                memories = get_mem0().get_all(user_id=user_id)
                return jsonify({"memories": memories})
            except Exception as exc:
                return jsonify({"memories": [], "error": str(exc)})

        # ── API: RAG ─────────────────────────────────────────────────────
        @app.route("/api/rag/stats")
        @_require_auth
        def api_rag_stats():
            try:
                from storage.vector_store import get_vector_store
                return jsonify(get_vector_store().stats())
            except Exception:
                return jsonify({"available": False, "count": 0})

        @app.route("/api/rag/reindex", methods=["POST"])
        @_require_auth
        def api_rag_reindex():
            try:
                from storage.vector_store import get_vector_store
                stats = get_vector_store().reindex_all()
                return jsonify({"ok": True, **stats})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)})

        # ── API: Backups ─────────────────────────────────────────────────
        @app.route("/api/backups")
        @_require_auth
        def api_backups():
            from storage.backup import get_backup_manager
            return jsonify(get_backup_manager().list_backups())

        @app.route("/api/backups/create", methods=["POST"])
        @_require_auth
        def api_backup_create():
            from storage.backup import get_backup_manager
            path = get_backup_manager().create_backup()
            return jsonify({"ok": True, "path": path})

        @app.route("/api/backups/restore", methods=["POST"])
        @_require_auth
        def api_backup_restore():
            data = request.get_json()
            name = data.get("backup_name", "")
            from storage.backup import get_backup_manager
            ok = get_backup_manager().restore_backup(name)
            return jsonify({"ok": ok})

        # ── API: Feature Requests ─────────────────────────────────────
        @app.route("/api/features")
        @_require_auth
        def api_features():
            from mindwork.feature_requests import get_feature_manager
            status_filter = request.args.get("status")
            reqs = get_feature_manager().list_requests(status=status_filter, limit=50)
            return jsonify({"requests": reqs})

        @app.route("/api/features/stats")
        @_require_auth
        def api_features_stats():
            from mindwork.feature_requests import get_feature_manager
            return jsonify(get_feature_manager().stats())

        @app.route("/api/features/submit", methods=["POST"])
        @_require_auth
        def api_features_submit():
            data = request.get_json()
            text = data.get("text", "").strip()
            if not text:
                return jsonify({"ok": False, "error": "Descrizione vuota"})
            from mindwork.feature_requests import get_feature_manager
            req = get_feature_manager().submit_request(
                text, submitted_by=session.get("username", "web"), source="web"
            )
            return jsonify({"ok": True, "request": req})

        @app.route("/api/features/approve", methods=["POST"])
        @_require_auth
        def api_features_approve():
            data = request.get_json()
            req_id = data.get("id", 0)
            from mindwork.feature_requests import get_feature_manager
            req = get_feature_manager().approve(int(req_id), approved_by=session.get("username", "web"))
            return jsonify({"ok": bool(req), "request": req})

        @app.route("/api/features/reject", methods=["POST"])
        @_require_auth
        def api_features_reject():
            data = request.get_json()
            req_id = data.get("id", 0)
            reason = data.get("reason", "")
            from mindwork.feature_requests import get_feature_manager
            req = get_feature_manager().reject(int(req_id), rejected_by=session.get("username", "web"), reason=reason)
            return jsonify({"ok": bool(req), "request": req})

        # ── User Management API (admin only) ─────────────────────────────
        @app.route("/api/users")
        @_require_admin
        def api_users():
            um = get_user_manager()
            return jsonify({"users": um.list_users()})

        @app.route("/api/users/create", methods=["POST"])
        @_require_admin
        def api_users_create():
            data = request.get_json()
            email = data.get("email", "").strip()
            name = data.get("name", "")
            role = data.get("role", "user")
            password = data.get("password", "")
            if not email:
                return jsonify({"ok": False, "error": "Email richiesta"})
            um = get_user_manager()
            user = um.create_user(email, password, name=name, role=role,
                                  created_by=session.get("email", "admin"))
            if not user:
                return jsonify({"ok": False, "error": "Utente gia' esistente"})
            return jsonify({"ok": True, "user": user})

        @app.route("/api/users/invite", methods=["POST"])
        @_require_admin
        def api_users_invite():
            data = request.get_json()
            email = data.get("email", "").strip()
            name = data.get("name", "")
            role = data.get("role", "user")
            if not email:
                return jsonify({"ok": False, "error": "Email richiesta"})
            um = get_user_manager()
            base = request.host_url.rstrip("/")
            user = um.invite_user(email, role=role, name=name,
                                  invited_by=session.get("email", "admin"),
                                  base_url=base)
            if not user:
                return jsonify({"ok": False, "error": "Utente gia' esistente"})
            return jsonify({"ok": True, "user": user})

        @app.route("/api/users/update", methods=["POST"])
        @_require_admin
        def api_users_update():
            data = request.get_json()
            email = data.get("email", "")
            updates = {k: v for k, v in data.items() if k in ("name", "role", "active")}
            um = get_user_manager()
            user = um.update_user(email, updates, updated_by=session.get("email", "admin"))
            if not user:
                return jsonify({"ok": False, "error": "Utente non trovato"})
            return jsonify({"ok": True, "user": user})

        @app.route("/api/users/delete", methods=["POST"])
        @_require_admin
        def api_users_delete():
            data = request.get_json()
            email = data.get("email", "")
            um = get_user_manager()
            ok = um.delete_user(email, deleted_by=session.get("email", "admin"))
            if not ok:
                return jsonify({"ok": False, "error": "Impossibile eliminare (admin predefinito?)"})
            return jsonify({"ok": True})

        @app.route("/api/users/reset-password", methods=["POST"])
        @_require_admin
        def api_users_reset_pw():
            data = request.get_json()
            email = data.get("email", "")
            new_pw = data.get("password", "")
            um = get_user_manager()
            if new_pw:
                ok = um.change_password(email, new_pw, changed_by=session.get("email", "admin"))
            else:
                base = request.host_url.rstrip("/")
                ok = um.request_password_reset(email, base_url=base)
            return jsonify({"ok": ok})

        @app.route("/api/smtp/test", methods=["POST"])
        @_require_admin
        def api_smtp_test():
            um = get_user_manager()
            return jsonify(um.test_smtp())

        # ── Plugin Management API ─────────────────────────────────────────
        @app.route("/api/plugins")
        @_require_admin
        def api_plugins_list():
            try:
                import plugin_loader
                return jsonify({
                    "loaded": plugin_loader.status_all(),
                    "available": plugin_loader.list_available(),
                })
            except Exception as exc:
                return jsonify({"error": str(exc), "loaded": [], "available": []})

        @app.route("/api/plugins/enable", methods=["POST"])
        @_require_admin
        def api_plugins_enable():
            data = request.get_json()
            pid = data.get("id", "")
            ver = data.get("version", "latest")
            try:
                import plugin_loader
                plugin_loader.enable_plugin(pid, ver)
                return jsonify({"ok": True})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)})

        @app.route("/api/plugins/disable", methods=["POST"])
        @_require_admin
        def api_plugins_disable():
            data = request.get_json()
            pid = data.get("id", "")
            try:
                import plugin_loader
                ok = plugin_loader.disable_plugin(pid)
                return jsonify({"ok": ok})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)})

        @app.route("/api/me")
        @_require_auth
        def api_me():
            um = get_user_manager()
            user = um.get_user(session.get("email", ""))
            return jsonify({"user": user, "is_admin": session.get("role") == "admin"})

        # ── GitHub Webhook — Auto-deploy after merge ────────────────────
        @app.route("/webhook/github", methods=["POST"])
        def webhook_github():
            import hmac
            import subprocess
            payload = request.get_data()
            # Verify signature if secret is set
            secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
            if secret:
                sig = request.headers.get("X-Hub-Signature-256", "")
                expected = "sha256=" + hmac.new(
                    secret.encode(), payload, hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(sig, expected):
                    return jsonify({"error": "Invalid signature"}), 403

            data = request.get_json(silent=True) or {}
            ref = data.get("ref", "")
            # Only deploy on push to main
            if ref != "refs/heads/main":
                return jsonify({"ok": True, "action": "ignored", "ref": ref})

            log.info("GitHub webhook: push to main — starting auto-deploy",
                     action=LogAction.UPDATE, status=LogStatus.OK)

            def _do_deploy():
                try:
                    subprocess.run(
                        ["git", "pull", "origin", "main"],
                        cwd=str(Path(__file__).resolve().parent.parent),
                        capture_output=True, text=True, timeout=60,
                    )
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "workmind"],
                        capture_output=True, text=True, timeout=30,
                    )
                except Exception as exc:
                    log.warning(f"Auto-deploy failed: {exc}", action=LogAction.UPDATE)

            threading.Thread(target=_do_deploy, daemon=True).start()
            return jsonify({"ok": True, "action": "deploying"})

    # ── Command handler ───────────────────────────────────────────────────

    def _handle_command(self, msg: str) -> str:
        parts = msg.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            return (
                "**Comandi disponibili:**\n"
                "- `/teach <fatto>` — Insegna un fatto\n"
                "- `/status` — Stato del bot\n"
                "- `/budget` — Spesa AI\n"
                "- `/audit` — Eventi recenti\n"
            )
        if cmd == "/teach" and arg:
            self._kb.teach_fact(arg, taught_by="chat")
            return f"Memorizzato: \"{arg}\""
        if cmd == "/status":
            kb = self._kb.summary()
            fb = self._feedback.stats()
            return (
                f"**{self._company.name}** — Online\n"
                f"KB: {kb['facts']} fatti, {kb['corrections']} correzioni\n"
                f"Feedback: {fb['total']} totali, accuratezza {fb['accuracy_rate']:.0%}"
            )
        if cmd == "/budget":
            b = self._budget.daily_summary()
            ds = b.get("deepseek", {})
            return f"DeepSeek oggi: ${ds.get('cost_usd',0):.4f} ({ds.get('calls',0)} chiamate)"
        return "Comando sconosciuto. Scrivi /help"

    # ── Settings persistence ──────────────────────────────────────────────

    def _load_settings(self) -> dict:
        defaults = {
            "company_name": self._company.name,
            "sector": self._company.sector,
            "timezone": self._company.timezone,
            "language": self._company.language,
            "supervisor_email": self._company.supervisor_email,
            "report_time": self._company.report_time_daily,
            "report_day": self._company.report_day_weekly,
            "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "network_shares": [],
            "smb_username": "",
            "smb_password": "",
            "smb_domain": "",
            "email_enabled": self._company.email.enabled,
            "email_provider": self._company.email.provider,
            "email_address": self._company.email.mailbox,
            "email_imap_host": self._company.email.imap_host,
            "email_imap_port": self._company.email.imap_port,
            "email_smtp_host": "",
            "email_smtp_port": 587,
            "email_pop3_host": "",
            "email_pop3_port": 995,
            "email_username": self._company.email.imap_user,
            "email_password": "",
            "db_enabled": self._company.database.enabled,
            "db_type": self._company.database.type,
            "db_host": self._company.database.host,
            "db_port": self._company.database.port,
            "db_name": self._company.database.name,
            "db_user": self._company.database.user,
            "watch_dirs": self._company.local_watch_dirs,
        }
        if _SETTINGS_FILE.exists():
            try:
                saved = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
                defaults.update(saved)
            except Exception:
                pass
        return defaults

    def _save_settings(self, data: dict) -> None:
        _SETTINGS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _apply_settings(self, data: dict) -> None:
        """Write settings back to company.yaml for persistence across restarts."""
        config_path = Path(__file__).resolve().parent.parent / "config" / "company.yaml"
        try:
            import yaml
            cfg = {
                "name": data.get("company_name", "WorkMind"),
                "sector": data.get("sector", ""),
                "language": data.get("language", "it"),
                "timezone": data.get("timezone", "Europe/Rome"),
                "supervisor_email": data.get("supervisor_email", ""),
                "report_time_daily": data.get("report_time", "22:00"),
                "report_day_weekly": data.get("report_day", "friday"),
                "local_watch_dirs": data.get("watch_dirs", []),
                "database": {
                    "enabled": data.get("db_enabled", False),
                    "type": data.get("db_type", "sqlserver"),
                    "host": data.get("db_host", ""),
                    "port": int(data.get("db_port", 1433)),
                    "name": data.get("db_name", ""),
                    "user": data.get("db_user", ""),
                    "schema_discovery": True,
                },
                "email": {
                    "enabled": data.get("email_enabled", False),
                    "provider": data.get("email_provider", "imap"),
                    "imap_host": data.get("email_imap_host", ""),
                    "imap_port": int(data.get("email_imap_port", 993)),
                    "imap_user": data.get("email_username", ""),
                    "mailbox": data.get("email_address", ""),
                },
                "smb": {
                    "enabled": bool(data.get("network_shares")),
                    "shares": [
                        {"server": s, "mount_point": f"/mnt/wm_share_{i}",
                         "username": data.get("smb_username", ""),
                         "domain": data.get("smb_domain", "")}
                        for i, s in enumerate(data.get("network_shares", []))
                    ],
                },
                "rdp": {"enabled": False},
            }
            config_path.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8")
            log.info("Settings salvati in company.yaml", action=LogAction.CONFIG, status=LogStatus.OK)
        except ImportError:
            # No yaml available, save only to JSON
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Login Template
# ═══════════════════════════════════════════════════════════════════════════════

_AUTH_STYLE = """
:root {
  --bg: #f5f5f7; --card: #ffffff; --text: #1d1d1f; --text2: #86868b;
  --accent: #0071e3; --accent-hover: #0077ED; --red: #ff3b30; --green: #34c759;
  --border: #d2d2d7; --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04);
  --radius: 12px; --font: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: var(--font); background: var(--bg); color: var(--text);
       display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-card {
  background: var(--card); border-radius: 16px; padding: 48px 40px; width: 400px;
  box-shadow: var(--shadow); border: 1px solid var(--border); text-align: center;
}
.login-card h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 6px; }
.login-card .subtitle { color: var(--text2); font-size: 14px; margin-bottom: 32px; }
.login-card input {
  width: 100%; padding: 12px 16px; border-radius: 10px; border: 1px solid var(--border);
  font-size: 15px; font-family: var(--font); outline: none; margin-bottom: 14px;
  transition: border-color 0.2s;
}
.login-card input:focus { border-color: var(--accent); }
.login-card button {
  width: 100%; padding: 13px; border-radius: 10px; border: none;
  background: var(--accent); color: white; font-size: 16px; font-weight: 600;
  font-family: var(--font); cursor: pointer; transition: background 0.2s; margin-top: 6px;
}
.login-card button:hover { background: var(--accent-hover); }
.error { color: var(--red); font-size: 13px; margin-bottom: 12px; }
.success { color: var(--green); font-size: 13px; margin-bottom: 12px; }
.link { color: var(--accent); font-size: 13px; text-decoration: none; display: inline-block; margin-top: 16px; }
.link:hover { text-decoration: underline; }
"""

_LOGIN_TEMPLATE = r"""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkMind — Login</title><style>""" + _AUTH_STYLE + """</style></head>
<body>
<div class="login-card">
  <h1>WorkMind</h1>
  <div class="subtitle">Accedi con la tua email</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST" action="/login">
    <input name="email" type="email" placeholder="Email" autofocus required>
    <input name="password" type="password" placeholder="Password" required>
    <button type="submit">Accedi</button>
  </form>
  <a class="link" href="/forgot-password">Password dimenticata?</a>
</div>
</body></html>
"""

_CHANGE_PW_TEMPLATE = r"""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkMind — Cambia Password</title><style>""" + _AUTH_STYLE + """</style></head>
<body>
<div class="login-card">
  <h1>Cambia Password</h1>
  <div class="subtitle">Devi impostare una nuova password</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if success %}<div class="success">{{ success }}</div>{% endif %}
  <form method="POST">
    <input name="new_password" type="password" placeholder="Nuova password (min 8 caratteri)" required minlength="8">
    <input name="confirm_password" type="password" placeholder="Conferma password" required>
    <button type="submit">Cambia Password</button>
  </form>
</div>
</body></html>
"""

_FORGOT_PW_TEMPLATE = r"""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkMind — Reset Password</title><style>""" + _AUTH_STYLE + """</style></head>
<body>
<div class="login-card">
  <h1>Reset Password</h1>
  <div class="subtitle">Inserisci la tua email per ricevere il link di reset</div>
  {% if msg %}<div class="success">{{ msg }}</div>{% endif %}
  <form method="POST">
    <input name="email" type="email" placeholder="La tua email" autofocus required>
    <button type="submit">Invia Link Reset</button>
  </form>
  <a class="link" href="/login">Torna al login</a>
</div>
</body></html>
"""

_RESET_PW_TEMPLATE = r"""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkMind — Nuova Password</title><style>""" + _AUTH_STYLE + """</style></head>
<body>
<div class="login-card">
  <h1>Nuova Password</h1>
  <div class="subtitle">Scegli la tua nuova password</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST">
    <input type="hidden" name="token" value="{{ token }}">
    <input name="new_password" type="password" placeholder="Nuova password (min 8 caratteri)" required minlength="8">
    <input name="confirm_password" type="password" placeholder="Conferma password" required>
    <button type="submit">Reimposta Password</button>
  </form>
  <a class="link" href="/login">Torna al login</a>
</div>
</body></html>
"""

# ═══════════════════════════════════════════════════════════════════════════════
# HTML Template — Apple-Style Single Page App
# ═══════════════════════════════════════════════════════════════════════════════

_HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>WorkMind — {{ company }}</title>
<!-- PWA -->
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0071e3">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="WorkMind">
<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
<link rel="apple-touch-icon" sizes="192x192" href="/static/icons/icon-192.png">
<link rel="icon" type="image/svg+xml" href="/static/icons/icon.svg">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icons/icon-192.png">
<style>
:root {
  --bg: #f5f5f7;
  --card: #ffffff;
  --text: #1d1d1f;
  --text2: #86868b;
  --accent: #0071e3;
  --accent-hover: #0077ED;
  --green: #34c759;
  --orange: #ff9500;
  --red: #ff3b30;
  --border: #d2d2d7;
  --sidebar-bg: #fafafa;
  --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04);
  --shadow-lg: 0 4px 24px rgba(0,0,0,0.08);
  --radius: 12px;
  --radius-lg: 16px;
  --font: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: var(--font); background: var(--bg); color: var(--text); height: 100vh; display: flex; }

/* ── Sidebar ─────────────────────────────────────────────────── */
.sidebar {
  width: 260px; min-width: 260px; background: var(--sidebar-bg);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
  padding: 24px 0; height: 100vh;
}
.sidebar-brand {
  padding: 0 24px 24px; border-bottom: 1px solid var(--border);
}
.sidebar-brand h1 {
  font-size: 20px; font-weight: 700; letter-spacing: -0.5px; color: var(--text);
}
.sidebar-brand .subtitle {
  font-size: 12px; color: var(--text2); margin-top: 2px;
}
.sidebar-nav { flex: 1; padding: 12px; }
.nav-item {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 500;
  color: var(--text2); transition: all 0.15s ease; margin-bottom: 2px;
}
.nav-item:hover { background: rgba(0,0,0,0.04); color: var(--text); }
.nav-item.active { background: rgba(0,113,227,0.08); color: var(--accent); }
.nav-item .icon { font-size: 18px; width: 24px; text-align: center; }

.sidebar-footer {
  padding: 16px 24px; border-top: 1px solid var(--border);
  font-size: 11px; color: var(--text2);
}
.status-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: var(--green); margin-right: 6px; animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

/* ── Main Content ────────────────────────────────────────────── */
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.page { display: none; flex: 1; overflow-y: auto; padding: 32px; }
.page.active { display: flex; flex-direction: column; }
.page-title {
  font-size: 28px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 24px;
}

/* ── Cards ────────────────────────────────────────────────────── */
.cards-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px; margin-bottom: 24px;
}
.card {
  background: var(--card); border-radius: var(--radius); padding: 20px;
  box-shadow: var(--shadow); border: 1px solid var(--border);
}
.card-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
}
.card-title { font-size: 13px; font-weight: 600; color: var(--text2); text-transform: uppercase; letter-spacing: 0.5px; }
.card-value { font-size: 32px; font-weight: 700; letter-spacing: -1px; }
.card-sub { font-size: 13px; color: var(--text2); margin-top: 4px; }

/* ── Chat ─────────────────────────────────────────────────────── */
.chat-container { flex: 1; display: flex; flex-direction: column; max-height: calc(100vh - 120px); }
.chat-messages {
  flex: 1; overflow-y: auto; padding: 16px 0; display: flex; flex-direction: column; gap: 12px;
}
.msg {
  max-width: 75%; padding: 12px 16px; border-radius: 18px; font-size: 14px;
  line-height: 1.5; word-wrap: break-word; white-space: pre-wrap;
}
.msg.user {
  align-self: flex-end; background: var(--accent); color: white;
  border-bottom-right-radius: 6px;
}
.msg.bot {
  align-self: flex-start; background: #e9e9eb; color: var(--text);
  border-bottom-left-radius: 6px;
}
.msg.bot.typing { color: var(--text2); font-style: italic; }
.chat-input-row {
  display: flex; gap: 8px; padding: 16px 0; border-top: 1px solid var(--border);
}
.chat-input {
  flex: 1; padding: 12px 16px; border-radius: 22px; border: 1px solid var(--border);
  font-size: 14px; font-family: var(--font); outline: none;
  transition: border-color 0.2s;
}
.chat-input:focus { border-color: var(--accent); }
.chat-send {
  width: 44px; height: 44px; border-radius: 50%; border: none;
  background: var(--accent); color: white; font-size: 18px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.2s;
}
.chat-send:hover { background: var(--accent-hover); }
.chat-send:disabled { background: var(--border); cursor: not-allowed; }

/* ── Settings ─────────────────────────────────────────────────── */
.settings-section {
  background: var(--card); border-radius: var(--radius); padding: 24px;
  box-shadow: var(--shadow); border: 1px solid var(--border); margin-bottom: 20px;
}
.settings-section h3 {
  font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex;
  align-items: center; gap: 8px;
}
.form-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;
}
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group.full { grid-column: span 2; }
.form-label { font-size: 12px; font-weight: 600; color: var(--text2); text-transform: uppercase; letter-spacing: 0.3px; }
.form-input, .form-select {
  padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border);
  font-size: 14px; font-family: var(--font); outline: none;
  transition: border-color 0.2s; background: white;
}
.form-input:focus, .form-select:focus { border-color: var(--accent); }
.form-toggle { display: flex; align-items: center; gap: 8px; }
.toggle {
  width: 44px; height: 24px; border-radius: 12px; background: #d1d1d6;
  position: relative; cursor: pointer; transition: background 0.2s;
}
.toggle.on { background: var(--green); }
.toggle::after {
  content: ''; position: absolute; width: 20px; height: 20px; border-radius: 50%;
  background: white; top: 2px; left: 2px; transition: transform 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
.toggle.on::after { transform: translateX(20px); }

.btn-primary {
  padding: 10px 24px; border-radius: 8px; border: none;
  background: var(--accent); color: white; font-size: 14px; font-weight: 600;
  font-family: var(--font); cursor: pointer; transition: background 0.2s;
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-save-row { display: flex; justify-content: flex-end; margin-top: 8px; }

.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.tag {
  display: flex; align-items: center; gap: 4px; padding: 4px 10px;
  background: rgba(0,113,227,0.08); color: var(--accent); border-radius: 6px;
  font-size: 12px; font-weight: 500;
}
.tag .remove { cursor: pointer; font-size: 14px; color: var(--red); }
.add-row { display: flex; gap: 8px; margin-top: 8px; }
.add-row input { flex: 1; }

.toast {
  position: fixed; bottom: 24px; right: 24px; padding: 12px 20px;
  background: #1d1d1f; color: white; border-radius: 10px; font-size: 14px;
  box-shadow: var(--shadow-lg); opacity: 0; transition: opacity 0.3s;
  z-index: 999;
}
.toast.show { opacity: 1; }

/* ── Audit table ──────────────────────────────────────────────── */
.audit-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.audit-table th {
  text-align: left; padding: 8px 12px; font-weight: 600; color: var(--text2);
  border-bottom: 1px solid var(--border); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.3px;
}
.audit-table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }
.audit-table tr:hover { background: #fafafa; }

.badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
  font-weight: 600;
}
.badge-blue { background: rgba(0,113,227,0.1); color: var(--accent); }
.badge-green { background: rgba(52,199,89,0.1); color: var(--green); }
.badge-orange { background: rgba(255,149,0,0.1); color: var(--orange); }

/* ── Bottom Nav (mobile) ───────────────────────────────────── */
.bottom-nav {
  display: none;
  position: fixed; bottom: 0; left: 0; right: 0;
  background: rgba(250,250,250,0.93);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border);
  z-index: 200;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
.bottom-nav-inner {
  display: flex; justify-content: space-around; align-items: center;
  height: 56px; padding: 0 4px;
}
.bottom-nav-item {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; padding: 6px 8px; border-radius: 10px;
  cursor: pointer; transition: color 0.15s ease; flex: 1;
  color: var(--text2); font-size: 10px; font-weight: 500; max-width: 72px;
  -webkit-tap-highlight-color: transparent;
}
.bottom-nav-item.active { color: var(--accent); }
.bottom-nav-item .bn-icon { font-size: 21px; line-height: 1; }

/* ── Responsive mobile ─────────────────────────────────────── */
@media (max-width: 768px) {
  .sidebar { display: none !important; }
  .bottom-nav { display: block; }
  .hide-mobile { display: none !important; }
  /* NON mettere overflow:hidden su body: blocca screenshot su Android */
  .main { overflow-y: auto; }
  /* Tutte le pagine: padding-bottom per non finire sotto bottom nav (56px) + margine */
  .page { padding: 16px 16px 120px; }
  .page-title { font-size: 22px; margin-bottom: 14px; }
  .cards-grid { grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px; }
  .card { padding: 14px; }
  .card-value { font-size: 24px; }
  .card-sub { font-size: 12px; }
  .chat-messages { gap: 8px; }
  .msg { max-width: 90%; font-size: 14px; }
  .settings-section { padding: 16px; margin-bottom: 12px; }
  .form-row { grid-template-columns: 1fr; }
  .form-group.full { grid-column: span 1; }
  .audit-table { font-size: 12px; width: 100%; table-layout: fixed; }
  .audit-table th, .audit-table td { padding: 8px 10px; }
  .audit-table th:first-child, .audit-table td:first-child { width: 115px; }

  /* ── Chat: input fisso sopra la bottom nav (stile WhatsApp/Telegram) ── */
  #page-chat {
    padding: 16px 16px 0;
  }
  .chat-container {
    max-height: none !important;
    display: flex;
    flex-direction: column;
  }
  /* Messaggi: scrollano, spazio in basso per input fisso + bottom nav */
  .chat-messages {
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 130px;  /* input ~66px + bottom-nav 56px + margine */
    max-height: none;
    flex: 1;
  }
  /* Input fisso in basso, esattamente sopra la bottom nav */
  .chat-input-row {
    position: fixed;
    bottom: 56px;           /* altezza bottom nav */
    left: 0; right: 0;
    padding: 10px 16px 12px;
    background: var(--bg);
    border-top: 1px solid var(--border);
    z-index: 150;
    box-shadow: 0 -4px 12px rgba(0,0,0,0.06);
  }
}
</style>
</head>
<body>

<!-- Sidebar -->
<div class="sidebar">
  <div class="sidebar-brand">
    <h1>WorkMind</h1>
    <div class="subtitle">{{ company }}</div>
  </div>
  <div class="sidebar-nav">
    <div class="nav-item active" onclick="showPage('dashboard')">
      <span class="icon">&#9673;</span> Dashboard
    </div>
    <div class="nav-item" onclick="showPage('chat')">
      <span class="icon">&#9993;</span> Chat
    </div>
    <div class="nav-item" onclick="showPage('audit')">
      <span class="icon">&#9776;</span> Audit Trail
    </div>
    <div class="nav-item" onclick="showPage('features')">
      <span class="icon">&#128161;</span> Richieste
    </div>
    <div class="nav-item" onclick="showPage('whatsapp')">
      <span class="icon">&#128172;</span> WhatsApp
    </div>
    <div class="nav-item admin-only" onclick="showPage('users')">
      <span class="icon">&#128101;</span> Utenti
    </div>
    <div class="nav-item admin-only" onclick="showPage('settings')">
      <span class="icon">&#9881;</span> Impostazioni
    </div>
  </div>
  <div class="sidebar-footer">
    <span class="status-dot"></span> Online<br>
    <span id="footer-uptime" style="margin-top:4px;display:block"></span>
    <a href="/logout" style="display:inline-block;margin-top:8px;font-size:12px;color:var(--red);text-decoration:none">Logout</a>
  </div>
</div>

<!-- Main -->
<div class="main">

  <!-- Dashboard -->
  <div class="page active" id="page-dashboard">
    <div class="page-title">Dashboard</div>
    <div class="cards-grid">
      <div class="card">
        <div class="card-header"><span class="card-title">Stato</span><span style="font-size:24px">&#9889;</span></div>
        <div class="card-value" style="color:var(--green)" id="d-status">Online</div>
        <div class="card-sub" id="d-uptime">-</div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Knowledge Base</span><span style="font-size:24px">&#128218;</span></div>
        <div class="card-value" id="d-kb-total">0</div>
        <div class="card-sub" id="d-kb-detail">-</div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Budget AI Oggi</span><span style="font-size:24px">&#128176;</span></div>
        <div class="card-value" id="d-budget">$0.00</div>
        <div class="card-sub" id="d-budget-detail">-</div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Feedback</span><span style="font-size:24px">&#128200;</span></div>
        <div class="card-value" id="d-accuracy">-</div>
        <div class="card-sub" id="d-fb-detail">-</div>
      </div>
    </div>
    <div class="settings-section">
      <h3>&#128220; Attivita' Recente</h3>
      <div id="d-recent-audit" style="max-height:300px;overflow-y:auto"></div>
    </div>
  </div>

  <!-- Chat -->
  <div class="page" id="page-chat">
    <div class="page-title">Chat</div>
    <div class="chat-container">
      <div class="chat-messages" id="chat-messages">
        <div class="msg bot">Ciao! Sono WorkMind. Scrivimi una domanda o usa /help per i comandi.</div>
      </div>
      <div class="chat-input-row">
        <input class="chat-input" id="chat-input" placeholder="Scrivi un messaggio..." autocomplete="off"
               onkeydown="if(event.key==='Enter')sendChat()">
        <button class="chat-send" onclick="sendChat()" id="chat-send-btn">&#9654;</button>
      </div>
    </div>
  </div>

  <!-- Audit -->
  <div class="page" id="page-audit">
    <div class="page-title">Audit Trail</div>
    <div class="settings-section">
      <table class="audit-table">
        <thead><tr><th>Quando</th><th>Tipo</th><th class="hide-mobile">Attore</th><th class="hide-mobile">Dettaglio</th></tr></thead>
        <tbody id="audit-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Features -->
  <div class="page" id="page-features">
    <div class="page-title">Richieste Funzionalita'</div>
    <div class="settings-section">
      <h3>&#10133; Nuova Richiesta</h3>
      <div style="display:flex;gap:8px">
        <input class="form-input" id="feature-input" placeholder="Descrivi la funzionalita' che vorresti..." style="flex:1">
        <button class="btn-primary" onclick="submitFeature()">Invia</button>
      </div>
      <div id="feature-result" style="margin-top:12px;font-size:13px"></div>
    </div>
    <div class="settings-section">
      <h3>&#128203; Richieste</h3>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn-primary" onclick="loadFeatures()" style="padding:6px 16px;font-size:13px">Aggiorna</button>
        <select class="form-select" id="feature-filter" onchange="loadFeatures()" style="width:auto">
          <option value="">Tutte</option>
          <option value="pending">In attesa</option>
          <option value="issue_created">Issue creata</option>
          <option value="approved">Approvate</option>
          <option value="rejected">Rifiutate</option>
          <option value="blocked">Bloccate</option>
          <option value="auto_done">Auto</option>
        </select>
      </div>
      <div id="features-list"></div>
    </div>
  </div>

  <!-- WhatsApp -->
  <div class="page" id="page-whatsapp">
    <div class="page-title">WhatsApp Business</div>

    <!-- Stats -->
    <div class="settings-section">
      <h3>&#128200; Statistiche</h3>
      <div id="wa-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px">
        <div class="card"><div class="card-value" id="wa-contacts">-</div><div class="card-label">Contatti</div></div>
        <div class="card"><div class="card-value" id="wa-consented">-</div><div class="card-label">Con consenso</div></div>
        <div class="card"><div class="card-value" id="wa-orders-total">-</div><div class="card-label">Ordini totali</div></div>
        <div class="card"><div class="card-value" id="wa-orders-pending">-</div><div class="card-label">Ordini in attesa</div></div>
      </div>
    </div>

    <!-- Invia messaggio -->
    <div class="settings-section">
      <h3>&#9993; Invia Messaggio</h3>
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <input class="form-input" id="wa-send-phone" placeholder="+39..." style="width:200px">
        <input class="form-input" id="wa-send-text" placeholder="Messaggio..." style="flex:1">
        <button class="btn-primary" onclick="waSend()">Invia</button>
      </div>
    </div>

    <!-- Ordini -->
    <div class="settings-section">
      <h3>&#128230; Ordini Recenti</h3>
      <button class="btn-primary" onclick="loadWaOrders()" style="padding:6px 16px;font-size:13px;margin-bottom:12px">Aggiorna</button>
      <div id="wa-orders-list"></div>
    </div>

    <!-- Contatti -->
    <div class="settings-section">
      <h3>&#128100; Contatti</h3>
      <button class="btn-primary" onclick="loadWaContacts()" style="padding:6px 16px;font-size:13px;margin-bottom:12px">Aggiorna</button>
      <div id="wa-contacts-list"></div>
    </div>

    <!-- Policy -->
    <div class="settings-section">
      <h3>&#128274; Policy &amp; Privacy</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Ordini abilitati</label>
          <select class="form-select" id="wa-orders-enabled"><option value="true">Si</option><option value="false">No</option></select>
        </div>
        <div class="form-group">
          <label class="form-label">Conferma ordini richiesta</label>
          <select class="form-select" id="wa-order-confirm"><option value="true">Si</option><option value="false">No</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Solo orario lavorativo</label>
          <select class="form-select" id="wa-biz-hours"><option value="false">No</option><option value="true">Si</option></select>
        </div>
        <div class="form-group">
          <label class="form-label">Max valore ordine (0=illimitato)</label>
          <input class="form-input" id="wa-max-order" type="number" value="0">
        </div>
      </div>
      <button class="btn-primary" onclick="saveWaPolicy()" style="margin-top:8px">Salva Policy</button>
    </div>
  </div>

  <!-- Users (admin only) -->
  <div class="page" id="page-users">
    <div class="page-title">Gestione Utenti</div>

    <!-- Invita utente -->
    <div class="settings-section">
      <h3>&#10133; Invita Utente</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Email</label>
          <input class="form-input" id="inv-email" type="email" placeholder="utente@esempio.it">
        </div>
        <div class="form-group">
          <label class="form-label">Nome</label>
          <input class="form-input" id="inv-name" placeholder="Mario Rossi">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Ruolo</label>
          <select class="form-select" id="inv-role">
            <option value="user">Utente</option>
            <option value="admin">Amministratore</option>
          </select>
        </div>
        <div class="form-group" style="display:flex;align-items:flex-end;gap:8px">
          <button class="btn-primary" onclick="inviteUser()">Invita via Email</button>
          <button class="btn-primary" onclick="createUserDirect()" style="background:var(--text2)">Crea Diretto</button>
        </div>
      </div>
    </div>

    <!-- Lista utenti -->
    <div class="settings-section">
      <h3>&#128101; Utenti Registrati</h3>
      <button class="btn-primary" onclick="loadUsers()" style="padding:6px 16px;font-size:13px;margin-bottom:12px">Aggiorna</button>
      <div id="users-list"></div>
    </div>

    <!-- SMTP Test -->
    <div class="settings-section">
      <h3>&#9993; SMTP</h3>
      <div style="display:flex;gap:12px;align-items:center">
        <button class="btn-primary" onclick="testSmtp()">Testa Connessione SMTP</button>
        <span id="smtp-result" style="font-size:13px"></span>
      </div>
    </div>

    <!-- Profilo personale -->
    <div class="settings-section">
      <h3>&#128274; La Tua Password</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Nuova password</label>
          <input class="form-input" id="my-new-pw" type="password" placeholder="Min 8 caratteri">
        </div>
        <div class="form-group">
          <label class="form-label">Conferma</label>
          <input class="form-input" id="my-confirm-pw" type="password" placeholder="Ripeti password">
        </div>
      </div>
      <button class="btn-primary" onclick="changeMyPassword()">Cambia Password</button>
    </div>
  </div>

  <!-- Settings -->
  <div class="page" id="page-settings">
    <div class="page-title">Impostazioni</div>

    <!-- Azienda -->
    <div class="settings-section">
      <h3>&#127970; Azienda</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Nome azienda</label>
          <input class="form-input" id="s-company-name" placeholder="La Mia Azienda Srl">
        </div>
        <div class="form-group">
          <label class="form-label">Settore</label>
          <select class="form-select" id="s-sector">
            <option value="manifatturiero">Manifatturiero</option>
            <option value="commercio">Commercio</option>
            <option value="servizi">Servizi</option>
            <option value="edilizia">Edilizia</option>
            <option value="sviluppo">Sviluppo</option>
            <option value="altro">Altro</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Email supervisore</label>
          <input class="form-input" id="s-supervisor-email" type="email" placeholder="mario@azienda.it">
        </div>
        <div class="form-group">
          <label class="form-label">Fuso orario</label>
          <input class="form-input" id="s-timezone" value="Europe/Rome">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Report giornaliero (ora)</label>
          <input class="form-input" id="s-report-time" type="time" value="22:00">
        </div>
        <div class="form-group">
          <label class="form-label">Report settimanale (giorno)</label>
          <select class="form-select" id="s-report-day">
            <option value="monday">Lunedi</option><option value="tuesday">Martedi</option>
            <option value="wednesday">Mercoledi</option><option value="thursday">Giovedi</option>
            <option value="friday" selected>Venerdi</option><option value="saturday">Sabato</option>
            <option value="sunday">Domenica</option>
          </select>
        </div>
      </div>
    </div>

    <!-- API Keys -->
    <div class="settings-section">
      <h3>&#128273; API Keys</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">DeepSeek API Key</label>
          <input class="form-input" id="s-deepseek-key" type="password" placeholder="sk-...">
        </div>
        <div class="form-group">
          <label class="form-label">Anthropic API Key</label>
          <input class="form-input" id="s-anthropic-key" type="password" placeholder="sk-ant-...">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Telegram Bot Token</label>
          <input class="form-input" id="s-telegram-token" type="password" placeholder="123456:ABC...">
        </div>
        <div class="form-group">
          <label class="form-label">Mem0 AI Memory</label>
          <input class="form-input" id="s-mem0-status" disabled value="Locale (DeepSeek + Qdrant)" style="background:#f0f0f0;color:var(--green)">
        </div>
      </div>
    </div>

    <!-- Cartelle di rete -->
    <div class="settings-section">
      <h3>&#128193; Cartelle di Rete (SMB)</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Username rete</label>
          <input class="form-input" id="s-smb-user" placeholder="workmind">
        </div>
        <div class="form-group">
          <label class="form-label">Password rete</label>
          <input class="form-input" id="s-smb-pass" type="password">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Dominio</label>
          <input class="form-input" id="s-smb-domain" placeholder="WORKGROUP">
        </div>
        <div class="form-group"></div>
      </div>
      <label class="form-label" style="margin-top:8px">Percorsi condivisi</label>
      <div class="tag-list" id="shares-list"></div>
      <div class="add-row">
        <input class="form-input" id="share-input" placeholder="\\192.168.1.5\Documenti">
        <button class="btn-primary" onclick="addShare()">Aggiungi</button>
      </div>
    </div>

    <!-- Cartelle locali -->
    <div class="settings-section">
      <h3>&#128194; Cartelle Locali da Monitorare</h3>
      <div class="tag-list" id="watchdirs-list"></div>
      <div class="add-row">
        <input class="form-input" id="watchdir-input" placeholder="/home/emanuele/documenti">
        <button class="btn-primary" onclick="addWatchDir()">Aggiungi</button>
      </div>
    </div>

    <!-- Email -->
    <div class="settings-section">
      <h3>&#9993; Email</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Indirizzo email</label>
          <input class="form-input" id="s-email-addr" type="email" placeholder="info@azienda.it">
        </div>
        <div class="form-group">
          <label class="form-label">Provider</label>
          <select class="form-select" id="s-email-provider">
            <option value="imap">IMAP/POP3</option>
            <option value="office365">Office 365</option>
            <option value="exchange_onprem">Exchange</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Username</label>
          <input class="form-input" id="s-email-user" placeholder="info@azienda.it">
        </div>
        <div class="form-group">
          <label class="form-label">Password</label>
          <input class="form-input" id="s-email-pass" type="password">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Server IMAP</label>
          <input class="form-input" id="s-imap-host" placeholder="mail.azienda.it">
        </div>
        <div class="form-group">
          <label class="form-label">Porta IMAP</label>
          <input class="form-input" id="s-imap-port" type="number" value="993">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Server POP3</label>
          <input class="form-input" id="s-pop3-host" placeholder="pop.azienda.it">
        </div>
        <div class="form-group">
          <label class="form-label">Porta POP3</label>
          <input class="form-input" id="s-pop3-port" type="number" value="995">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Server SMTP</label>
          <input class="form-input" id="s-smtp-host" placeholder="smtp.azienda.it">
        </div>
        <div class="form-group">
          <label class="form-label">Porta SMTP</label>
          <input class="form-input" id="s-smtp-port" type="number" value="587">
        </div>
      </div>
    </div>

    <!-- Database -->
    <div class="settings-section">
      <h3>&#128451; Database Gestionale</h3>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Tipo</label>
          <select class="form-select" id="s-db-type">
            <option value="sqlserver">SQL Server</option>
            <option value="mysql">MySQL</option>
            <option value="postgres">PostgreSQL</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Host</label>
          <input class="form-input" id="s-db-host" placeholder="192.168.1.10">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Porta</label>
          <input class="form-input" id="s-db-port" type="number" value="1433">
        </div>
        <div class="form-group">
          <label class="form-label">Nome database</label>
          <input class="form-input" id="s-db-name" placeholder="GestionaleDB">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Utente (read-only)</label>
          <input class="form-input" id="s-db-user" placeholder="workmind_reader">
        </div>
        <div class="form-group"></div>
      </div>
    </div>

    <!-- Save Button -->
    <div class="btn-save-row">
      <button class="btn-primary" onclick="saveSettings()" style="padding:12px 40px;font-size:16px">
        Salva Impostazioni
      </button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- Bottom Nav — visibile solo su mobile -->
<nav class="bottom-nav" id="bottom-nav">
  <div class="bottom-nav-inner">
    <div class="bottom-nav-item active" id="bn-dashboard" onclick="showPage('dashboard')">
      <span class="bn-icon">&#9673;</span>
      <span>Home</span>
    </div>
    <div class="bottom-nav-item" id="bn-chat" onclick="showPage('chat')">
      <span class="bn-icon">&#128172;</span>
      <span>Chat</span>
    </div>
    <div class="bottom-nav-item" id="bn-features" onclick="showPage('features')">
      <span class="bn-icon">&#128161;</span>
      <span>Idee</span>
    </div>
    <div class="bottom-nav-item" id="bn-audit" onclick="showPage('audit')">
      <span class="bn-icon">&#9776;</span>
      <span>Log</span>
    </div>
    <div class="bottom-nav-item admin-only" id="bn-settings" onclick="showPage('settings')">
      <span class="bn-icon">&#9881;</span>
      <span>Config</span>
    </div>
  </div>
</nav>

<script>
// ── Navigation ───────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  const idx = {dashboard:0, chat:1, audit:2, features:3, whatsapp:4, users:5, settings:6}[name];
  const navItems = document.querySelectorAll('.nav-item');
  if (idx !== undefined && navItems[idx]) navItems[idx].classList.add('active');
  // Sync bottom nav
  document.querySelectorAll('.bottom-nav-item').forEach(el => el.classList.remove('active'));
  const bn = document.getElementById('bn-' + name);
  if (bn) bn.classList.add('active');
  if (name === 'audit') loadAudit();
  if (name === 'features') loadFeatures();
  if (name === 'whatsapp') loadWhatsApp();
  if (name === 'users') loadUsers();
}

// ── Toast ────────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Dashboard ────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const [status, budget, audit] = await Promise.all([
      fetch('/api/status').then(r=>r.json()),
      fetch('/api/budget').then(r=>r.json()),
      fetch('/api/audit').then(r=>r.json()),
    ]);
    document.getElementById('d-status').textContent = status.status === 'online' ? 'Online' : 'Offline';
    document.getElementById('d-uptime').textContent = 'Uptime: ' + status.uptime;
    document.getElementById('footer-uptime').textContent = status.uptime;

    const kb = status.kb || {};
    const total = (kb.facts||0) + (kb.corrections||0) + (kb.processes||0) + (kb.glossary_terms||0);
    document.getElementById('d-kb-total').textContent = total;
    document.getElementById('d-kb-detail').textContent =
      `${kb.facts||0} fatti, ${kb.corrections||0} correzioni, ${kb.processes||0} processi`;

    const ds = budget.deepseek || {}; const cl = budget.claude || {};
    const totalCost = (ds.cost_usd||0) + (cl.cost_usd||0);
    document.getElementById('d-budget').textContent = '$' + totalCost.toFixed(4);
    document.getElementById('d-budget-detail').textContent =
      `DeepSeek: ${ds.calls||0} calls | Claude: ${cl.calls||0} calls`;

    const fb = status.feedback || {};
    document.getElementById('d-accuracy').textContent =
      fb.total > 0 ? ((fb.accuracy_rate||0)*100).toFixed(0) + '%' : '-';
    document.getElementById('d-fb-detail').textContent =
      `${fb.confirmed||0} confermati, ${fb.corrected||0} corretti, ${fb.rejected||0} rifiutati`;

    // Recent audit
    const el = document.getElementById('d-recent-audit');
    el.innerHTML = (audit||[]).slice(0,8).map(e =>
      `<div style="padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:13px">
        <span style="color:var(--text2)">${(e.timestamp||'').slice(11,16)}</span>
        <span class="badge badge-blue" style="margin:0 8px">${e.event_type||''}</span>
        ${e.summary||''}
      </div>`
    ).join('') || '<div style="color:var(--text2);padding:16px">Nessuna attivita recente</div>';
  } catch(err) { console.error(err); }
}

// ── Audit ─────────────────────────────────────────────────────
async function loadAudit() {
  const data = await fetch('/api/audit').then(r=>r.json());
  document.getElementById('audit-tbody').innerHTML = (data||[]).map(e => {
    const ts = (e.timestamp||'').replace('T',' ').slice(0,16);
    const evType = (e.event_type||'').replace('AuditEventType.','');
    return `<tr>
      <td style="white-space:nowrap">${ts}</td>
      <td><span class="badge badge-blue">${evType}</span></td>
      <td class="hide-mobile">${e.actor||''}</td>
      <td class="hide-mobile" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.summary||''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan=4 style="text-align:center;color:var(--text2)">Nessun evento</td></tr>';
}

// ── Chat ─────────────────────────────────────────────────────
async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  const messages = document.getElementById('chat-messages');
  messages.innerHTML += `<div class="msg user">${escapeHtml(msg)}</div>`;
  messages.innerHTML += `<div class="msg bot typing" id="typing">Sto pensando...</div>`;
  messages.scrollTop = messages.scrollHeight;

  document.getElementById('chat-send-btn').disabled = true;

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({message: msg})
    });
    const data = await resp.json();
    document.getElementById('typing').remove();
    messages.innerHTML += `<div class="msg bot">${escapeHtml(data.reply||'...')}</div>`;
  } catch(err) {
    document.getElementById('typing').remove();
    messages.innerHTML += `<div class="msg bot">Errore di connessione.</div>`;
  }
  document.getElementById('chat-send-btn').disabled = false;
  messages.scrollTop = messages.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

// ── Settings ─────────────────────────────────────────────────
let networkShares = [];
let watchDirs = [];

async function loadSettings() {
  const s = await fetch('/api/settings').then(r=>r.json());
  document.getElementById('s-company-name').value = s.company_name || '';
  document.getElementById('s-sector').value = s.sector || 'altro';
  document.getElementById('s-supervisor-email').value = s.supervisor_email || '';
  document.getElementById('s-timezone').value = s.timezone || 'Europe/Rome';
  document.getElementById('s-report-time').value = s.report_time || '22:00';
  document.getElementById('s-report-day').value = s.report_day || 'friday';
  document.getElementById('s-deepseek-key').value = s.deepseek_api_key || '';
  document.getElementById('s-anthropic-key').value = s.anthropic_api_key || '';
  document.getElementById('s-telegram-token').value = s.telegram_token || '';
  document.getElementById('s-smb-user').value = s.smb_username || '';
  document.getElementById('s-smb-pass').value = s.smb_password || '';
  document.getElementById('s-smb-domain').value = s.smb_domain || '';
  document.getElementById('s-email-addr').value = s.email_address || '';
  document.getElementById('s-email-provider').value = s.email_provider || 'imap';
  document.getElementById('s-email-user').value = s.email_username || '';
  document.getElementById('s-email-pass').value = s.email_password || '';
  document.getElementById('s-imap-host').value = s.email_imap_host || '';
  document.getElementById('s-imap-port').value = s.email_imap_port || 993;
  document.getElementById('s-pop3-host').value = s.email_pop3_host || '';
  document.getElementById('s-pop3-port').value = s.email_pop3_port || 995;
  document.getElementById('s-smtp-host').value = s.email_smtp_host || '';
  document.getElementById('s-smtp-port').value = s.email_smtp_port || 587;
  document.getElementById('s-db-type').value = s.db_type || 'sqlserver';
  document.getElementById('s-db-host').value = s.db_host || '';
  document.getElementById('s-db-port').value = s.db_port || 1433;
  document.getElementById('s-db-name').value = s.db_name || '';
  document.getElementById('s-db-user').value = s.db_user || '';
  networkShares = s.network_shares || [];
  watchDirs = s.watch_dirs || [];
  renderShares(); renderWatchDirs();
}

function renderShares() {
  document.getElementById('shares-list').innerHTML = networkShares.map((s,i) =>
    `<div class="tag">${s} <span class="remove" onclick="networkShares.splice(${i},1);renderShares()">&times;</span></div>`
  ).join('');
}
function renderWatchDirs() {
  document.getElementById('watchdirs-list').innerHTML = watchDirs.map((s,i) =>
    `<div class="tag">${s} <span class="remove" onclick="watchDirs.splice(${i},1);renderWatchDirs()">&times;</span></div>`
  ).join('');
}
function addShare() {
  const v = document.getElementById('share-input').value.trim();
  if (v) { networkShares.push(v); renderShares(); document.getElementById('share-input').value = ''; }
}
function addWatchDir() {
  const v = document.getElementById('watchdir-input').value.trim();
  if (v) { watchDirs.push(v); renderWatchDirs(); document.getElementById('watchdir-input').value = ''; }
}

async function saveSettings() {
  const data = {
    company_name: document.getElementById('s-company-name').value,
    sector: document.getElementById('s-sector').value,
    supervisor_email: document.getElementById('s-supervisor-email').value,
    timezone: document.getElementById('s-timezone').value,
    language: 'it',
    report_time: document.getElementById('s-report-time').value,
    report_day: document.getElementById('s-report-day').value,
    deepseek_api_key: document.getElementById('s-deepseek-key').value,
    anthropic_api_key: document.getElementById('s-anthropic-key').value,
    telegram_token: document.getElementById('s-telegram-token').value,
    smb_username: document.getElementById('s-smb-user').value,
    smb_password: document.getElementById('s-smb-pass').value,
    smb_domain: document.getElementById('s-smb-domain').value,
    network_shares: networkShares,
    watch_dirs: watchDirs,
    email_enabled: !!document.getElementById('s-imap-host').value,
    email_provider: document.getElementById('s-email-provider').value,
    email_address: document.getElementById('s-email-addr').value,
    email_username: document.getElementById('s-email-user').value,
    email_password: document.getElementById('s-email-pass').value,
    email_imap_host: document.getElementById('s-imap-host').value,
    email_imap_port: parseInt(document.getElementById('s-imap-port').value) || 993,
    email_pop3_host: document.getElementById('s-pop3-host').value,
    email_pop3_port: parseInt(document.getElementById('s-pop3-port').value) || 995,
    email_smtp_host: document.getElementById('s-smtp-host').value,
    email_smtp_port: parseInt(document.getElementById('s-smtp-port').value) || 587,
    db_enabled: !!document.getElementById('s-db-host').value,
    db_type: document.getElementById('s-db-type').value,
    db_host: document.getElementById('s-db-host').value,
    db_port: parseInt(document.getElementById('s-db-port').value) || 1433,
    db_name: document.getElementById('s-db-name').value,
    db_user: document.getElementById('s-db-user').value,
  };
  await fetch('/api/settings', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(data)
  });
  showToast('Impostazioni salvate!');
}

// ── Users ───────────────────────────────────────────────────
async function loadUsers() {
  try {
    const r = await fetch('/api/users');
    if (r.status === 403) { document.getElementById('users-list').innerHTML = '<p style="color:var(--red)">Accesso riservato agli admin.</p>'; return; }
    const d = await r.json();
    const list = document.getElementById('users-list');
    if (!d.users || !d.users.length) { list.innerHTML = '<p>Nessun utente.</p>'; return; }
    list.innerHTML = d.users.map(u => {
      const role = u.role === 'admin' ? '<span style="color:var(--accent);font-weight:600">ADMIN</span>' : '<span style="color:var(--text2)">USER</span>';
      const status = u.active !== false ? '<span style="color:var(--green)">Attivo</span>' : '<span style="color:var(--red)">Disattivato</span>';
      const lastLogin = u.last_login ? new Date(u.last_login).toLocaleString('it-IT') : 'Mai';
      const isDefault = u.email === 'toprecensione@gmail.com';
      const actions = !isDefault ? `
        <button onclick="toggleUser('${u.email}', ${u.active === false})" style="padding:3px 8px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--card);cursor:pointer">${u.active !== false ? 'Disattiva' : 'Attiva'}</button>
        <button onclick="deleteUser('${u.email}')" style="padding:3px 8px;font-size:11px;border:1px solid var(--red);border-radius:6px;background:var(--card);color:var(--red);cursor:pointer">Elimina</button>
        <button onclick="resetUserPw('${u.email}')" style="padding:3px 8px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--card);cursor:pointer">Reset PW</button>
      ` : '';
      return `<div style="background:var(--bg-primary,#fafafa);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <strong>${u.name}</strong> ${role}<br>
            <span style="font-size:12px;color:var(--text2)">${u.email}</span>
          </div>
          <div style="text-align:right;font-size:12px">
            ${status}<br>
            <span style="color:var(--text2)">Ultimo login: ${lastLogin}</span>
          </div>
        </div>
        <div style="margin-top:6px;display:flex;gap:6px">${actions}</div>
      </div>`;
    }).join('');
  } catch(e) {}
}

async function inviteUser() {
  const email = document.getElementById('inv-email').value.trim();
  const name = document.getElementById('inv-name').value.trim();
  const role = document.getElementById('inv-role').value;
  if (!email) return;
  const r = await fetch('/api/users/invite', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email, name, role})
  });
  const d = await r.json();
  if (d.ok) {
    showToast('Invito inviato a ' + email);
    document.getElementById('inv-email').value = '';
    document.getElementById('inv-name').value = '';
    loadUsers();
  } else {
    showToast('Errore: ' + (d.error || 'invito fallito'));
  }
}

async function createUserDirect() {
  const email = document.getElementById('inv-email').value.trim();
  const name = document.getElementById('inv-name').value.trim();
  const role = document.getElementById('inv-role').value;
  if (!email) return;
  const pw = prompt('Password per il nuovo utente (min 8 caratteri):');
  if (!pw || pw.length < 8) { showToast('Password troppo corta'); return; }
  const r = await fetch('/api/users/create', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email, name, role, password: pw})
  });
  const d = await r.json();
  if (d.ok) {
    showToast('Utente creato: ' + email);
    document.getElementById('inv-email').value = '';
    document.getElementById('inv-name').value = '';
    loadUsers();
  } else {
    showToast('Errore: ' + (d.error || 'creazione fallita'));
  }
}

async function toggleUser(email, activate) {
  await fetch('/api/users/update', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email, active: activate})
  });
  showToast(activate ? 'Utente attivato' : 'Utente disattivato');
  loadUsers();
}

async function deleteUser(email) {
  if (!confirm('Eliminare ' + email + '?')) return;
  const r = await fetch('/api/users/delete', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email})
  });
  const d = await r.json();
  showToast(d.ok ? 'Utente eliminato' : 'Errore: ' + (d.error || ''));
  loadUsers();
}

async function resetUserPw(email) {
  const choice = confirm('OK = Invia email reset\nAnnulla = Imposta manualmente');
  if (choice) {
    await fetch('/api/users/reset-password', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email})
    });
    showToast('Email di reset inviata a ' + email);
  } else {
    const pw = prompt('Nuova password (min 8 caratteri):');
    if (!pw || pw.length < 8) { showToast('Password troppo corta'); return; }
    await fetch('/api/users/reset-password', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email, password: pw})
    });
    showToast('Password cambiata per ' + email);
  }
}

async function testSmtp() {
  document.getElementById('smtp-result').textContent = 'Test in corso...';
  const r = await fetch('/api/smtp/test', {method:'POST'});
  const d = await r.json();
  const el = document.getElementById('smtp-result');
  if (d.ok) {
    el.textContent = 'SMTP OK: ' + d.host + ':' + d.port;
    el.style.color = 'var(--green)';
  } else {
    el.textContent = 'Errore: ' + (d.error || 'connessione fallita');
    el.style.color = 'var(--red)';
  }
}

async function changeMyPassword() {
  const pw = document.getElementById('my-new-pw').value;
  const confirm = document.getElementById('my-confirm-pw').value;
  if (pw.length < 8) { showToast('Password troppo corta (min 8)'); return; }
  if (pw !== confirm) { showToast('Le password non coincidono'); return; }
  const me = await (await fetch('/api/me')).json();
  await fetch('/api/users/reset-password', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email: me.user.email, password: pw})
  });
  showToast('Password cambiata!');
  document.getElementById('my-new-pw').value = '';
  document.getElementById('my-confirm-pw').value = '';
}

// ── WhatsApp ────────────────────────────────────────────────
async function loadWhatsApp() {
  loadWaStats();
  loadWaOrders();
  loadWaContacts();
  loadWaPolicy();
}

async function loadWaStats() {
  try {
    const r = await fetch('/api/whatsapp/stats');
    const d = await r.json();
    document.getElementById('wa-contacts').textContent = d.total_contacts || 0;
    document.getElementById('wa-consented').textContent = d.consented_chat || 0;
    document.getElementById('wa-orders-total').textContent = d.total_orders || 0;
    document.getElementById('wa-orders-pending').textContent = d.pending_orders || 0;
  } catch(e) {
    document.getElementById('wa-contacts').textContent = '-';
  }
}

async function loadWaOrders() {
  try {
    const r = await fetch('/api/whatsapp/orders');
    const d = await r.json();
    const list = document.getElementById('wa-orders-list');
    if (!d.orders || !d.orders.length) { list.innerHTML = '<p style="color:var(--text-secondary)">Nessun ordine.</p>'; return; }
    const icons = {pending:'&#9203;',confirmed:'&#9989;',cancelled:'&#10060;',shipped:'&#128230;',delivered:'&#127881;',completed:'&#9989;'};
    list.innerHTML = d.orders.map(o => {
      const icon = icons[o.status] || '&#10067;';
      const date = new Date(o.created_at).toLocaleString('it-IT');
      const ph = o.phone ? o.phone.slice(0,3)+'***'+o.phone.slice(-3) : '?';
      return `<div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong>#${o.id} — ${o.description.slice(0,50)}</strong>
          <span style="font-size:12px">${icon} ${o.status}</span>
        </div>
        <div style="font-size:11px;color:var(--text-secondary);margin-top:4px">${ph} — ${date}</div>
      </div>`;
    }).join('');
  } catch(e) {}
}

async function loadWaContacts() {
  try {
    const r = await fetch('/api/whatsapp/contacts');
    const d = await r.json();
    const list = document.getElementById('wa-contacts-list');
    if (!d.contacts || !d.contacts.length) { list.innerHTML = '<p style="color:var(--text-secondary)">Nessun contatto.</p>'; return; }
    list.innerHTML = d.contacts.map(c => {
      const ph = c.phone ? c.phone.slice(0,3)+'***'+c.phone.slice(-3) : '?';
      const last = new Date(c.last_seen).toLocaleString('it-IT');
      return `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px">
        <span><strong>${c.name || ph}</strong> (${ph})</span>
        <span style="color:var(--text-secondary)">${c.messages} msg — ${last}</span>
      </div>`;
    }).join('');
  } catch(e) {}
}

async function loadWaPolicy() {
  try {
    const r = await fetch('/api/whatsapp/policy');
    const d = await r.json();
    document.getElementById('wa-orders-enabled').value = String(d.enabled !== false);
    document.getElementById('wa-order-confirm').value = String(d.require_confirmation !== false);
    document.getElementById('wa-biz-hours').value = String(!!d.business_hours_only);
    document.getElementById('wa-max-order').value = d.max_order_value || 0;
  } catch(e) {}
}

async function saveWaPolicy() {
  await fetch('/api/whatsapp/policy', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      orders_enabled: document.getElementById('wa-orders-enabled').value === 'true',
      order_require_confirmation: document.getElementById('wa-order-confirm').value === 'true',
      business_hours_only: document.getElementById('wa-biz-hours').value === 'true',
      max_order_value: parseFloat(document.getElementById('wa-max-order').value) || 0,
    })
  });
  showToast('Policy WhatsApp salvata!');
}

async function waSend() {
  const phone = document.getElementById('wa-send-phone').value.trim();
  const text = document.getElementById('wa-send-text').value.trim();
  if (!phone || !text) return;
  const r = await fetch('/api/whatsapp/send', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phone, text})
  });
  const d = await r.json();
  if (d.ok) {
    showToast('Messaggio inviato!');
    document.getElementById('wa-send-text').value = '';
  } else {
    showToast('Errore: ' + (d.error || 'invio fallito'));
  }
}

// ── Features ────────────────────────────────────────────────
async function loadFeatures() {
  const filter = document.getElementById('feature-filter').value;
  const url = filter ? `/api/features?status=${filter}` : '/api/features';
  const r = await fetch(url);
  const data = await r.json();
  const list = document.getElementById('features-list');
  if (!data.requests || data.requests.length === 0) {
    list.innerHTML = '<p style="color:var(--text-secondary);padding:16px">Nessuna richiesta trovata.</p>';
    return;
  }
  const levelColors = {auto:'var(--green)',review:'var(--yellow)',block:'var(--red)'};
  const statusLabels = {
    pending:'In attesa',classified:'Classificata',approved:'Approvata',
    rejected:'Rifiutata',issue_created:'Issue creata',pr_created:'PR creata',
    deployed:'Deployata',auto_done:'Eseguita',blocked:'Bloccata'
  };
  list.innerHTML = data.requests.map(req => {
    const lc = levelColors[req.level] || 'var(--text-secondary)';
    const sl = statusLabels[req.status] || req.status;
    const date = new Date(req.created_at).toLocaleString('it-IT');
    const canAct = ['pending','classified','issue_created'].includes(req.status);
    const actions = canAct ? `
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="btn-primary" onclick="approveFeature(${req.id})" style="padding:4px 12px;font-size:12px">Approva</button>
        <button class="btn-primary" onclick="rejectFeature(${req.id})" style="padding:4px 12px;font-size:12px;background:var(--red)">Rifiuta</button>
      </div>` : '';
    const ghLink = req.github_issue ? `<a href="${req.github_issue.url}" target="_blank" style="color:var(--accent);font-size:12px">GitHub #${req.github_issue.number}</a>` : '';
    return `<div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong style="font-size:14px">#${req.id} — ${req.title}</strong>
        <span style="font-size:11px;color:${lc};font-weight:600;text-transform:uppercase">${req.level}</span>
      </div>
      <p style="font-size:13px;color:var(--text-secondary);margin:4px 0">${req.description}</p>
      <div style="display:flex;gap:12px;align-items:center;font-size:11px;color:var(--text-secondary)">
        <span>${sl}</span><span>${date}</span><span>${req.submitted_by}</span>${ghLink}
      </div>
      ${actions}
    </div>`;
  }).join('');
}

async function submitFeature() {
  const input = document.getElementById('feature-text');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  showToast('Invio richiesta...');
  const r = await fetch('/api/features/submit', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text})
  });
  const data = await r.json();
  if (data.request) {
    const lvl = data.request.level.toUpperCase();
    showToast(`Richiesta #${data.request.id} classificata: ${lvl}`);
  }
  loadFeatures();
}

async function approveFeature(id) {
  await fetch('/api/features/approve', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})
  });
  showToast(`Richiesta #${id} approvata`);
  loadFeatures();
}

async function rejectFeature(id) {
  const reason = prompt('Motivo del rifiuto (opzionale):') || '';
  await fetch('/api/features/reject', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id, reason})
  });
  showToast(`Richiesta #${id} rifiutata`);
  loadFeatures();
}

// ── Init ─────────────────────────────────────────────────────
// Nascondi pagine admin se utente non e' admin
(async function initAuth() {
  try {
    const r = await fetch('/api/me');
    const d = await r.json();
    if (!d.is_admin) {
      document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
    }
    // Mostra nome utente nel footer
    const footer = document.querySelector('.sidebar-footer');
    if (footer && d.user) {
      const nameEl = document.createElement('span');
      nameEl.style.cssText = 'display:block;font-weight:600;font-size:12px;margin-bottom:4px';
      nameEl.textContent = d.user.name + (d.is_admin ? ' (Admin)' : '');
      footer.insertBefore(nameEl, footer.firstChild);
    }
  } catch(e) {}
})();
loadDashboard();
loadSettings();
setInterval(loadDashboard, 15000);

// ── PWA: Service Worker ───────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .catch(err => console.log('SW:', err));
  });
}
</script>
</body>
</html>
"""

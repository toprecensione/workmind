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

from flask import Flask, jsonify, redirect, request, render_template_string, session, url_for

from config.settings import config, DATA_DIR
from config.company import get_company_config, load_company_config, CompanyConfig
from ai_client.client import get_ai_client, AIMessage, ModelRole
from ai_client.budget import get_budget
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit
from mindwork.feedback import get_feedback
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("interface.web_ui")

_SETTINGS_FILE = DATA_DIR / "ui_settings.json"

_DEFAULT_USERNAME = "admin"
_DEFAULT_PASSWORD = "workmind"


def _hash_password(password: str) -> str:
    """Hash a password with SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _get_credentials() -> tuple[str, str]:
    """Return (username, password_hash) from ui_settings.json or defaults."""
    if _SETTINGS_FILE.exists():
        try:
            saved = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            username = saved.get("auth_username", _DEFAULT_USERNAME)
            pw_hash = saved.get("auth_password_hash", _hash_password(_DEFAULT_PASSWORD))
            return username, pw_hash
        except Exception:
            pass
    return _DEFAULT_USERNAME, _hash_password(_DEFAULT_PASSWORD)


def _require_auth(f):
    """Decorator that redirects to /login if not authenticated."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect("/login")
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
        self._start_time = time.time()
        self._register_routes()

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
                username = request.form.get("username", "")
                password = request.form.get("password", "")
                exp_user, exp_hash = _get_credentials()
                if username == exp_user and _hash_password(password) == exp_hash:
                    session["authenticated"] = True
                    session["username"] = username
                    return redirect("/")
                error = "Credenziali non valide"
            return render_template_string(_LOGIN_TEMPLATE, error=error)

        @app.route("/logout")
        def logout():
            session.clear()
            return redirect("/login")

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

        # ── API: Chat ─────────────────────────────────────────────────────
        @app.route("/api/chat", methods=["POST"])
        @_require_auth
        def api_chat():
            data = request.get_json()
            message = data.get("message", "").strip()
            if not message:
                return jsonify({"reply": "Scrivi un messaggio."})

            # Handle slash commands
            if message.startswith("/"):
                reply = self._handle_command(message)
                return jsonify({"reply": reply})

            # Chat with DeepSeek (RAG + Supermemory enhanced)
            try:
                context = self._kb.build_context_prompt()
                # RAG: ricerca semantica nei documenti indicizzati (ChromaDB)
                rag_context = ""
                try:
                    from storage.vector_store import get_vector_store
                    rag_context = get_vector_store().build_rag_context(message)
                except Exception:
                    pass

                # Mem0: memoria avanzata locale (DeepSeek + HuggingFace + Qdrant)
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
                    f"Sei WorkMind, l'assistente operativo intelligente di {self._company.name}. "
                    f"Rispondi in italiano in modo conciso e professionale.\n"
                )
                if memory_context:
                    system += f"\n{memory_context}\n"
                if rag_context:
                    system += f"\n{rag_context}\n"
                if context:
                    system += f"\n{context}\n"

                response = self._ai.complete_simple(
                    message, system_prompt=system,
                    role=ModelRole.FAST, max_tokens=1024, temperature=0.3,
                )

                # Salva conversazione in Mem0 (background)
                try:
                    from storage.mem0_store import get_mem0
                    mem = get_mem0()
                    if mem.available:
                        import threading
                        threading.Thread(
                            target=mem.add_conversation,
                            args=(message, response),
                            kwargs={"user_id": session.get("username", "supervisor")},
                            daemon=True,
                        ).start()
                except Exception:
                    pass

                return jsonify({"reply": response})
            except Exception as exc:
                return jsonify({"reply": f"Errore AI: {exc}"})

        # ── API: Settings ─────────────────────────────────────────────────
        @app.route("/api/settings", methods=["GET"])
        @_require_auth
        def get_settings():
            return jsonify(self._load_settings())

        @app.route("/api/settings", methods=["POST"])
        @_require_auth
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

_LOGIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkMind — Login</title>
<style>
:root {
  --bg: #f5f5f7; --card: #ffffff; --text: #1d1d1f; --text2: #86868b;
  --accent: #0071e3; --accent-hover: #0077ED; --red: #ff3b30;
  --border: #d2d2d7; --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04);
  --radius: 12px; --font: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: var(--font); background: var(--bg); color: var(--text);
       display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-card {
  background: var(--card); border-radius: 16px; padding: 48px 40px; width: 380px;
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
</style>
</head>
<body>
<div class="login-card">
  <h1>WorkMind</h1>
  <div class="subtitle">Accedi per continuare</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST" action="/login">
    <input name="username" placeholder="Username" autofocus required>
    <input name="password" type="password" placeholder="Password" required>
    <button type="submit">Accedi</button>
  </form>
</div>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════════════════════
# HTML Template — Apple-Style Single Page App
# ═══════════════════════════════════════════════════════════════════════════════

_HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkMind — {{ company }}</title>
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
    <div class="nav-item" onclick="showPage('settings')">
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
        <thead><tr><th>Quando</th><th>Tipo</th><th>Attore</th><th>Dettaglio</th></tr></thead>
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

<script>
// ── Navigation ───────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.querySelectorAll('.nav-item')[
    {dashboard:0, chat:1, audit:2, features:3, settings:4}[name]
  ].classList.add('active');
  if (name === 'audit') loadAudit();
  if (name === 'features') loadFeatures();
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
  document.getElementById('audit-tbody').innerHTML = (data||[]).map(e =>
    `<tr>
      <td>${(e.timestamp||'').replace('T',' ').slice(0,16)}</td>
      <td><span class="badge badge-blue">${e.event_type||''}</span></td>
      <td>${e.actor||''}</td>
      <td>${e.summary||''}</td>
    </tr>`
  ).join('') || '<tr><td colspan=4 style="text-align:center;color:var(--text2)">Nessun evento</td></tr>';
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
loadDashboard();
loadSettings();
setInterval(loadDashboard, 15000);
</script>
</body>
</html>
"""

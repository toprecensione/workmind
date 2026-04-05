"""
WorkMind User & Authentication Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Sistema di autenticazione completo:
- Utenti con email + password (bcrypt/sha256-salted)
- Ruoli: admin (configurazione completa) / user (solo consultazione)
- SMTP nativo per inviti, reset password, notifiche
- Admin predefinito: toprecensione@gmail.com
- Gestione utenti da pannello admin
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Optional

from config.settings import DATA_DIR
from storage.audit_trail import get_audit, AuditEventType
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("storage.user_manager")

_USERS_FILE = DATA_DIR / "users.json"
_TOKENS_FILE = DATA_DIR / "auth_tokens.json"

# SMTP Aruba
_SMTP_HOST = os.getenv("SMTP_HOST", "smtpa.aruba.it")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
_SMTP_SSL = os.getenv("SMTP_SSL", "true").lower() == "true"
_SMTP_USER = os.getenv("SMTP_USER", "smtp@faberweb.it")
_SMTP_PASS = os.getenv("SMTP_PASS", "sm2013tp")
_SMTP_FROM = os.getenv("SMTP_FROM", _SMTP_USER)

# Admin predefinito
_DEFAULT_ADMIN_EMAIL = "toprecensione@gmail.com"
_DEFAULT_ADMIN_PASSWORD = "WorkMind2026!"


class UserRole(str, Enum):
    ADMIN = "admin"     # Configurazione completa, gestione utenti, API keys
    USER = "user"       # Solo consultazione dashboard, chat, audit


class UserManager:
    """Gestisce utenti, autenticazione e invio email."""

    def __init__(self) -> None:
        self._audit = get_audit()
        self._lock = threading.Lock()
        self._users = self._load_users()
        self._tokens = self._load_tokens()
        self._ensure_admin()

    # ── Authentication ───────────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> dict | None:
        """Verifica credenziali. Ritorna user dict o None."""
        email = email.strip().lower()
        user = self._users.get(email)
        if not user:
            return None
        if not user.get("active", True):
            return None
        if self._verify_password(password, user["password_hash"], user.get("salt", "")):
            user["last_login"] = datetime.now(timezone.utc).isoformat()
            self._save_users()
            self._audit.record(
                AuditEventType.SYSTEM,
                f"Login: {email} ({user['role']})",
                actor=email,
            )
            return self._safe_user(user)
        return None

    def get_user(self, email: str) -> dict | None:
        email = email.strip().lower()
        user = self._users.get(email)
        return self._safe_user(user) if user else None

    def list_users(self) -> list[dict]:
        return [self._safe_user(u) for u in self._users.values()]

    # ── User CRUD ────────────────────────────────────────────────────────

    def create_user(
        self,
        email: str,
        password: str,
        name: str = "",
        role: str = UserRole.USER,
        created_by: str = "system",
    ) -> dict | None:
        """Crea un nuovo utente."""
        email = email.strip().lower()
        if email in self._users:
            return None  # Esiste gia'

        salt = secrets.token_hex(16)
        user = {
            "email": email,
            "name": name or email.split("@")[0],
            "role": role,
            "password_hash": self._hash_password(password, salt),
            "salt": salt,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by,
            "last_login": None,
            "must_change_password": False,
        }

        with self._lock:
            self._users[email] = user
            self._save_users()

        self._audit.record(
            AuditEventType.SYSTEM,
            f"Utente creato: {email} (ruolo: {role}) da {created_by}",
            actor=created_by,
        )
        log.info(f"Utente creato: {email} ({role})", action=LogAction.CONFIG, status=LogStatus.OK)
        return self._safe_user(user)

    def update_user(self, email: str, updates: dict, updated_by: str = "admin") -> dict | None:
        """Aggiorna un utente. Campi consentiti: name, role, active."""
        email = email.strip().lower()
        user = self._users.get(email)
        if not user:
            return None

        allowed = {"name", "role", "active"}
        with self._lock:
            for k, v in updates.items():
                if k in allowed:
                    user[k] = v
            self._save_users()

        self._audit.record(
            AuditEventType.SYSTEM,
            f"Utente aggiornato: {email} — {list(updates.keys())} da {updated_by}",
            actor=updated_by,
        )
        return self._safe_user(user)

    def delete_user(self, email: str, deleted_by: str = "admin") -> bool:
        """Elimina un utente. Non si puo' eliminare l'admin predefinito."""
        email = email.strip().lower()
        if email == _DEFAULT_ADMIN_EMAIL:
            return False
        with self._lock:
            if email in self._users:
                del self._users[email]
                self._save_users()
                self._audit.record(
                    AuditEventType.SYSTEM,
                    f"Utente eliminato: {email} da {deleted_by}",
                    actor=deleted_by,
                )
                return True
        return False

    def change_password(self, email: str, new_password: str, changed_by: str = "") -> bool:
        """Cambia la password di un utente."""
        email = email.strip().lower()
        user = self._users.get(email)
        if not user:
            return False

        salt = secrets.token_hex(16)
        with self._lock:
            user["password_hash"] = self._hash_password(new_password, salt)
            user["salt"] = salt
            user["must_change_password"] = False
            self._save_users()

        self._audit.record(
            AuditEventType.SYSTEM,
            f"Password cambiata per {email} da {changed_by or email}",
            actor=changed_by or email,
        )
        return True

    def is_admin(self, email: str) -> bool:
        email = email.strip().lower()
        user = self._users.get(email)
        return user is not None and user.get("role") == UserRole.ADMIN

    # ── Password Reset ───────────────────────────────────────────────────

    def request_password_reset(self, email: str, base_url: str = "") -> bool:
        """Genera token reset e invia email."""
        email = email.strip().lower()
        user = self._users.get(email)
        if not user:
            return False

        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        with self._lock:
            self._tokens[token] = {
                "email": email,
                "type": "password_reset",
                "expires": expires,
                "used": False,
            }
            self._save_tokens()

        reset_url = f"{base_url}/reset-password?token={token}" if base_url else token
        subject = "WorkMind — Reset Password"
        body = (
            f"<h2>Reset Password</h2>"
            f"<p>Ciao {user['name']},</p>"
            f"<p>Hai richiesto il reset della password per WorkMind.</p>"
            f"<p><a href='{reset_url}' style='display:inline-block;padding:12px 24px;"
            f"background:#0071e3;color:white;border-radius:8px;text-decoration:none;"
            f"font-weight:600'>Reimposta Password</a></p>"
            f"<p>Oppure usa questo codice: <strong>{token[:8]}</strong></p>"
            f"<p style='color:#86868b;font-size:12px'>Il link scade tra 2 ore.</p>"
            f"<hr><p style='color:#86868b;font-size:11px'>WorkMind — Non rispondere a questa email.</p>"
        )
        return self.send_email(email, subject, body, html=True)

    def verify_reset_token(self, token: str) -> str | None:
        """Verifica token reset. Ritorna email o None."""
        entry = self._tokens.get(token)
        if not entry:
            return None
        if entry.get("used"):
            return None
        expires = datetime.fromisoformat(entry["expires"])
        if datetime.now(timezone.utc) > expires:
            return None
        return entry["email"]

    def use_reset_token(self, token: str, new_password: str) -> bool:
        """Usa il token per cambiare la password."""
        email = self.verify_reset_token(token)
        if not email:
            return False
        with self._lock:
            self._tokens[token]["used"] = True
            self._save_tokens()
        return self.change_password(email, new_password, changed_by="password_reset")

    # ── Invite User ──────────────────────────────────────────────────────

    def invite_user(
        self,
        email: str,
        role: str = UserRole.USER,
        name: str = "",
        invited_by: str = "admin",
        base_url: str = "",
    ) -> dict | None:
        """Crea utente con password temporanea e invia invito via email."""
        temp_password = secrets.token_urlsafe(12)
        user = self.create_user(
            email=email, password=temp_password,
            name=name, role=role, created_by=invited_by,
        )
        if not user:
            return None

        # Segna che deve cambiare password
        self._users[email.strip().lower()]["must_change_password"] = True
        self._save_users()

        subject = "WorkMind — Sei stato invitato!"
        body = (
            f"<h2>Benvenuto su WorkMind!</h2>"
            f"<p>Ciao {name or email},</p>"
            f"<p><strong>{invited_by}</strong> ti ha invitato a usare WorkMind.</p>"
            f"<p>Le tue credenziali temporanee:</p>"
            f"<table style='border:1px solid #d2d2d7;border-radius:8px;padding:16px;margin:16px 0'>"
            f"<tr><td style='padding:4px 12px;color:#86868b'>Email:</td><td><strong>{email}</strong></td></tr>"
            f"<tr><td style='padding:4px 12px;color:#86868b'>Password:</td><td><strong>{temp_password}</strong></td></tr>"
            f"</table>"
            f"<p>Accedi e cambia la password al primo login.</p>"
            f"<hr><p style='color:#86868b;font-size:11px'>WorkMind — Non rispondere a questa email.</p>"
        )
        self.send_email(email, subject, body, html=True)
        return user

    # ── SMTP Email ───────────────────────────────────────────────────────

    def send_email(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        """Invia email via SMTP Aruba."""
        if not _SMTP_USER or not _SMTP_PASS:
            log.warning("SMTP non configurato", action=LogAction.CONFIG)
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = _SMTP_FROM
            msg["To"] = to
            msg["Subject"] = subject

            if html:
                msg.attach(MIMEText(body, "html", "utf-8"))
            else:
                msg.attach(MIMEText(body, "plain", "utf-8"))

            if _SMTP_SSL:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context, timeout=15) as server:
                    server.login(_SMTP_USER, _SMTP_PASS)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
                    server.starttls()
                    server.login(_SMTP_USER, _SMTP_PASS)
                    server.send_message(msg)

            log.info(f"Email inviata a {to}: {subject}", action=LogAction.CONFIG, status=LogStatus.OK)
            return True
        except Exception as exc:
            log.error(f"Errore invio email a {to}: {exc}", action=LogAction.CONFIG)
            return False

    def test_smtp(self) -> dict:
        """Testa la connessione SMTP."""
        try:
            if _SMTP_SSL:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context, timeout=10) as server:
                    server.login(_SMTP_USER, _SMTP_PASS)
            else:
                with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as server:
                    server.starttls()
                    server.login(_SMTP_USER, _SMTP_PASS)
            return {"ok": True, "host": _SMTP_HOST, "port": _SMTP_PORT, "user": _SMTP_USER}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Password Hashing ─────────────────────────────────────────────────

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """Hash password con SHA-256 + salt."""
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
        """Verifica password contro hash memorizzato."""
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest() == stored_hash

    # ── Init ─────────────────────────────────────────────────────────────

    def _ensure_admin(self) -> None:
        """Assicura che l'admin predefinito esista."""
        if _DEFAULT_ADMIN_EMAIL not in self._users:
            salt = secrets.token_hex(16)
            self._users[_DEFAULT_ADMIN_EMAIL] = {
                "email": _DEFAULT_ADMIN_EMAIL,
                "name": "Amministratore",
                "role": UserRole.ADMIN,
                "password_hash": self._hash_password(_DEFAULT_ADMIN_PASSWORD, salt),
                "salt": salt,
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": "system",
                "last_login": None,
                "must_change_password": False,
            }
            self._save_users()
            log.info(f"Admin predefinito creato: {_DEFAULT_ADMIN_EMAIL}",
                     action=LogAction.STARTUP, status=LogStatus.OK)

    # ── Safe User (no password in output) ────────────────────────────────

    @staticmethod
    def _safe_user(user: dict) -> dict:
        return {k: v for k, v in user.items() if k not in ("password_hash", "salt")}

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_users(self) -> dict:
        if _USERS_FILE.exists():
            try:
                return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_users(self) -> None:
        _USERS_FILE.write_text(
            json.dumps(self._users, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_tokens(self) -> dict:
        if _TOKENS_FILE.exists():
            try:
                return json.loads(_TOKENS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_tokens(self) -> None:
        _TOKENS_FILE.write_text(
            json.dumps(self._tokens, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ─── Singleton ───────────────────────────────────────────────────────────────

_mgr: Optional[UserManager] = None


def get_user_manager() -> UserManager:
    global _mgr
    if _mgr is None:
        _mgr = UserManager()
    return _mgr

"""ConnectorRegistry — gestione runtime dei connector dal DB."""
from __future__ import annotations
import imaplib
import smtplib
import ssl
from datetime import datetime, timezone
from typing import Optional
import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Connector
from app.services.connectors.catalog import CONNECTOR_CATALOG  # noqa: F401
from app.services.encryption import decrypt_config, encrypt_config  # noqa: F401

log = structlog.get_logger()


class ConnectorRegistry:
    """Singleton caricato all'avvio. Accede ai connector dal DB."""

    async def get_config(self, db: AsyncSession, org_id: str, connector_type: str) -> Optional[dict]:
        """Ritorna il config decifrato di un connector, o None se non configurato/disabilitato."""
        result = await db.execute(
            select(Connector).where(
                Connector.org_id == org_id,
                Connector.type == connector_type,
                Connector.is_enabled,
            )
        )
        row: Optional[Connector] = result.scalar_one_or_none()
        if not row or not row.config_enc:
            return None
        try:
            settings = get_settings()
            return decrypt_config(row.config_enc, settings.workmind_secret_key.get_secret_value())
        except Exception as exc:
            log.error("connector_decrypt_error", type=connector_type, error=str(exc))
            return None

    async def test_connector(self, db: AsyncSession, org_id: str, connector_type: str) -> tuple[bool, str]:
        """
        Testa la connessione live. Ritorna (ok, message).
        Aggiorna status + tested_at nel DB.
        """
        result = await db.execute(
            select(Connector).where(Connector.org_id == org_id, Connector.type == connector_type)
        )
        row: Optional[Connector] = result.scalar_one_or_none()
        if not row or not row.config_enc:
            return False, "Connector non configurato"

        settings = get_settings()
        try:
            cfg = decrypt_config(row.config_enc, settings.workmind_secret_key.get_secret_value())
        except Exception:
            return False, "Errore decifratura config"

        try:
            ok, msg = await _test_dispatch(connector_type, cfg)
        except Exception as exc:
            ok, msg = False, str(exc)

        row.status     = "ok" if ok else "error"
        row.status_msg = msg if not ok else None
        row.tested_at  = datetime.now(timezone.utc)
        await db.commit()
        return ok, msg


_registry = ConnectorRegistry()


def get_connector_registry() -> ConnectorRegistry:
    return _registry


async def _test_dispatch(connector_type: str, cfg: dict) -> tuple[bool, str]:
    """Dispatcher per i test di connessione per tipo."""
    match connector_type:
        case "telegram":
            return await _test_telegram(cfg)
        case "smtp":
            return _test_smtp(cfg)
        case "imap":
            return _test_imap(cfg)
        case "github":
            return await _test_github(cfg)
        case "whatsapp":
            return await _test_whatsapp(cfg)
        case "anthropic":
            return await _test_anthropic(cfg)
        case "deepseek":
            return await _test_deepseek(cfg)
        case "ollama":
            return await _test_ollama(cfg)
        case "backup":
            return _test_backup(cfg)
        case _:
            return True, "Test non disponibile per questo tipo"


async def _test_telegram(cfg: dict) -> tuple[bool, str]:
    token = cfg.get("bot_token", "")
    if not token:
        return False, "Bot token mancante"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
    if r.status_code == 200:
        name = r.json().get("result", {}).get("username", "?")
        return True, f"Bot @{name} raggiunto con successo"
    return False, f"Errore Telegram: {r.status_code} {r.text[:200]}"


def _test_smtp(cfg: dict) -> tuple[bool, str]:
    host = cfg.get("host", "")
    port = int(cfg.get("port", 465))
    use_ssl = bool(cfg.get("ssl", True))
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    try:
        ctx = ssl.create_default_context()
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls(context=ctx)
        server.login(username, password)
        server.quit()
        return True, f"SMTP {host}:{port} — login riuscito"
    except Exception as exc:
        return False, f"SMTP error: {exc}"


def _test_imap(cfg: dict) -> tuple[bool, str]:
    host = cfg.get("host", "")
    port = int(cfg.get("port", 993))
    use_ssl = bool(cfg.get("ssl", True))
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    try:
        if use_ssl:
            m = imaplib.IMAP4_SSL(host, port)
        else:
            m = imaplib.IMAP4(host, port)
        m.login(username, password)
        status, data = m.select(cfg.get("folder", "INBOX"), readonly=True)
        count = data[0].decode() if data and data[0] else "?"
        m.logout()
        return True, f"IMAP {host} — {count} messaggi in {cfg.get('folder','INBOX')}"
    except Exception as exc:
        return False, f"IMAP error: {exc}"


async def _test_github(cfg: dict) -> tuple[bool, str]:
    token = cfg.get("token", "")
    if not token:
        return False, "Token GitHub mancante"
    async with httpx.AsyncClient(timeout=10, headers={"Authorization": f"token {token}"}) as c:
        r = await c.get("https://api.github.com/user")
    if r.status_code == 200:
        login = r.json().get("login", "?")
        return True, f"GitHub — autenticato come @{login}"
    return False, f"GitHub error: {r.status_code}"


async def _test_whatsapp(cfg: dict) -> tuple[bool, str]:
    token = cfg.get("token", "")
    phone_id = cfg.get("phone_number_id", "")
    if not token or not phone_id:
        return False, "Token o Phone Number ID mancante"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"https://graph.facebook.com/v20.0/{phone_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 200:
        return True, "WhatsApp Business — numero verificato"
    return False, f"WhatsApp error: {r.status_code} {r.text[:200]}"


async def _test_anthropic(cfg: dict) -> tuple[bool, str]:
    api_key = cfg.get("api_key", "")
    if not api_key:
        return False, "API key mancante"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json={"model": "claude-haiku-4-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
        )
    if r.status_code in (200, 400):
        return True, "Anthropic API — chiave valida"
    return False, f"Anthropic error: {r.status_code}"


async def _test_deepseek(cfg: dict) -> tuple[bool, str]:
    api_key = cfg.get("api_key", "")
    if not api_key:
        return False, "API key mancante"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 200:
        return True, "DeepSeek API — chiave valida"
    return False, f"DeepSeek error: {r.status_code}"


async def _test_ollama(cfg: dict) -> tuple[bool, str]:
    base_url = cfg.get("base_url", "http://localhost:11434")
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{base_url}/api/tags")
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            return True, f"Ollama — {len(models)} modelli disponibili"
        return False, f"Ollama error: {r.status_code}"
    except Exception as exc:
        return False, f"Ollama non raggiungibile: {exc}"


def _test_backup(cfg: dict) -> tuple[bool, str]:
    import os
    path = cfg.get("backup_path", "")
    if not path:
        return False, "Percorso backup non configurato"
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, ".wm_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True, f"Cartella {path} — scrivibile"
    except Exception as exc:
        return False, f"Errore accesso cartella: {exc}"

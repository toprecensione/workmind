"""
WorkMind Email Connector
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Legge email da:
- Office 365 (Microsoft Graph API via OAuth2)
- Exchange on-premise (EWS)
- IMAP generico (fallback)

Le email vengono estratte, parsate e passate al NLP Engine.
Solo lettura — il bot non invia mai email.
"""

from __future__ import annotations

import email as email_lib
import imaplib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from config.company import CompanyConfig, get_company_config
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("connectors.email")


@dataclass
class EmailMessage:
    message_id: str
    subject: str
    sender: str
    recipients: list[str] = field(default_factory=list)
    date: str = ""
    body_text: str = ""
    body_html: str = ""
    attachments: list[dict] = field(default_factory=list)  # [{name, size, content_type}]
    folder: str = "INBOX"

    @property
    def body_plain(self) -> str:
        """Ritorna il body come testo pulito."""
        if self.body_text:
            return self.body_text
        if self.body_html:
            return re.sub(r"<[^>]+>", " ", self.body_html)
        return ""

    @property
    def preview(self) -> str:
        return f"[{self.sender}] {self.subject}: {self.body_plain[:200]}"


class EmailConnector:
    """
    Connettore email multi-provider. Seleziona automaticamente il backend
    in base a config.email.provider.
    """

    def __init__(self, company_cfg: Optional[CompanyConfig] = None) -> None:
        self._cfg = (company_cfg or get_company_config()).email
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch_recent(self, max_count: Optional[int] = None) -> list[EmailMessage]:
        """Scarica le email recenti dai folder configurati."""
        if not self.enabled:
            return []

        limit = max_count or self._cfg.max_emails_per_fetch
        provider = self._cfg.provider

        try:
            if provider == "office365":
                return self._fetch_office365(limit)
            elif provider == "exchange_onprem":
                return self._fetch_exchange(limit)
            elif provider == "imap":
                return self._fetch_imap(limit)
            else:
                log.error(f"Provider email sconosciuto: {provider}", action=LogAction.CONFIG)
                return []
        except Exception as exc:
            log.error(
                f"Errore fetch email ({provider}): {exc}",
                action=LogAction.SCAN, status=LogStatus.ERROR,
                suggestion="Verifica credenziali email e permessi.",
            )
            return []

    # ── Office 365 (Microsoft Graph) ──────────────────────────────────────────

    def _fetch_office365(self, limit: int) -> list[EmailMessage]:
        token = self._get_graph_token()
        if not token:
            return []

        messages: list[EmailMessage] = []
        for folder in self._cfg.folders_monitor:
            url = (
                f"https://graph.microsoft.com/v1.0/users/{self._cfg.mailbox}"
                f"/mailFolders/{folder}/messages"
                f"?$top={limit}&$orderby=receivedDateTime desc"
                f"&$select=id,subject,from,toRecipients,receivedDateTime,body,hasAttachments"
            )
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                resp.raise_for_status()
                data = resp.json()

            for item in data.get("value", []):
                msg = EmailMessage(
                    message_id=item.get("id", ""),
                    subject=item.get("subject", ""),
                    sender=item.get("from", {}).get("emailAddress", {}).get("address", ""),
                    recipients=[
                        r.get("emailAddress", {}).get("address", "")
                        for r in item.get("toRecipients", [])
                    ],
                    date=item.get("receivedDateTime", ""),
                    folder=folder,
                )
                body = item.get("body", {})
                if body.get("contentType") == "html":
                    msg.body_html = body.get("content", "")
                else:
                    msg.body_text = body.get("content", "")
                messages.append(msg)

        log.info(
            f"Office 365: {len(messages)} email scaricate",
            action=LogAction.SCAN, status=LogStatus.OK,
        )
        return messages

    def _get_graph_token(self) -> Optional[str]:
        """Ottiene un access token OAuth2 via client_credentials flow."""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"https://login.microsoftonline.com/{self._cfg.tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": self._cfg.client_id,
                        "client_secret": self._cfg.client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data.get("expires_in", 3600) - 60
                return self._access_token
        except Exception as exc:
            log.error(f"OAuth2 token error: {exc}", action=LogAction.AUTH, status=LogStatus.ERROR)
            return None

    # ── Exchange On-Premise (EWS) ─────────────────────────────────────────────

    def _fetch_exchange(self, limit: int) -> list[EmailMessage]:
        try:
            from exchangelib import (
                Credentials, Account, Configuration, DELEGATE, NTLM,
            )
        except ImportError:
            log.error(
                "exchangelib non installato: pip install exchangelib",
                action=LogAction.CONFIG, status=LogStatus.ERROR,
            )
            return []

        creds = Credentials(self._cfg.imap_user, self._cfg.client_secret)
        config = Configuration(
            server=self._cfg.exchange_url.replace("https://", "").split("/")[0],
            credentials=creds,
            auth_type=NTLM,
        )
        account = Account(
            self._cfg.mailbox,
            config=config,
            access_type=DELEGATE,
            autodiscover=False,
        )

        messages: list[EmailMessage] = []
        for item in account.inbox.all().order_by("-datetime_received")[:limit]:
            messages.append(EmailMessage(
                message_id=item.message_id or "",
                subject=item.subject or "",
                sender=str(item.sender.email_address) if item.sender else "",
                recipients=[str(r.email_address) for r in (item.to_recipients or [])],
                date=str(item.datetime_received or ""),
                body_text=item.text_body or "",
                body_html=item.body or "",
                folder="INBOX",
            ))

        log.info(f"Exchange: {len(messages)} email scaricate", action=LogAction.SCAN, status=LogStatus.OK)
        return messages

    # ── IMAP generico ─────────────────────────────────────────────────────────

    def _fetch_imap(self, limit: int) -> list[EmailMessage]:
        host = self._cfg.imap_host
        port = self._cfg.imap_port
        user = self._cfg.imap_user
        password = self._cfg.imap_password

        if not all([host, user, password]):
            log.error("Configurazione IMAP incompleta", action=LogAction.CONFIG, status=LogStatus.ERROR)
            return []

        messages: list[EmailMessage] = []
        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(user, password)

            for folder in self._cfg.folders_monitor:
                try:
                    status, _ = conn.select(folder, readonly=True)
                    if status != "OK":
                        continue
                except Exception:
                    continue

                # Cerca le email degli ultimi 7 giorni
                since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
                status, msg_ids = conn.search(None, f'(SINCE "{since}")')
                if status != "OK":
                    continue

                ids = msg_ids[0].split()
                for mid in ids[-limit:]:
                    status, data = conn.fetch(mid, "(RFC822)")
                    if status != "OK" or not data[0]:
                        continue
                    raw = data[0][1]
                    msg = email_lib.message_from_bytes(raw)
                    parsed = self._parse_imap_message(msg, folder)
                    if parsed:
                        messages.append(parsed)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

        log.info(f"IMAP: {len(messages)} email scaricate", action=LogAction.SCAN, status=LogStatus.OK)
        return messages

    @staticmethod
    def _parse_imap_message(msg: email_lib.message.Message, folder: str) -> Optional[EmailMessage]:
        subject = msg.get("Subject", "")
        sender = msg.get("From", "")
        date_str = msg.get("Date", "")
        message_id = msg.get("Message-ID", "")
        recipients = [r.strip() for r in (msg.get("To", "")).split(",") if r.strip()]

        body_text = ""
        body_html = ""
        attachments = []
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                attachments.append({
                    "name": part.get_filename() or "attachment",
                    "content_type": ctype,
                    "size": len(part.get_payload(decode=True) or b""),
                })
            elif ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")

        return EmailMessage(
            message_id=message_id,
            subject=subject,
            sender=sender,
            recipients=recipients,
            date=date_str,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            folder=folder,
        )

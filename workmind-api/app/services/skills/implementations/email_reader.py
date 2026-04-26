"""Skill: email_reader — legge email IMAP e le processa con AI."""
from __future__ import annotations
import asyncio
import email
import imaplib
from email.header import decode_header
import structlog
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import get_settings
from app.services.connectors import get_connector_registry

log = structlog.get_logger()


def make_email_reader_job(org_id: str, cfg: dict):
    async def run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            imap_cfg = await get_connector_registry().get_config(db, org_id, "imap")
        await engine.dispose()
        if not imap_cfg:
            return
        messages = await asyncio.to_thread(_fetch_unread_emails, imap_cfg, cfg)
        if messages:
            await _process_emails(org_id, messages, cfg)
    return run


def _fetch_unread_emails(imap_cfg: dict, skill_cfg: dict) -> list[dict]:
    """Fetch unread emails via IMAP and return parsed message dicts."""
    host = imap_cfg.get("host", "")
    port = int(imap_cfg.get("port", 993))
    use_ssl = imap_cfg.get("ssl", True)
    folder = imap_cfg.get("folder", "INBOX")
    filter_domain = skill_cfg.get("filter_domain", "")
    messages = []

    try:
        if use_ssl:
            m = imaplib.IMAP4_SSL(host, port)
        else:
            m = imaplib.IMAP4(host, port)
        m.login(imap_cfg["username"], imap_cfg["password"])
        m.select(folder, readonly=False)

        _, data = m.search(None, "UNSEEN")
        uids = data[0].split() if data[0] else []

        for uid in uids[:20]:  # max 20 alla volta
            _, msg_data = m.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = msg.get("From", "")
            subject_raw, enc = decode_header(msg.get("Subject", ""))[0]
            subject = subject_raw.decode(enc or "utf-8") if isinstance(subject_raw, bytes) else subject_raw

            if filter_domain and filter_domain not in sender:
                continue

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            # Parse sender name and email address
            sender_name = ""
            sender_email = sender
            if "<" in sender:
                parts = sender.split("<", 1)
                sender_name = parts[0].strip().strip('"')
                sender_email = parts[1].rstrip(">").strip()

            log.info("email_reader_new", org_id="", sender=sender, subject=subject, body_len=len(body))
            messages.append({
                "sender": sender,
                "sender_email": sender_email,
                "sender_name": sender_name,
                "subject": subject,
                "body": body,
            })

        m.logout()
    except Exception as exc:
        log.error("email_reader_fetch_error", error=str(exc))

    return messages


async def _process_emails(org_id: str, messages: list[dict], skill_cfg: dict) -> None:
    """Process fetched emails: forward to chat and/or auto-reply via SMTP."""
    from app.db.engine import get_session_factory
    from app.services.channel_router import handle_incoming_message

    try:
        SessionLocal = get_session_factory()
    except RuntimeError:
        log.error("email_reader_no_db_engine")
        return

    for item in messages:
        sender_email = item["sender_email"]
        sender_name = item["sender_name"]
        subject = item["subject"]
        body_text = item["body"]
        reply = None

        try:
            async with SessionLocal() as db:
                # forward_to_chat: send email content through AI pipeline
                if skill_cfg.get("forward_to_chat", False):
                    reply = await handle_incoming_message(
                        db=db,
                        channel_type="email",
                        external_id=sender_email,
                        text=f"[Email da {sender_email}]\nOggetto: {subject}\n\n{body_text}",
                        user_display_name=sender_name or sender_email,
                    )

                # auto_reply: send AI-generated reply back via SMTP
                if skill_cfg.get("auto_reply", False) and reply:
                    smtp_cfg = await get_connector_registry().get_config(db, org_id, "smtp")
                    if smtp_cfg:
                        await asyncio.to_thread(
                            _send_smtp_reply, smtp_cfg, sender_email, subject, reply
                        )
        except Exception as exc:
            log.error("email_reader_process_error", sender=sender_email, error=str(exc))


def _send_smtp_reply(smtp_cfg: dict, to: str, subject: str, body: str) -> None:
    """Send reply email via SMTP (synchronous, run in thread)."""
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = smtp_cfg.get("from_address") or smtp_cfg.get("username", "")
    msg["To"] = to
    msg["Subject"] = f"Re: {subject}"
    ctx = ssl.create_default_context()
    port = int(smtp_cfg.get("port", 465))
    try:
        if port == 587:
            with smtplib.SMTP(smtp_cfg["host"], port, timeout=15) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.login(smtp_cfg["username"], smtp_cfg["password"])
                s.sendmail(msg["From"], [to], msg.as_string())
        else:
            with smtplib.SMTP_SSL(smtp_cfg["host"], port, context=ctx, timeout=15) as s:
                s.login(smtp_cfg["username"], smtp_cfg["password"])
                s.sendmail(msg["From"], [to], msg.as_string())
    except Exception as exc:
        log.error("email_reader_smtp_reply_error", to=to, error=str(exc))

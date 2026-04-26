"""
WorkMind API — Email Service
Async wrapper around smtplib for sending transactional emails via Aruba SMTP.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

log = structlog.get_logger("workmind.email")


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    settings,  # app.config.Settings — avoid circular import at module level
) -> bool:
    """
    Send an HTML email via SMTP.

    Runs the synchronous smtplib call in a thread-pool executor so as not to
    block the event loop.  Returns True on success, False on any error.
    """

    def _send_sync() -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if settings.smtp_ssl:
            smtp_cls = smtplib.SMTP_SSL
            with smtp_cls(settings.smtp_host, settings.smtp_port) as server:
                server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
                server.sendmail(settings.smtp_from, [to], msg.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
                server.sendmail(settings.smtp_from, [to], msg.as_string())

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _send_sync)
        log.info("email_sent", to=to, subject=subject)
        return True
    except Exception as exc:
        log.warning("email_send_failed", to=to, subject=subject, error=str(exc))
        return False


def build_reset_email(reset_url: str, expires_minutes: int = 30) -> str:
    """
    Build a professional Italian-language HTML email for password reset.
    Returns the full HTML string with inline CSS ready to send.
    """
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Reset Password — WorkMind</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background-color:#ffffff;border-radius:8px;overflow:hidden;
                      box-shadow:0 2px 8px rgba(0,0,0,0.08);max-width:600px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="background-color:#1a56db;padding:32px 40px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;
                         letter-spacing:-0.5px;">WorkMind</h1>
              <p style="margin:8px 0 0;color:#bfdbfe;font-size:13px;">
                Piattaforma di gestione intelligente
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 16px;color:#111827;font-size:20px;font-weight:600;">
                Reimpostazione password
              </h2>
              <p style="margin:0 0 16px;color:#374151;font-size:15px;line-height:1.6;">
                Abbiamo ricevuto una richiesta di reimpostazione della password per il tuo account
                WorkMind.
              </p>
              <p style="margin:0 0 28px;color:#374151;font-size:15px;line-height:1.6;">
                Clicca sul pulsante qui sotto per scegliere una nuova password.
                Il link &egrave; valido per <strong>{expires_minutes} minuti</strong>.
              </p>

              <!-- CTA Button -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:0 0 28px;">
                    <a href="{reset_url}"
                       style="display:inline-block;background-color:#1a56db;color:#ffffff;
                              text-decoration:none;font-size:15px;font-weight:600;
                              padding:14px 36px;border-radius:6px;
                              letter-spacing:0.2px;">
                      Reimposta la password
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Plain-text fallback link -->
              <p style="margin:0 0 8px;color:#6b7280;font-size:13px;line-height:1.5;">
                Se il pulsante non funziona, copia e incolla questo link nel browser:
              </p>
              <p style="margin:0 0 28px;word-break:break-all;">
                <a href="{reset_url}"
                   style="color:#1a56db;font-size:13px;text-decoration:underline;">
                  {reset_url}
                </a>
              </p>

              <hr style="border:none;border-top:1px solid #e5e7eb;margin:0 0 24px;" />

              <p style="margin:0;color:#9ca3af;font-size:12px;line-height:1.5;">
                Se non hai richiesto la reimpostazione della password, ignora questa email:
                il tuo account &egrave; al sicuro e nessuna modifica &egrave; stata apportata.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f9fafb;padding:20px 40px;text-align:center;
                       border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#9ca3af;font-size:12px;">
                &copy; 2026 WorkMind &mdash; Uso interno riservato
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

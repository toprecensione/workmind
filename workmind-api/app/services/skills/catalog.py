"""Catalogo statico delle skill disponibili."""
from __future__ import annotations
from dataclasses import dataclass, field
from app.services.connectors.catalog import CField


@dataclass
class SkillDef:
    id: str
    name: str
    description: str
    icon: str
    category: str       # notifications | ai | messaging | devops | storage | medic
    requires: list[str] # lista di connector type richiesti
    config_schema: list[CField] = field(default_factory=list)


SKILL_CATALOG: dict[str, SkillDef] = {
    "telegram_notifications": SkillDef(
        id="telegram_notifications", name="Notifiche Telegram", icon="bell", category="notifications",
        description="Notifiche proattive via Telegram: stock basso, vendite, anomalie.",
        requires=["telegram"],
        config_schema=[
            CField("daily_summary_enabled",   "Riepilogo giornaliero",    "boolean", default=True),
            CField("daily_summary_hour",      "Ora riepilogo (0-23)",     "number",  default=8),
            CField("low_stock_alert",         "Alert scorte basse",       "boolean", default=True),
            CField("new_sale_notification",   "Notifica ogni vendita",    "boolean", default=False),
        ],
    ),
    "telegram_commands": SkillDef(
        id="telegram_commands", name="Comandi Bot Telegram", icon="terminal", category="messaging",
        description="Gestisce comandi Telegram: /start /help /status /stock /vendite /chat",
        requires=["telegram"],
        config_schema=[],
    ),
    "telegram_voice": SkillDef(
        id="telegram_voice", name="Trascrizione vocale Telegram", icon="mic", category="ai",
        description="Trascrive messaggi vocali Telegram con AI e li elabora come testo.",
        requires=["telegram"],
        config_schema=[],
    ),
    "email_alerts": SkillDef(
        id="email_alerts", name="Alert via Email", icon="mail", category="notifications",
        description="Email automatiche per eventi critici: stock esaurito, errori, report settimanale.",
        requires=["smtp"],
        config_schema=[
            CField("alert_email",           "Email destinatario",       "email",   required=True),
            CField("weekly_report_enabled", "Report settimanale",       "boolean", default=True),
            CField("weekly_report_day",     "Giorno report (0=lun)",    "number",  default=0),
            CField("stock_alert_enabled",   "Alert stock esaurito",     "boolean", default=True),
        ],
    ),
    "email_reader": SkillDef(
        id="email_reader", name="Lettura Email con AI", icon="inbox", category="ai",
        description="Legge email in arrivo, le classifica con AI e le inola alla chat interna.",
        requires=["imap"],
        config_schema=[
            CField("auto_reply",       "Risposta automatica AI",    "boolean", default=False),
            CField("forward_to_chat",  "Inoltra alla chat interna", "boolean", default=True),
            CField("filter_domain",    "Filtra dominio mittente",   "text",    hint="Es: ideasito.it. Vuoto = tutti"),
        ],
    ),
    "whatsapp_chat": SkillDef(
        id="whatsapp_chat", name="Chat WhatsApp con AI", icon="whatsapp", category="messaging",
        description="Risponde automaticamente ai clienti su WhatsApp usando l'AI.",
        requires=["whatsapp"],
        config_schema=[
            CField("welcome_message", "Messaggio benvenuto", "textarea",
                   default="Ciao! Sono l'assistente MEDIC. Come posso aiutarti?"),
            CField("ai_role",         "Livello AI",          "select",   default="reliable",
                   options=[{"value":"fast","label":"Fast (DeepSeek)"},{"value":"reliable","label":"Reliable (Claude)"}]),
        ],
    ),
    "github_issues": SkillDef(
        id="github_issues", name="GitHub Issues automatici", icon="github", category="devops",
        description="Crea GitHub Issues da segnalazioni utenti e feature request.",
        requires=["github"],
        config_schema=[
            CField("repo",               "Repository (owner/repo)", "text", required=True),
            CField("label_bug",          "Label bug",               "text", default="bug"),
            CField("label_feature",      "Label feature request",   "text", default="enhancement"),
        ],
    ),
    "backup_auto": SkillDef(
        id="backup_auto", name="Backup automatico", icon="archive", category="storage",
        description="Backup periodici del DB con notifica su Telegram o email.",
        requires=["backup"],
        config_schema=[
            CField("notify_telegram", "Notifica su Telegram", "boolean", default=True),
            CField("notify_email",    "Notifica via Email",   "boolean", default=False),
            CField("notify_email_to", "Email destinatario",   "email"),
        ],
    ),
    "low_stock_alert": SkillDef(
        id="low_stock_alert", name="Alert Scorte MEDIC", icon="alert-triangle", category="medic",
        description="Avvisa quando i prodotti MEDIC scendono sotto la soglia minima.",
        requires=[],  # almeno telegram o smtp, controllato a runtime
        config_schema=[
            CField("check_interval_hours",  "Controlla ogni (ore)",     "number",  default=4),
            CField("notify_via_telegram",   "Notifica Telegram",        "boolean", default=True),
            CField("notify_via_email",      "Notifica Email",           "boolean", default=False),
            CField("email_recipient",       "Email destinatario",       "email"),
        ],
    ),
    "daily_report": SkillDef(
        id="daily_report", name="Report giornaliero MEDIC", icon="bar-chart", category="medic",
        description="Riepilogo mattutino di vendite, stock e attività del giorno precedente.",
        requires=[],  # almeno telegram o smtp
        config_schema=[
            CField("send_hour",           "Ora invio (0-23)",     "number",  default=8),
            CField("notify_via_telegram", "Invia su Telegram",    "boolean", default=True),
            CField("notify_via_email",    "Invia via email",      "boolean", default=False),
            CField("email_recipient",     "Email destinatario",   "email"),
        ],
    ),
}

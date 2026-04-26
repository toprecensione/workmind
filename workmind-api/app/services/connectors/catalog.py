"""Catalogo statico dei connector disponibili."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CField:
    key: str
    label: str
    type: Literal["text","password","number","boolean","email","textarea","select"]
    required: bool = False
    default: Any = None
    hint: str = ""
    options: list[dict] = field(default_factory=list)  # solo per type=select


@dataclass
class ConnectorDef:
    type: str
    name: str
    description: str
    icon: str          # nome icona per frontend
    category: str      # messaging | email | ai | devops | storage
    fields: list[CField]
    sensitive_keys: list[str] = field(default_factory=list)


CONNECTOR_CATALOG: dict[str, ConnectorDef] = {
    "telegram": ConnectorDef(
        type="telegram", name="Telegram Bot", icon="telegram", category="messaging",
        description="Ricevi e invia messaggi tramite Telegram. Abilita comandi bot, notifiche e trascrizione vocale.",
        sensitive_keys=["bot_token", "webhook_secret"],
        fields=[
            CField("bot_token",       "Bot Token",              "password", required=True,  hint="Da @BotFather su Telegram"),
            CField("webhook_secret",  "Webhook Secret",         "password", required=False, hint="Stringa casuale per validare webhook"),
            CField("chat_id_default", "Chat ID default",        "text",     required=False, hint="Chat ID per notifiche proattive"),
            CField("allowed_chat_ids","Chat IDs autorizzati",   "text",     required=False, hint="IDs separati da virgola. Vuoto = tutti"),
        ],
    ),
    "whatsapp": ConnectorDef(
        type="whatsapp", name="WhatsApp Business", icon="whatsapp", category="messaging",
        description="Gestisci clienti via WhatsApp Business Cloud API.",
        sensitive_keys=["token", "verify_token", "app_secret"],
        fields=[
            CField("token",           "API Token",              "password", required=True),
            CField("phone_number_id", "Phone Number ID",        "text",     required=True),
            CField("verify_token",    "Webhook Verify Token",   "password", required=True),
            CField("app_secret",      "App Secret",             "password", required=False, hint="Per validare firma webhook"),
        ],
    ),
    "smtp": ConnectorDef(
        type="smtp", name="Email (SMTP)", icon="mail", category="email",
        description="Invia email per notifiche, alert e report automatici.",
        sensitive_keys=["password"],
        fields=[
            CField("host",         "SMTP Host",         "text",     required=True,  default="smtpa.aruba.it"),
            CField("port",         "Porta",             "number",   required=True,  default=465),
            CField("ssl",          "Usa SSL/TLS",       "boolean",  default=True),
            CField("username",     "Username",          "text",     required=True),
            CField("password",     "Password",          "password", required=True),
            CField("from_address", "Indirizzo mittente","email",    required=True),
            CField("from_name",    "Nome mittente",     "text",     default="WorkMind"),
        ],
    ),
    "imap": ConnectorDef(
        type="imap", name="Email (IMAP)", icon="inbox", category="email",
        description="Leggi ed elabora email in arrivo con AI.",
        sensitive_keys=["password"],
        fields=[
            CField("host",     "IMAP Host",            "text",    required=True),
            CField("port",     "Porta",                "number",  default=993),
            CField("ssl",      "Usa SSL/TLS",          "boolean", default=True),
            CField("username", "Username / Email",     "email",   required=True),
            CField("password", "Password",             "password",required=True),
            CField("folder",   "Cartella",             "text",    default="INBOX"),
            CField("check_interval_minutes","Controlla ogni (min)","number", default=15),
        ],
    ),
    "github": ConnectorDef(
        type="github", name="GitHub", icon="github", category="devops",
        description="Crea Issues e commenta PR su GitHub automaticamente.",
        sensitive_keys=["token"],
        fields=[
            CField("token",          "Personal Access Token","password",required=True, hint="GitHub → Settings → Developer settings → PAT"),
            CField("default_repo",   "Repository default",  "text",    hint="owner/repo (es: toprecensione/workmind)"),
            CField("default_labels", "Labels di default",   "text",    hint="Separati da virgola (es: workmind,auto)"),
        ],
    ),
    "anthropic": ConnectorDef(
        type="anthropic", name="Anthropic / Claude", icon="anthropic", category="ai",
        description="Provider AI Claude. Usato per risposte affidabili, analisi e chat.",
        sensitive_keys=["api_key"],
        fields=[
            CField("api_key",         "API Key",                "password", required=True),
            CField("daily_limit_usd", "Limite giornaliero ($)", "number",   default=10.0),
            CField("default_model",   "Modello default",        "select",   default="claude-haiku-4-5",
                   options=[{"value":"claude-haiku-4-5","label":"Claude Haiku 4.5"},{"value":"claude-sonnet-4-6","label":"Claude Sonnet 4.6"}]),
        ],
    ),
    "deepseek": ConnectorDef(
        type="deepseek", name="DeepSeek", icon="cpu", category="ai",
        description="Provider AI DeepSeek. Veloce ed economico per classificazione e MEDIC chat.",
        sensitive_keys=["api_key"],
        fields=[
            CField("api_key",         "API Key",                "password", required=True),
            CField("daily_limit_usd", "Limite giornaliero ($)", "number",   default=5.0),
        ],
    ),
    "ollama": ConnectorDef(
        type="ollama", name="Ollama (LLM locale)", icon="cpu", category="ai",
        description="Modelli AI locali senza costi API. Richiede profilo PRO con GPU.",
        sensitive_keys=[],
        fields=[
            CField("base_url",    "URL Ollama",       "text", default="http://localhost:11434"),
            CField("model",       "Modello chat",     "text", default="qwen2.5:14b"),
            CField("embed_model", "Modello embedding","text", default="nomic-embed-text"),
        ],
    ),
    "backup": ConnectorDef(
        type="backup", name="Backup automatico", icon="archive", category="storage",
        description="Backup periodici del database e dei file su disco locale.",
        sensitive_keys=[],
        fields=[
            CField("backup_path",     "Cartella backup",              "text",    default="/home/emanuele/workmind-v2/backups"),
            CField("retention_days",  "Giorni di retention",          "number",  default=30),
            CField("schedule_hour",   "Ora esecuzione (0-23)",        "number",  default=2),
            CField("include_db",      "Includi database PostgreSQL",  "boolean", default=True),
            CField("include_uploads", "Includi file caricati",        "boolean", default=True),
        ],
    ),
}

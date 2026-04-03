"""
WorkMind Company Configuration
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Ogni bot Ubuntu ha un file config/company.yaml che descrive l'azienda cliente:
credenziali DB, cartelle condivise, email, ecc.

Il file .env contiene le password (mai in company.yaml).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from logging_system import get_logger, LogStatus, LogAction

log = get_logger("config.company")

_DEFAULT_COMPANY_YAML = Path(__file__).resolve().parent.parent / "config" / "company.yaml"


# ─── Sub-config: Database ─────────────────────────────────────────────────────

@dataclass
class DatabaseConfig:
    enabled: bool = False
    type: str = "sqlserver"          # sqlserver | mysql | postgres
    host: str = ""
    port: int = 1433
    name: str = ""                   # nome database/schema
    user: str = ""
    # password: letta da env WORKMIND_DB_PASSWORD
    tables_include: list = field(default_factory=list)   # se vuoto: tutte
    tables_exclude: list = field(default_factory=list)
    max_rows_per_query: int = 5000
    schema_discovery: bool = True    # mappa automaticamente le tabelle all'avvio

    @property
    def password(self) -> str:
        return os.getenv("WORKMIND_DB_PASSWORD", "")

    @property
    def connection_string(self) -> str:
        if self.type == "sqlserver":
            return (
                f"mssql+pyodbc://{self.user}:{self.password}@{self.host}:{self.port}"
                f"/{self.name}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
            )
        if self.type == "mysql":
            return f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        if self.type == "postgres":
            return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        return ""


# ─── Sub-config: Email ────────────────────────────────────────────────────────

@dataclass
class EmailConfig:
    enabled: bool = False
    provider: str = "office365"      # office365 | exchange_onprem | imap
    # Office 365 / Azure AD
    tenant_id: str = ""
    client_id: str = ""
    # client_secret: letto da env WORKMIND_EMAIL_SECRET
    mailbox: str = ""                # indirizzo email da monitorare
    # Exchange on-premise
    exchange_url: str = ""           # es. https://mail.azienda.it/EWS/Exchange.asmx
    # IMAP fallback
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    # password IMAP da env WORKMIND_IMAP_PASSWORD
    fetch_interval_minutes: int = 5
    max_emails_per_fetch: int = 50
    folders_monitor: list = field(default_factory=lambda: ["INBOX"])

    @property
    def client_secret(self) -> str:
        return os.getenv("WORKMIND_EMAIL_SECRET", "")

    @property
    def imap_password(self) -> str:
        return os.getenv("WORKMIND_IMAP_PASSWORD", "")


# ─── Sub-config: Cartelle condivise SMB ──────────────────────────────────────

@dataclass
class SmbConfig:
    enabled: bool = False
    shares: list = field(default_factory=list)
    # Ogni elemento: { server: "\\\\SRV\\Share", mount_point: "/mnt/share1",
    #                  username: "user", domain: "AZIENDA" }
    # password da env WORKMIND_SMB_PASSWORD
    recursive_watch: bool = True
    extensions_monitor: list = field(default_factory=lambda: [
        ".pdf", ".docx", ".xlsx", ".csv", ".txt",
        ".eml", ".msg", ".dxf", ".dwg",
    ])

    @property
    def password(self) -> str:
        return os.getenv("WORKMIND_SMB_PASSWORD", "")


# ─── Sub-config: RDP ──────────────────────────────────────────────────────────

@dataclass
class RdpConfig:
    enabled: bool = False
    host: str = ""
    port: int = 3389
    username: str = "WorkMind_RDP"
    # password da env WORKMIND_RDP_PASSWORD
    screenshot_interval_minutes: int = 15
    target_windows: list = field(default_factory=list)  # titoli finestre da catturare

    @property
    def password(self) -> str:
        return os.getenv("WORKMIND_RDP_PASSWORD", "")


# ─── Configurazione principale azienda ───────────────────────────────────────

@dataclass
class CompanyConfig:
    name: str = "Azienda"
    sector: str = ""                 # manifatturiero | commercio | servizi | edilizia | ...
    language: str = "it"
    timezone: str = "Europe/Rome"
    supervisor_email: str = ""       # email del supervisore per notifiche
    report_time_daily: str = "22:00"
    report_day_weekly: str = "friday"

    # Moduli attivi
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    email:    EmailConfig    = field(default_factory=EmailConfig)
    smb:      SmbConfig      = field(default_factory=SmbConfig)
    rdp:      RdpConfig      = field(default_factory=RdpConfig)

    # Cartelle locali da monitorare (oltre all'SMB)
    local_watch_dirs: list = field(default_factory=list)

    # Personalizzazione NLP
    custom_entities: list = field(default_factory=list)   # entità custom per questo settore
    document_types: list = field(default_factory=lambda: [
        "fattura", "ordine", "contratto", "DDT", "offerta",
        "email", "relazione", "preventivo", "altro",
    ])


# ─── Loader ───────────────────────────────────────────────────────────────────

def load_company_config(path: Optional[Path] = None) -> CompanyConfig:
    """
    Carica company.yaml. Se il file non esiste ritorna una config di default
    (utile in dev/test).
    """
    config_path = path or _DEFAULT_COMPANY_YAML

    if not config_path.exists():
        log.warning(
            f"company.yaml non trovato in {config_path} — uso configurazione di default",
            action=LogAction.CONFIG, status=LogStatus.WARNING,
            suggestion="Crea config/company.yaml copiando config/company.yaml.example",
        )
        return CompanyConfig()

    if not _YAML_AVAILABLE:
        log.error(
            "PyYAML non installato — impossibile leggere company.yaml",
            action=LogAction.CONFIG, status=LogStatus.ERROR,
        )
        return CompanyConfig()

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.error(
            f"Errore parsing company.yaml: {exc}",
            action=LogAction.CONFIG, status=LogStatus.ERROR,
        )
        return CompanyConfig()

    cfg = CompanyConfig(
        name=raw.get("name", "Azienda"),
        sector=raw.get("sector", ""),
        language=raw.get("language", "it"),
        timezone=raw.get("timezone", "Europe/Rome"),
        supervisor_email=raw.get("supervisor_email", ""),
        report_time_daily=raw.get("report_time_daily", "22:00"),
        report_day_weekly=raw.get("report_day_weekly", "friday"),
        local_watch_dirs=raw.get("local_watch_dirs", []),
        custom_entities=raw.get("custom_entities", []),
        document_types=raw.get("document_types", CompanyConfig().document_types),
    )

    # Database
    db_raw = raw.get("database", {})
    if db_raw:
        cfg.database = DatabaseConfig(
            enabled=db_raw.get("enabled", False),
            type=db_raw.get("type", "sqlserver"),
            host=db_raw.get("host", ""),
            port=int(db_raw.get("port", 1433)),
            name=db_raw.get("name", ""),
            user=db_raw.get("user", ""),
            tables_include=db_raw.get("tables_include", []),
            tables_exclude=db_raw.get("tables_exclude", []),
            max_rows_per_query=int(db_raw.get("max_rows_per_query", 5000)),
            schema_discovery=db_raw.get("schema_discovery", True),
        )

    # Email
    email_raw = raw.get("email", {})
    if email_raw:
        cfg.email = EmailConfig(
            enabled=email_raw.get("enabled", False),
            provider=email_raw.get("provider", "office365"),
            tenant_id=email_raw.get("tenant_id", ""),
            client_id=email_raw.get("client_id", ""),
            mailbox=email_raw.get("mailbox", ""),
            exchange_url=email_raw.get("exchange_url", ""),
            imap_host=email_raw.get("imap_host", ""),
            imap_port=int(email_raw.get("imap_port", 993)),
            imap_user=email_raw.get("imap_user", ""),
            fetch_interval_minutes=int(email_raw.get("fetch_interval_minutes", 5)),
            max_emails_per_fetch=int(email_raw.get("max_emails_per_fetch", 50)),
            folders_monitor=email_raw.get("folders_monitor", ["INBOX"]),
        )

    # SMB
    smb_raw = raw.get("smb", {})
    if smb_raw:
        cfg.smb = SmbConfig(
            enabled=smb_raw.get("enabled", False),
            shares=smb_raw.get("shares", []),
            recursive_watch=smb_raw.get("recursive_watch", True),
            extensions_monitor=smb_raw.get("extensions_monitor", SmbConfig().extensions_monitor),
        )

    # RDP
    rdp_raw = raw.get("rdp", {})
    if rdp_raw:
        cfg.rdp = RdpConfig(
            enabled=rdp_raw.get("enabled", False),
            host=rdp_raw.get("host", ""),
            port=int(rdp_raw.get("port", 3389)),
            username=rdp_raw.get("username", "WorkMind_RDP"),
            screenshot_interval_minutes=int(rdp_raw.get("screenshot_interval_minutes", 15)),
            target_windows=rdp_raw.get("target_windows", []),
        )

    log.info(
        f"Configurazione azienda caricata: {cfg.name} ({cfg.sector})",
        action=LogAction.CONFIG, status=LogStatus.OK,
    )
    return cfg


# ─── Singleton ────────────────────────────────────────────────────────────────

_company: Optional[CompanyConfig] = None


def get_company_config() -> CompanyConfig:
    global _company
    if _company is None:
        _company = load_company_config()
    return _company

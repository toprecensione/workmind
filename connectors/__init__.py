"""
WorkMind Connectors
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Moduli di connessione alle fonti dati aziendali:
- DocumentParser: PDF, Excel, DOCX, CSV, DWG/DXF
- DatabaseConnector: SQL Server, MySQL, PostgreSQL con schema discovery
- EmailConnector: Office 365, Exchange on-premise, IMAP
- SmbWatcher: file watcher cartelle condivise
- RdpCapture: screenshot di gestionali via RDP
"""

from connectors.document_parser import DocumentParser, ParsedDocument
from connectors.database import DatabaseConnector
from connectors.email_connector import EmailConnector
from connectors.smb_watcher import SmbWatcher
from connectors.rdp_capture import RdpCapture

__all__ = [
    "DocumentParser", "ParsedDocument",
    "DatabaseConnector",
    "EmailConnector",
    "SmbWatcher",
    "RdpCapture",
]

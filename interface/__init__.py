"""
WorkMind Interface Layer
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

- ChatServer: chat Gradio su porta 7860 con comandi /teach, /status, /report
- Dashboard: dashboard HTML multi-bot
"""

from interface.chat_server import ChatServer
from interface.dashboard import DashboardServer

__all__ = ["ChatServer", "DashboardServer"]

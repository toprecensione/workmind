"""
WorkMind AI Client
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Wrapper unificato per DeepSeek API e Claude (Anthropic) API.
- DeepSeek: 80% dei task (classificazione, entità, riassunti) — economico
- Claude Sonnet: 15% dei task (analisi, report, validazione)
- Claude Vision: OCR schermate RDP
- Fallback automatico: se un provider fallisce, tenta il successivo
- Budget manager: limiti giornalieri per bot con alert
"""

from ai_client.client import AIClient, AIMessage, AIResponse, ModelRole
from ai_client.budget import BudgetManager

__all__ = ["AIClient", "AIMessage", "AIResponse", "ModelRole", "BudgetManager"]

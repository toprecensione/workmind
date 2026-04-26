"""Telegram commands skill — registers and handles bot slash commands."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

COMMANDS = [
    ("start", "Avvia l'assistente WorkMind"),
    ("help", "Mostra i comandi disponibili"),
    ("status", "Stato sistema e stock"),
    ("report", "Report giornaliero veloce"),
    ("cerca", "Cerca nella knowledge base: /cerca <query>"),
]


async def register_commands(bot_token: str) -> bool:
    """Register bot commands with Telegram BotFather API."""
    import httpx
    payload = {"commands": [{"command": c, "description": d} for c, d in COMMANDS]}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{bot_token}/setMyCommands",
            json=payload,
        )
        return r.status_code == 200


async def handle_command(command: str, args: str, org_id: str, db: Any) -> str:
    """Handle incoming /command from Telegram webhook."""
    from sqlalchemy import select, func
    from app.db.models import MedicProduct

    cmd = command.lstrip("/").split("@")[0].lower()

    if cmd in ("start", "help"):
        return (
            "👋 *WorkMind MEDIC*\n\n"
            + "\n".join(f"/{c} — {d}" for c, d in COMMANDS)
        )
    elif cmd == "status":
        from app.db.models import Organization
        from uuid import UUID
        org = await db.get(Organization, UUID(org_id))
        low = await db.scalar(
            select(func.count(MedicProduct.id)).where(
                MedicProduct.org_id == UUID(org_id),
                MedicProduct.is_active,
                MedicProduct.stock_qty <= MedicProduct.low_stock_threshold,
            )
        )
        return (
            f"✅ Sistema attivo\n"
            f"🏢 {org.name if org else org_id}\n"
            f"⚠️ Prodotti stock basso: {low or 0}"
        )
    elif cmd == "report":
        # Trigger daily report inline
        from app.services.skills.implementations.daily_report import get_quick_summary
        return await get_quick_summary(org_id, db)
    elif cmd == "cerca":
        if not args.strip():
            return "Uso: /cerca <testo da cercare>"
        try:
            from app.api.routes.kb import _vector_search
            results = await _vector_search(args.strip(), org_id, db, top_k=3)
        except Exception as exc:
            logger.error(f"KB search failed: {exc}")
            return "Errore durante la ricerca nella knowledge base."
        if not results:
            return "Nessun risultato trovato nella knowledge base."
        lines = [f"🔍 *Risultati per «{args.strip()}»*\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('content', '')[:200]}…")
        return "\n".join(lines)
    return ""


def make_telegram_commands_job(org_id: str, config: dict):
    """Not a scheduled job — commands are handled via webhook. Returns no-op."""
    async def _noop():
        pass
    return _noop

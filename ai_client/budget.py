"""
WorkMind Budget Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Monitora e limita la spesa giornaliera per provider AI.
Prezzi approssimati (aggiornare se cambiano):
  DeepSeek: ~$0.14/M input token, ~$0.28/M output token
  Claude Sonnet 4.x: ~$3/M input, ~$15/M output
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from config.settings import config, DATA_DIR
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("ai_client.budget")

# Prezzi per 1M token (USD)
_PRICE_TABLE: dict[str, dict[str, float]] = {
    "deepseek": {"input": 0.14, "output": 0.28},
    "claude":   {"input": 3.00, "output": 15.00},
}

_BUDGET_FILE = DATA_DIR / "budget_usage.json"
_LOCK = threading.Lock()


class BudgetManager:
    """
    Gestione budget giornaliero per provider AI.

    Carica/salva i contatori su file JSON.
    Ogni giorno i contatori vengono azzerati automaticamente.
    """

    def __init__(self) -> None:
        self._data: dict = self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def can_spend(self, provider: str, estimated_tokens: int = 1000) -> bool:
        """Restituisce True se c'è ancora budget disponibile per oggi."""
        limit = self._get_daily_limit(provider)
        if limit <= 0:
            return True  # nessun limite configurato
        spent = self._today_cost(provider)
        return spent < limit

    def record_usage(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> float:
        """Registra l'uso di token e ritorna il costo in USD."""
        price = _PRICE_TABLE.get(provider, {"input": 0.0, "output": 0.0})
        cost = (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000

        today = date.today().isoformat()
        with _LOCK:
            self._ensure_today(provider, today)
            self._data[provider][today]["input_tokens"]  += input_tokens
            self._data[provider][today]["output_tokens"] += output_tokens
            self._data[provider][today]["cost_usd"]      += cost
            self._data[provider][today]["calls"]         += 1
            self._save()

        limit = self._get_daily_limit(provider)
        spent = self._today_cost(provider)
        if limit > 0 and spent > limit * 0.80:
            log.warning(
                f"Budget {provider}: ${spent:.3f} / ${limit:.2f} (>{80}%)",
                action=LogAction.MONITOR, status=LogStatus.WARNING,
                suggestion=f"Ridurre le chiamate a {provider} o aumentare il limite.",
            )
        return cost

    def daily_summary(self) -> dict[str, dict]:
        """Riepilogo spesa odierna per provider."""
        today = date.today().isoformat()
        summary = {}
        for provider in _PRICE_TABLE:
            d = self._data.get(provider, {}).get(today, {})
            summary[provider] = {
                "calls":         d.get("calls", 0),
                "input_tokens":  d.get("input_tokens", 0),
                "output_tokens": d.get("output_tokens", 0),
                "cost_usd":      round(d.get("cost_usd", 0.0), 4),
                "limit_usd":     self._get_daily_limit(provider),
            }
        return summary

    # ── Internal ──────────────────────────────────────────────────────────────

    def _today_cost(self, provider: str) -> float:
        today = date.today().isoformat()
        return self._data.get(provider, {}).get(today, {}).get("cost_usd", 0.0)

    def _get_daily_limit(self, provider: str) -> float:
        cfg = getattr(config, "ai", None)
        if cfg is None:
            return 0.0
        if provider == "deepseek":
            return getattr(cfg, "deepseek_daily_limit_usd", 0.0)
        if provider == "claude":
            return getattr(cfg, "claude_daily_limit_usd", 0.0)
        return 0.0

    def _ensure_today(self, provider: str, today: str) -> None:
        self._data.setdefault(provider, {})
        self._data[provider].setdefault(today, {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0
        })

    def _load(self) -> dict:
        if _BUDGET_FILE.exists():
            try:
                return json.loads(_BUDGET_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        _BUDGET_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# Singleton
_budget: Optional[BudgetManager] = None


def get_budget() -> BudgetManager:
    global _budget
    if _budget is None:
        _budget = BudgetManager()
    return _budget

"""
WorkMind — Data Agent
Executes pre-defined analytical SQL queries on the WorkMind database and returns
structured JSON results. Scoped to the caller's org_id for multi-tenancy safety.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent

log = structlog.get_logger("workmind.data_agent")


# ── Predefined query registry ──────────────────────────────────────────────────
# Each entry: (sql_template, description)
# All queries MUST include an :org_id parameter for org-scoping.

_QUERIES: dict[str, tuple[str, str]] = {
    "top_products_by_sales": (
        """
        SELECT
            p.name                              AS product,
            SUM(s.quantity)                     AS total_units_sold,
            SUM(s.total_eur)                    AS total_revenue_eur
        FROM medic_sales s
        JOIN medic_products p ON p.id = s.product_id
        WHERE s.org_id = :org_id
        GROUP BY p.name
        ORDER BY total_revenue_eur DESC NULLS LAST
        LIMIT 10
        """,
        "Top 10 products by revenue",
    ),
    "low_stock_products": (
        """
        SELECT
            p.name                              AS product,
            p.stock_qty                         AS current_stock,
            p.low_stock_threshold               AS threshold,
            p.unit
        FROM medic_products p
        WHERE
            p.org_id = :org_id
            AND p.is_active = true
            AND p.stock_qty <= p.low_stock_threshold
        ORDER BY p.stock_qty ASC
        """,
        "Products at or below low-stock threshold",
    ),
    "recent_sales": (
        """
        SELECT
            s.sale_date                         AS date,
            p.name                              AS product,
            s.quantity,
            s.unit_price_eur,
            s.total_eur
        FROM medic_sales s
        JOIN medic_products p ON p.id = s.product_id
        WHERE
            s.org_id = :org_id
            AND s.sale_date >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY s.sale_date DESC
        LIMIT 50
        """,
        "Sales in the last 30 days",
    ),
    "inventory_summary": (
        """
        SELECT
            p.name                              AS product,
            p.stock_qty                         AS total_stock,
            p.unit,
            COALESCE(SUM(l.quantity_remaining), 0) AS lot_remaining,
            COUNT(l.id)                         AS active_lots
        FROM medic_products p
        LEFT JOIN medic_inventory_lots l
            ON l.product_id = p.id
            AND (l.expiry_date IS NULL OR l.expiry_date > CURRENT_DATE)
            AND l.quantity_remaining > 0
        WHERE p.org_id = :org_id AND p.is_active = true
        GROUP BY p.id, p.name, p.stock_qty, p.unit
        ORDER BY p.name
        """,
        "Current inventory summary per product",
    ),
    "expiring_soon": (
        """
        SELECT
            p.name                              AS product,
            l.lot_number,
            l.quantity_remaining,
            l.expiry_date
        FROM medic_inventory_lots l
        JOIN medic_products p ON p.id = l.product_id
        WHERE
            l.org_id = :org_id
            AND l.expiry_date IS NOT NULL
            AND l.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days'
            AND l.quantity_remaining > 0
        ORDER BY l.expiry_date ASC
        """,
        "Lots expiring within 90 days",
    ),
}


def _rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    """Convert SQLAlchemy row mappings to plain dicts with JSON-safe values."""
    result = []
    for row in rows.mappings():
        d: dict[str, Any] = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):  # datetime/date
                d[k] = v.isoformat()
            elif v is None:
                d[k] = None
            else:
                try:
                    d[k] = float(v) if "." in str(v) else v
                except (TypeError, ValueError):
                    d[k] = v
        result.append(d)
    return result


class DataAgent(BaseAgent):
    name = "data_agent"

    async def run(self, query: str, context: dict) -> dict:
        """
        Execute one or more pre-defined SQL queries based on *query* intent.

        Expected context keys:
          - org_id: UUID
          - session: AsyncSession
          - query_key: str | None   (if provided, run that specific query)

        If *query_key* is not in context, the agent tries to match the query
        text against query names and descriptions, falling back to running
        all available queries.

        Returns: {"results": {query_key: [rows]}, "descriptions": {query_key: desc}}
        """
        org_id: uuid.UUID = context["org_id"]
        session: AsyncSession = context["session"]
        query_key: str | None = context.get("query_key")

        # Determine which queries to run
        if query_key and query_key in _QUERIES:
            keys_to_run = [query_key]
        else:
            # Simple keyword matching against query names
            q_lower = query.lower()
            matched = [
                k for k in _QUERIES
                if any(word in q_lower for word in k.split("_"))
            ]
            keys_to_run = matched if matched else list(_QUERIES.keys())

        results: dict[str, list[dict[str, Any]]] = {}
        descriptions: dict[str, str] = {}

        for key in keys_to_run:
            sql_template, description = _QUERIES[key]
            descriptions[key] = description
            try:
                rows = await session.execute(
                    text(sql_template),
                    {"org_id": str(org_id)},
                )
                results[key] = _rows_to_dicts(rows)
                log.info(
                    "data_agent_query_ok",
                    key=key,
                    rows=len(results[key]),
                    org_id=str(org_id),
                )
            except Exception as exc:
                log.error("data_agent_query_error", key=key, error=str(exc))
                results[key] = []

        return {"results": results, "descriptions": descriptions}

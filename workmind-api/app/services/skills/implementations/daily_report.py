"""Skill: daily_report — report giornaliero MEDIC."""
from __future__ import annotations
from datetime import date, timedelta
import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import get_settings
from app.db.models import MedicSale, MedicProduct, MedicInventoryLot
from app.services.connectors import get_connector_registry
from app.services.skills.implementations.low_stock_alert import _send_telegram, _send_email
import asyncio

log = structlog.get_logger()


def make_daily_report_job(org_id: str, cfg: dict):
    async def run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            try:
                await _run_daily_report(db, org_id, cfg)
            except Exception as exc:
                log.error("daily_report_error", error=str(exc))
        await engine.dispose()
    return run


async def _run_daily_report(db, org_id: str, cfg: dict):
    yesterday = date.today() - timedelta(days=1)

    # Vendite ieri
    sales_r = await db.execute(
        select(
            func.count(MedicSale.id).label("count"),
            func.sum(MedicSale.quantity).label("qty"),
            func.sum(MedicSale.unit_price_eur * MedicSale.quantity).label("revenue"),
        ).where(
            MedicSale.org_id == org_id,
            MedicSale.sale_date == yesterday,
        )
    )
    stats = sales_r.one()

    # Prodotti sotto soglia
    prod_r = await db.execute(
        select(MedicProduct).where(
            MedicProduct.org_id == org_id,
            MedicProduct.is_active,
        )
    )
    products = prod_r.scalars().all()
    low_stock = [p for p in products if p.stock_qty <= p.low_stock_threshold]

    # Lotti in scadenza 7 gg
    exp_cut = date.today() + timedelta(days=7)
    exp_r = await db.execute(
        select(MedicInventoryLot, MedicProduct.name.label("pname"))
        .join(MedicProduct, MedicInventoryLot.product_id == MedicProduct.id)
        .where(
            MedicInventoryLot.org_id == org_id,
            MedicInventoryLot.quantity_remaining > 0,
            MedicInventoryLot.expiry_date is not None,
            MedicInventoryLot.expiry_date <= exp_cut,
        )
    )
    expiring = exp_r.all()

    revenue = float(stats.revenue or 0)
    lines = [
        f"📊 *Report MEDIC — {yesterday.strftime('%d/%m/%Y')}*\n",
        f"🛒 Vendite: {stats.count or 0} operazioni | {stats.qty or 0} unità | €{revenue:.2f}",
        f"📦 Prodotti totali: {len(products)} | Sotto soglia: {len(low_stock)}",
    ]
    if low_stock:
        lines.append("⚠️ Sotto soglia: " + ", ".join(p.name for p in low_stock))
    if expiring:
        lines.append(f"⏰ Lotti in scadenza 7gg: {len(expiring)}")
        for row in expiring[:3]:
            lot, pname = row
            lines.append(f"  • {pname}: {lot.quantity_remaining} pz → scade {lot.expiry_date}")

    message = "\n".join(lines)
    reg = get_connector_registry()

    if cfg.get("notify_via_telegram", True):
        tg_cfg = await reg.get_config(db, org_id, "telegram")
        if tg_cfg and tg_cfg.get("chat_id_default"):
            await _send_telegram(tg_cfg["bot_token"], tg_cfg["chat_id_default"], message)

    if cfg.get("notify_via_email") and cfg.get("email_recipient"):
        smtp_cfg = await reg.get_config(db, org_id, "smtp")
        if smtp_cfg:
            await asyncio.to_thread(_send_email, smtp_cfg, cfg["email_recipient"],
                                    f"Report MEDIC {yesterday.strftime('%d/%m/%Y')}", message)


async def get_quick_summary(org_id: str, db) -> str:
    """Return a compact daily summary string for inline use (e.g. /report command)."""
    from datetime import date, timedelta
    yesterday = date.today() - timedelta(days=1)

    sales_r = await db.execute(
        select(
            func.count(MedicSale.id).label("count"),
            func.sum(MedicSale.unit_price_eur * MedicSale.quantity).label("revenue"),
        ).where(
            MedicSale.org_id == org_id,
            MedicSale.sale_date == yesterday,
        )
    )
    stats = sales_r.one()

    prod_r = await db.execute(
        select(MedicProduct).where(
            MedicProduct.org_id == org_id,
            MedicProduct.is_active,
        )
    )
    products = prod_r.scalars().all()
    low_stock = [p for p in products if p.stock_qty <= p.low_stock_threshold]

    revenue = float(stats.revenue or 0)
    lines = [
        f"📊 *Report MEDIC — {yesterday.strftime('%d/%m/%Y')}*",
        f"🛒 Vendite ieri: {stats.count or 0} | €{revenue:.2f}",
        f"📦 Prodotti: {len(products)} totali | {len(low_stock)} sotto soglia",
    ]
    if low_stock:
        names = ", ".join(p.name for p in low_stock[:5])
        if len(low_stock) > 5:
            names += f" (+{len(low_stock) - 5})"
        lines.append(f"⚠️ {names}")
    return "\n".join(lines)

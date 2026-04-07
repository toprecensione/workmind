#!/usr/bin/env python3
"""
WorkMind — Main Entry Point
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Usage:
    python main.py [--scan-dirs /path/a /path/b] [--update-now] [--once]
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from config.settings import config, BASE_DIR
from config.company import get_company_config
from logging_system import get_logger, LogStatus, LogAction
from agent_manager import AgentManager
from mindwork import MindWork
from updater import AutoUpdater
from version import get_full_version

log = get_logger("main")

_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    log.info(f"Signal {signum} received — initiating graceful shutdown",
             action=LogAction.SHUTDOWN, status=LogStatus.STOPPING)
    _shutdown = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WorkMind Node Runner")
    parser.add_argument(
        "--scan-dirs", nargs="*",
        default=[str(BASE_DIR / "data")],
        help="Directories MindWork should monitor",
    )
    parser.add_argument(
        "--update-now", action="store_true",
        help="Run an update check immediately on startup",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run one scan/analyse/report cycle then exit",
    )
    return parser.parse_args()


def main() -> int:
    global _shutdown

    args = parse_args()
    company = get_company_config()

    log.info(
        f"WorkMind starting — version {get_full_version()} — {company.name}",
        action=LogAction.STARTUP, status=LogStatus.STARTED,
        extra={
            "node_id":     config.node.node_id,
            "environment": config.node.environment,
            "company":     company.name,
            "scan_dirs":   args.scan_dirs,
        },
    )

    # ── Register OS signals ────────────────────────────────────────────────
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT,  _signal_handler)

    # ── Optional immediate update ──────────────────────────────────────────
    if args.update_now:
        updater = AutoUpdater()
        updated = updater.check_and_update()
        if updated:
            log.info("Update applied — restarting…", action=LogAction.UPDATE, status=LogStatus.OK)
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # ── Bootstrap Agent Manager ───────────────────────────────────────────
    agent = AgentManager()
    agent.start()

    # ── Bootstrap connectors ──────────────────────────────────────────────
    _start_connectors(company)

    # ── Bootstrap MindWork ────────────────────────────────────────────────
    mw = MindWork(agent=agent, target_dirs=args.scan_dirs)

    if args.once:
        mw.run_once()
        agent.stop()
        return 0

    mw.start()

    # ── Load Plugins ──────────────────────────────────────────────────────
    try:
        import plugin_loader
        plugins = plugin_loader.load_plugins()
        plugin_loader.startup_all()
        log.info(f"Plugin loader attivo: {[p.id for p in plugins]}",
                 action=LogAction.STARTUP, status=LogStatus.OK)
    except Exception as exc:
        log.warning(f"Plugin loader non avviato: {exc}", action=LogAction.STARTUP)
        plugins = []

    # ── Start report scheduler ────────────────────────────────────────────
    report_sched = None
    try:
        from mindwork.report_scheduler import ReportScheduler
        report_sched = ReportScheduler()
        report_sched.start()
    except Exception as exc:
        log.warning(f"Report scheduler non avviato: {exc}", action=LogAction.STARTUP)

    # ── Start Web UI (Apple-style) ────────────────────────────────────────
    try:
        from interface.web_ui import WorkMindUI
        ui = WorkMindUI(port=7860)
        ui.start()
    except Exception as exc:
        log.warning(f"Web UI non avviata: {exc}", action=LogAction.STARTUP)

    # ── Start Telegram Bot ────────────────────────────────────────────────
    try:
        from interface.telegram_bot import WorkMindTelegramBot
        tg_bot = WorkMindTelegramBot()
        tg_bot.start()
    except Exception as exc:
        log.warning(f"Telegram bot non avviato: {exc}", action=LogAction.STARTUP)

    # ── Start Telegram Notifications ──────────────────────────────────────
    tg_notifier = None
    try:
        from interface.telegram_notifications import get_notifier
        tg_notifier = get_notifier()
        tg_notifier.start()
    except Exception as exc:
        log.warning(f"Telegram notifier non avviato: {exc}", action=LogAction.STARTUP)

    # ── Start Backup Manager ──────────────────────────────────────────────
    backup_mgr = None
    try:
        from storage.backup import get_backup_manager
        backup_mgr = get_backup_manager()
        backup_mgr.start(interval_hours=24)
    except Exception as exc:
        log.warning(f"Backup manager non avviato: {exc}", action=LogAction.STARTUP)

    # ── Periodic update check ─────────────────────────────────────────────
    updater         = AutoUpdater()
    update_interval = config.update.check_interval_minutes * 60
    last_update_check = 0.0

    # ── Main loop ─────────────────────────────────────────────────────────
    log.info(
        "WorkMind is running — UI: http://0.0.0.0:7860 — Press Ctrl+C to stop.",
        action=LogAction.STARTUP, status=LogStatus.OK,
    )
    try:
        while not _shutdown:
            now = time.time()
            if now - last_update_check >= update_interval:
                last_update_check = now
                try:
                    updated = updater.check_and_update()
                    if updated:
                        log.info(
                            "Update applied — scheduling graceful restart",
                            action=LogAction.UPDATE, status=LogStatus.OK,
                        )
                        _shutdown = True
                except Exception:
                    pass
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down…", action=LogAction.SHUTDOWN, status=LogStatus.STOPPING)
        try:
            import plugin_loader
            plugin_loader.shutdown_all()
        except Exception:
            pass
        mw.stop()
        if report_sched:
            report_sched.stop()
        if tg_notifier:
            tg_notifier.stop()
        if backup_mgr:
            backup_mgr.stop()
        agent.stop()
        log.info("WorkMind stopped cleanly.", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)

    return 0


def _start_connectors(company) -> None:
    """Avvia i connettori dati in base alla configurazione aziendale."""

    if company.database.enabled:
        try:
            from connectors.database import DatabaseConnector
            db = DatabaseConnector()
            if db.connect():
                if company.database.schema_discovery:
                    schema = db.discover_schema()
                    log.info(f"DB schema: {len(schema.tables)} tabelle", action=LogAction.SCAN)
        except Exception as exc:
            log.warning(f"Database connector non avviato: {exc}", action=LogAction.STARTUP)

    if company.email.enabled:
        try:
            from connectors.email_connector import EmailConnector
            email_conn = EmailConnector()
            emails = email_conn.fetch_recent(max_count=10)
            log.info(f"Email: {len(emails)} messaggi recenti", action=LogAction.SCAN)
        except Exception as exc:
            log.warning(f"Email connector non avviato: {exc}", action=LogAction.STARTUP)

    if company.smb.enabled:
        try:
            from connectors.smb_watcher import SmbWatcher
            smb = SmbWatcher()
            smb.start()
        except Exception as exc:
            log.warning(f"SMB watcher non avviato: {exc}", action=LogAction.STARTUP)

    if company.rdp.enabled:
        try:
            from connectors.rdp_capture import RdpCapture
            rdp = RdpCapture()
            rdp.start()
        except Exception as exc:
            log.warning(f"RDP capture non avviato: {exc}", action=LogAction.STARTUP)


if __name__ == "__main__":
    sys.exit(main())

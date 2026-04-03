#!/usr/bin/env python3
"""
WorkMind — Main Entry Point
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Usage:
    python main.py [--scan-dirs /path/a /path/b] [--update-now]
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from config.settings import config, BASE_DIR
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
    args = parse_args()

    log.info(
        f"WorkMind starting — version {get_full_version()}",
        action=LogAction.STARTUP, status=LogStatus.STARTED,
        extra={
            "node_id":     config.node.node_id,
            "environment": config.node.environment,
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
            # Restart this process with the new code
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # ── Bootstrap Agent Manager ───────────────────────────────────────────
    agent = AgentManager()
    agent.start()

    # ── Bootstrap MindWork ────────────────────────────────────────────────
    mw = MindWork(agent=agent, target_dirs=args.scan_dirs)

    if args.once:
        mw.run_once()
        agent.stop()
        return 0

    mw.start()

    # ── Periodic update check ─────────────────────────────────────────────
    updater         = AutoUpdater()
    update_interval = config.update.check_interval_minutes * 60
    last_update_check = 0.0

    # ── Main loop ─────────────────────────────────────────────────────────
    log.info("WorkMind is running. Press Ctrl+C to stop.", action=LogAction.STARTUP, status=LogStatus.OK)
    try:
        while not _shutdown:
            now = time.time()
            if now - last_update_check >= update_interval:
                last_update_check = now
                updated = updater.check_and_update()
                if updated:
                    log.info(
                        "Update applied — scheduling graceful restart",
                        action=LogAction.UPDATE, status=LogStatus.OK,
                    )
                    _shutdown = True   # let systemd / Docker restart us cleanly
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down…", action=LogAction.SHUTDOWN, status=LogStatus.STOPPING)
        mw.stop()
        agent.stop()
        log.info("WorkMind stopped cleanly.", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)

    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())

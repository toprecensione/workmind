"""
MindWork — Main Orchestrator
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
"""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import TYPE_CHECKING, List

from config.settings import config
from logging_system import get_logger, LogStatus, LogAction
from mindwork.scanner  import DirectoryScanner
from mindwork.analyser import PatternAnalyser
from mindwork.reporter import ReportEngine

if TYPE_CHECKING:
    from agent_manager.manager import AgentManager

log = get_logger("mindwork.core")


class MindWork:
    """
    Top-level controller.  Runs scan → analyse → report cycles on a schedule.
    All OS interaction is brokered through AgentManager.
    """

    def __init__(self, agent: "AgentManager", target_dirs: List[str]) -> None:
        self._agent   = agent
        self._targets = target_dirs
        self._scanner = DirectoryScanner(agent)
        self._analyser = PatternAnalyser()
        self._reporter = ReportEngine(agent)
        self._running  = False
        self._thread: threading.Thread | None = None

    def run_once(self) -> None:
        """Execute a single scan/analyse/report cycle synchronously."""
        for target in self._targets:
            try:
                snapshot = self._scanner.scan(target)
                result   = self._analyser.analyse(snapshot)
                self._reporter.generate(result)
            except Exception as exc:
                log.error(
                    f"Cycle failed for '{target}': {exc}",
                    action=LogAction.ANALYSE, status=LogStatus.ERROR,
                    exc_info=True,
                    suggestion="Check path permissions and Agent Manager logs.",
                )

    def start(self) -> None:
        """Start background periodic cycle."""
        self._running = True
        interval = config.mindwork.scan_interval_minutes * 60
        self._thread = threading.Thread(target=self._loop, args=(interval,), daemon=True, name="MindWorkCycle")
        self._thread.start()
        log.info("MindWork periodic cycle started", action=LogAction.STARTUP, status=LogStatus.STARTED,
                 extra={"interval_minutes": config.mindwork.scan_interval_minutes})

    def stop(self) -> None:
        self._running = False
        log.info("MindWork cycle stopped", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)

    def _loop(self, interval: float) -> None:
        while self._running:
            self.run_once()
            time.sleep(interval)


__all__ = ["MindWork"]

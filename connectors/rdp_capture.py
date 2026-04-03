"""
WorkMind RDP Capture
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Cattura screenshot di gestionali Windows via RDP (xfreerdp su Linux).
Le immagini vengono poi processate da Claude Vision per OCR.

Flusso:
  1. xfreerdp connette al desktop remoto
  2. Screenshot periodico delle finestre target
  3. Immagine inviata a Claude Vision per estrazione testo
  4. Testo estratto passato al NLP Engine
"""

from __future__ import annotations

import os
import subprocess
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from config.company import CompanyConfig, get_company_config
from config.settings import DATA_DIR
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("connectors.rdp_capture")

_SCREENSHOT_DIR = DATA_DIR / "rdp_screenshots"
_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class RdpScreenshot:
    path: str
    captured_at: float
    host: str
    window_title: str = ""
    ocr_text: str = ""


class RdpCapture:
    """
    Cattura periodica di screenshot via RDP.
    Richiede xfreerdp installato su Ubuntu.
    """

    def __init__(
        self,
        company_cfg: Optional[CompanyConfig] = None,
        on_screenshot: Optional[Callable[[RdpScreenshot], None]] = None,
    ) -> None:
        self._cfg = (company_cfg or get_company_config()).rdp
        self._callback = on_screenshot
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled and bool(self._cfg.host)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled:
            log.info("RDP capture disabilitato", action=LogAction.CONFIG)
            return

        if not self._check_xfreerdp():
            log.error(
                "xfreerdp non trovato",
                action=LogAction.STARTUP, status=LogStatus.ERROR,
                suggestion="Installa: sudo apt install freerdp2-x11",
            )
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="RDPCapture",
        )
        self._thread.start()
        log.info(
            f"RDP capture avviato: {self._cfg.host} ogni {self._cfg.screenshot_interval_minutes}min",
            action=LogAction.STARTUP, status=LogStatus.OK,
        )

    def stop(self) -> None:
        self._running = False
        log.info("RDP capture fermato", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)

    # ── Capture loop ──────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        interval = self._cfg.screenshot_interval_minutes * 60
        while self._running:
            try:
                screenshot = self._take_screenshot()
                if screenshot and self._callback:
                    self._callback(screenshot)
            except Exception as exc:
                log.error(f"Errore screenshot RDP: {exc}", action=LogAction.SCAN)
            time.sleep(interval)

    def _take_screenshot(self) -> Optional[RdpScreenshot]:
        """
        Usa xfreerdp con /sec:nla per connettersi, acquisire uno screenshot e disconnettersi.
        L'approccio è headless: si usa un framebuffer virtuale (Xvfb).
        """
        timestamp = int(time.time())
        filename = f"rdp_{self._cfg.host}_{timestamp}.png"
        filepath = _SCREENSHOT_DIR / filename

        cmd = [
            "xfreerdp",
            f"/v:{self._cfg.host}:{self._cfg.port}",
            f"/u:{self._cfg.username}",
            f"/p:{self._cfg.password}",
            "/cert:ignore",
            "/sec:nla",
            "+compression",
            "/size:1920x1080",
            f"/screenshot:{filepath}",
            "/timeout:15000",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
                env={**os.environ, "DISPLAY": ":99"},
            )

            if filepath.exists():
                log.info(
                    f"Screenshot RDP catturato: {filename}",
                    action=LogAction.SCAN, status=LogStatus.OK,
                )
                return RdpScreenshot(
                    path=str(filepath),
                    captured_at=timestamp,
                    host=self._cfg.host,
                )
            else:
                log.warning(
                    "Screenshot non generato (xfreerdp exit senza file)",
                    action=LogAction.SCAN, status=LogStatus.WARNING,
                )
                return None
        except subprocess.TimeoutExpired:
            log.warning("xfreerdp timeout", action=LogAction.SCAN, status=LogStatus.WARNING)
            return None
        except Exception as exc:
            log.error(f"xfreerdp fallito: {exc}", action=LogAction.SCAN)
            return None

    def capture_now(self) -> Optional[RdpScreenshot]:
        """Screenshot singolo on-demand."""
        return self._take_screenshot()

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_xfreerdp() -> bool:
        try:
            result = subprocess.run(
                ["xfreerdp", "--version"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def cleanup_old_screenshots(self, max_age_hours: int = 24) -> int:
        """Rimuove screenshot più vecchi di max_age_hours."""
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for f in _SCREENSHOT_DIR.glob("rdp_*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        return removed

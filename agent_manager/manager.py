"""
WorkMind Agent Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Responsibilities
────────────────
• Spawn / terminate MindWork subprocesses
• Enforce CPU / memory / filesystem permission boundaries
• Monitor process health via heartbeats
• Restart failed processes with exponential back-off
• Log every lifecycle event in structured JSON
• Provide a controlled API surface for MindWork to request OS-level actions
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Optional

import psutil

from config.settings import config, AgentConfig
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("agent_manager")


# ─── Process State ────────────────────────────────────────────────────────────

class ProcessState(str, Enum):
    IDLE       = "idle"
    STARTING   = "starting"
    RUNNING    = "running"
    RESTARTING = "restarting"
    STOPPING   = "stopping"
    FAILED     = "failed"
    STOPPED    = "stopped"


@dataclass
class ManagedProcess:
    name: str
    command: list[str]
    state: ProcessState = ProcessState.IDLE
    pid: Optional[int]  = None
    restart_count: int  = 0
    last_started: float = 0.0
    last_heartbeat: float = 0.0
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False, compare=False)


# ─── Permission Guard ─────────────────────────────────────────────────────────

class PermissionError(Exception):
    """Raised when MindWork requests a forbidden operation."""


class PermissionGuard:
    """
    Validates every filesystem/OS request from MindWork before execution.
    Operates on an allow-list principle: if not explicitly allowed → denied.
    """

    def __init__(self, cfg: AgentConfig) -> None:
        self._allowed = [Path(p).resolve() for p in cfg.allowed_base_paths]
        self._forbidden = [Path(p).resolve() for p in cfg.forbidden_paths]

    def check_path(self, requested: str | Path) -> Path:
        """
        Return the resolved Path if allowed, otherwise raise PermissionError.
        """
        resolved = Path(requested).resolve()

        for forbidden in self._forbidden:
            try:
                resolved.relative_to(forbidden)
                raise PermissionError(
                    f"Access denied: '{resolved}' is inside forbidden path '{forbidden}'"
                )
            except ValueError:
                pass  # not relative to this forbidden path — good

        for allowed in self._allowed:
            try:
                resolved.relative_to(allowed)
                return resolved  # explicitly allowed
            except ValueError:
                pass

        raise PermissionError(
            f"Access denied: '{resolved}' is outside all allowed paths. "
            f"Allowed roots: {[str(p) for p in self._allowed]}"
        )

    def check_operation(self, operation: str) -> None:
        """Block inherently dangerous operation names."""
        _blocked_ops = {
            "rm_rf", "chmod_777", "sudo", "chown_root",
            "install_package", "write_crontab", "reboot", "shutdown",
        }
        if operation.lower() in _blocked_ops:
            raise PermissionError(f"Operation '{operation}' is not permitted.")


# ─── Resource Monitor ─────────────────────────────────────────────────────────

class ResourceMonitor:
    """Polls CPU / memory usage of a managed process and kills if exceeded."""

    def __init__(self, cfg: AgentConfig) -> None:
        self._cfg = cfg

    def check(self, proc: ManagedProcess) -> tuple[bool, str]:
        """
        Returns (within_limits, reason).
        within_limits = False means the caller should kill the process.
        """
        if proc.pid is None:
            return True, "no pid"
        try:
            ps = psutil.Process(proc.pid)
            cpu  = ps.cpu_percent(interval=0.5)
            mem  = ps.memory_info().rss / (1024 * 1024)  # MB
            fds  = ps.num_fds() if hasattr(ps, "num_fds") else 0

            if cpu > self._cfg.max_cpu_percent:
                return False, f"CPU {cpu:.1f}% > limit {self._cfg.max_cpu_percent}%"
            if mem > self._cfg.max_memory_mb:
                return False, f"Memory {mem:.0f} MB > limit {self._cfg.max_memory_mb} MB"
            if fds > self._cfg.max_open_files:
                return False, f"Open FDs {fds} > limit {self._cfg.max_open_files}"
            return True, "ok"
        except psutil.NoSuchProcess:
            return False, "process no longer exists"


# ─── Agent Manager ────────────────────────────────────────────────────────────

class AgentManager:
    """
    Central orchestrator.  Call `start()` to begin the supervisor loop.
    """

    def __init__(self, cfg: AgentConfig | None = None) -> None:
        self._cfg       = cfg or config.agent
        self._guard     = PermissionGuard(self._cfg)
        self._monitor   = ResourceMonitor(self._cfg)
        self._processes: Dict[str, ManagedProcess] = {}
        self._running   = False
        self._lock      = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register(self, name: str, command: list[str]) -> None:
        """Register a named process. Does not start it yet."""
        with self._lock:
            self._processes[name] = ManagedProcess(name=name, command=command)
        log.info(f"Process '{name}' registered", action=LogAction.CONFIG, status=LogStatus.OK)

    def start_process(self, name: str) -> None:
        """Spawn (or re-spawn) a registered process."""
        with self._lock:
            proc = self._processes.get(name)
            if proc is None:
                raise KeyError(f"Unknown process: '{name}'")
            self._spawn(proc)

    def stop_process(self, name: str, timeout: int = 10) -> None:
        with self._lock:
            proc = self._processes.get(name)
            if proc is None or proc._proc is None:
                return
            self._terminate(proc, timeout)

    def request_file_read(self, path: str) -> Path:
        """MindWork calls this to get a validated, safe Path for reading."""
        safe_path = self._guard.check_path(path)
        log.info(
            f"File read approved: {safe_path}",
            action=LogAction.PERMISSION, status=LogStatus.OK,
        )
        return safe_path

    def request_file_write(self, path: str) -> Path:
        """MindWork calls this to get a validated, safe Path for writing."""
        safe_path = self._guard.check_path(path)
        log.info(
            f"File write approved: {safe_path}",
            action=LogAction.PERMISSION, status=LogStatus.OK,
        )
        return safe_path

    def start(self) -> None:
        """Start the supervisor background thread."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._supervisor_loop,
            name="AgentManagerSupervisor",
            daemon=True,
        )
        self._thread.start()
        log.info("AgentManager supervisor started", action=LogAction.STARTUP, status=LogStatus.STARTED)

    def stop(self) -> None:
        """Graceful shutdown of all managed processes + supervisor."""
        log.info("AgentManager shutting down…", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)
        self._running = False
        with self._lock:
            for proc in self._processes.values():
                if proc._proc:
                    self._terminate(proc)
        if self._thread:
            self._thread.join(timeout=15)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _spawn(self, proc: ManagedProcess) -> None:
        proc.state = ProcessState.STARTING
        log.info(
            f"Spawning '{proc.name}': {' '.join(proc.command)}",
            action=LogAction.SPAWN, status=LogStatus.STARTED,
            extra={"command": proc.command, "restart_count": proc.restart_count},
        )
        try:
            p = subprocess.Popen(
                proc.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,       # new process group → clean kill
            )
            proc._proc         = p
            proc.pid           = p.pid
            proc.state         = ProcessState.RUNNING
            proc.last_started  = time.time()
            proc.last_heartbeat = time.time()
            log.info(
                f"Process '{proc.name}' started (pid={p.pid})",
                action=LogAction.SPAWN, status=LogStatus.OK,
            )
        except Exception as exc:
            proc.state = ProcessState.FAILED
            log.error(
                f"Failed to spawn '{proc.name}': {exc}",
                action=LogAction.SPAWN, status=LogStatus.ERROR,
                exc_info=True,
            )

    def _terminate(self, proc: ManagedProcess, timeout: int = 10) -> None:
        proc.state = ProcessState.STOPPING
        if proc._proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc._proc.wait(timeout=timeout)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.state = ProcessState.STOPPED
        proc.pid   = None
        proc._proc = None
        log.info(f"Process '{proc.name}' terminated", action=LogAction.KILL, status=LogStatus.STOPPED)

    def _supervisor_loop(self) -> None:
        while self._running:
            time.sleep(self._cfg.heartbeat_interval_seconds)
            with self._lock:
                for proc in list(self._processes.values()):
                    self._check_process(proc)

    def _check_process(self, proc: ManagedProcess) -> None:
        if proc.state not in (ProcessState.RUNNING, ProcessState.STARTING):
            return

        # Check if the OS process is still alive
        if proc._proc and proc._proc.poll() is not None:
            exit_code = proc._proc.returncode
            log.warning(
                f"Process '{proc.name}' exited unexpectedly (code={exit_code})",
                action=LogAction.MONITOR, status=LogStatus.WARNING,
                extra={"exit_code": exit_code},
                suggestion="Check logs for the subprocess for detailed error information.",
            )
            proc.state = ProcessState.FAILED
            self._maybe_restart(proc)
            return

        # Check resource limits
        within_limits, reason = self._monitor.check(proc)
        if not within_limits:
            log.warning(
                f"Process '{proc.name}' exceeded resource limit: {reason}",
                action=LogAction.MONITOR, status=LogStatus.WARNING,
                suggestion="Review MindWork scan concurrency settings to reduce load.",
            )
            self._terminate(proc)
            self._maybe_restart(proc)
            return

        # Heartbeat OK
        proc.last_heartbeat = time.time()
        log.debug(
            f"Heartbeat ok: '{proc.name}' (pid={proc.pid})",
            action=LogAction.HEARTBEAT, status=LogStatus.OK,
        )

    def _maybe_restart(self, proc: ManagedProcess) -> None:
        if proc.restart_count >= self._cfg.max_restart_attempts:
            proc.state = ProcessState.FAILED
            log.error(
                f"Process '{proc.name}' exceeded max restart attempts ({self._cfg.max_restart_attempts}). "
                "Manual intervention required.",
                action=LogAction.SPAWN, status=LogStatus.ERROR,
                suggestion="Inspect logs and restart manually after fixing the root cause.",
            )
            return

        proc.restart_count += 1
        backoff = self._cfg.restart_backoff_seconds * proc.restart_count
        log.info(
            f"Scheduling restart #{proc.restart_count} for '{proc.name}' in {backoff}s…",
            action=LogAction.SPAWN, status=LogStatus.PENDING,
        )
        proc.state = ProcessState.RESTARTING
        threading.Timer(backoff, self._spawn, args=(proc,)).start()

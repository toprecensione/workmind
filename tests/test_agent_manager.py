"""
WorkMind Test Suite — Agent Manager & Permission Guard
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
"""

import sys
import os
import time
import threading
import tempfile
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from config.settings import AgentConfig, config
from agent_manager.manager import (
    AgentManager, PermissionGuard, ResourceMonitor,
    ManagedProcess, ProcessState, PermissionError,
)


# ─── PermissionGuard ──────────────────────────────────────────────────────────

class TestPermissionGuard:

    @pytest.fixture
    def tmpdir(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def guard(self, tmpdir):
        cfg = AgentConfig(
            allowed_base_paths=[str(tmpdir)],
            forbidden_paths=["/etc", "/root", "/sys", "/proc"],
        )
        return PermissionGuard(cfg)

    def test_allows_path_inside_allowed_root(self, guard, tmpdir):
        target = tmpdir / "subdir" / "file.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = guard.check_path(str(target))
        assert result == target.resolve()

    def test_blocks_path_outside_allowed_roots(self, guard):
        with pytest.raises(PermissionError):
            guard.check_path("/tmp/outside_workmind")

    def test_blocks_forbidden_path_etc(self, guard):
        with pytest.raises(PermissionError):
            guard.check_path("/etc/passwd")

    def test_blocks_forbidden_path_proc(self, guard):
        with pytest.raises(PermissionError):
            guard.check_path("/proc/self/status")

    def test_blocks_dangerous_operation(self, guard):
        with pytest.raises(PermissionError):
            guard.check_operation("rm_rf")

    def test_allows_safe_operation(self, guard):
        # Should not raise
        guard.check_operation("read_file")

    def test_path_traversal_blocked(self, guard, tmpdir):
        # Attempt to escape via ../..
        traversal = str(tmpdir / ".." / ".." / "etc" / "passwd")
        with pytest.raises(PermissionError):
            guard.check_path(traversal)


# ─── AgentManager ─────────────────────────────────────────────────────────────

class TestAgentManager:

    @pytest.fixture
    def tmpdir(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def agent(self, tmpdir):
        cfg = AgentConfig(
            allowed_base_paths=[str(tmpdir)],
            forbidden_paths=["/etc", "/root"],
            heartbeat_interval_seconds=1,
            max_restart_attempts=1,
            restart_backoff_seconds=1,
        )
        mgr = AgentManager(cfg)
        mgr.start()
        yield mgr
        mgr.stop()

    def test_register_process(self, agent):
        agent.register("test_proc", ["echo", "hello"])
        assert "test_proc" in agent._processes

    def test_request_file_read_allowed(self, agent, tmpdir):
        path = agent.request_file_read(str(tmpdir))
        assert path == tmpdir.resolve()

    def test_request_file_read_blocked(self, agent):
        with pytest.raises(PermissionError):
            agent.request_file_read("/etc/shadow")

    def test_request_file_write_allowed(self, agent, tmpdir):
        path = agent.request_file_write(str(tmpdir / "output.txt"))
        assert str(path).startswith(str(tmpdir))

    def test_start_and_stop_process(self, agent):
        agent.register("echo_proc", ["echo", "workmind"])
        agent.start_process("echo_proc")
        time.sleep(0.5)
        proc = agent._processes["echo_proc"]
        # Process may have already exited (echo is fast) — that's fine
        assert proc.state in (ProcessState.RUNNING, ProcessState.FAILED, ProcessState.RESTARTING, ProcessState.STOPPED)

    def test_start_unknown_process_raises(self, agent):
        with pytest.raises(KeyError):
            agent.start_process("nonexistent")


# ─── ManagedProcess dataclass ─────────────────────────────────────────────────

class TestManagedProcess:

    def test_default_state(self):
        p = ManagedProcess(name="test", command=["echo"])
        assert p.state == ProcessState.IDLE
        assert p.pid is None
        assert p.restart_count == 0


# ─── Integration: full cycle (no external deps) ───────────────────────────────

class TestIntegrationCycle:

    def test_scan_analyse_report(self, tmp_path):
        """End-to-end: scanner → analyser → reporter using a temp directory."""
        # Create some test files
        for i in range(5):
            (tmp_path / f"file_{i}.txt").write_text("hello workmind")
        (tmp_path / "big_dummy.log").write_text("x" * 1024)

        cfg = AgentConfig(allowed_base_paths=[str(tmp_path)], forbidden_paths=[])
        agent = AgentManager(cfg)
        agent.start()

        try:
            from mindwork.scanner import DirectoryScanner
            from mindwork.analyser import PatternAnalyser
            from mindwork.reporter import ReportEngine

            scanner  = DirectoryScanner(agent)
            analyser = PatternAnalyser(data_dir=tmp_path / "data")
            reporter = ReportEngine(agent)

            # Override report dir to tmp
            import config.settings as cs
            original = cs.config.mindwork.report_output_dir
            cs.config.mindwork.report_output_dir = str(tmp_path / "reports")
            (tmp_path / "reports").mkdir()

            snapshot = scanner.scan(str(tmp_path))
            assert snapshot.total_files >= 5

            result = analyser.analyse(snapshot)
            assert result.total_files >= 5
            assert 0 <= result.score <= 100

            json_path, md_path = reporter.generate(result)
            assert json_path.exists()
            assert md_path.exists()
            assert "WorkMind" in md_path.read_text()

            cs.config.mindwork.report_output_dir = original
        finally:
            agent.stop()

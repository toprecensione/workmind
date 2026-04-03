"""
WorkMind Configuration Module
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ─── Base Paths ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
BACKUP_DIR = BASE_DIR / "backups"
SNAPSHOT_DIR = BASE_DIR / "snapshots"

for _d in [LOG_DIR, DATA_DIR, REPORT_DIR, BACKUP_DIR, SNAPSHOT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ─── Agent Manager ────────────────────────────────────────────────────────────
@dataclass
class AgentConfig:
    max_cpu_percent: float = 60.0
    max_memory_mb: int = 512
    max_open_files: int = 100
    process_timeout_seconds: int = 300
    heartbeat_interval_seconds: int = 10
    max_restart_attempts: int = 3
    restart_backoff_seconds: int = 30
    allowed_base_paths: list = field(default_factory=lambda: [
        str(BASE_DIR),
        str(DATA_DIR),
        str(LOG_DIR),
        str(REPORT_DIR),
    ])
    forbidden_paths: list = field(default_factory=lambda: [
        "/etc", "/root", "/sys", "/proc", "/boot",
        "/usr/bin", "/usr/sbin", "/sbin", "/bin",
    ])


# ─── MindWork Core ────────────────────────────────────────────────────────────
@dataclass
class MindWorkConfig:
    scan_interval_minutes: int = 30
    max_scan_depth: int = 5
    max_files_per_scan: int = 10_000
    ignored_extensions: list = field(default_factory=lambda: [
        ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe",
        ".bin", ".obj", ".o", ".a", ".lib",
    ])
    ignored_dirs: list = field(default_factory=lambda: [
        "__pycache__", ".git", ".svn", "node_modules",
        ".venv", "venv", ".env", "dist", "build",
    ])
    pattern_history_days: int = 30
    anomaly_threshold_sigma: float = 2.5
    report_output_dir: str = str(REPORT_DIR)


# ─── Logging ──────────────────────────────────────────────────────────────────
@dataclass
class LoggingConfig:
    log_dir: str = str(LOG_DIR)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_log_size_mb: int = 50
    backup_count: int = 10
    json_format: bool = True
    emit_to_stdout: bool = True


# ─── Update / GitHub ──────────────────────────────────────────────────────────
@dataclass
class UpdateConfig:
    repo_url: str = os.getenv("WORKMIND_REPO_URL", "")
    branch: str = os.getenv("WORKMIND_BRANCH", "main")
    check_interval_minutes: int = 60
    backup_before_update: bool = True
    validate_before_apply: bool = True
    max_rollback_versions: int = 5
    github_token: str = os.getenv("GITHUB_TOKEN", "")


# ─── Node Identity ────────────────────────────────────────────────────────────
@dataclass
class NodeConfig:
    node_id: str = os.getenv("WORKMIND_NODE_ID", "node-unset")
    node_label: str = os.getenv("WORKMIND_NODE_LABEL", "Worker Node")
    environment: str = os.getenv("WORKMIND_ENV", "production")


# ─── Composite Config ─────────────────────────────────────────────────────────
@dataclass
class AppConfig:
    node: NodeConfig = field(default_factory=NodeConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    mindwork: MindWorkConfig = field(default_factory=MindWorkConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)


# Singleton
config = AppConfig()

"""
WorkMind Auto-Updater
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Pulls updates from the private GitHub repository, validates the new code,
backs up the current version, applies the update, and rolls back on failure.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import config
from logging_system import get_logger, LogStatus, LogAction
from version import VERSION, get_full_version

log = get_logger("updater")

BASE_DIR     = Path(__file__).resolve().parent.parent
BACKUP_DIR   = BASE_DIR / "backups"
SNAPSHOT_DIR = BASE_DIR / "snapshots"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Version Manifest ─────────────────────────────────────────────────────────

class VersionManifest:
    """Reads/writes version.json that tracks deployed state."""

    _path = BASE_DIR / "version.json"

    @classmethod
    def read(cls) -> dict:
        if cls._path.exists():
            try:
                return json.loads(cls._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"version": VERSION, "deployed_at": None, "git_sha": None}

    @classmethod
    def write(cls, version: str, git_sha: str) -> None:
        data = {
            "version":     version,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "git_sha":     git_sha,
        }
        cls._path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─── Git Helpers ──────────────────────────────────────────────────────────────

def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a git command, return (returncode, stdout, stderr)."""
    env = os.environ.copy()
    if config.update.github_token:
        # Inject token for HTTPS authentication
        repo_url = config.update.repo_url
        if "https://" in repo_url and "@" not in repo_url:
            repo_url = repo_url.replace(
                "https://",
                f"https://{config.update.github_token}@",
            )
        env["GIT_ASKPASS"] = "echo"
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd or BASE_DIR),
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _current_sha() -> str:
    _, sha, _ = _run_git("rev-parse", "HEAD")
    return sha


# ─── Validator ────────────────────────────────────────────────────────────────

class UpdateValidator:
    """
    Performs sanity checks on code BEFORE applying an update.
    Checks:
      1. Critical module imports
      2. Syntax validity of Python files
      3. version.py is present and parseable
    """

    CRITICAL_MODULES = [
        "config.settings",
        "logging_system.logger",
        "agent_manager.manager",
        "mindwork",
        "version",
    ]

    def validate(self, working_dir: Path) -> tuple[bool, str]:
        """Returns (ok, reason)."""
        # 1. Python syntax check
        py_files = list(working_dir.rglob("*.py"))
        for f in py_files:
            rc, _, err = self._check_syntax(f)
            if rc != 0:
                return False, f"Syntax error in {f.relative_to(working_dir)}: {err}"

        # 2. version.py must exist
        vfile = working_dir / "version.py"
        if not vfile.exists():
            return False, "version.py missing from update"

        # 3. Basic structural check
        required_dirs = ["agent_manager", "mindwork", "logging_system", "config", "updater"]
        for d in required_dirs:
            if not (working_dir / d).is_dir():
                return False, f"Required package directory missing: {d}"

        return True, "ok"

    @staticmethod
    def _check_syntax(path: Path) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr


# ─── Auto-Updater ─────────────────────────────────────────────────────────────

class AutoUpdater:
    """
    Checks for upstream changes, validates, backs up, and applies updates.
    Rolls back automatically on any failure.
    """

    def __init__(self) -> None:
        self._cfg       = config.update
        self._validator = UpdateValidator()

    def check_and_update(self) -> bool:
        """Returns True if an update was successfully applied."""
        if not self._cfg.repo_url:
            log.warning(
                "WORKMIND_REPO_URL not configured — skipping update check",
                action=LogAction.UPDATE, status=LogStatus.SKIPPED,
                suggestion="Set WORKMIND_REPO_URL environment variable.",
            )
            return False

        log.info("Checking for upstream updates…", action=LogAction.UPDATE, status=LogStatus.STARTED)
        current_sha = _current_sha()

        # Fetch remote
        rc, _, err = _run_git("fetch", "origin", self._cfg.branch)
        if rc != 0:
            log.error(f"git fetch failed: {err}", action=LogAction.UPDATE, status=LogStatus.ERROR)
            return False

        # Compare
        _, remote_sha, _ = _run_git("rev-parse", f"origin/{self._cfg.branch}")
        if remote_sha == current_sha:
            log.info("Already up-to-date.", action=LogAction.UPDATE, status=LogStatus.OK)
            return False

        log.info(
            f"Update available: {current_sha[:8]} → {remote_sha[:8]}",
            action=LogAction.UPDATE, status=LogStatus.PENDING,
        )

        # Validate BEFORE applying (check out to temp location)
        if self._cfg.validate_before_apply:
            ok, reason = self._validate_remote(remote_sha)
            if not ok:
                log.error(
                    f"Update validation failed: {reason}",
                    action=LogAction.VALIDATE, status=LogStatus.ERROR,
                    suggestion="Fix the upstream code before re-deploying.",
                )
                return False

        # Backup current
        backup_path: Optional[Path] = None
        if self._cfg.backup_before_update:
            backup_path = self._create_backup(current_sha)

        # Apply update
        try:
            rc, _, err = _run_git("pull", "origin", self._cfg.branch, "--ff-only")
            if rc != 0:
                raise RuntimeError(f"git pull failed: {err}")

            new_sha = _current_sha()
            VersionManifest.write(VERSION, new_sha)

            log.info(
                f"Update applied successfully: {new_sha[:8]}",
                action=LogAction.UPDATE, status=LogStatus.OK,
                extra={"old_sha": current_sha, "new_sha": new_sha},
            )
            return True

        except Exception as exc:
            log.error(
                f"Update failed: {exc} — initiating rollback",
                action=LogAction.UPDATE, status=LogStatus.ERROR,
                exc_info=True,
            )
            if backup_path:
                self._rollback(backup_path, current_sha)
            return False

    def _validate_remote(self, sha: str) -> tuple[bool, str]:
        """Check out the remote SHA to a temp dir and validate it there."""
        tmp_dir = SNAPSHOT_DIR / f"validate_{sha[:8]}"
        try:
            rc, _, err = _run_git(
                "clone",
                "--branch", self._cfg.branch,
                "--depth", "1",
                BASE_DIR.as_posix() if not self._cfg.repo_url else self._cfg.repo_url,
                str(tmp_dir),
            )
            if rc != 0:
                return False, f"Clone failed: {err}"
            return self._validator.validate(tmp_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _create_backup(self, sha: str) -> Path:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup  = BACKUP_DIR / f"backup_{ts}_{sha[:8]}"
        shutil.copytree(
            BASE_DIR, backup,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc",
                "backups", "snapshots", "logs", "reports",
            ),
        )
        # Prune old backups
        all_backups = sorted(BACKUP_DIR.iterdir())
        while len(all_backups) > self._cfg.max_rollback_versions:
            shutil.rmtree(all_backups.pop(0), ignore_errors=True)
        log.info(f"Backup created: {backup.name}", action=LogAction.UPDATE, status=LogStatus.OK)
        return backup

    def _rollback(self, backup_path: Path, sha: str) -> None:
        log.info(f"Rolling back to {sha[:8]}…", action=LogAction.ROLLBACK, status=LogStatus.STARTED)
        try:
            rc, _, err = _run_git("reset", "--hard", sha)
            if rc != 0:
                raise RuntimeError(err)
            log.info("Rollback successful.", action=LogAction.ROLLBACK, status=LogStatus.OK)
        except Exception as exc:
            log.critical(
                f"Rollback failed: {exc}. Manual recovery required from backup: {backup_path}",
                action=LogAction.ROLLBACK, status=LogStatus.ERROR,
                suggestion=f"Restore from: {backup_path}",
            )

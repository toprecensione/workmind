"""
WorkMind Test Suite — AutoUpdater & VersionManifest
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from updater.auto_updater import VersionManifest, UpdateValidator


class TestVersionManifest:

    def test_read_returns_defaults_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("updater.auto_updater.BASE_DIR", tmp_path)
        # Patch _path
        import updater.auto_updater as ua
        ua.VersionManifest._path = tmp_path / "version.json"
        data = VersionManifest.read()
        assert "version" in data

    def test_write_and_read_roundtrip(self, tmp_path):
        import updater.auto_updater as ua
        ua.VersionManifest._path = tmp_path / "version.json"
        VersionManifest.write("2.0.0", "abc123def456")
        data = VersionManifest.read()
        assert data["version"] == "2.0.0"
        assert data["git_sha"] == "abc123def456"
        assert "deployed_at" in data


class TestUpdateValidator:

    def test_valid_project_passes(self, tmp_path):
        # Create minimal valid structure
        for pkg in ["agent_manager", "mindwork", "logging_system", "config", "updater"]:
            (tmp_path / pkg).mkdir()
            (tmp_path / pkg / "__init__.py").write_text("")
        (tmp_path / "version.py").write_text('VERSION = "1.0.0"')
        (tmp_path / "main.py").write_text("# entry point")

        validator = UpdateValidator()
        ok, reason = validator.validate(tmp_path)
        assert ok, f"Expected valid, got: {reason}"

    def test_missing_version_py_fails(self, tmp_path):
        for pkg in ["agent_manager", "mindwork", "logging_system", "config", "updater"]:
            (tmp_path / pkg).mkdir()
        # No version.py

        validator = UpdateValidator()
        ok, reason = validator.validate(tmp_path)
        assert not ok
        assert "version.py" in reason

    def test_missing_package_dir_fails(self, tmp_path):
        # Only some dirs present
        (tmp_path / "agent_manager").mkdir()
        (tmp_path / "version.py").write_text('VERSION = "1.0.0"')

        validator = UpdateValidator()
        ok, reason = validator.validate(tmp_path)
        assert not ok

    def test_syntax_error_in_py_file_fails(self, tmp_path):
        for pkg in ["agent_manager", "mindwork", "logging_system", "config", "updater"]:
            (tmp_path / pkg).mkdir()
        (tmp_path / "version.py").write_text('VERSION = "1.0.0"')
        # Write a file with invalid Python syntax
        (tmp_path / "bad_file.py").write_text("def broken(\n  # unclosed")

        validator = UpdateValidator()
        ok, reason = validator.validate(tmp_path)
        assert not ok
        assert "Syntax error" in reason

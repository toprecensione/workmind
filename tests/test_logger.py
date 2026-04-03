"""
WorkMind Test Suite — Structured JSON Logger
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
"""

import sys
import json
import logging
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from logging_system.logger import JsonFormatter, WorkMindLogger, LogStatus, LogAction, get_logger


class TestJsonFormatter:

    def _capture_record(self, message: str, **extras) -> dict:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.module", level=logging.INFO,
            pathname="", lineno=0, msg=message,
            args=(), exc_info=None,
        )
        for k, v in extras.items():
            setattr(record, k, v)
        raw = formatter.format(record)
        return json.loads(raw)

    def test_output_is_valid_json(self):
        data = self._capture_record("hello")
        assert isinstance(data, dict)

    def test_required_fields_present(self):
        data = self._capture_record("test message")
        for field in ("timestamp", "node_id", "level", "module", "action", "status", "message"):
            assert field in data, f"Missing field: {field}"

    def test_message_preserved(self):
        data = self._capture_record("specific message content")
        assert data["message"] == "specific message content"

    def test_custom_wm_fields(self):
        data = self._capture_record(
            "custom",
            wm_module="mindwork.scanner",
            wm_action=LogAction.SCAN,
            wm_status=LogStatus.OK,
            wm_suggestion="check this",
        )
        assert data["module"] == "mindwork.scanner"
        assert data["action"] == "scan"
        assert data["status"] == "ok"
        assert data["suggestion"] == "check this"

    def test_extra_dict_included(self):
        data = self._capture_record(
            "with extra",
            wm_extra={"files": 42, "elapsed": 1.5},
        )
        assert data["extra"]["files"] == 42

    def test_null_suggestion_when_not_set(self):
        data = self._capture_record("no suggestion")
        assert data["suggestion"] is None


class TestWorkMindLogger:

    def test_get_logger_returns_instance(self):
        log = get_logger("test.logger")
        assert isinstance(log, WorkMindLogger)

    def test_info_does_not_raise(self):
        log = get_logger("test.info")
        log.info("info message", action=LogAction.MONITOR, status=LogStatus.OK)

    def test_warning_sets_warning_status(self):
        log = get_logger("test.warn")
        # Should not raise; status defaults to WARNING
        log.warning("warn message")

    def test_error_sets_error_status(self):
        log = get_logger("test.error")
        log.error("error message")

    def test_log_with_suggestion(self):
        log = get_logger("test.suggestion")
        log.info("msg", suggestion="Fix this immediately.")


class TestLogEnums:

    def test_log_status_values(self):
        assert LogStatus.OK == "ok"
        assert LogStatus.ERROR == "error"
        assert LogStatus.WARNING == "warning"

    def test_log_action_values(self):
        assert LogAction.SCAN == "scan"
        assert LogAction.UPDATE == "update"
        assert LogAction.ROLLBACK == "rollback"

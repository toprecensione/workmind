"""
MindWork — Pattern Analyser & Anomaly Detector
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import config
from logging_system import get_logger, LogStatus, LogAction
from mindwork.scanner import DirectorySnapshot

log = get_logger("mindwork.analyser")


# ─── Anomaly ──────────────────────────────────────────────────────────────────

@dataclass
class Anomaly:
    anomaly_type: str
    severity: str          # "low" | "medium" | "high"
    description: str
    value: float
    threshold: float
    suggestion: str


# ─── Analysis Result ──────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    snapshot_root: str
    analysis_ts: float
    total_files: int
    total_size_gb: float
    top_extensions_by_count: Dict[str, int]
    top_extensions_by_size: Dict[str, int]
    avg_file_size_bytes: float
    file_size_stddev: float
    anomalies: List[Anomaly]
    suggestions: List[str]
    score: float   # 0–100 health score

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ─── Pattern History ──────────────────────────────────────────────────────────

@dataclass
class HistoryRecord:
    ts: float
    root: str
    total_files: int
    total_size_bytes: int
    extension_counts: Dict[str, int]


class PatternHistory:
    """Persists scan summaries to disk for trend analysis."""

    def __init__(self, history_path: Path) -> None:
        self._path = history_path
        self._records: List[HistoryRecord] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._records = [HistoryRecord(**r) for r in raw]
            except Exception as exc:
                log.warning(f"Could not load pattern history: {exc}", action=LogAction.ANALYSE)
                self._records = []

    def save(self) -> None:
        self._path.write_text(
            json.dumps([asdict(r) for r in self._records], indent=2),
            encoding="utf-8",
        )

    def add(self, record: HistoryRecord) -> None:
        self._records.append(record)
        # Keep only last N days
        cutoff = time.time() - config.mindwork.pattern_history_days * 86400
        self._records = [r for r in self._records if r.ts >= cutoff]
        self.save()

    def file_count_series(self, root: str) -> List[int]:
        return [r.total_files for r in self._records if r.root == root]

    def size_series(self, root: str) -> List[int]:
        return [r.total_size_bytes for r in self._records if r.root == root]


# ─── Analyser ─────────────────────────────────────────────────────────────────

class PatternAnalyser:
    """
    Analyses a DirectorySnapshot against historical patterns,
    detects anomalies, and produces actionable suggestions.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        data_dir    = data_dir or Path(config.mindwork.report_output_dir).parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        history_file = data_dir / "pattern_history.json"
        self._history = PatternHistory(history_file)
        self._sigma   = config.mindwork.anomaly_threshold_sigma

    def analyse(self, snapshot: DirectorySnapshot) -> AnalysisResult:
        log.info(
            f"Analysing snapshot: {snapshot.root}",
            action=LogAction.ANALYSE, status=LogStatus.STARTED,
        )

        sizes = [f.size_bytes for f in snapshot.files]
        avg_size = statistics.mean(sizes) if sizes else 0.0
        std_size = statistics.stdev(sizes) if len(sizes) > 1 else 0.0

        anomalies: List[Anomaly] = []
        suggestions: List[str]  = []

        # ── Historical trend anomalies ─────────────────────────────────────
        count_series = self._history.file_count_series(snapshot.root)
        if len(count_series) >= 3:
            mean_c = statistics.mean(count_series)
            std_c  = statistics.stdev(count_series) if len(count_series) > 1 else 1
            z = (snapshot.total_files - mean_c) / (std_c or 1)
            if abs(z) > self._sigma:
                severity = "high" if abs(z) > self._sigma * 1.5 else "medium"
                anomalies.append(Anomaly(
                    anomaly_type = "file_count_spike",
                    severity     = severity,
                    description  = f"File count ({snapshot.total_files}) deviates {z:+.1f}σ from historical mean ({mean_c:.0f})",
                    value        = snapshot.total_files,
                    threshold    = mean_c + self._sigma * std_c,
                    suggestion   = "Investigate recent bulk file creation or deletion events.",
                ))

        size_series = self._history.size_series(snapshot.root)
        if len(size_series) >= 3:
            mean_s = statistics.mean(size_series)
            std_s  = statistics.stdev(size_series) if len(size_series) > 1 else 1
            z = (snapshot.total_size_bytes - mean_s) / (std_s or 1)
            if abs(z) > self._sigma:
                severity = "high" if abs(z) > self._sigma * 1.5 else "medium"
                anomalies.append(Anomaly(
                    anomaly_type = "size_spike",
                    severity     = severity,
                    description  = f"Total size ({snapshot.total_size_bytes/1e9:.2f} GB) deviates {z:+.1f}σ from historical mean",
                    value        = snapshot.total_size_bytes,
                    threshold    = mean_s + self._sigma * std_s,
                    suggestion   = "Check for large temporary files or unexpected data ingestion.",
                ))

        # ── Large individual files ─────────────────────────────────────────
        large_threshold = 500 * 1024 * 1024  # 500 MB
        large_files = [f for f in snapshot.files if f.size_bytes > large_threshold]
        if large_files:
            anomalies.append(Anomaly(
                anomaly_type = "large_files",
                severity     = "medium",
                description  = f"{len(large_files)} file(s) exceed 500 MB",
                value        = len(large_files),
                threshold    = 0,
                suggestion   = f"Review: {', '.join(f.name for f in large_files[:3])}…",
            ))
            suggestions.append(f"Consider archiving or compressing {len(large_files)} large file(s).")

        # ── Permission anomalies ───────────────────────────────────────────
        world_writable = [f for f in snapshot.files if "w" in f.permissions[7:]]
        if world_writable:
            anomalies.append(Anomaly(
                anomaly_type = "world_writable_files",
                severity     = "high",
                description  = f"{len(world_writable)} world-writable file(s) detected",
                value        = len(world_writable),
                threshold    = 0,
                suggestion   = "Remove world-write permissions to reduce security exposure.",
            ))
            suggestions.append("Audit world-writable file permissions immediately.")

        # ── General suggestions ────────────────────────────────────────────
        if snapshot.total_size_bytes > 10 * 1024 ** 3:
            suggestions.append("Total directory size exceeds 10 GB — consider cleanup or archiving.")
        if ".log" in snapshot.extension_counts and snapshot.extension_counts[".log"] > 100:
            suggestions.append("High number of .log files detected — consider log rotation.")
        if ".tmp" in snapshot.extension_counts:
            suggestions.append(f"Found {snapshot.extension_counts['.tmp']} .tmp files — safe to delete.")

        # ── Health score ──────────────────────────────────────────────────
        score = 100.0
        for a in anomalies:
            if a.severity == "high":   score -= 20
            elif a.severity == "medium": score -= 8
            else:                        score -= 3
        score = max(0.0, score)

        result = AnalysisResult(
            snapshot_root            = snapshot.root,
            analysis_ts              = time.time(),
            total_files              = snapshot.total_files,
            total_size_gb            = snapshot.total_size_bytes / 1024**3,
            top_extensions_by_count  = snapshot.extension_counts,
            top_extensions_by_size   = snapshot.extension_sizes,
            avg_file_size_bytes      = avg_size,
            file_size_stddev         = std_size,
            anomalies                = anomalies,
            suggestions              = suggestions,
            score                    = score,
        )

        # Persist to history
        self._history.add(HistoryRecord(
            ts                = snapshot.scan_ts,
            root              = snapshot.root,
            total_files       = snapshot.total_files,
            total_size_bytes  = snapshot.total_size_bytes,
            extension_counts  = snapshot.extension_counts,
        ))

        log.info(
            f"Analysis complete — score={score:.1f}, anomalies={len(anomalies)}",
            action=LogAction.ANALYSE, status=LogStatus.OK,
            extra={"score": score, "anomaly_count": len(anomalies)},
            suggestion=suggestions[0] if suggestions else None,
        )
        return result

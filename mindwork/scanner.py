"""
MindWork — Directory & File Intelligence Scanner
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

MindWork does NOT interact with the OS directly.
All filesystem paths must be validated via AgentManager.request_file_read().
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from config.settings import config, MindWorkConfig
from logging_system import get_logger, LogStatus, LogAction

if TYPE_CHECKING:
    from agent_manager.manager import AgentManager

log = get_logger("mindwork.scanner")


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class FileEntry:
    path: str
    name: str
    extension: str
    size_bytes: int
    modified_ts: float
    created_ts: float
    permissions: str
    checksum_md5: Optional[str] = None


@dataclass
class DirectorySnapshot:
    root: str
    scan_ts: float
    total_files: int
    total_dirs: int
    total_size_bytes: int
    extension_counts: Dict[str, int]
    extension_sizes: Dict[str, int]
    largest_files: List[dict]
    oldest_files: List[dict]
    newest_files: List[dict]
    files: List[FileEntry] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["files"] = [asdict(f) for f in self.files]
        return d


@dataclass
class UsagePattern:
    date: str                          # YYYY-MM-DD
    extension_accesses: Dict[str, int]
    hourly_activity: Dict[int, int]    # hour → file-count
    largest_growth_extensions: List[str]


# ─── Scanner ──────────────────────────────────────────────────────────────────

class DirectoryScanner:
    """
    Walks a directory tree and collects structured metadata.
    All path access is routed through AgentManager for permission enforcement.
    """

    def __init__(self, agent: "AgentManager", cfg: MindWorkConfig | None = None) -> None:
        self._agent = agent
        self._cfg   = cfg or config.mindwork

    def scan(self, root: str) -> DirectorySnapshot:
        safe_root = self._agent.request_file_read(root)
        log.info(
            f"Starting directory scan: {safe_root}",
            action=LogAction.SCAN, status=LogStatus.STARTED,
        )
        start = time.time()

        files: List[FileEntry]    = []
        ext_counts: Counter       = Counter()
        ext_sizes: Counter        = Counter()
        dir_count                 = 0
        file_count                = 0

        for depth, (dirpath, dirnames, filenames) in enumerate(os.walk(safe_root)):
            # Depth limit
            rel = Path(dirpath).relative_to(safe_root)
            if len(rel.parts) >= self._cfg.max_scan_depth:
                dirnames.clear()
                continue

            # Ignore dirs
            dirnames[:] = [
                d for d in dirnames
                if d not in self._cfg.ignored_dirs and not d.startswith(".")
            ]
            dir_count += len(dirnames)

            for fname in filenames:
                if file_count >= self._cfg.max_files_per_scan:
                    break
                ext = Path(fname).suffix.lower()
                if ext in self._cfg.ignored_extensions:
                    continue

                fpath = Path(dirpath) / fname
                try:
                    st = fpath.stat()
                    perm = stat.filemode(st.st_mode)
                    entry = FileEntry(
                        path        = str(fpath),
                        name        = fname,
                        extension   = ext or "(none)",
                        size_bytes  = st.st_size,
                        modified_ts = st.st_mtime,
                        created_ts  = st.st_ctime,
                        permissions = perm,
                    )
                    files.append(entry)
                    ext_counts[entry.extension] += 1
                    ext_sizes[entry.extension]  += st.st_size
                    file_count += 1
                except (PermissionError, OSError):
                    pass

        total_size = sum(f.size_bytes for f in files)
        sorted_by_size    = sorted(files, key=lambda f: f.size_bytes, reverse=True)
        sorted_by_mtime   = sorted(files, key=lambda f: f.modified_ts, reverse=True)
        sorted_by_oldest  = sorted(files, key=lambda f: f.modified_ts)

        snapshot = DirectorySnapshot(
            root             = str(safe_root),
            scan_ts          = time.time(),
            total_files      = file_count,
            total_dirs       = dir_count,
            total_size_bytes = total_size,
            extension_counts = dict(ext_counts.most_common(20)),
            extension_sizes  = dict(ext_sizes.most_common(20)),
            largest_files    = [{"path": f.path, "size_bytes": f.size_bytes} for f in sorted_by_size[:10]],
            oldest_files     = [{"path": f.path, "modified": f.modified_ts} for f in sorted_by_oldest[:10]],
            newest_files     = [{"path": f.path, "modified": f.modified_ts} for f in sorted_by_mtime[:10]],
            files            = files,
        )

        elapsed = time.time() - start
        log.info(
            f"Scan complete: {file_count} files in {elapsed:.2f}s",
            action=LogAction.SCAN, status=LogStatus.OK,
            extra={"root": str(safe_root), "files": file_count, "dirs": dir_count, "elapsed_s": elapsed},
        )
        return snapshot

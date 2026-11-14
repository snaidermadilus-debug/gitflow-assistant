"""History: commit log helpers and the GitFlow operation journal."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from gitflow_assistant.core.git_engine import GitEngine, redact
from gitflow_assistant.utils.path_manager import data_dir, ensure_dir

PUBLISH_OPERATIONS = ("upload", "update", "push")


@dataclass
class OperationRecord:
    """One entry in the operation journal."""

    timestamp: float
    operation: str
    project: str
    success: bool
    detail: str

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))


class OperationHistory:
    """Append-only JSON-lines journal stored in the user data directory."""

    def __init__(self, store: Optional[Path] = None, max_entries: int = 1000) -> None:
        self.store = store or (data_dir() / "history.jsonl")
        self.max_entries = max_entries

    def record(self, operation: str, project: Path, success: bool, detail: str = "") -> OperationRecord:
        """Append an operation (details are redacted)."""
        entry = OperationRecord(time.time(), operation, str(project), success, redact(detail)[:500])
        ensure_dir(self.store.parent)
        with self.store.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        self._trim()
        return entry

    def _trim(self) -> None:
        lines = self.store.read_text(encoding="utf-8").splitlines()
        if len(lines) > self.max_entries:
            self.store.write_text("\n".join(lines[-self.max_entries:]) + "\n", encoding="utf-8")

    def list(self, limit: int = 50, operations: Optional[Tuple[str, ...]] = None,
             project: Optional[Path] = None) -> List[OperationRecord]:
        """Most recent first, optionally filtered."""
        if not self.store.exists():
            return []
        records: List[OperationRecord] = []
        for line in self.store.read_text(encoding="utf-8").splitlines():
            try:
                records.append(OperationRecord(**json.loads(line)))
            except (ValueError, TypeError):
                continue
        if operations:
            records = [r for r in records if r.operation in operations]
        if project:
            records = [r for r in records if r.project == str(project)]
        return list(reversed(records))[:limit]

    def publications(self, limit: int = 50) -> List[OperationRecord]:
        """Upload/update/push operations."""
        return self.list(limit, PUBLISH_OPERATIONS)


def compare(engine: GitEngine, ref_a: str, ref_b: str, stat_only: bool = False) -> str:
    """Diff between two commits/branches."""
    return engine.diff(ref_a=ref_a, ref_b=ref_b, stat=stat_only)

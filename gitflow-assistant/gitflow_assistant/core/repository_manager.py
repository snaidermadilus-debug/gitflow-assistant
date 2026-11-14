"""Recent projects registry and current project selection."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from gitflow_assistant.utils.path_manager import data_dir, ensure_dir

MAX_RECENT = 30


@dataclass
class RecentProject:
    """A project known to GitFlow Assistant."""

    path: str
    name: str
    last_used: float


class RepositoryManager:
    """Persist the list of recent projects in the user data directory."""

    def __init__(self, store: Optional[Path] = None) -> None:
        self.store = store or (data_dir() / "projects.json")

    def _read(self) -> List[RecentProject]:
        if not self.store.exists():
            return []
        try:
            raw = json.loads(self.store.read_text(encoding="utf-8"))
            return [RecentProject(**item) for item in raw.get("projects", [])]
        except (OSError, ValueError, TypeError):
            return []

    def _write(self, projects: List[RecentProject]) -> None:
        ensure_dir(self.store.parent)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps({"projects": [asdict(p) for p in projects]}, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.store)

    def list(self) -> List[RecentProject]:
        """Recent projects, most recently used first."""
        return sorted(self._read(), key=lambda p: p.last_used, reverse=True)

    def add(self, path: Path) -> RecentProject:
        """Register (or refresh) a project and mark it as current."""
        resolved = str(Path(path).expanduser().resolve())
        projects = [p for p in self._read() if p.path != resolved]
        entry = RecentProject(path=resolved, name=Path(resolved).name or resolved, last_used=time.time())
        projects.insert(0, entry)
        projects = sorted(projects, key=lambda p: p.last_used, reverse=True)[:MAX_RECENT]
        self._write(projects)
        return entry

    def remove(self, path: Path) -> bool:
        """Forget a project (files are not touched)."""
        resolved = str(Path(path).expanduser().resolve())
        projects = self._read()
        remaining = [p for p in projects if p.path != resolved]
        if len(remaining) == len(projects):
            return False
        self._write(remaining)
        return True

    def current(self) -> Optional[Path]:
        """Most recently selected project that still exists."""
        for project in self.list():
            if Path(project.path).is_dir():
                return Path(project.path)
        return None

    def prune_missing(self) -> int:
        """Remove entries whose directory no longer exists."""
        projects = self._read()
        remaining = [p for p in projects if Path(p.path).is_dir()]
        if len(remaining) != len(projects):
            self._write(remaining)
        return len(projects) - len(remaining)

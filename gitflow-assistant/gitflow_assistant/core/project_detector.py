"""Detect Git projects and summarise their state.

Directory discovery is always bounded (user-chosen base directories, maximum
depth and maximum number of visited directories) – the tool never walks the
whole storage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from gitflow_assistant.core.git_engine import GitEngine, GitError, redact

SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".cache", ".gradle", "build", "dist", "target",
             ".tox", ".mypy_cache", ".pytest_cache", "Android", "proc", "sys"}


@dataclass
class ProjectInfo:
    """Summary of a local project."""

    path: Path
    name: str
    exists: bool
    is_git: bool = False
    root: Optional[Path] = None
    branch: Optional[str] = None
    has_commits: bool = False
    remote_name: Optional[str] = None
    remote_url: Optional[str] = None
    upstream: Optional[str] = None
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicts: List[str] = field(default_factory=list)
    operation: Optional[str] = None
    error: Optional[str] = None

    @property
    def pending(self) -> int:
        return self.staged + self.unstaged + self.untracked

    @property
    def state(self) -> str:
        """Short machine state: missing, not-git, error, conflict, dirty, ahead, behind, diverged, clean."""
        if not self.exists:
            return "missing"
        if not self.is_git:
            return "not-git"
        if self.error:
            return "error"
        if self.conflicts or self.operation:
            return "conflict"
        if self.pending:
            return "dirty"
        if self.ahead and self.behind:
            return "diverged"
        if self.ahead:
            return "ahead"
        if self.behind:
            return "behind"
        return "clean"


def detect_project(path: Path, git: Optional[GitEngine] = None) -> ProjectInfo:
    """Inspect ``path`` and return a :class:`ProjectInfo` (no network access)."""
    path = Path(path).expanduser().resolve()
    info = ProjectInfo(path=path, name=path.name or str(path), exists=path.is_dir())
    if not info.exists:
        return info
    engine = git or GitEngine(path)
    engine.cwd = path
    try:
        if not engine.is_repository():
            return info
        info.is_git = True
        info.root = engine.root()
        if info.root:
            engine.cwd = info.root
            info.name = info.root.name
        status = engine.status()
        info.branch = status.branch
        info.has_commits = status.has_commits
        info.upstream = status.upstream
        info.ahead, info.behind = status.ahead, status.behind
        info.staged = len(status.staged)
        info.unstaged = len(status.unstaged)
        info.untracked = len(status.untracked)
        info.conflicts = [f.path for f in status.conflicted]
        info.operation = engine.operation_in_progress()
        remotes = engine.remotes()
        if remotes:
            name = "origin" if "origin" in remotes else sorted(remotes)[0]
            info.remote_name = name
            info.remote_url = remotes[name].get("push") or remotes[name].get("fetch")
    except GitError as exc:
        info.error = redact(str(exc))
    return info


def find_repositories(bases: Iterable[Path], max_depth: int = 3, max_directories: int = 5000) -> List[Path]:
    """Find git working trees below ``bases`` with bounded depth and breadth.

    A directory containing ``.git`` (directory or file, for worktrees/submodules)
    is a repository; its subdirectories are not explored further.
    """
    found: List[Path] = []
    visited = 0
    for base in bases:
        base = Path(base).expanduser()
        if not base.is_dir():
            continue
        queue = [(base.resolve(), 0)]
        while queue and visited < max_directories:
            current, depth = queue.pop(0)
            visited += 1
            if (current / ".git").exists():
                found.append(current)
                continue
            if depth >= max_depth:
                continue
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False) and entry.name not in SKIP_DIRS \
                                    and not entry.name.startswith("."):
                                queue.append((Path(entry.path), depth + 1))
                        except OSError:
                            continue
            except OSError:
                continue
    return sorted(set(found))

"""Non-destructive safety backups.

A backup contains:

* ``repository.bundle`` – full history of all refs (``git bundle create --all``);
  restore with ``git clone repository.bundle <dir>``;
* ``worktree-changes.zip`` – copies of modified/untracked (non-ignored) files;
* ``manifest.json`` – metadata (branch, HEAD, file list).
"""

from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.utils.path_manager import data_dir, ensure_dir


@dataclass
class BackupInfo:
    """A backup directory."""

    path: Path
    project: str
    created: str
    head: str
    files: int


def backups_root() -> Path:
    """Directory holding backups."""
    return data_dir() / "backups"


def create_backup(engine: GitEngine, destination_root: Optional[Path] = None) -> BackupInfo:
    """Create a backup of history and uncommitted work. Nothing in the project is modified."""
    root = engine.root() or engine.cwd
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
    base = ensure_dir(destination_root or backups_root())
    target = base / f"{root.name}-{stamp}"
    suffix = 1
    while True:
        try:
            target.mkdir()
            break
        except FileExistsError:
            target = base / f"{root.name}-{stamp}-{suffix}"
            suffix += 1
    head = engine.head_sha() or ""
    if engine.has_commits():
        engine.bundle(target / "repository.bundle")
    status = engine.status()
    changed = [f.path for f in status.files if not f.is_ignored and (root / f.path).is_file()]
    if changed:
        with zipfile.ZipFile(target / "worktree-changes.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for rel in changed:
                archive.write(root / rel, arcname=rel)
    manifest = {"project": str(root), "created": stamp, "branch": status.branch, "head": head,
                "changed_files": changed, "restore": "git clone repository.bundle <dir>; unzip worktree-changes.zip"}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return BackupInfo(target, str(root), stamp, head[:7], len(changed))


def list_backups(destination_root: Optional[Path] = None) -> List[BackupInfo]:
    """Existing backups, newest first."""
    base = destination_root or backups_root()
    if not base.is_dir():
        return []
    items: List[BackupInfo] = []
    for folder in sorted(base.iterdir(), reverse=True):
        manifest = folder / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append(BackupInfo(folder, data.get("project", ""), data.get("created", ""),
                                str(data.get("head", ""))[:7], len(data.get("changed_files", []))))
    return items

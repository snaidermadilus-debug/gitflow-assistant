"""Per-platform locations for configuration, data and logs.

* Linux / Termux: XDG base directories (``~/.config``, ``~/.local/share``).
* Windows: ``%APPDATA%`` / ``%LOCALAPPDATA%``.
* macOS: ``~/Library/Application Support``.

``GITFLOW_HOME`` overrides everything (useful for tests and portable installs).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Mapping, Optional

APP_DIR_NAME = "gitflow-assistant"


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if env is None else env


def config_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Directory holding public configuration (never secrets)."""
    e = _env(env)
    if e.get("GITFLOW_HOME"):
        return Path(e["GITFLOW_HOME"]) / "config"
    if sys.platform.startswith("win"):
        base = e.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = e.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def data_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Directory for history, recent projects, backups and logs."""
    e = _env(env)
    if e.get("GITFLOW_HOME"):
        return Path(e["GITFLOW_HOME"]) / "data"
    if sys.platform.startswith("win"):
        base = e.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME / "data"
    base = e.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize(path: str) -> Path:
    """Expand ``~`` and environment variables and resolve to an absolute path."""
    expanded = os.path.expandvars(os.path.expanduser(path.strip().strip('"').strip("'")))
    return Path(expanded).resolve()


def termux_storage_candidates() -> List[Path]:
    """Common Termux locations that may contain projects.

    ``~/storage`` only exists after the user ran ``termux-setup-storage``.
    """
    home = Path.home()
    candidates = [home, home / "storage" / "shared", home / "storage" / "downloads"]
    return [p for p in candidates if p.exists()]


def is_within(child: Path, parent: Path) -> bool:
    """Return True if ``child`` is ``parent`` or located inside it."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def display_path(path: Path) -> str:
    """Shorten a path with ``~`` for display."""
    try:
        return "~" + os.sep + str(path.relative_to(Path.home())) if path != Path.home() else "~"
    except ValueError:
        return str(path)

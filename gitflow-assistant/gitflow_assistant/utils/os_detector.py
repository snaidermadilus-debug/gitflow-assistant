"""Operating-system and runtime environment detection.

Termux is treated as a first-class platform: it is detected through the
``TERMUX_VERSION`` variable or the ``com.termux`` prefix path.
"""

from __future__ import annotations

import ntpath
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

TERMUX_PREFIX_MARKER = "com.termux"


@dataclass(frozen=True)
class PlatformInfo:
    """Immutable description of the runtime environment."""

    system: str  # "linux", "windows", "darwin", "android"
    is_termux: bool
    is_windows: bool
    machine: str
    python_version: str
    shell: str
    interactive: bool

    @property
    def label(self) -> str:
        """Human readable platform label."""
        if self.is_termux:
            return f"Android/Termux ({self.machine})"
        names = {"linux": "Linux", "windows": "Windows", "darwin": "macOS"}
        return f"{names.get(self.system, self.system)} ({self.machine})"


def is_termux(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when running inside Termux on Android."""
    env = os.environ if env is None else env
    if env.get("TERMUX_VERSION"):
        return True
    prefix = env.get("PREFIX", "")
    return TERMUX_PREFIX_MARKER in prefix


def detect_shell(env: Optional[Mapping[str, str]] = None, system: Optional[str] = None) -> str:
    """Best-effort detection of the user's shell name."""
    env = os.environ if env is None else env
    system = system or platform.system().lower()
    if system == "windows":
        if env.get("PSModulePath") and env.get("PROMPT") is None:
            return "powershell"
        return ntpath.basename(env.get("COMSPEC", "cmd.exe")).lower()
    shell = env.get("SHELL", "")
    return os.path.basename(shell) if shell else "sh"


def detect_platform(env: Optional[Mapping[str, str]] = None) -> PlatformInfo:
    """Collect information about the current platform."""
    env = os.environ if env is None else env
    system = platform.system().lower()
    termux = is_termux(env)
    if termux:
        system = "android"
    interactive = bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())
    return PlatformInfo(
        system=system,
        is_termux=termux,
        is_windows=system == "windows",
        machine=platform.machine() or "unknown",
        python_version=platform.python_version(),
        shell=detect_shell(env, system),
        interactive=interactive,
    )


def which(program: str) -> Optional[str]:
    """Locate an executable on PATH (handles Windows extensions)."""
    return shutil.which(program)

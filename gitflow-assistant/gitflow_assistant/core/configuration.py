"""Centralised, persistent configuration.

* Defaults live in ``gitflow_assistant/config/defaults.yaml`` (read with PyYAML
  when available, otherwise with the small built-in parser below).
* User settings are stored as JSON in the platform config directory – never
  inside managed projects and never containing secrets.
* Export/import strips any key that looks like a secret.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gitflow_assistant.utils.path_manager import config_dir, ensure_dir

DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "config" / "defaults.yaml"
CONFIG_FILENAME = "config.json"
_SECRET_KEY = re.compile(r"(?:^|[_.-])(?:token|secret|password|passwd|private_key|api_key|apikey|credentials?)$",
                         re.IGNORECASE)


class ConfigError(ValueError):
    """Invalid configuration key or value."""


# --------------------------------------------------------------- mini YAML
def _scalar(text: str) -> Any:
    text = text.strip()
    if not text or text in ("~", "null", "Null", "NULL"):
        return None
    if text[0] in "\"'" and text[-1] == text[0] and len(text) >= 2:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(p) for p in _split_inline(inner)] if inner else []
    if text.startswith("{") and text.endswith("}") and not text[1:-1].strip():
        return {}
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _split_inline(text: str) -> List[str]:
    parts, buf, quote = [], "", ""
    for ch in text:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parse the YAML subset used by ``defaults.yaml``.

    Supports nested mappings by indentation, scalars, inline lists and block
    lists of scalars. Comments (``#`` at line start or after a space) are ignored.
    """
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, root)]
    pending: Optional[Tuple[Dict[str, Any], str, int]] = None
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if pending is not None and indent <= pending[2]:
            pending = None  # the previous key was an empty mapping
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if content.startswith("- "):
            if pending is not None:
                parent, key, _ = pending
                parent[key] = []
                stack.append((indent - 1, parent[key]))
                pending = None
            container = stack[-1][1]
            if not isinstance(container, list):
                raise ConfigError(f"unexpected list item: {raw!r}")
            container.append(_scalar(content[2:]))
            continue
        if ":" not in content:
            raise ConfigError(f"invalid line: {raw!r}")
        key, _, value = content.partition(":")
        key = key.strip().strip("\"'")
        container = stack[-1][1]
        if pending is not None:
            parent, pkey, pindent = pending
            parent[pkey] = {}
            stack.append((pindent, parent[pkey]))
            container = parent[pkey]
            pending = None
        if not isinstance(container, dict):
            raise ConfigError(f"unexpected mapping: {raw!r}")
        if value.strip():
            container[key] = _scalar(value)
        else:
            container[key] = {}
            pending = (container, key, indent)
    return root


def load_defaults(path: Path = DEFAULTS_FILE) -> Dict[str, Any]:
    """Load built-in defaults (PyYAML if installed, mini-parser otherwise)."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    except ImportError:
        data = parse_simple_yaml(text)
    if not isinstance(data, dict):
        raise ConfigError("defaults.yaml must contain a mapping")
    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def strip_secrets(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy without secret-looking keys (recursive)."""
    clean: Dict[str, Any] = {}
    for key, value in data.items():
        if _SECRET_KEY.search(key):
            continue
        clean[key] = strip_secrets(value) if isinstance(value, dict) else copy.deepcopy(value)
    return clean


class Configuration:
    """User configuration backed by a JSON file, layered over defaults."""

    def __init__(self, path: Optional[Path] = None, defaults: Optional[Dict[str, Any]] = None) -> None:
        self.path = path or (config_dir() / CONFIG_FILENAME)
        self.defaults = defaults if defaults is not None else load_defaults()
        self.user: Dict[str, Any] = {}
        self.load_error: Optional[str] = None
        self.load()

    # ---------------------------------------------------------------- I/O
    def load(self) -> None:
        """Read the user file. A corrupt file is reported, not silently replaced."""
        self.user = {}
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.user = strip_secrets(data)
            else:
                self.load_error = "configuration root is not an object"
        except (OSError, json.JSONDecodeError) as exc:
            self.load_error = f"cannot read {self.path}: {exc}"

    def save(self) -> None:
        """Persist user settings atomically."""
        ensure_dir(self.path.parent)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(strip_secrets(self.user), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------- access
    @property
    def data(self) -> Dict[str, Any]:
        """Effective configuration (defaults + user)."""
        return _deep_merge(self.defaults, self.user)

    def get(self, key: str, default: Any = None) -> Any:
        """Read a dotted key such as ``security.max_file_size_mb``."""
        node: Any = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def _default_for(self, key: str) -> Any:
        node: Any = self.defaults
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"unknown configuration key: {key}")
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> Any:
        """Set a dotted key, coercing strings to the type of the default."""
        if _SECRET_KEY.search(key.split(".")[-1]):
            raise ConfigError("secrets cannot be stored in the configuration file")
        if key.startswith("aliases.") and key.count(".") == 1:
            self.set_alias(key.split(".", 1)[1], str(value))
            return str(value).strip()
        default = self._default_for(key)
        coerced = self._coerce(value, default, key)
        node = self.user
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = coerced
        return coerced

    def set_alias(self, alias: str, command: str) -> None:
        """Create or update a command alias."""
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,19}", alias):
            raise ConfigError(f"invalid alias: {alias!r}")
        self.user.setdefault("aliases", {})[alias] = command.strip()

    def remove_alias(self, alias: str) -> bool:
        """Remove a user alias; returns True if it existed."""
        return self.user.get("aliases", {}).pop(alias, None) is not None

    def unset(self, key: str) -> None:
        """Restore a key to its default value."""
        self._default_for(key)
        node = self.user
        parts = key.split(".")
        for part in parts[:-1]:
            if part not in node:
                return
            node = node[part]
        node.pop(parts[-1], None)

    def reset(self) -> None:
        """Discard every user setting (defaults remain)."""
        self.user = {}

    def append_unique(self, key: str, value: str) -> None:
        """Append to a list setting without duplicates."""
        current = list(self.get(key) or [])
        if value not in current:
            current.append(value)
        self.set(key, current)

    @staticmethod
    def _coerce(value: Any, default: Any, key: str) -> Any:
        if not isinstance(value, str) or isinstance(default, str) or default is None:
            return value
        text = value.strip()
        if isinstance(default, bool):
            if text.lower() in ("true", "yes", "on", "1", "sim"):
                return True
            if text.lower() in ("false", "no", "off", "0", "nao", "não"):
                return False
            raise ConfigError(f"{key} expects true/false")
        if isinstance(default, int):
            try:
                number = int(text)
            except ValueError as exc:
                raise ConfigError(f"{key} expects an integer") from exc
            if number < 0:
                raise ConfigError(f"{key} must be positive")
            return number
        if isinstance(default, list):
            return [p.strip() for p in text.split(",") if p.strip()]
        if isinstance(default, dict):
            raise ConfigError(f"{key} is a section; set one of its sub-keys")
        return text

    # ------------------------------------------------------ import/export
    def export_to(self, destination: Path) -> Path:
        """Export user settings (without secrets) as JSON."""
        destination.write_text(json.dumps(strip_secrets(self.user), indent=2, ensure_ascii=False), encoding="utf-8")
        return destination

    def import_from(self, source: Path) -> List[str]:
        """Import settings, keeping only known keys. Returns ignored keys."""
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ConfigError("imported file must contain a JSON object")
        ignored: List[str] = []

        def walk(node: Dict[str, Any], prefix: str) -> None:
            for key, value in node.items():
                full = f"{prefix}{key}"
                if _SECRET_KEY.search(key):
                    ignored.append(full)
                    continue
                if full.startswith("aliases."):
                    try:
                        self.set_alias(key, str(value))
                    except ConfigError:
                        ignored.append(full)
                    continue
                try:
                    default = self._default_for(full)
                except ConfigError:
                    ignored.append(full)
                    continue
                if isinstance(default, dict) and isinstance(value, dict):
                    walk(value, full + ".")
                else:
                    self.set(full, value)

        walk(data, "")
        return ignored

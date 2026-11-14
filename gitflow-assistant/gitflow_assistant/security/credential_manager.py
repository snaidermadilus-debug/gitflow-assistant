"""Credential discovery and optional secure storage.

Resolution order for a GitHub token:

1. Session token (kept in memory only, never persisted).
2. ``GITHUB_TOKEN`` / ``GH_TOKEN`` environment variables.
3. OS keyring (only if the optional ``keyring`` package and a real backend exist).
4. GitHub CLI: ``gh auth token``.
5. Git credential helper: ``git credential fill`` for ``https://github.com``.

Tokens are never written to logs or config files and are always masked in the UI.
When no secure storage is available, the token is **not** saved in plain text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, Optional

KEYRING_SERVICE = "gitflow-assistant"
KEYRING_USER = "github-token"
KEYRING_GEMINI = "gemini-api-key"


class CredentialStorageUnavailable(RuntimeError):
    """No secure credential backend is available on this system."""


@dataclass
class TokenInfo:
    """A resolved token and where it came from."""

    token: str
    source: str  # session | env:GITHUB_TOKEN | keyring | gh | git-credential

    @property
    def masked(self) -> str:
        return mask_token(self.token)


def mask_token(token: str) -> str:
    """Never display a full token."""
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}…{token[-4:]}"


def _run(argv: list, input_text: Optional[str] = None, timeout: int = 15) -> Optional[str]:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GH_PROMPT_DISABLED": "1"})
    try:
        proc = subprocess.run(argv, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              stdin=None if input_text is not None else subprocess.DEVNULL,
                              encoding="utf-8", errors="replace", timeout=timeout, env=env, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _load_keyring():  # type: ignore[no-untyped-def]
    try:
        import keyring  # type: ignore
        from keyring.backends import fail  # type: ignore
    except Exception:  # noqa: BLE001 - any import problem means "unavailable"
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001
        return None
    if isinstance(backend, fail.Keyring) or "fail" in type(backend).__module__ or "null" in type(backend).__module__:
        return None
    return keyring


class CredentialManager:
    """Find, store and remove GitHub credentials without leaking them."""

    def __init__(self, host: str = "github.com", runner: Callable[..., Optional[str]] = _run,
                 env: Optional[Dict[str, str]] = None, use_keyring: bool = True) -> None:
        self.host = host
        self._runner = runner
        self._env = os.environ if env is None else env
        self._session: Optional[str] = None
        self._gemini_session: Optional[str] = None
        self._use_keyring = use_keyring

    # ------------------------------------------------------------- session
    def set_session_token(self, token: str) -> None:
        """Use a token for this process only (temporary, not persisted)."""
        token = token.strip()
        if not token:
            raise ValueError("empty token")
        self._session = token

    # ---------------------------------------------------------- discovery
    def from_env(self) -> Optional[TokenInfo]:
        for var in ("GITHUB_TOKEN", "GH_TOKEN"):
            value = self._env.get(var, "").strip()
            if value:
                return TokenInfo(value, f"env:{var}")
        return None

    def from_keyring(self) -> Optional[TokenInfo]:
        if not self._use_keyring:
            return None
        backend = _load_keyring()
        if not backend:
            return None
        try:
            value = backend.get_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:  # noqa: BLE001 - keyring backends raise various errors
            return None
        return TokenInfo(value, "keyring") if value else None

    def gh_available(self) -> bool:
        """True if the GitHub CLI is installed."""
        return shutil.which("gh") is not None

    def from_gh(self) -> Optional[TokenInfo]:
        if not self.gh_available():
            return None
        out = self._runner(["gh", "auth", "token", "--hostname", self.host])
        token = (out or "").strip()
        return TokenInfo(token, "gh") if token else None

    def from_git_credential(self) -> Optional[TokenInfo]:
        if not shutil.which("git"):
            return None
        out = self._runner(["git", "credential", "fill"], input_text=f"protocol=https\nhost={self.host}\n\n")
        if not out:
            return None
        fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        password = fields.get("password", "").strip()
        return TokenInfo(password, "git-credential") if password else None

    def resolve(self, allow_credential_helper: bool = True) -> Optional[TokenInfo]:
        """Return the first available token following the documented order."""
        if self._session:
            return TokenInfo(self._session, "session")
        for finder in (self.from_env, self.from_keyring, self.from_gh):
            found = finder()
            if found:
                return found
        if allow_credential_helper:
            return self.from_git_credential()
        return None

    # ------------------------------------------------------------ storage
    def resolve_gemini_key(self) -> Optional[TokenInfo]:
        """Gemini API key: session, ``GEMINI_API_KEY``/``GOOGLE_API_KEY``, then the OS keyring."""
        if self._gemini_session:
            return TokenInfo(self._gemini_session, "session")
        for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            value = self._env.get(var, "").strip()
            if value:
                return TokenInfo(value, f"env:{var}")
        backend = _load_keyring() if self._use_keyring else None
        if backend:
            try:
                value = backend.get_password(KEYRING_SERVICE, KEYRING_GEMINI)
            except Exception:  # noqa: BLE001
                return None
            if value:
                return TokenInfo(value, "keyring")
        return None

    def set_gemini_session_key(self, key: str) -> None:
        """Use a Gemini key for this process only."""
        if not key.strip():
            raise ValueError("empty key")
        self._gemini_session = key.strip()

    def store_gemini_key(self, key: str) -> str:
        """Persist the Gemini key in the OS keyring (never in plain text)."""
        return self.store(key, account=KEYRING_GEMINI)

    def forget_gemini_key(self) -> bool:
        """Remove the Gemini session key and keyring entry."""
        removed = self._gemini_session is not None
        self._gemini_session = None
        backend = _load_keyring() if self._use_keyring else None
        if backend:
            try:
                backend.delete_password(KEYRING_SERVICE, KEYRING_GEMINI)
            except Exception:  # noqa: BLE001 - entry did not exist
                return removed
            removed = True
        return removed

    def secure_storage_available(self) -> bool:
        """True if an OS keyring backend can be used."""
        return self._use_keyring and _load_keyring() is not None

    def store(self, token: str, account: str = KEYRING_USER) -> str:
        """Persist the token in the OS keyring.

        Raises :class:`CredentialStorageUnavailable` instead of falling back to
        plain-text storage.
        """
        backend = _load_keyring() if self._use_keyring else None
        if not backend:
            raise CredentialStorageUnavailable(
                "no secure credential storage available (install 'keyring' with a supported backend, "
                "use 'gh auth login', or export the environment variable for the session)")
        backend.set_password(KEYRING_SERVICE, account, token.strip())
        return "keyring"

    def forget(self) -> bool:
        """Remove the session token and the keyring entry (if any)."""
        removed = self._session is not None
        self._session = None
        backend = _load_keyring() if self._use_keyring else None
        if backend:
            try:
                backend.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:  # noqa: BLE001 - entry did not exist
                return removed
            removed = True
        return removed

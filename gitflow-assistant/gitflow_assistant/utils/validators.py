"""Input validation shared by the CLI, TUI and services.

These checks protect against option injection (values starting with ``-``)
and malformed references before anything is passed to ``git``.
"""

from __future__ import annotations

import re
from typing import Optional

_REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SCP_URL = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._~/-]+?(\.git)?/?$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(ValueError):
    """Raised when user supplied input is invalid."""


def validate_branch_name(name: str) -> str:
    """Validate a branch name following ``git check-ref-format`` rules."""
    name = name.strip()
    invalid = (
        not name
        or name.startswith(("-", "/", "."))
        or name.endswith(("/", ".", ".lock"))
        or ".." in name
        or "//" in name
        or "@{" in name
        or name == "@"
        or any(ch in name for ch in " ~^:?*[\\")
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
        or any(part.startswith(".") for part in name.split("/"))
    )
    if invalid:
        raise ValidationError(f"invalid branch name: {name!r}")
    return name


def validate_remote_name(name: str) -> str:
    """Validate a remote name such as ``origin``."""
    name = name.strip()
    if not _REMOTE_NAME.match(name):
        raise ValidationError(f"invalid remote name: {name!r}")
    return name


def validate_remote_url(url: str) -> str:
    """Accept https://, ssh://, git://, file:// URLs, SCP-like SSH and local paths."""
    url = url.strip()
    if not url or url.startswith("-") or any(c in url for c in "\n\r\t "):
        raise ValidationError(f"invalid remote URL: {url!r}")
    lowered = url.lower()
    if lowered.startswith(("https://", "http://", "ssh://", "git://", "file://")):
        return url
    if _SCP_URL.match(url):
        return url
    if url.startswith(("/", "./", "../", "~")) or re.match(r"^[A-Za-z]:[\\/]", url):
        return url
    raise ValidationError(f"unsupported remote URL: {url!r}")


def validate_repo_name(name: str) -> str:
    """Validate a GitHub repository name."""
    name = name.strip()
    if not _REPO_NAME.match(name) or name in (".", ".."):
        raise ValidationError(f"invalid repository name: {name!r}")
    return name


def validate_commit_message(message: str, max_subject: int = 72) -> str:
    """Ensure the commit message is not empty; returns the stripped message.

    A subject longer than ``max_subject`` is accepted (Git allows it) – callers
    can use :func:`commit_message_warning` to warn the user.
    """
    message = message.strip()
    if not message:
        raise ValidationError("commit message cannot be empty")
    return message


def commit_message_warning(message: str, max_subject: int = 72) -> Optional[str]:
    """Return a style warning for the commit subject line, if any."""
    subject = message.strip().splitlines()[0] if message.strip() else ""
    if len(subject) > max_subject:
        return f"subject has {len(subject)} characters (recommended <= {max_subject})"
    return None


def validate_email(email: str) -> str:
    """Validate an e-mail address used for ``user.email``."""
    email = email.strip()
    if not _EMAIL.match(email):
        raise ValidationError(f"invalid e-mail: {email!r}")
    return email


def validate_path_arg(path: str) -> str:
    """Reject empty paths and NUL bytes. Paths are always passed after ``--``."""
    if not path or "\x00" in path:
        raise ValidationError(f"invalid path: {path!r}")
    return path

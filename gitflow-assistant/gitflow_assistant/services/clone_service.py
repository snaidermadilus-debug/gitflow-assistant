"""Clone remote repositories into a local directory."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from gitflow_assistant.core.git_engine import GitError, redact
from gitflow_assistant.core.sync_manager import classify_failure
from gitflow_assistant.i18n import t
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.errors import RemoteOperationFailed, UsageError
from gitflow_assistant.utils.validators import validate_remote_url


def repo_name_from_url(url: str) -> str:
    """Derive the directory name git would use for ``url``."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() in ("http", "https", "ssh", "git", "file"):
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    elif "@" in url.partition(":")[0] and ":" in url:
        tail = url.partition(":")[2].rstrip("/").rsplit("/", 1)[-1]
    else:
        tail = url.rstrip("/").replace("\\", "/").rsplit("/", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail or "repository"


def clone(ctx: AppContext, url: str, destination: Optional[Path] = None, branch: Optional[str] = None,
          depth: Optional[int] = None) -> Path:
    """Clone ``url``; the destination must not exist or must be an empty directory."""
    url = validate_remote_url(url)
    if destination is None:
        base = Path(str(ctx.config.get("projects_dir") or "")).expanduser() if ctx.config.get("projects_dir") \
            else Path.cwd()
        destination = base / repo_name_from_url(url)
    destination = destination.expanduser().resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise UsageError(t("clone.exists", path=str(destination)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    engine = ctx.engine(destination.parent)
    safe_url = redact(url)
    with ctx.ui.progress(t("clone.running", url=safe_url)):
        result = engine.clone(url, destination, branch=branch, depth=depth, interactive_auth=ctx.ui.interactive)
    if not result.ok:
        kind = classify_failure(result)
        error = redact(result.error_text())
        ctx.history.record("clone", destination, False, error)
        hint = {"auth": t("hint.auth1"), "network": t("hint.net1")}.get(kind, "")
        raise RemoteOperationFailed(f"{error}\n{hint}".strip())
    if not ctx.engine(destination).is_repository():
        raise GitError(t("clone.failed_verify", path=str(destination)))
    ctx.repos.add(destination)
    ctx.history.record("clone", destination, True, safe_url)
    ctx.ui.success(t("clone.done", path=str(destination)))
    return destination

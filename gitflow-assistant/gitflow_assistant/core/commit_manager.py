"""Commit creation helpers: message building and safe commits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from gitflow_assistant.core.git_engine import GitEngine, GitError
from gitflow_assistant.utils.templates import COMMIT_TEMPLATES
from gitflow_assistant.utils.validators import ValidationError, validate_commit_message


@dataclass
class CommitOutcome:
    """Result of a commit."""

    sha: str
    short_sha: str
    files: List[str]
    message: str


def build_conventional(kind: str, description: str, scope: str = "", breaking: bool = False) -> str:
    """Build a Conventional Commits message, e.g. ``feat(cli): add scan``."""
    if kind not in COMMIT_TEMPLATES:
        raise ValidationError(f"unknown commit type: {kind} (use one of {', '.join(COMMIT_TEMPLATES)})")
    description = description.strip()
    if not description:
        raise ValidationError("commit description cannot be empty")
    scope_part = f"({scope.strip()})" if scope.strip() else ""
    return f"{kind}{scope_part}{'!' if breaking else ''}: {description}"


class CommitManager:
    """Stage selected files and create commits without ever committing empty changes."""

    def __init__(self, engine: GitEngine) -> None:
        self.engine = engine

    def ensure_identity(self) -> Optional[str]:
        """Return an error message if ``user.name``/``user.email`` are not configured."""
        name = self.engine.get_config("user.name")
        email = self.engine.get_config("user.email")
        if not name or not email:
            return "git identity missing: set user.name and user.email (gitflow config set git.user_name ...)"
        return None

    def stage(self, paths: Sequence[str]) -> List[str]:
        """Stage ``paths`` and return what is staged afterwards."""
        if paths:
            self.engine.add(list(paths))
        return self.engine.staged_files()

    def commit(self, message: str, paths: Sequence[str] = ()) -> CommitOutcome:
        """Optionally stage ``paths`` then commit the index.

        Raises :class:`GitError` if there is nothing staged (no empty commits).
        """
        message = validate_commit_message(message)
        identity_error = self.ensure_identity()
        if identity_error:
            raise GitError(identity_error)
        staged = self.stage(paths)
        deletions = self.engine.run(["diff", "--cached", "--name-only", "-z", "--diff-filter=D"]).stdout
        staged_all = staged + [p for p in deletions.split("\x00") if p]
        if not staged_all:
            raise GitError("nothing staged to commit")
        self.engine.commit(message)
        return CommitOutcome(sha=self.engine.head_sha() or "", short_sha=self.engine.head_sha(short=True) or "",
                             files=staged_all, message=message)

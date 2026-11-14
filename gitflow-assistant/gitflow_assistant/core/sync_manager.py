"""Synchronisation analysis and safe pull/push.

Safety guarantees
-----------------
* Never ``push --force``; a rejected push is reported with guidance.
* ``pull`` defaults to fast-forward only. Merge or rebase are only used when
  explicitly requested, and a backup branch pointing to the pre-sync commit is
  created first so no local commit can be lost.
* On conflicts the operation is left for the user to resolve or abort
  (``git merge --abort`` / ``git rebase --abort`` restore the previous state).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from gitflow_assistant.core.git_engine import GitEngine, GitError, GitResult

REJECT_MARKERS = ("[rejected]", "non-fast-forward", "fetch first", "! [remote rejected]", "failed to push")
AUTH_MARKERS = ("authentication failed", "could not read username", "permission denied", "403", "terminal prompts disabled")
NETWORK_MARKERS = ("could not resolve host", "unable to access", "connection timed out", "network is unreachable",
                   "timeout after", "connection refused", "could not read from remote repository")


@dataclass
class SyncState:
    """Relationship between the local branch and its upstream."""

    branch: Optional[str]
    remote: Optional[str]
    upstream: Optional[str]
    ahead: int = 0
    behind: int = 0
    fetched: bool = False
    fetch_error: Optional[str] = None
    remote_branch_exists: bool = False

    @property
    def diverged(self) -> bool:
        return self.ahead > 0 and self.behind > 0

    @property
    def up_to_date(self) -> bool:
        return self.ahead == 0 and self.behind == 0


@dataclass
class SyncOutcome:
    """Result of a pull or push."""

    ok: bool
    action: str
    kind: str = "ok"  # ok | rejected | auth | network | conflict | error | nothing
    message: str = ""
    conflicts: List[str] = field(default_factory=list)
    backup_branch: Optional[str] = None


def classify_failure(result: GitResult) -> str:
    """Classify a failed network git command."""
    text = (result.stderr + "\n" + result.stdout).lower()
    if result.timed_out or any(m in text for m in NETWORK_MARKERS if m != "could not read from remote repository"):
        return "network"
    if any(m in text for m in AUTH_MARKERS):
        return "auth"
    if any(m in text for m in REJECT_MARKERS):
        return "rejected"
    if "could not read from remote repository" in text:
        return "auth"
    if "conflict" in text:
        return "conflict"
    return "error"


class SyncManager:
    """High level synchronisation built on :class:`GitEngine`."""

    def __init__(self, engine: GitEngine, remote: str = "origin", interactive_auth: bool = False) -> None:
        self.engine = engine
        self.remote = remote
        self.interactive_auth = interactive_auth

    def analyze(self, fetch: bool = True) -> SyncState:
        """Compute ahead/behind, fetching first when ``fetch`` is True."""
        branch = self.engine.current_branch()
        remotes = self.engine.remotes()
        remote = self.remote if self.remote in remotes else (sorted(remotes)[0] if remotes else None)
        state = SyncState(branch=branch, remote=remote, upstream=None)
        if not remote:
            return state
        if fetch:
            res = self.engine.fetch(remote, interactive_auth=self.interactive_auth)
            state.fetched = res.ok
            if not res.ok:
                state.fetch_error = res.error_text()
        upstream = self.engine.upstream() if branch else None
        if not upstream and branch:
            candidate = f"{remote}/{branch}"
            if candidate in self.engine.remote_branches():
                upstream = candidate
        state.upstream = upstream
        state.remote_branch_exists = bool(upstream)
        if upstream:
            state.ahead, state.behind = self.engine.ahead_behind(upstream)
        elif self.engine.has_commits():
            res = self.engine.run(["rev-list", "--count", "HEAD"])
            state.ahead = int(res.stdout.strip() or 0) if res.ok else 0
        return state

    def create_backup_branch(self) -> Optional[str]:
        """Create ``gitflow-backup/<branch>-<timestamp>`` at HEAD (non-destructive)."""
        branch = self.engine.current_branch()
        if not branch or not self.engine.has_commits():
            return None
        name = f"gitflow-backup/{branch}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.engine.create_branch(name)
        return name

    def pull(self, strategy: str = "ff-only", backup: bool = True, allow_unrelated: bool = False) -> SyncOutcome:
        """Pull the upstream of the current branch with the given strategy."""
        op = self.engine.operation_in_progress()
        if op:
            return SyncOutcome(False, "pull", "conflict", f"a {op} is in progress; finish or abort it first",
                               conflicts=self.engine.conflicts())
        branch = self.engine.current_branch()
        if not branch:
            return SyncOutcome(False, "pull", "error", "detached HEAD: switch to a branch first")
        backup_branch = self.create_backup_branch() if backup and strategy != "ff-only" else None
        args_branch = None if self.engine.upstream() else branch
        if allow_unrelated:
            res = self.engine.run(["pull", "--no-rebase", "--no-edit", "--allow-unrelated-histories",
                                   self.remote, branch], timeout=self.engine.network_timeout,
                                  interactive_auth=self.interactive_auth)
        else:
            res = self.engine.pull(self.remote, args_branch, strategy, interactive_auth=self.interactive_auth)
        if res.ok:
            return SyncOutcome(True, "pull", "ok", res.stdout.strip(), backup_branch=backup_branch)
        conflicts = self.engine.conflicts()
        if conflicts or self.engine.operation_in_progress():
            return SyncOutcome(False, "pull", "conflict", res.error_text(), conflicts=conflicts,
                               backup_branch=backup_branch)
        text = res.error_text().lower()
        if "not possible to fast-forward" in text or "diverging" in text or "divergent" in text:
            kind = "rejected"
        else:
            kind = classify_failure(res)
        return SyncOutcome(False, "pull", kind, res.error_text(), backup_branch=backup_branch)

    def push(self, set_upstream: bool = False) -> SyncOutcome:
        """Push the current branch. Never forces."""
        branch = self.engine.current_branch()
        if not branch:
            return SyncOutcome(False, "push", "error", "detached HEAD: switch to a branch first")
        if not self.engine.has_commits():
            return SyncOutcome(False, "push", "nothing", "no commits to push")
        needs_upstream = set_upstream or not self.engine.upstream()
        res = self.engine.push(self.remote, branch, set_upstream=needs_upstream, interactive_auth=self.interactive_auth)
        if res.ok:
            return SyncOutcome(True, "push", "ok", (res.stdout + res.stderr).strip())
        return SyncOutcome(False, "push", classify_failure(res), res.error_text())

    def abort(self) -> SyncOutcome:
        """Abort an in-progress merge/rebase, restoring the previous state."""
        op = self.engine.operation_in_progress()
        if not op:
            return SyncOutcome(False, "abort", "nothing", "no operation in progress")
        try:
            self.engine.abort_operation(op)
        except GitError as exc:
            return SyncOutcome(False, "abort", "error", str(exc))
        return SyncOutcome(True, "abort", "ok", f"{op} aborted")

"""Safe, structured bridge between Python and the installed ``git`` executable.

Design rules
------------
* ``subprocess.run`` with an argument list – never ``shell=True``.
* Every call has a timeout and an explicit working directory.
* Machine-readable output only (``--porcelain=v1 -z``, ``--format`` with
  separators, exit codes). Colours and pagers are disabled.
* User supplied values that could be parsed as options are validated, and
  paths are always passed after ``--``.
* Credentials embedded in URLs are redacted from errors and logs.
* No destructive command (reset --hard, clean, push --force) is exposed.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from gitflow_assistant.utils.validators import (
    ValidationError,
    validate_branch_name,
    validate_path_arg,
    validate_remote_name,
    validate_remote_url,
)

log = logging.getLogger("gitflow.git")

DEFAULT_TIMEOUT = 60
NETWORK_TIMEOUT = 300
_URL_CRED = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<cred>[^/@\s]+)@", re.IGNORECASE)
_TOKEN_LIKE = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


def redact(text: str) -> str:
    """Remove credentials from URLs and GitHub token-like strings."""
    text = _URL_CRED.sub(lambda m: f"{m.group('scheme')}***@", text)
    return _TOKEN_LIKE.sub("***", text)


class GitError(RuntimeError):
    """Raised when a git command fails. ``result`` holds the details."""

    def __init__(self, message: str, result: Optional["GitResult"] = None) -> None:
        super().__init__(redact(message))
        self.result = result


class GitNotInstalledError(GitError):
    """The git executable could not be found."""


@dataclass
class GitResult:
    """Structured result of a git invocation."""

    args: List[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def command(self) -> str:
        return redact("git " + " ".join(self.args))

    def error_text(self) -> str:
        msg = (self.stderr or self.stdout).strip()
        return redact(msg) if msg else f"exit code {self.returncode}"


@dataclass
class FileStatus:
    """One entry of ``git status --porcelain=v1 -z``."""

    path: str
    index: str  # X column
    worktree: str  # Y column
    orig_path: Optional[str] = None

    @property
    def is_untracked(self) -> bool:
        return self.index == "?" and self.worktree == "?"

    @property
    def is_ignored(self) -> bool:
        return self.index == "!" and self.worktree == "!"

    @property
    def is_conflicted(self) -> bool:
        pair = self.index + self.worktree
        return pair in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

    @property
    def is_staged(self) -> bool:
        return self.index not in (" ", "?", "!") and not self.is_conflicted

    @property
    def is_unstaged(self) -> bool:
        return self.worktree not in (" ", "?", "!") and not self.is_conflicted

    @property
    def code(self) -> str:
        return self.index + self.worktree


@dataclass
class BranchInfo:
    """A local branch."""

    name: str
    is_current: bool
    upstream: str = ""
    commit: str = ""


@dataclass
class CommitInfo:
    """A commit from ``git log``."""

    sha: str
    short_sha: str
    author: str
    email: str
    date: str
    subject: str


@dataclass
class RepoStatus:
    """Aggregated repository status."""

    branch: Optional[str]
    upstream: Optional[str]
    ahead: int
    behind: int
    files: List[FileStatus] = field(default_factory=list)
    detached: bool = False
    has_commits: bool = True

    @property
    def staged(self) -> List[FileStatus]:
        return [f for f in self.files if f.is_staged]

    @property
    def unstaged(self) -> List[FileStatus]:
        return [f for f in self.files if f.is_unstaged]

    @property
    def untracked(self) -> List[FileStatus]:
        return [f for f in self.files if f.is_untracked]

    @property
    def conflicted(self) -> List[FileStatus]:
        return [f for f in self.files if f.is_conflicted]

    @property
    def is_clean(self) -> bool:
        return not [f for f in self.files if not f.is_ignored]


def parse_porcelain_z(data: str) -> List[FileStatus]:
    """Parse ``git status --porcelain=v1 -z`` output."""
    entries: List[FileStatus] = []
    parts = data.split("\x00")
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        x, y, path = item[0], item[1], item[3:]
        orig = None
        if x in "RC" or y in "RC":
            # rename/copy: the next NUL-separated field is the original path
            if i < len(parts):
                orig = parts[i]
                i += 1
        entries.append(FileStatus(path=path, index=x, worktree=y, orig_path=orig))
    return entries


class GitEngine:
    """Run git commands inside one working directory.

    Parameters
    ----------
    cwd:
        Directory where git is executed.
    timeout:
        Default timeout in seconds for local commands.
    network_timeout:
        Timeout for fetch/pull/push/clone.
    git_executable:
        Name or path of the git binary.
    """

    def __init__(self, cwd: Path, timeout: int = DEFAULT_TIMEOUT, network_timeout: int = NETWORK_TIMEOUT,
                 git_executable: str = "git") -> None:
        self.cwd = Path(cwd)
        self.timeout = timeout
        self.network_timeout = network_timeout
        self.git = git_executable

    # ------------------------------------------------------------------ runner
    def _env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env.update({
            "GIT_TERMINAL_PROMPT": env.get("GIT_TERMINAL_PROMPT", "0"),
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_OPTIONAL_LOCKS": "0",
        })
        return env

    def run(self, args: Sequence[str], check: bool = False, timeout: Optional[int] = None,
            cwd: Optional[Path] = None, interactive_auth: bool = False) -> GitResult:
        """Execute ``git <args>`` and return a :class:`GitResult`.

        ``interactive_auth`` lets git ask for credentials on the terminal
        (used for push/pull/clone when the user is present).
        """
        argv = [self.git, "-c", "color.ui=false", "-c", "core.quotepath=false", *args]
        workdir = Path(cwd) if cwd else self.cwd
        env = self._env()
        if interactive_auth:
            env.pop("GIT_TERMINAL_PROMPT", None)
        log.debug("run: %s (cwd=%s)", redact(" ".join(argv[1:])), workdir)
        try:
            proc = subprocess.run(
                argv, cwd=str(workdir), env=env, timeout=timeout or self.timeout,
                stdin=None if interactive_auth else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace", shell=False,
            )
            result = GitResult(list(args), proc.returncode, proc.stdout or "", proc.stderr or "")
        except FileNotFoundError as exc:
            if not workdir.exists():
                raise GitError(f"directory does not exist: {workdir}") from exc
            raise GitNotInstalledError("git executable not found; install Git and make sure it is on PATH") from exc
        except NotADirectoryError as exc:
            raise GitError(f"not a directory: {workdir}") from exc
        except subprocess.TimeoutExpired as exc:
            result = GitResult(list(args), -1, "", f"timeout after {exc.timeout}s", timed_out=True)
        if not result.ok:
            log.debug("failed (%s): %s", result.returncode, result.error_text())
        if check and not result.ok:
            raise GitError(f"{result.command}: {result.error_text()}", result)
        return result

    # ---------------------------------------------------------- installation
    def is_installed(self) -> bool:
        """Return True if the git executable can be run."""
        try:
            return self.run(["--version"], cwd=Path.cwd() if not self.cwd.exists() else None).ok
        except GitNotInstalledError:
            return False

    def version(self) -> Optional[Tuple[int, ...]]:
        """Return the git version as a tuple, e.g. ``(2, 43, 0)``."""
        try:
            res = self.run(["--version"], cwd=Path.cwd() if not self.cwd.exists() else None)
        except GitNotInstalledError:
            return None
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", res.stdout)
        if not match:
            return None
        return tuple(int(x) for x in match.groups() if x is not None)

    # ----------------------------------------------------------- repository
    def is_repository(self) -> bool:
        """True if ``cwd`` is inside a git working tree."""
        if not self.cwd.is_dir():
            return False
        res = self.run(["rev-parse", "--is-inside-work-tree"])
        return res.ok and res.stdout.strip() == "true"

    def root(self) -> Optional[Path]:
        """Top-level directory of the repository, or None."""
        if not self.cwd.is_dir():
            return None
        res = self.run(["rev-parse", "--show-toplevel"])
        return Path(res.stdout.strip()).resolve() if res.ok and res.stdout.strip() else None

    def init(self, initial_branch: str = "main") -> GitResult:
        """Initialise a repository with the given initial branch."""
        branch = validate_branch_name(initial_branch)
        res = self.run(["init"], check=True)
        # portable across git < 2.28 (no --initial-branch)
        self.run(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True)
        return res

    def has_commits(self) -> bool:
        """True if HEAD points to an existing commit."""
        return self.run(["rev-parse", "--verify", "--quiet", "HEAD"]).ok

    def current_branch(self) -> Optional[str]:
        """Current branch name (works on unborn branches); None if detached."""
        res = self.run(["symbolic-ref", "--quiet", "--short", "HEAD"])
        return res.stdout.strip() if res.ok and res.stdout.strip() else None

    def upstream(self, branch: Optional[str] = None) -> Optional[str]:
        """Upstream of ``branch`` (``origin/main``) or None."""
        ref = f"{validate_branch_name(branch)}@{{upstream}}" if branch else "@{upstream}"
        res = self.run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", ref])
        return res.stdout.strip() if res.ok and res.stdout.strip() else None

    def ahead_behind(self, upstream: Optional[str] = None) -> Tuple[int, int]:
        """Number of commits ahead/behind the upstream."""
        up = upstream or self.upstream()
        if not up or not self.has_commits():
            return 0, 0
        res = self.run(["rev-list", "--left-right", "--count", f"HEAD...{up}"])
        if not res.ok:
            return 0, 0
        left, right = (res.stdout.split() + ["0", "0"])[:2]
        return int(left), int(right)

    def status(self, include_ignored: bool = False) -> RepoStatus:
        """Full repository status parsed from porcelain v1 output."""
        args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
        if include_ignored:
            args.append("--ignored=matching")
        res = self.run(args, check=True)
        branch = self.current_branch()
        upstream = self.upstream() if branch else None
        ahead, behind = self.ahead_behind(upstream) if upstream else (0, 0)
        return RepoStatus(branch=branch, upstream=upstream, ahead=ahead, behind=behind,
                          files=parse_porcelain_z(res.stdout), detached=branch is None and self.has_commits(),
                          has_commits=self.has_commits())

    def changed_files(self) -> List[FileStatus]:
        """All modified, staged, untracked and conflicted files."""
        return self.status().files

    # --------------------------------------------------------------- staging
    def add(self, paths: Sequence[str]) -> GitResult:
        """Stage the given paths (never ``-A`` implicitly)."""
        if not paths:
            raise ValidationError("no paths to add")
        clean = [validate_path_arg(p) for p in paths]
        return self.run(["add", "--", *clean], check=True)

    def unstage(self, paths: Sequence[str]) -> GitResult:
        """Remove paths from the index, keeping working tree changes."""
        clean = [validate_path_arg(p) for p in paths]
        if self.has_commits():
            return self.run(["reset", "--quiet", "HEAD", "--", *clean], check=True)
        return self.run(["rm", "--cached", "--quiet", "-r", "--", *clean], check=True)

    def remove(self, paths: Sequence[str], keep_local: bool = True) -> GitResult:
        """Stop tracking paths. With ``keep_local`` the files stay on disk.

        Deleting from disk (``keep_local=False``) must only be called after an
        explicit user confirmation; git refuses if files have local changes.
        """
        clean = [validate_path_arg(p) for p in paths]
        args = ["rm", "-r"]
        if keep_local:
            args.append("--cached")
        return self.run([*args, "--", *clean], check=True)

    def staged_files(self) -> List[str]:
        """Paths currently staged (added/copied/modified/renamed)."""
        res = self.run(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], check=True)
        return [p for p in res.stdout.split("\x00") if p]

    def staged_blob(self, path: str, max_bytes: int) -> bytes:
        """Read up to ``max_bytes`` of the staged content of ``path``."""
        validate_path_arg(path)
        argv = [self.git, "cat-file", "blob", f":{path}"]
        try:
            with subprocess.Popen(argv, cwd=str(self.cwd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL, env=self._env(), shell=False) as proc:
                assert proc.stdout is not None
                data = proc.stdout.read(max_bytes)
                proc.stdout.close()
                proc.wait(timeout=self.timeout)
                return data
        except (OSError, subprocess.TimeoutExpired):
            return b""

    def staged_size(self, path: str) -> int:
        """Size in bytes of the staged blob of ``path``."""
        res = self.run(["cat-file", "-s", f":{validate_path_arg(path)}"])
        return int(res.stdout.strip()) if res.ok and res.stdout.strip().isdigit() else 0

    def check_ignore(self, paths: Sequence[str]) -> List[str]:
        """Return the subset of ``paths`` ignored by .gitignore rules."""
        if not paths:
            return []
        res = self.run(["check-ignore", "--", *[validate_path_arg(p) for p in paths]])
        return [p for p in res.stdout.splitlines() if p]

    # --------------------------------------------------------------- commits
    def commit(self, message: str, allow_empty: bool = False) -> GitResult:
        """Create a commit from the index. Refuses empty commits by default."""
        if not message.strip():
            raise ValidationError("commit message cannot be empty")
        if not allow_empty and not self.staged_files() and not self._staged_deletions():
            raise GitError("nothing staged to commit")
        args = ["commit", "--file=-"]
        if allow_empty:
            args.append("--allow-empty")
        argv = [self.git, "-c", "color.ui=false", *args]
        try:
            proc = subprocess.run(argv, cwd=str(self.cwd), input=message, env=self._env(), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                  timeout=self.timeout, shell=False)
        except FileNotFoundError as exc:
            raise GitNotInstalledError("git executable not found") from exc
        result = GitResult(args, proc.returncode, proc.stdout, proc.stderr)
        if not result.ok:
            raise GitError(f"commit failed: {result.error_text()}", result)
        return result

    def _staged_deletions(self) -> List[str]:
        res = self.run(["diff", "--cached", "--name-only", "-z", "--diff-filter=D"])
        return [p for p in res.stdout.split("\x00") if p]

    def head_sha(self, short: bool = False) -> Optional[str]:
        """SHA of HEAD."""
        args = ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]
        res = self.run(args)
        return res.stdout.strip() if res.ok else None

    def log(self, limit: int = 20, ref: Optional[str] = None, path: Optional[str] = None) -> List[CommitInfo]:
        """Commit history as structured records."""
        if not self.has_commits():
            return []
        fmt = FIELD_SEP.join(["%H", "%h", "%an", "%ae", "%aI", "%s"]) + RECORD_SEP
        args = ["log", f"--max-count={max(1, int(limit))}", f"--format={fmt}"]
        if ref:
            self._check_ref(ref)
            args.append(ref)
        if path:
            args += ["--", validate_path_arg(path)]
        res = self.run(args, check=True)
        commits = []
        for record in res.stdout.split(RECORD_SEP):
            fields = record.strip("\n").split(FIELD_SEP)
            if len(fields) == 6:
                commits.append(CommitInfo(*fields))
        return commits

    def diff(self, staged: bool = False, paths: Sequence[str] = (), stat: bool = False,
             ref_a: Optional[str] = None, ref_b: Optional[str] = None) -> str:
        """Unified diff (or ``--stat``) without colours."""
        args = ["diff", "--no-color", "--no-ext-diff"]
        if stat:
            args.append("--stat")
        if staged:
            args.append("--cached")
        for ref in (ref_a, ref_b):
            if ref:
                self._check_ref(ref)
                args.append(ref)
        if paths:
            args += ["--", *[validate_path_arg(p) for p in paths]]
        return self.run(args, check=True).stdout

    # -------------------------------------------------------------- branches
    def branches(self) -> List[BranchInfo]:
        """Local branches with upstream and short commit."""
        fmt = FIELD_SEP.join(["%(refname:short)", "%(HEAD)", "%(upstream:short)", "%(objectname:short)"])
        res = self.run(["for-each-ref", f"--format={fmt}", "refs/heads"], check=True)
        out: List[BranchInfo] = []
        for line in res.stdout.splitlines():
            parts = line.split(FIELD_SEP)
            if len(parts) == 4:
                out.append(BranchInfo(name=parts[0], is_current=parts[1] == "*", upstream=parts[2], commit=parts[3]))
        current = self.current_branch()
        if current and not any(b.name == current for b in out):
            out.append(BranchInfo(name=current, is_current=True))  # unborn branch
        return out

    def remote_branches(self) -> List[str]:
        """Remote-tracking branches (``origin/main``)."""
        res = self.run(["for-each-ref", "--format=%(refname:short)", "refs/remotes"], check=True)
        return [b for b in res.stdout.splitlines() if b and not b.endswith("/HEAD")]

    def create_branch(self, name: str, start_point: Optional[str] = None, switch: bool = False) -> GitResult:
        """Create a branch (optionally switching to it)."""
        name = validate_branch_name(name)
        if start_point:
            self._check_ref(start_point)
        if switch:
            args = ["checkout", "-b", name] + ([start_point] if start_point else [])
        else:
            args = ["branch", name] + ([start_point] if start_point else [])
        return self.run(args, check=True)

    def switch_branch(self, name: str) -> GitResult:
        """Switch branches. Git itself refuses if local changes would be lost."""
        name = validate_branch_name(name)
        return self.run(["checkout", name, "--"], check=True)

    def delete_branch(self, name: str) -> GitResult:
        """Delete a *fully merged* branch (``-d``, never ``-D``)."""
        name = validate_branch_name(name)
        return self.run(["branch", "-d", name], check=True)

    def branch_exists(self, name: str) -> bool:
        """True if a local branch named ``name`` exists."""
        name = validate_branch_name(name)
        return self.run(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"]).ok

    def rename_current_branch(self, new_name: str) -> GitResult:
        """Rename the current branch (``-m`` refuses to overwrite)."""
        return self.run(["branch", "-m", validate_branch_name(new_name)], check=True)

    # --------------------------------------------------------------- remotes
    def remotes(self) -> Dict[str, Dict[str, str]]:
        """Mapping ``name -> {"fetch": url, "push": url}`` (URLs redacted)."""
        res = self.run(["remote", "-v"])
        remotes: Dict[str, Dict[str, str]] = {}
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                kind = parts[2].strip("()")
                remotes.setdefault(parts[0], {})[kind] = redact(parts[1])
        return remotes

    def remote_url(self, name: str = "origin") -> Optional[str]:
        """Raw URL of a remote (not redacted; do not log)."""
        res = self.run(["remote", "get-url", validate_remote_name(name)])
        return res.stdout.strip() if res.ok else None

    def set_remote(self, name: str, url: str) -> GitResult:
        """Add the remote or update its URL if it already exists."""
        name = validate_remote_name(name)
        url = validate_remote_url(url)
        if name in self.remotes():
            return self.run(["remote", "set-url", name, url], check=True)
        return self.run(["remote", "add", name, url], check=True)

    def remove_remote(self, name: str) -> GitResult:
        """Remove a remote definition (does not touch the server)."""
        return self.run(["remote", "remove", validate_remote_name(name)], check=True)

    # --------------------------------------------------------------- network
    def fetch(self, remote: str = "origin", prune: bool = False, interactive_auth: bool = False) -> GitResult:
        """Fetch from a remote."""
        args = ["fetch", validate_remote_name(remote)]
        if prune:
            args.append("--prune")
        return self.run(args, timeout=self.network_timeout, interactive_auth=interactive_auth)

    def pull(self, remote: str = "origin", branch: Optional[str] = None, strategy: str = "ff-only",
             interactive_auth: bool = False) -> GitResult:
        """Pull with an explicit strategy: ``ff-only`` (default), ``merge`` or ``rebase``."""
        flags = {"ff-only": ["--ff-only"], "merge": ["--no-rebase", "--no-edit"], "rebase": ["--rebase"]}
        if strategy not in flags:
            raise ValidationError(f"unknown pull strategy: {strategy}")
        args = ["pull", *flags[strategy], validate_remote_name(remote)]
        if branch:
            args.append(validate_branch_name(branch))
        return self.run(args, timeout=self.network_timeout, interactive_auth=interactive_auth)

    def push(self, remote: str = "origin", branch: Optional[str] = None, set_upstream: bool = False,
             interactive_auth: bool = False) -> GitResult:
        """Push without any force option. Rejections are returned, never bypassed."""
        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        args.append(validate_remote_name(remote))
        if branch:
            args.append(validate_branch_name(branch))
        return self.run(args, timeout=self.network_timeout, interactive_auth=interactive_auth)

    def clone(self, url: str, destination: Path, branch: Optional[str] = None, depth: Optional[int] = None,
              interactive_auth: bool = False) -> GitResult:
        """Clone ``url`` into ``destination`` (which must not exist or be empty)."""
        url = validate_remote_url(url)
        args = ["clone"]
        if branch:
            args += ["--branch", validate_branch_name(branch)]
        if depth:
            args += ["--depth", str(int(depth))]
        args += ["--", url, str(destination)]
        return self.run(args, timeout=self.network_timeout, cwd=destination.parent, interactive_auth=interactive_auth)

    def ls_remote(self, remote: str = "origin") -> GitResult:
        """Check connectivity/authentication against a remote."""
        return self.run(["ls-remote", "--heads", validate_remote_name(remote)], timeout=self.network_timeout)

    # ------------------------------------------------------------- conflicts
    def conflicts(self) -> List[str]:
        """Paths with unresolved merge conflicts."""
        res = self.run(["diff", "--name-only", "-z", "--diff-filter=U"])
        return [p for p in res.stdout.split("\x00") if p]

    def operation_in_progress(self) -> Optional[str]:
        """Return ``merge``, ``rebase``, ``cherry-pick`` or ``revert`` if one is in progress."""
        res = self.run(["rev-parse", "--git-dir"])
        if not res.ok:
            return None
        git_dir = Path(res.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.cwd / git_dir
        markers = {"MERGE_HEAD": "merge", "rebase-merge": "rebase", "rebase-apply": "rebase",
                   "CHERRY_PICK_HEAD": "cherry-pick", "REVERT_HEAD": "revert"}
        for marker, name in markers.items():
            if (git_dir / marker).exists():
                return name
        return None

    def abort_operation(self, operation: str) -> GitResult:
        """Abort an in-progress merge/rebase/cherry-pick/revert (restores the pre-operation state)."""
        if operation not in ("merge", "rebase", "cherry-pick", "revert"):
            raise ValidationError(f"cannot abort: {operation}")
        return self.run([operation, "--abort"], check=True)

    # ------------------------------------------------------------- integrity
    def verify_integrity(self) -> GitResult:
        """Run ``git fsck --no-progress --connectivity-only``."""
        return self.run(["fsck", "--no-progress", "--connectivity-only"], timeout=self.network_timeout)

    # ---------------------------------------------------------------- config
    def get_config(self, key: str, global_scope: bool = False) -> Optional[str]:
        """Read a git config value."""
        args = ["config"] + (["--global"] if global_scope else []) + ["--get", key]
        res = self.run(args)
        return res.stdout.strip() if res.ok else None

    def set_config(self, key: str, value: str, global_scope: bool = False) -> GitResult:
        """Write a git config value (repository scope by default)."""
        if value.startswith("-"):
            raise ValidationError(f"invalid config value: {value!r}")
        args = ["config"] + (["--global"] if global_scope else []) + [key, value]
        return self.run(args, check=True)

    def stash_push(self, message: str) -> GitResult:
        """Save local changes (including untracked files) to the stash – non destructive."""
        return self.run(["stash", "push", "--include-untracked", "-m", message], check=True)

    def stash_pop(self) -> GitResult:
        """Re-apply the latest stash."""
        return self.run(["stash", "pop"])

    def bundle(self, destination: Path) -> GitResult:
        """Write a git bundle with all refs (complete history backup)."""
        return self.run(["bundle", "create", str(destination), "--all"], check=True, timeout=self.network_timeout)

    # --------------------------------------------------------------- helpers
    def _check_ref(self, ref: str) -> None:
        if not ref or ref.startswith("-") or any(c in ref for c in " \t\n\x00"):
            raise ValidationError(f"invalid revision: {ref!r}")

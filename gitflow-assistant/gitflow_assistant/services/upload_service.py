"""Publication workflows: first publish (``upload``) and ``update``.

Guarantees: changes are always shown before staging, staged content is
scanned for secrets before committing, empty commits are never created, and
remote conflicts are never bypassed with force pushes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from gitflow_assistant.core.commit_manager import CommitManager, CommitOutcome, build_conventional
from gitflow_assistant.core.git_engine import FileStatus, GitEngine, GitError
from gitflow_assistant.core.github_client import GitHubAuthError, GitHubError, web_url_for_remote
from gitflow_assistant.core.security_scanner import ScanReport
from gitflow_assistant.core.sync_manager import SyncManager, SyncOutcome
from gitflow_assistant.i18n import t
from gitflow_assistant.security.secret_detector import CONFIRMED
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.errors import Cancelled, ProjectRequired, RemoteOperationFailed, SecurityBlocked, UsageError
from gitflow_assistant.utils.templates import COMMIT_TEMPLATES
from gitflow_assistant.utils.validators import commit_message_warning, validate_repo_name


@dataclass
class PublishOptions:
    """Options shared by ``upload``, ``update`` and ``commit``."""

    message: Optional[str] = None
    paths: Optional[List[str]] = None
    all_files: bool = False
    remote_url: Optional[str] = None
    create_github: bool = False
    repo_name: Optional[str] = None
    private: Optional[bool] = None
    description: str = ""
    use_ssh: bool = False
    strategy: Optional[str] = None
    accept_findings: bool = False
    push: bool = True
    ai: bool = False


@dataclass
class PublishResult:
    """Outcome of a publication workflow."""

    commit: Optional[CommitOutcome] = None
    pushed: bool = False
    url: Optional[str] = None
    notes: List[str] = field(default_factory=list)


# ----------------------------------------------------------------- helpers
def describe_status(entry: FileStatus) -> str:
    """Translate a porcelain code to a short label."""
    if entry.is_untracked:
        return t("status.untracked")
    if entry.is_conflicted:
        return t("status.conflict")
    code = entry.index if entry.index not in (" ", "?") else entry.worktree
    return {"M": t("status.modified"), "A": t("status.added"), "D": t("status.deleted"),
            "R": t("status.renamed"), "C": t("status.copied"), "T": t("status.modified")}.get(code, code)


def render_findings(ctx: AppContext, report: ScanReport) -> None:
    """Show review-worthy findings as a table."""
    rows = [[t(f"cat.{f.category}"), f.path, str(f.line or "-"), f.description, f.excerpt] for f in report.review_needed]
    if rows:
        ctx.ui.table(t("scan.findings"), [t("col.category"), t("col.file"), t("col.line"), t("col.reason"),
                                          t("col.excerpt")], rows)
    ctx.ui.info(t("scan.disclaimer"))


def select_changes(ctx: AppContext, engine: GitEngine, opts: PublishOptions) -> List[str]:
    """Show pending changes and return the paths chosen by the user."""
    status = engine.status()
    if status.conflicted:
        raise GitError(t("err.conflicts", files=", ".join(f.path for f in status.conflicted)))
    candidates = [f for f in status.files if not f.is_ignored]
    if not candidates:
        return []
    ctx.ui.table(t("publish.changes"), [t("col.n"), t("col.state"), t("col.file")],
                 [[str(i + 1), describe_status(f) + (" *" if f.is_staged else ""), f.path]
                  for i, f in enumerate(candidates)])
    paths = [f.path for f in candidates]
    if opts.paths:
        selected = []
        for requested in opts.paths:
            norm = requested.replace("\\", "/").rstrip("/")
            matched = [p for p in paths if p == norm or p.startswith(norm + "/") or norm in (".", "")]
            if not matched:
                raise UsageError(t("err.path_not_changed", path=requested))
            selected += [m for m in matched if m not in selected]
    elif opts.all_files:
        selected = paths
    elif ctx.ui.interactive:
        indexes = ctx.ui.select_many(t("publish.select_files"), paths, default_all=True)
        selected = [paths[i] for i in indexes]
    else:
        raise UsageError(t("err.need_selection"))
    # keep the index consistent with the selection: unstage deselected staged files (working tree untouched)
    deselected_staged = [f.path for f in candidates if f.is_staged and f.path not in selected]
    if deselected_staged:
        engine.unstage(deselected_staged)
    return selected


def review_staged(ctx: AppContext, engine: GitEngine, opts: PublishOptions) -> None:
    """Scan staged content and let the user resolve every finding."""
    with ctx.ui.progress(t("scan.running")):
        report = ctx.scanner().scan_staged(engine)
    if report.is_clean:
        ctx.ui.success(t("scan.clean", count=report.scanned))
        return
    render_findings(ctx, report)
    block_secrets = bool(ctx.config.get("security.block_secrets", True))
    if not ctx.ui.interactive:
        if opts.accept_findings and not (report.secrets and block_secrets):
            ctx.ui.warning(t("scan.accepted_noninteractive"))
            return
        if opts.accept_findings and report.secrets and block_secrets:
            raise SecurityBlocked(t("scan.blocked_secrets"))
        raise SecurityBlocked(t("scan.blocked_review"))
    options = [t("scan.opt_exclude"), t("scan.opt_false_positive"), t("scan.opt_keep"), t("scan.opt_cancel")]
    for path in report.flagged_paths:
        findings = [f for f in report.review_needed if f.path == path]
        is_secret = any(f.category == CONFIRMED for f in findings)
        choice = ctx.ui.choose(t("scan.decide", path=path), options, default=0)
        if choice == 0:
            engine.unstage([path])
            ctx.ui.info(t("scan.excluded", path=path))
        elif choice == 1:
            for finding in findings:
                ctx.config.append_unique("security.false_positives", finding.fingerprint)
            ctx.config.save()
            ctx.ui.info(t("scan.marked_fp", path=path))
        elif choice == 2:
            if is_secret and block_secrets and not ctx.ui.confirm_risky(
                    t("scan.keep_secret", path=path), [t("scan.keep_secret_c1"), t("scan.keep_secret_c2")]):
                engine.unstage([path])
                ctx.ui.info(t("scan.excluded", path=path))
        else:
            raise SecurityBlocked(t("common.cancelled"))


def _ai(ctx: AppContext):  # type: ignore[no-untyped-def]
    from gitflow_assistant.services.ai_service import AIAssistant
    return AIAssistant(ctx)


def ai_suggest_message(ctx: AppContext, engine: GitEngine, ask_consent: bool = True) -> Optional[str]:
    """Get a Gemini suggestion for the staged diff; None if the user writes it manually or AI fails."""
    from gitflow_assistant.core.gemini_client import GeminiError
    try:
        suggestion = _ai(ctx).suggest_commit_message(engine.diff(staged=True), ask_consent=ask_consent)
    except GeminiError as exc:
        ctx.ui.warning(t("ai.failed", error=str(exc)))
        return None
    ctx.ui.info(t("ai.suggestion", message=suggestion))
    if not ctx.ui.interactive:
        return suggestion
    choice = ctx.ui.choose(t("ai.use_question"), [t("ai.opt_use"), t("ai.opt_edit"), t("ai.opt_manual")], 0)
    if choice == 0:
        return suggestion
    if choice == 1:
        return ctx.ui.ask(t("commit.message"), suggestion)
    return None


def ai_summary_step(ctx: AppContext, engine: GitEngine) -> None:
    """Offer a plain-language summary of the staged changes before committing."""
    from gitflow_assistant.core.gemini_client import GeminiError
    if not (ctx.ui.interactive and ctx.config.get("ai.summary_before_commit", True) and _ai(ctx).available()):
        return
    if not ctx.ui.confirm(t("ai.offer_summary"), False):
        return
    try:
        summary = _ai(ctx).summarize(engine.diff(staged=True), ask_consent=False)
    except GeminiError as exc:
        ctx.ui.warning(t("ai.failed", error=str(exc)))
        return
    ctx.ui.heading(t("ai.summary_title"))
    ctx.ui.text_block(summary, "markdown")


def ask_message(ctx: AppContext, opts: PublishOptions, engine: Optional[GitEngine] = None) -> str:
    """Return the commit message from options, from Gemini, or ask for it."""
    if opts.message and opts.message.strip():
        return opts.message.strip()
    if opts.ai and engine is not None:
        suggestion = ai_suggest_message(ctx, engine)
        if suggestion:
            return suggestion
    if not ctx.ui.interactive:
        raise UsageError(t("err.need_message"))
    default = str(ctx.config.get("commit.default_message") or "")
    ai_ready = engine is not None and not opts.ai and _ai(ctx).available()
    if ctx.config.get("commit.style") == "conventional":
        kinds = list(COMMIT_TEMPLATES)
        extra = [t("ai.opt_suggest")] if ai_ready else []
        choice = ctx.ui.choose(t("commit.type"), extra + kinds + [t("commit.free")], default=0)
        if ai_ready and choice == 0:
            assert engine is not None
            suggestion = ai_suggest_message(ctx, engine)
            if suggestion:
                return suggestion
            return ctx.ui.ask(t("commit.message"), default)
        choice -= len(extra)
        if choice < len(kinds):
            description = ctx.ui.ask(t("commit.description"), default)
            scope = ctx.ui.ask(t("commit.scope"), "")
            return build_conventional(kinds[choice], description, scope)
    elif ai_ready and ctx.ui.confirm(t("ai.offer_suggest"), True):
        assert engine is not None
        suggestion = ai_suggest_message(ctx, engine)
        if suggestion:
            return suggestion
    return ctx.ui.ask(t("commit.message"), default)


def commit_step(ctx: AppContext, engine: GitEngine, opts: PublishOptions) -> Optional[CommitOutcome]:
    """Select, stage, scan and commit. Returns None when there is nothing to commit."""
    manager = CommitManager(engine)
    identity = manager.ensure_identity()
    if identity:
        raise GitError(t("err.identity"))
    previously_staged = set(engine.staged_files())
    selected = select_changes(ctx, engine, opts)
    if not selected:
        ctx.ui.info(t("publish.no_changes"))
        return None
    engine.add(selected)
    try:
        review_staged(ctx, engine, opts)
        staged_now = [p for p in engine.run(["diff", "--cached", "--name-only", "-z"]).stdout.split("\x00") if p]
        if not staged_now:
            ctx.ui.info(t("publish.no_changes"))
            return None
        ai_summary_step(ctx, engine)
        message = ask_message(ctx, opts, engine)
        warning = commit_message_warning(message, int(ctx.config.get("commit.max_subject_length", 72)))
        if warning:
            ctx.ui.warning(warning)
        if not ctx.ui.confirm(t("commit.confirm", count=len(staged_now), message=message.splitlines()[0])):
            raise Cancelled(t("common.cancelled"))
        outcome = manager.commit(message)
    except BaseException:
        # restore the index for files GitFlow staged in this run (working tree untouched)
        restore = [p for p in selected if p not in previously_staged]
        if restore:
            try:
                engine.unstage(restore)
            except GitError:
                ctx.ui.warning(t("commit.unstage_failed"))
        raise
    ctx.ui.success(t("commit.created", sha=outcome.short_sha, count=len(outcome.files)))
    return outcome


def explain_failure(ctx: AppContext, outcome: SyncOutcome) -> None:
    """Print a human explanation and next steps for a failed sync."""
    ctx.ui.error(outcome.message)
    hints = {
        "auth": [t("hint.auth1"), t("hint.auth2"), t("hint.auth3")],
        "network": [t("hint.net1"), t("hint.net2")],
        "rejected": [t("hint.rej1"), t("hint.rej2")],
        "conflict": [t("hint.conf1"), t("hint.conf2")],
    }.get(outcome.kind, [])
    for hint in hints:
        ctx.ui.info("  • " + hint)
    if outcome.backup_branch:
        ctx.ui.info(t("sync.backup_kept", branch=outcome.backup_branch))


def create_github_repo(ctx: AppContext, engine: GitEngine, opts: PublishOptions) -> str:
    """Create a GitHub repository and return its clone URL."""
    name = opts.repo_name or (engine.root() or engine.cwd).name
    if ctx.ui.interactive and not opts.repo_name:
        name = ctx.ui.ask(t("github.repo_name"), name)
    name = validate_repo_name(name)
    private = opts.private
    if private is None:
        private = bool(ctx.config.get("github.default_private", False))
        if ctx.ui.interactive:
            private = ctx.ui.choose(t("github.visibility"), [t("github.public"), t("github.private")],
                                    1 if private else 0) == 1
    description = opts.description
    if ctx.ui.interactive and not description:
        description = ctx.ui.ask(t("github.description"), "")
    try:
        client = ctx.github()
        with ctx.ui.progress(t("github.creating", name=name)):
            repo = client.create_repo(name, private=private, description=description)
    except GitHubAuthError as exc:
        raise RemoteOperationFailed(f"{exc}\n{t('hint.auth1')}\n{t('hint.auth3')}") from exc
    except GitHubError as exc:
        raise RemoteOperationFailed(str(exc)) from exc
    ctx.ui.success(t("github.created", url=repo.html_url))
    return repo.ssh_url if opts.use_ssh else repo.clone_url


def ensure_remote(ctx: AppContext, engine: GitEngine, opts: PublishOptions) -> Optional[str]:
    """Make sure the default remote exists; returns its name or None to skip pushing."""
    remote = ctx.remote_name
    if remote in engine.remotes() and not opts.remote_url:
        return remote
    url = opts.remote_url
    if not url and opts.create_github:
        url = create_github_repo(ctx, engine, opts)
    if not url:
        if not ctx.ui.interactive:
            raise UsageError(t("err.need_remote"))
        choice = ctx.ui.choose(t("publish.remote_question"),
                               [t("publish.remote_url"), t("publish.remote_create"), t("publish.remote_skip")], 0)
        if choice == 2:
            return None
        url = create_github_repo(ctx, engine, opts) if choice == 1 else ctx.ui.ask(t("publish.remote_enter"))
    engine.set_remote(remote, url)
    ctx.ui.success(t("publish.remote_set", name=remote))
    return remote


def push_with_recovery(ctx: AppContext, engine: GitEngine, sync: SyncManager) -> SyncOutcome:
    """Push; if rejected, offer to integrate remote changes (never force)."""
    with ctx.ui.progress(t("sync.pushing")):
        outcome = sync.push()
    if outcome.ok or outcome.kind != "rejected" or not ctx.ui.interactive:
        return outcome
    ctx.ui.warning(t("sync.rejected_explain"))
    choice = ctx.ui.choose(t("sync.rejected_question"), [t("sync.opt_merge"), t("sync.opt_rebase"), t("common.cancel")], 0)
    if choice == 2:
        return outcome
    strategy = "merge" if choice == 0 else "rebase"
    with ctx.ui.progress(t("sync.pulling")):
        pulled = sync.pull(strategy)
        if not pulled.ok and "unrelated histories" in pulled.message.lower():
            if ctx.ui.confirm(t("sync.unrelated"), False):
                pulled = sync.pull("merge", allow_unrelated=True)
    if not pulled.ok:
        return pulled
    with ctx.ui.progress(t("sync.pushing")):
        return sync.push()


def _finish(ctx: AppContext, engine: GitEngine, operation: str, result: PublishResult, success: bool,
            detail: str) -> PublishResult:
    ctx.history.record(operation, engine.root() or engine.cwd, success, detail)
    return result


# ---------------------------------------------------------------- workflows
def publish(ctx: AppContext, path: Path, opts: PublishOptions) -> PublishResult:
    """First publication of a project (init → review → commit → remote → push)."""
    engine = ctx.engine(path)
    if not engine.is_installed():
        raise GitError(t("err.git_missing"))
    if not path.is_dir():
        raise ProjectRequired(t("err.not_dir", path=str(path)))
    if not engine.is_repository():
        if not ctx.ui.confirm(t("publish.init_question", path=str(path))):
            raise Cancelled(t("common.cancelled"))
        engine.init(str(ctx.config.get("default_branch", "main")))
        ctx.ui.success(t("publish.initialized", branch=ctx.config.get("default_branch", "main")))
    engine.cwd = engine.root() or path
    ctx.repos.add(engine.cwd)
    if not (engine.cwd / ".gitignore").exists():
        ctx.ui.warning(t("publish.no_gitignore"))
    result = PublishResult()
    result.commit = commit_step(ctx, engine, opts)
    if not engine.has_commits():
        raise UsageError(t("publish.nothing"))
    if not opts.push:
        return _finish(ctx, engine, "upload", result, True, "commit only")
    remote = ensure_remote(ctx, engine, opts)
    if not remote:
        result.notes.append(t("publish.local_only"))
        return _finish(ctx, engine, "upload", result, True, "local only")
    sync = SyncManager(engine, remote, interactive_auth=ctx.ui.interactive)
    outcome = push_with_recovery(ctx, engine, sync)
    if not outcome.ok:
        explain_failure(ctx, outcome)
        _finish(ctx, engine, "upload", result, False, outcome.message)
        raise RemoteOperationFailed(t("sync.push_failed"))
    result.pushed = True
    raw_url = engine.remote_url(remote) or ""
    result.url = web_url_for_remote(raw_url) or engine.remotes().get(remote, {}).get("push")
    ctx.ui.success(t("publish.done", url=result.url or remote))
    return _finish(ctx, engine, "upload", result, True, result.url or "")


def update(ctx: AppContext, opts: PublishOptions) -> PublishResult:
    """Update an already published project (fetch → commit → integrate → push)."""
    engine = ctx.require_repo()
    op = engine.operation_in_progress()
    if op:
        raise GitError(t("err.op_in_progress", op=op))
    if ctx.remote_name not in engine.remotes():
        ctx.ui.warning(t("update.no_remote"))
        return publish(ctx, engine.cwd, opts)
    ctx.repos.add(engine.cwd)
    sync = SyncManager(engine, ctx.remote_name, interactive_auth=ctx.ui.interactive)
    with ctx.ui.progress(t("sync.fetching")):
        state = sync.analyze(fetch=True)
    offline = bool(state.fetch_error)
    if offline:
        ctx.ui.warning(t("sync.fetch_failed", error=state.fetch_error or ""))
    status = engine.status()
    ctx.ui.table(t("update.summary"), [t("col.item"), t("col.value")], [
        [t("col.branch"), state.branch or "-"], [t("col.upstream"), state.upstream or "-"],
        [t("col.ahead"), str(state.ahead)], [t("col.behind"), str(state.behind)],
        [t("col.local_changes"), str(len([f for f in status.files if not f.is_ignored]))],
    ])
    result = PublishResult()
    if not status.is_clean:
        result.commit = commit_step(ctx, engine, opts)
    if offline:
        result.notes.append(t("update.offline_note"))
        return _finish(ctx, engine, "update", result, True, "offline: local commit only")
    state = sync.analyze(fetch=False)
    if state.behind:
        stashed = False
        if not engine.status().is_clean:
            if not ctx.ui.confirm(t("update.stash_question")):
                raise Cancelled(t("common.cancelled"))
            engine.stash_push("gitflow: auto-stash before update")
            stashed = True
        strategy = "ff-only"
        if state.diverged:
            ctx.ui.warning(t("update.diverged", ahead=state.ahead, behind=state.behind))
            strategy = opts.strategy or ""
            if not strategy:
                if not ctx.ui.interactive:
                    raise UsageError(t("err.need_strategy"))
                choice = ctx.ui.choose(t("sync.rejected_question"),
                                       [t("sync.opt_merge"), t("sync.opt_rebase"), t("common.cancel")], 0)
                if choice == 2:
                    raise Cancelled(t("common.cancelled"))
                strategy = "merge" if choice == 0 else "rebase"
        with ctx.ui.progress(t("sync.pulling")):
            pulled = sync.pull(strategy)
        if stashed and pulled.ok:
            pop = engine.stash_pop()
            if not pop.ok:
                ctx.ui.warning(t("update.stash_pop_failed"))
        elif stashed:
            ctx.ui.warning(t("update.stash_kept"))
        if not pulled.ok:
            explain_failure(ctx, pulled)
            _finish(ctx, engine, "update", result, False, pulled.message)
            raise RemoteOperationFailed(t("sync.pull_failed"))
        ctx.ui.success(t("sync.pulled"))
    state = sync.analyze(fetch=False)
    if state.ahead or not state.upstream:
        if opts.push:
            outcome = push_with_recovery(ctx, engine, sync)
            if not outcome.ok:
                explain_failure(ctx, outcome)
                _finish(ctx, engine, "update", result, False, outcome.message)
                raise RemoteOperationFailed(t("sync.push_failed"))
            result.pushed = True
    final = sync.analyze(fetch=False)
    if final.up_to_date:
        ctx.ui.success(t("update.done"))
    else:
        ctx.ui.warning(t("update.partial", ahead=final.ahead, behind=final.behind))
    result.url = web_url_for_remote(engine.remote_url(ctx.remote_name) or "")
    return _finish(ctx, engine, "update", result, final.up_to_date, f"ahead={final.ahead} behind={final.behind}")

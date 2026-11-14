"""Command handlers shared by the CLI and the TUI.

Each handler receives the :class:`AppContext` and parsed arguments and returns
a process exit code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from gitflow_assistant.core.commit_manager import build_conventional
from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.core.github_client import GitHubClient, GitHubError, parse_github_remote
from gitflow_assistant.core.project_detector import ProjectInfo, detect_project, find_repositories
from gitflow_assistant.core.security_scanner import IGNORED
from gitflow_assistant.core.sync_manager import SyncManager
from gitflow_assistant.i18n import t
from gitflow_assistant.interface.prompts import ConsoleUI
from gitflow_assistant.security.credential_manager import CredentialStorageUnavailable, mask_token
from gitflow_assistant.services import backup_service, branch_service, clone_service, doctor_service
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.errors import Cancelled, ProjectRequired, RemoteOperationFailed, UsageError
from gitflow_assistant.services.history_service import compare
from gitflow_assistant.services.upload_service import (
    PublishOptions,
    commit_step,
    describe_status,
    explain_failure,
    publish,
    render_findings,
    update,
)
from gitflow_assistant.utils.os_detector import detect_platform
from gitflow_assistant.utils.path_manager import normalize, termux_storage_candidates
from gitflow_assistant.utils.templates import build_gitignore, build_readme, detect_languages, merge_gitignore

Handler = Callable[[AppContext, argparse.Namespace], int]


def _ui(ctx: AppContext) -> ConsoleUI:
    assert isinstance(ctx.ui, ConsoleUI)
    return ctx.ui


def _json(ctx: AppContext) -> bool:
    return _ui(ctx).out.json_mode


def _opts(args: argparse.Namespace) -> PublishOptions:
    return PublishOptions(
        message=getattr(args, "message", None), paths=getattr(args, "files", None),
        all_files=bool(getattr(args, "all_files", False)), remote_url=getattr(args, "remote_url", None),
        create_github=bool(getattr(args, "create_github", False)), repo_name=getattr(args, "repo_name", None),
        private=getattr(args, "private", None), description=getattr(args, "description", "") or "",
        use_ssh=bool(getattr(args, "ssh", False)), strategy=getattr(args, "strategy", None),
        accept_findings=bool(getattr(args, "accept_findings", False)), push=not getattr(args, "no_push", False),
        ai=bool(getattr(args, "ai", False)))


def project_rows(info: ProjectInfo) -> List[List[str]]:
    """Key/value rows describing a project."""
    return [[t("col.project"), info.name], [t("col.path"), str(info.path)],
            [t("col.state"), t(f"state.{info.state}")], [t("col.branch"), info.branch or "-"],
            [t("col.remote"), info.remote_url or "-"], [t("col.upstream"), info.upstream or "-"],
            [t("col.ahead"), str(info.ahead)], [t("col.behind"), str(info.behind)],
            [t("col.staged"), str(info.staged)], [t("col.unstaged"), str(info.unstaged)],
            [t("col.untracked"), str(info.untracked)],
            [t("col.conflicts"), ", ".join(info.conflicts) or (info.operation or "0")]]


def _project_json(info: ProjectInfo) -> Dict[str, object]:
    return {"name": info.name, "path": str(info.path), "state": info.state, "branch": info.branch,
            "remote": info.remote_url, "upstream": info.upstream, "ahead": info.ahead, "behind": info.behind,
            "staged": info.staged, "unstaged": info.unstaged, "untracked": info.untracked,
            "conflicts": info.conflicts, "operation": info.operation}


# ------------------------------------------------------------------ project
def cmd_init(ctx: AppContext, args: argparse.Namespace) -> int:
    path = normalize(args.path) if args.path else (ctx.project_override or Path.cwd())
    path = Path(path).resolve()
    if not path.is_dir():
        if not ctx.ui.confirm(t("init.create_dir", path=str(path))):
            raise Cancelled(t("common.cancelled"))
        path.mkdir(parents=True)
    engine = ctx.engine(path)
    if engine.is_repository():
        ctx.ui.info(t("init.already", path=str(engine.root())))
        ctx.repos.add(engine.root() or path)
        return 0
    branch = args.branch or str(ctx.config.get("default_branch", "main"))
    if not ctx.ui.confirm(t("publish.init_question", path=str(path))):
        raise Cancelled(t("common.cancelled"))
    engine.init(branch)
    ctx.repos.add(path)
    ctx.history.record("init", path, True, branch)
    ctx.ui.success(t("publish.initialized", branch=branch))
    if args.gitignore and not (path / ".gitignore").exists():
        (path / ".gitignore").write_text(build_gitignore(detect_languages(path)), encoding="utf-8")
        ctx.ui.success(t("gitignore.written", path=str(path / ".gitignore")))
    return 0


def cmd_status(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    if args.fetch and ctx.remote_name in engine.remotes():
        with ctx.ui.progress(t("sync.fetching")):
            res = engine.fetch(ctx.remote_name)
        if not res.ok:
            ctx.ui.warning(t("sync.fetch_failed", error=res.error_text()))
    info = detect_project(engine.cwd, engine)
    status = engine.status()
    if _json(ctx):
        data = _project_json(info)
        data["files"] = [{"path": f.path, "code": f.code} for f in status.files]
        _ui(ctx).out.emit_json(data)
        return 0
    ctx.ui.table(t("status.title"), [t("col.item"), t("col.value")], project_rows(info))
    rows = [[f.code.replace(" ", "."), describe_status(f), f.path] for f in status.files if not f.is_ignored]
    if rows:
        ctx.ui.table(t("publish.changes"), [t("col.code"), t("col.state"), t("col.file")], rows)
    else:
        ctx.ui.success(t("status.clean"))
    return 0


def _scan_bases(ctx: AppContext, dirs: List[str]) -> List[Path]:
    if dirs:
        return [normalize(d) for d in dirs]
    configured = ctx.config.get("projects_dir")
    if configured:
        return [normalize(str(configured))]
    if detect_platform().is_termux:
        return termux_storage_candidates()
    return [Path.cwd()]


def cmd_projects(ctx: AppContext, args: argparse.Namespace) -> int:
    action = args.action or "list"
    if action == "add":
        path = normalize(args.path)
        if not path.is_dir():
            raise UsageError(t("err.not_dir", path=str(path)))
        ctx.repos.add(path)
        ctx.ui.success(t("projects.added", path=str(path)))
        return 0
    if action == "remove":
        removed = ctx.repos.remove(normalize(args.path))
        (ctx.ui.success if removed else ctx.ui.warning)(t("projects.removed" if removed else "projects.unknown",
                                                          path=args.path))
        return 0 if removed else 1
    if action == "prune":
        ctx.ui.success(t("projects.pruned", count=ctx.repos.prune_missing()))
        return 0
    if action == "scan":
        depth = args.depth if args.depth is not None else int(ctx.config.get("scan.max_depth", 3))
        bases = _scan_bases(ctx, args.dirs)
        with ctx.ui.progress(t("projects.scanning", dirs=", ".join(map(str, bases)), depth=depth)):
            found = find_repositories(bases, depth, int(ctx.config.get("scan.max_directories", 5000)))
        if args.add:
            for repo in found:
                ctx.repos.add(repo)
        if _json(ctx):
            _ui(ctx).out.emit_json([str(p) for p in found])
        elif found:
            ctx.ui.table(t("projects.found", count=len(found)), [t("col.n"), t("col.path")],
                         [[str(i + 1), str(p)] for i, p in enumerate(found)])
        else:
            ctx.ui.warning(t("projects.none_found"))
        return 0
    recents = ctx.repos.list()
    infos = [detect_project(Path(p.path)) for p in recents]
    if _json(ctx):
        _ui(ctx).out.emit_json([_project_json(i) for i in infos])
        return 0
    if not infos:
        ctx.ui.info(t("projects.empty"))
        return 0
    current = ctx.project_path()
    ctx.ui.table(t("projects.title"), [t("col.n"), t("col.project"), t("col.state"), t("col.branch"),
                                       t("col.pending"), t("col.path")],
                 [[("*" if current and i.path == current else "") + str(n + 1), i.name, t(f"state.{i.state}"),
                   i.branch or "-", str(i.pending), str(i.path)] for n, i in enumerate(infos)])
    return 0


def cmd_select(ctx: AppContext, args: argparse.Namespace) -> int:
    raw: Optional[str] = args.path
    if not raw:
        recents = ctx.repos.list()
        options = [f"{p.name}  ({p.path})" for p in recents] + [t("select.enter_path")]
        choice = ctx.ui.choose(t("select.question"), options, 0)
        raw = recents[choice].path if choice < len(recents) else ctx.ui.ask(t("select.path"), str(Path.cwd()))
    path = normalize(raw)
    if not path.is_dir():
        raise UsageError(t("err.not_dir", path=str(path)))
    engine = ctx.engine(path)
    root = engine.root() if engine.is_repository() else None
    ctx.repos.add(root or path)
    ctx.ui.success(t("select.done", path=str(root or path)))
    if not root:
        ctx.ui.warning(t("select.not_git"))
    return 0


# ------------------------------------------------------------- publication
def _publication_report(ctx: AppContext, result) -> int:  # type: ignore[no-untyped-def]
    for note in result.notes:
        ctx.ui.info(note)
    if _json(ctx):
        _ui(ctx).out.emit_json({"commit": result.commit.short_sha if result.commit else None,
                                "pushed": result.pushed, "url": result.url, "notes": result.notes})
    return 0


def _upload_target(ctx: AppContext, args: argparse.Namespace) -> Path:
    """Explicit path > -C > current repository > ask (current folder vs last selected) > current folder."""
    if args.path:
        return normalize(args.path)
    if ctx.project_override:
        return ctx.project_override.expanduser().resolve()
    cwd = Path.cwd()
    if ctx.engine(cwd).is_repository():
        return cwd
    selected = ctx.repos.current()
    if selected and selected != cwd.resolve() and ctx.ui.interactive:
        choice = ctx.ui.choose(t("upload.which_project"), [t("upload.this_folder", path=str(cwd)),
                                                          t("upload.selected_project", path=str(selected))], 0)
        return selected if choice == 1 else cwd
    return cwd


def cmd_upload(ctx: AppContext, args: argparse.Namespace) -> int:
    return _publication_report(ctx, publish(ctx, _upload_target(ctx, args), _opts(args)))


def cmd_update(ctx: AppContext, args: argparse.Namespace) -> int:
    return _publication_report(ctx, update(ctx, _opts(args)))


def cmd_clone(ctx: AppContext, args: argparse.Namespace) -> int:
    dest = normalize(args.destination) if args.destination else None
    path = clone_service.clone(ctx, args.url, dest, branch=args.branch, depth=args.depth)
    if _json(ctx):
        _ui(ctx).out.emit_json({"path": str(path)})
    return 0


def cmd_commit(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    opts = _opts(args)
    if args.kind:
        opts.message = build_conventional(args.kind, opts.message or "", args.scope) if opts.message else None
        if not opts.message:
            raise UsageError(t("err.need_message"))
    outcome = commit_step(ctx, engine, opts)
    if outcome:
        ctx.history.record("commit", engine.cwd, True, f"{outcome.short_sha} {outcome.message.splitlines()[0]}")
    if _json(ctx):
        _ui(ctx).out.emit_json({"commit": outcome.sha if outcome else None, "files": outcome.files if outcome else []})
    return 0


def cmd_push(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    if ctx.remote_name not in engine.remotes():
        raise UsageError(t("err.need_remote"))
    sync = SyncManager(engine, ctx.remote_name, interactive_auth=ctx.ui.interactive)
    with ctx.ui.progress(t("sync.pushing")):
        outcome = sync.push()
    ctx.history.record("push", engine.cwd, outcome.ok, outcome.message)
    if not outcome.ok:
        explain_failure(ctx, outcome)
        raise RemoteOperationFailed(t("sync.push_failed"))
    ctx.ui.success(t("sync.pushed"))
    return 0


def cmd_pull(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    if ctx.remote_name not in engine.remotes():
        raise UsageError(t("err.need_remote"))
    sync = SyncManager(engine, ctx.remote_name, interactive_auth=ctx.ui.interactive)
    strategy = args.strategy or "ff-only"
    with ctx.ui.progress(t("sync.pulling")):
        outcome = sync.pull(strategy)
    if not outcome.ok and outcome.kind == "rejected" and not args.strategy and ctx.ui.interactive:
        ctx.ui.warning(t("sync.diverged_pull"))
        choice = ctx.ui.choose(t("sync.rejected_question"), [t("sync.opt_merge"), t("sync.opt_rebase"),
                                                            t("common.cancel")], 0)
        if choice == 2:
            raise Cancelled(t("common.cancelled"))
        with ctx.ui.progress(t("sync.pulling")):
            outcome = sync.pull("merge" if choice == 0 else "rebase")
    ctx.history.record("pull", engine.cwd, outcome.ok, outcome.message)
    if not outcome.ok:
        explain_failure(ctx, outcome)
        raise RemoteOperationFailed(t("sync.pull_failed"))
    ctx.ui.success(t("sync.pulled"))
    if outcome.backup_branch:
        ctx.ui.info(t("sync.backup_kept", branch=outcome.backup_branch))
    return 0


def cmd_abort(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    op = engine.operation_in_progress()
    if not op:
        ctx.ui.info(t("abort.nothing"))
        return 0
    if not ctx.ui.confirm(t("abort.question", op=op)):
        raise Cancelled(t("common.cancelled"))
    outcome = SyncManager(engine, ctx.remote_name).abort()
    if not outcome.ok:
        ctx.ui.error(outcome.message)
        return 1
    ctx.ui.success(t("abort.done", op=op))
    return 0


# ------------------------------------------------------------ branches/log
def cmd_branch(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    action = args.action or "list"
    if action == "create":
        branch_service.create(ctx, engine, args.name, args.start_point, args.switch)
    elif action == "switch":
        branch_service.switch(ctx, engine, args.name, args.stash)
    elif action == "delete":
        branch_service.delete(ctx, engine, args.name)
    elif action == "rename":
        branch_service.rename(ctx, engine, args.new_name)
    else:
        branches = branch_service.list_branches(engine)
        if _json(ctx):
            _ui(ctx).out.emit_json([b.__dict__ for b in branches] + [{"remote": r} for r in engine.remote_branches()])
            return 0
        ctx.ui.table(t("branch.title"), ["", t("col.branch"), t("col.upstream"), t("col.commit")],
                     [["*" if b.is_current else "", b.name, b.upstream or "-", b.commit or "-"] for b in branches])
        remote = engine.remote_branches()
        if remote:
            ctx.ui.info(t("branch.remote_list", branches=", ".join(remote)))
    return 0


def cmd_history(ctx: AppContext, args: argparse.Namespace) -> int:
    action = args.action or "log"
    if action in ("ops", "publications"):
        records = ctx.history.publications(args.limit) if action == "publications" else ctx.history.list(args.limit)
        if _json(ctx):
            _ui(ctx).out.emit_json([r.__dict__ for r in records])
        elif records:
            ctx.ui.table(t("history.ops_title"), [t("col.date"), t("col.operation"), t("col.result"),
                                                  t("col.project"), t("col.detail")],
                         [[r.when, r.operation, "OK" if r.success else "FAIL", Path(r.project).name, r.detail[:60]]
                          for r in records])
        else:
            ctx.ui.info(t("history.empty"))
        return 0
    engine = ctx.require_repo()
    commits = engine.log(args.limit, ref=getattr(args, "ref", None), path=getattr(args, "file", None))
    if _json(ctx):
        _ui(ctx).out.emit_json([c.__dict__ for c in commits])
    elif commits:
        ctx.ui.table(t("history.log_title"), [t("col.commit"), t("col.date"), t("col.author"), t("col.message")],
                     [[c.short_sha, c.date[:16].replace("T", " "), c.author, c.subject] for c in commits])
    else:
        ctx.ui.info(t("history.no_commits"))
    return 0


def cmd_diff(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    refs = args.refs or []
    if len(refs) > 2:
        raise UsageError(t("diff.too_many"))
    if len(refs) == 2:
        text = compare(engine, refs[0], refs[1], args.stat)
    else:
        text = engine.diff(staged=args.staged, paths=args.files or (), stat=args.stat,
                           ref_a=refs[0] if refs else None)
    if not text.strip():
        ctx.ui.info(t("diff.empty"))
        return 0
    ctx.ui.text_block(text, "" if args.stat else "diff")
    return 0


# ---------------------------------------------------------------- security
def cmd_scan(ctx: AppContext, args: argparse.Namespace) -> int:
    if args.mark_false_positive:
        for fp in args.mark_false_positive:
            ctx.config.append_unique("security.false_positives", fp)
        ctx.config.save()
        ctx.ui.success(t("scan.fp_saved", count=len(args.mark_false_positive)))
        return 0
    engine = ctx.require_repo()
    scanner = ctx.scanner()
    with ctx.ui.progress(t("scan.running")):
        report = scanner.scan_staged(engine) if args.staged else scanner.scan_project(engine)
    if _json(ctx):
        _ui(ctx).out.emit_json({"scanned": report.scanned, "findings": [f.__dict__ for f in report.findings],
                                "binary_skipped": report.skipped_binary, "truncated": report.truncated})
        return 6 if report.secrets else 0
    ignored = report.by_category(IGNORED)
    if args.show_ignored and ignored:
        ctx.ui.table(t("scan.ignored_title"), [t("col.file"), t("col.reason")],
                     [[f.path, f.description] for f in ignored])
    others = [f for f in report.findings if f.category in ("allowed", "false_positive")]
    if others:
        ctx.ui.table(t("scan.reviewed_title"), [t("col.category"), t("col.file"), t("col.reason")],
                     [[t(f"cat.{f.category}"), f.path, f.description] for f in others])
    if report.is_clean:
        ctx.ui.success(t("scan.clean", count=report.scanned))
        ctx.ui.info(t("scan.disclaimer"))
        return 0
    render_findings(ctx, report)
    ctx.ui.table(t("scan.fingerprints"), [t("col.file"), t("col.line"), "fingerprint"],
                 [[f.path, str(f.line or "-"), f.fingerprint] for f in report.review_needed])
    ctx.ui.info(t("scan.fp_hint"))
    return 6 if report.secrets else 0


def cmd_untrack(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    if args.delete:
        if not ctx.ui.confirm_risky(t("untrack.delete_question", count=len(args.paths)),
                                    [t("untrack.delete_c1"), t("untrack.delete_c2")]):
            raise Cancelled(t("common.cancelled"))
    engine.remove(args.paths, keep_local=not args.delete)
    ctx.history.record("untrack", engine.cwd, True, " ".join(args.paths))
    ctx.ui.success(t("untrack.done_delete" if args.delete else "untrack.done", count=len(args.paths)))
    return 0


# ------------------------------------------------------------- diagnostics
def cmd_doctor(ctx: AppContext, args: argparse.Namespace) -> int:
    with ctx.ui.progress(t("doctor.running")):
        checks = doctor_service.run_diagnostics(ctx, network=not args.offline)
    if _json(ctx):
        _ui(ctx).out.emit_json([c.__dict__ for c in checks])
    else:
        labels = {"ok": "OK", "warn": t("doctor.warn"), "fail": t("doctor.fail")}
        ctx.ui.table(t("doctor.title"), [t("col.check"), t("col.result"), t("col.detail"), t("col.suggestion")],
                     [[c.name, labels[c.status], c.detail, c.suggestion] for c in checks])
    return 1 if any(c.status == "fail" for c in checks) else 0


# ------------------------------------------------------------ configuration
def cmd_config(ctx: AppContext, args: argparse.Namespace) -> int:
    cfg = ctx.config
    action = args.action or "show"
    if action == "show":
        _ui(ctx).out.emit_json(cfg.data)
    elif action == "path":
        ctx.ui.info(str(cfg.path))
    elif action == "get":
        value = cfg.get(args.key)
        if value is None:
            raise UsageError(t("config.unknown", key=args.key))
        _ui(ctx).out.emit_json(value) if isinstance(value, (dict, list)) else ctx.ui.text_block(str(value))
    elif action == "set":
        value = cfg.set(args.key, args.value)
        cfg.save()
        ctx.ui.success(t("config.saved", key=args.key, value=value))
        if args.key in ("git.user_name", "git.user_email") and value:
            git_key = "user.name" if args.key == "git.user_name" else "user.email"
            if args.key == "git.user_email":
                from gitflow_assistant.utils.validators import validate_email
                validate_email(str(value))
            if ctx.ui.confirm(t("config.apply_git", key=git_key)):
                GitEngine(Path.cwd()).set_config(git_key, str(value), global_scope=True)
                ctx.ui.success(t("config.applied_git", key=git_key))
    elif action == "unset":
        cfg.unset(args.key)
        cfg.save()
        ctx.ui.success(t("config.unset", key=args.key))
    elif action == "reset":
        if not ctx.ui.confirm(t("config.reset_question"), False):
            raise Cancelled(t("common.cancelled"))
        cfg.reset()
        cfg.save()
        ctx.ui.success(t("config.reset_done"))
    elif action == "export":
        ctx.ui.success(t("config.exported", path=str(cfg.export_to(normalize(args.file)))))
    elif action == "import":
        ignored = cfg.import_from(normalize(args.file))
        cfg.save()
        ctx.ui.success(t("config.imported"))
        if ignored:
            ctx.ui.warning(t("config.ignored_keys", keys=", ".join(ignored)))
    elif action == "alias":
        if not args.name:
            aliases = cfg.get("aliases") or {}
            ctx.ui.table(t("config.aliases"), ["alias", t("col.command")], [[k, v] for k, v in sorted(aliases.items())])
        else:
            if not args.target:
                raise UsageError(t("config.alias_usage"))
            cfg.set_alias(args.name, " ".join(args.target))
            cfg.save()
            ctx.ui.success(t("config.alias_saved", name=args.name))
    elif action == "unalias":
        removed = cfg.remove_alias(args.name)
        cfg.save()
        (ctx.ui.success if removed else ctx.ui.warning)(t("config.alias_removed" if removed else "config.alias_unknown",
                                                          name=args.name))
    return 0


def cmd_remote(ctx: AppContext, args: argparse.Namespace) -> int:
    engine = ctx.require_repo()
    action = args.action or "list"
    if action == "set":
        engine.set_remote(args.name, args.url)
        ctx.ui.success(t("publish.remote_set", name=args.name))
    elif action == "remove":
        if not ctx.ui.confirm(t("remote.remove_question", name=args.name), False):
            raise Cancelled(t("common.cancelled"))
        engine.remove_remote(args.name)
        ctx.ui.success(t("remote.removed", name=args.name))
    else:
        remotes = engine.remotes()
        if _json(ctx):
            _ui(ctx).out.emit_json(remotes)
        elif remotes:
            ctx.ui.table(t("remote.title"), [t("col.remote"), "fetch", "push"],
                         [[n, u.get("fetch", ""), u.get("push", "")] for n, u in remotes.items()])
        else:
            ctx.ui.info(t("remote.none"))
    return 0


# ------------------------------------------------------------------ GitHub
def _repo_ref(ctx: AppContext, value: Optional[str]) -> Tuple[str, str]:
    if value:
        if value.count("/") != 1:
            raise UsageError(t("github.repo_format"))
        owner, name = value.split("/")
        return owner, name
    engine = ctx.require_repo()
    parsed = parse_github_remote(engine.remote_url(ctx.remote_name) or "")
    if not parsed:
        raise UsageError(t("github.no_github_remote"))
    return parsed


def cmd_github(ctx: AppContext, args: argparse.Namespace) -> int:
    action = args.action or "status"
    creds = ctx.credentials
    if action == "status":
        info = creds.resolve()
        if not info:
            ctx.ui.warning(t("github.not_authenticated"))
            for hint in (t("hint.auth1"), t("hint.auth2"), t("hint.auth3")):
                ctx.ui.info("  • " + hint)
            return 7
        client = GitHubClient(info.token, str(ctx.config.get("github.api_url")))
        user = client.user()
        ctx.ui.table("GitHub", [t("col.item"), t("col.value")],
                     [[t("github.user"), str(user.get("login"))], [t("github.source"), info.source],
                      ["token", info.masked], ["scopes", str(user.get("_scopes") or "-")],
                      [t("github.rate"), str(client.rate_remaining)]])
        return 0
    if action == "login":
        if args.device:
            client_id = str(ctx.config.get("github.oauth_client_id") or "")
            client = GitHubClient(None, str(ctx.config.get("github.api_url")))
            web = str(ctx.config.get("github.web_url"))
            code = client.request_device_code(client_id, web_url=web)
            ctx.ui.info(t("github.device_instructions", url=code.get("verification_uri", ""),
                          code=code.get("user_code", "")))
            with ctx.ui.progress(t("github.device_waiting")):
                token = client.poll_device_token(client_id, str(code.get("device_code", "")),
                                                 int(code.get("interval", 5)), int(code.get("expires_in", 900)), web)
        elif args.token_stdin:
            token = sys.stdin.readline().strip()
        else:
            import getpass
            if not ctx.ui.interactive:
                raise UsageError(t("github.token_stdin_hint"))
            token = getpass.getpass(t("github.token_prompt")).strip()
        if not token:
            raise UsageError(t("github.empty_token"))
        user = GitHubClient(token, str(ctx.config.get("github.api_url"))).user()
        creds.set_session_token(token)
        ctx.ui.success(t("github.logged_in", user=user.get("login"), token=mask_token(token)))
        if args.store:
            try:
                creds.store(token)
                ctx.ui.success(t("github.stored"))
            except CredentialStorageUnavailable as exc:
                ctx.ui.warning(str(exc))
                return 1
        else:
            ctx.ui.info(t("github.session_only"))
        return 0
    if action == "logout":
        removed = creds.forget()
        ctx.ui.success(t("github.logged_out") if removed else t("github.nothing_stored"))
        if creds.gh_available():
            ctx.ui.info(t("github.gh_logout_hint"))
        return 0
    if action == "create":
        client = ctx.github()
        repo = client.create_repo(args.name, private=bool(args.private), description=args.description)
        ctx.ui.success(t("github.created", url=repo.html_url))
        if args.set_remote:
            engine = ctx.require_repo()
            engine.set_remote(ctx.remote_name, repo.ssh_url if args.ssh else repo.clone_url)
            ctx.ui.success(t("publish.remote_set", name=ctx.remote_name))
        return 0
    if action == "repos":
        repos = ctx.github().list_repos(args.limit)
        if _json(ctx):
            _ui(ctx).out.emit_json([r.__dict__ for r in repos])
        else:
            ctx.ui.table(t("github.repos_title"), [t("col.repo"), t("col.visibility"), t("col.description"), "URL"],
                         [[r.full_name, t("github.private") if r.private else t("github.public"), r.description[:50],
                           r.html_url] for r in repos])
        return 0
    owner, name = _repo_ref(ctx, getattr(args, "repo", None))
    client = ctx.github(require_token=action == "describe")
    if action == "info":
        repo = client.get_repo(owner, name)
        perms = ", ".join(k for k, v in repo.permissions.items() if v) or "-"
        ctx.ui.table(repo.full_name, [t("col.item"), t("col.value")],
                     [[t("col.description"), repo.description or "-"],
                      [t("col.visibility"), t("github.private") if repo.private else t("github.public")],
                      ["URL", repo.html_url], ["HTTPS", repo.clone_url], ["SSH", repo.ssh_url],
                      [t("github.default_branch"), repo.default_branch], [t("github.permissions"), perms]])
    elif action == "describe":
        repo = client.update_description(owner, name, args.text)
        ctx.ui.success(t("github.described", repo=repo.full_name))
    elif action == "branches":
        ctx.ui.table(f"{owner}/{name}", [t("col.branch")], [[b] for b in client.list_branches(owner, name)])
    elif action == "commits":
        commits = client.list_commits(owner, name, limit=args.limit)
        ctx.ui.table(f"{owner}/{name}", [t("col.commit"), t("col.date"), t("col.author"), t("col.message")],
                     [[c["sha"], c["date"][:16], c["author"], c["message"]] for c in commits])
    return 0


# --------------------------------------------------------------- generators
def _project_dir(ctx: AppContext) -> Path:
    path = ctx.project_path() or Path.cwd()
    engine = ctx.engine(path)
    return engine.root() or path


def cmd_gitignore(ctx: AppContext, args: argparse.Namespace) -> int:
    root = _project_dir(ctx)
    languages = args.languages or detect_languages(root)
    content = build_gitignore(languages)
    if args.print_only:
        ctx.ui.text_block(content)
        return 0
    target = root / ".gitignore"
    ctx.ui.info(t("gitignore.languages", langs=", ".join(languages) or "-"))
    if target.exists():
        merged = merge_gitignore(target.read_text(encoding="utf-8", errors="replace"), content)
        if merged == target.read_text(encoding="utf-8", errors="replace"):
            ctx.ui.success(t("gitignore.up_to_date"))
            return 0
        if not ctx.ui.confirm(t("gitignore.merge_question", path=str(target))):
            raise Cancelled(t("common.cancelled"))
        target.write_text(merged, encoding="utf-8")
    else:
        if not ctx.ui.confirm(t("gitignore.create_question", path=str(target))):
            raise Cancelled(t("common.cancelled"))
        target.write_text(content, encoding="utf-8")
    ctx.ui.success(t("gitignore.written", path=str(target)))
    return 0


def cmd_readme(ctx: AppContext, args: argparse.Namespace) -> int:
    root = _project_dir(ctx)
    description = args.description
    if not description and ctx.ui.interactive and not args.print_only:
        description = ctx.ui.ask(t("readme.description"), "")
    content = build_readme(root.name, description, detect_languages(root))
    if args.print_only:
        ctx.ui.text_block(content, "markdown")
        return 0
    target = root / "README.md"
    if target.exists():
        if not args.overwrite:
            raise UsageError(t("readme.exists", path=str(target)))
        if not ctx.ui.confirm_risky(t("readme.overwrite_question", path=str(target)), [t("readme.overwrite_c1")]):
            raise Cancelled(t("common.cancelled"))
    elif not ctx.ui.confirm(t("readme.create_question", path=str(target))):
        raise Cancelled(t("common.cancelled"))
    target.write_text(content, encoding="utf-8")
    ctx.ui.success(t("readme.written", path=str(target)))
    return 0


def cmd_backup(ctx: AppContext, args: argparse.Namespace) -> int:
    if (args.action or "create") == "list":
        items = backup_service.list_backups()
        if not items:
            ctx.ui.info(t("backup.none"))
        ctx.ui.table(t("backup.title"), [t("col.date"), t("col.project"), "HEAD", t("col.files"), t("col.path")],
                     [[b.created, Path(b.project).name, b.head, str(b.files), str(b.path)] for b in items])
        return 0
    engine = ctx.require_repo()
    with ctx.ui.progress(t("backup.running")):
        info = backup_service.create_backup(engine)
    ctx.history.record("backup", engine.cwd, True, str(info.path))
    ctx.ui.success(t("backup.done", path=str(info.path), files=info.files))
    return 0


def cmd_ai(ctx: AppContext, args: argparse.Namespace) -> int:
    from gitflow_assistant.core.gemini_client import GeminiClient, GeminiError
    from gitflow_assistant.services.ai_service import AIAssistant, staged_or_worktree_diff

    action = args.action or "status"
    creds = ctx.credentials
    try:
        if action == "status":
            key = creds.resolve_gemini_key()
            rows = [[t("ai.provider"), "Google Gemini"], [t("ai.model"), str(ctx.config.get("ai.model"))],
                    [t("ai.enabled"), str(ctx.config.get("ai.enabled"))],
                    [t("ai.key"), f"{key.source} ({key.masked})" if key else t("doctor.not_set")],
                    [t("ai.consent_label"), str(ctx.config.get("ai.confirm_send"))]]
            ctx.ui.table("AI", [t("col.item"), t("col.value")], rows)
            if not key:
                ctx.ui.info(t("ai.key_hint"))
                return 7
            return 0
        if action == "login":
            if args.key_stdin:
                key_value = sys.stdin.readline().strip()
            else:
                import getpass
                if not ctx.ui.interactive:
                    raise UsageError(t("ai.key_stdin_hint"))
                ctx.ui.info(t("ai.key_hint"))
                key_value = getpass.getpass(t("ai.key_prompt")).strip()
            if not key_value:
                raise UsageError(t("github.empty_token"))
            with ctx.ui.progress(t("ai.validating")):
                GeminiClient(key_value, model=str(ctx.config.get("ai.model")), retries=1).list_models()
            creds.set_gemini_session_key(key_value)
            ctx.ui.success(t("ai.key_valid", key=mask_token(key_value)))
            if args.store:
                try:
                    creds.store_gemini_key(key_value)
                    ctx.ui.success(t("github.stored"))
                except CredentialStorageUnavailable as exc:
                    ctx.ui.warning(str(exc))
                    ctx.ui.info(t("ai.env_hint"))
                    return 1
            else:
                ctx.ui.info(t("ai.env_hint"))
            return 0
        if action == "logout":
            removed = creds.forget_gemini_key()
            ctx.ui.success(t("github.logged_out") if removed else t("github.nothing_stored"))
            return 0
        assistant = AIAssistant(ctx)
        if action == "models":
            models = assistant.client().list_models()
            if _json(ctx):
                _ui(ctx).out.emit_json(models)
            else:
                current = str(ctx.config.get("ai.model"))
                ctx.ui.table(t("ai.models_title"), [t("ai.model")],
                             [[("* " if m == current else "") + m] for m in models])
            return 0
        engine = ctx.require_repo()
        if action == "commit-message":
            message = assistant.suggest_commit_message(engine.diff(staged=True))
            if _json(ctx):
                _ui(ctx).out.emit_json({"message": message})
            else:
                ctx.ui.text_block(message)
            return 0
        summary = assistant.summarize(staged_or_worktree_diff(engine, args.staged, args.refs))
        if _json(ctx):
            _ui(ctx).out.emit_json({"summary": summary})
        else:
            ctx.ui.heading(t("ai.summary_title"))
            ctx.ui.text_block(summary, "markdown")
        return 0
    except GeminiError as exc:
        raise RemoteOperationFailed(t("ai.failed", error=str(exc)) + _gemini_hint(exc.status)) from exc


def _gemini_hint(status: int) -> str:
    hints = {0: "ai.hint_network", 400: "ai.hint_key", 401: "ai.hint_key", 403: "ai.hint_403",
             404: "ai.hint_404", 429: "ai.hint_429"}
    key = hints.get(status)
    return "\n" + t(key) if key else ""


def cmd_menu(ctx: AppContext, args: argparse.Namespace) -> int:
    from gitflow_assistant.interface.tui_menu import run_menu

    return run_menu(ctx)


HANDLERS: Dict[str, Handler] = {
    "init": cmd_init, "status": cmd_status, "projects": cmd_projects, "select": cmd_select,
    "upload": cmd_upload, "publish": cmd_upload, "update": cmd_update, "sync": cmd_update, "clone": cmd_clone,
    "commit": cmd_commit, "push": cmd_push, "pull": cmd_pull, "abort": cmd_abort, "branch": cmd_branch,
    "history": cmd_history, "log": cmd_history, "diff": cmd_diff, "scan": cmd_scan, "doctor": cmd_doctor,
    "config": cmd_config, "remote": cmd_remote, "github": cmd_github, "gh": cmd_github,
    "gitignore": cmd_gitignore, "readme": cmd_readme, "backup": cmd_backup, "untrack": cmd_untrack,
    "menu": cmd_menu, "ai": cmd_ai,
}

__all__ = ["HANDLERS", "ProjectRequired", "GitHubError", "project_rows"]

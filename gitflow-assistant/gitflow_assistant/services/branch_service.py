"""Branch management with protection of local changes."""

from __future__ import annotations

from typing import List, Optional

from gitflow_assistant.core.git_engine import BranchInfo, GitEngine, GitError
from gitflow_assistant.i18n import t
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.errors import Cancelled, UsageError
from gitflow_assistant.utils.validators import validate_branch_name


def list_branches(engine: GitEngine) -> List[BranchInfo]:
    """Local branches."""
    return engine.branches()


def create(ctx: AppContext, engine: GitEngine, name: str, start_point: Optional[str] = None,
           switch: bool = False) -> None:
    """Create a branch, optionally switching to it."""
    name = validate_branch_name(name)
    if engine.branch_exists(name):
        raise UsageError(t("branch.exists", name=name))
    if not engine.has_commits():
        if switch:
            engine.run(["symbolic-ref", "HEAD", f"refs/heads/{name}"], check=True)
            ctx.ui.success(t("branch.switched", name=name))
            return
        raise UsageError(t("branch.no_commits"))
    engine.create_branch(name, start_point, switch=switch)
    ctx.history.record("branch-create", engine.cwd, True, name)
    ctx.ui.success(t("branch.created", name=name) + (" " + t("branch.switched", name=name) if switch else ""))


def switch(ctx: AppContext, engine: GitEngine, name: str, stash: Optional[bool] = None) -> None:
    """Switch branch. Local changes are never discarded: the user may stash them or cancel."""
    name = validate_branch_name(name)
    if not engine.branch_exists(name):
        remote_ref = f"{ctx.remote_name}/{name}"
        if remote_ref in engine.remote_branches():
            engine.create_branch(name, remote_ref)
        else:
            raise UsageError(t("branch.not_found", name=name))
    status = engine.status()
    dirty = [f for f in status.files if not f.is_ignored and not f.is_untracked]
    stashed = False
    if dirty:
        if stash is None:
            if not ctx.ui.interactive:
                raise UsageError(t("branch.dirty_noninteractive"))
            choice = ctx.ui.choose(t("branch.dirty_question", count=len(dirty)),
                                   [t("branch.opt_stash"), t("branch.opt_carry"), t("common.cancel")], 0)
            if choice == 2:
                raise Cancelled(t("common.cancelled"))
            stash = choice == 0
        if stash:
            engine.stash_push(f"gitflow: before switching to {name}")
            stashed = True
    try:
        engine.switch_branch(name)
    except GitError:
        if stashed:
            engine.stash_pop()
        raise
    ctx.history.record("branch-switch", engine.cwd, True, name)
    ctx.ui.success(t("branch.switched", name=name))
    if stashed:
        ctx.ui.info(t("branch.stash_saved"))


def delete(ctx: AppContext, engine: GitEngine, name: str) -> None:
    """Delete a fully merged branch after confirmation (never ``-D``)."""
    name = validate_branch_name(name)
    if name == engine.current_branch():
        raise UsageError(t("branch.delete_current"))
    if not ctx.ui.confirm_risky(t("branch.delete_question", name=name), [t("branch.delete_c1")]):
        raise Cancelled(t("common.cancelled"))
    try:
        engine.delete_branch(name)
    except GitError as exc:
        if "not fully merged" in str(exc):
            raise GitError(t("branch.not_merged", name=name)) from exc
        raise
    ctx.history.record("branch-delete", engine.cwd, True, name)
    ctx.ui.success(t("branch.deleted", name=name))


def rename(ctx: AppContext, engine: GitEngine, new_name: str) -> None:
    """Rename the current branch."""
    new_name = validate_branch_name(new_name)
    if engine.branch_exists(new_name):
        raise UsageError(t("branch.exists", name=new_name))
    engine.rename_current_branch(new_name)
    ctx.ui.success(t("branch.renamed", name=new_name))

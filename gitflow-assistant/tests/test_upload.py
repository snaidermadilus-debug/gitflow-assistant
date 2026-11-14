"""Tests for the publication workflows (upload / update / commit)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import git
from gitflow_assistant.core.git_engine import GitEngine, GitResult
from gitflow_assistant.services import branch_service, clone_service
from gitflow_assistant.services.errors import Cancelled, RemoteOperationFailed, SecurityBlocked, UsageError
from gitflow_assistant.services.upload_service import PublishOptions, commit_step, publish, update

SECRET = 'STRIPE = "sk_live_' + "abcdefghijklmnopqrstuvwx" + '"\n'


def _new_project(tmp_path: Path) -> Path:
    project = tmp_path / "newproj"
    project.mkdir()
    (project / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "keys.py").write_text(SECRET, encoding="utf-8")
    return project


def test_first_publish_non_interactive(tmp_path: Path, bare_remote: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    project = _new_project(tmp_path)
    ctx = make_ctx(interactive=False)
    result = publish(ctx, project, PublishOptions(message="feat: first", paths=["main.py"], remote_url=str(bare_remote)))
    assert result.pushed and result.commit and result.commit.files == ["main.py"]
    assert "main" in git(bare_remote, "branch")
    assert GitEngine(project).upstream() == "origin/main"
    assert "?? keys.py" in git(project, "status", "--porcelain")
    assert ctx.history.publications()[0].success


def test_publish_blocks_secrets_and_restores_index(tmp_path: Path, bare_remote: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    project = _new_project(tmp_path)
    ctx = make_ctx(interactive=False)
    with pytest.raises(SecurityBlocked):
        publish(ctx, project, PublishOptions(message="x", all_files=True, remote_url=str(bare_remote),
                                             accept_findings=True))
    engine = GitEngine(project)
    assert engine.staged_files() == [] and not engine.has_commits()


def test_non_interactive_requires_selection(tmp_path: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    project = _new_project(tmp_path)
    with pytest.raises(UsageError):
        publish(make_ctx(interactive=False), project, PublishOptions(message="x"))


def test_interactive_publish_excludes_secret_file(tmp_path: Path, bare_remote: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    project = _new_project(tmp_path)
    # answers: init? yes | select all | keys.py -> exclude(0) | commit type: free text (index 10) |
    # message | confirm commit | remote: enter URL (0) | URL
    answers = [True, None, 0, 10, "feat: initial", True, 0, str(bare_remote)]
    ctx = make_ctx(answers)
    result = publish(ctx, project, PublishOptions())
    assert result.pushed
    tracked = git(project, "ls-files").split()
    assert tracked == ["main.py"] and (project / "keys.py").exists()


def test_no_empty_commit(repo: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(interactive=False, project=repo)
    assert commit_step(ctx, GitEngine(repo), PublishOptions(message="x", all_files=True)) is None
    assert len(git(repo, "log", "--oneline").splitlines()) == 1


def test_commit_cancel_restores_index(repo: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    (repo / "n.txt").write_text("n", encoding="utf-8")
    ctx = make_ctx([None, False], project=repo)  # select all, refuse confirmation
    with pytest.raises(Cancelled):
        commit_step(ctx, GitEngine(repo), PublishOptions(message="feat: n"))
    assert GitEngine(repo).staged_files() == []


def _published(repo: Path, remote: Path, tmp_path: Path) -> Path:
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    return other


def test_update_fast_forward_and_push(repo: Path, bare_remote: Path, tmp_path: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    other = _published(repo, bare_remote, tmp_path)
    (other / "remote.txt").write_text("r", encoding="utf-8")
    git(other, "add", "remote.txt")
    git(other, "commit", "-q", "-m", "remote")
    git(other, "push", "-q")
    (repo / "local.txt").write_text("l", encoding="utf-8")
    ctx = make_ctx(interactive=False, project=repo)
    with pytest.raises(UsageError):  # diverged after local commit -> strategy required
        update(ctx, PublishOptions(message="feat: local", all_files=True))
    # the local commit was created before the integration step
    assert "feat: local" in git(repo, "log", "-1", "--format=%s")
    result = update(ctx, PublishOptions(strategy="merge"))
    assert result.pushed
    assert (repo / "remote.txt").exists()
    assert git(bare_remote, "log", "-1", "--format=%s", "main").strip().startswith("Merge")
    backups = [b for b in git(repo, "branch").split() if b.startswith("gitflow-backup/")]
    assert backups, "a backup branch must be created before merging"


def test_push_rejection_is_never_forced(repo: Path, bare_remote: Path, tmp_path: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    from gitflow_assistant.core.sync_manager import SyncManager
    other = _published(repo, bare_remote, tmp_path)
    (other / "r.txt").write_text("r", encoding="utf-8")
    git(other, "add", "r.txt")
    git(other, "commit", "-q", "-m", "remote")
    git(other, "push", "-q")
    (repo / "l.txt").write_text("l", encoding="utf-8")
    git(repo, "add", "l.txt")
    git(repo, "commit", "-q", "-m", "local")
    outcome = SyncManager(GitEngine(repo)).push()
    assert not outcome.ok and outcome.kind == "rejected"
    assert git(bare_remote, "log", "-1", "--format=%s", "main").strip() == "remote"


def test_update_offline_keeps_local_commit(repo: Path, tmp_path: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))
    (repo / "x.txt").write_text("x", encoding="utf-8")
    ctx = make_ctx(interactive=False, project=repo)
    result = update(ctx, PublishOptions(message="feat: offline", all_files=True))
    assert result.commit and not result.pushed and result.notes


def test_clone_service_and_branch_switch_with_stash(bare_remote: Path, repo: Path, tmp_path: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    _published(repo, bare_remote, tmp_path)
    ctx = make_ctx(interactive=False)
    dest = clone_service.clone(ctx, str(bare_remote), tmp_path / "cloned")
    assert (dest / "README.md").exists() and ctx.repos.current() == dest
    with pytest.raises(UsageError):
        clone_service.clone(ctx, str(bare_remote), dest)
    engine = GitEngine(dest)
    branch_service.create(ctx, engine, "feature")
    (dest / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(UsageError):
        branch_service.switch(ctx, engine, "feature")
    branch_service.switch(ctx, engine, "feature", stash=True)
    assert engine.current_branch() == "feature"
    assert "gitflow: before switching" in git(dest, "stash", "list")


def test_clone_credentials_are_redacted_from_output_and_history(tmp_path: Path, make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from gitflow_assistant.services import clone_service

    ctx = make_ctx(interactive=False)
    destination = tmp_path / "private-repo"
    url = "https://alice:secret-password@example.com/private-repo.git"

    monkeypatch.setattr(
        GitEngine,
        "clone",
        lambda self, *args, **kwargs: GitResult(["clone"], 0, "", ""),
    )
    monkeypatch.setattr(GitEngine, "is_repository", lambda self: True)

    clone_service.clone(ctx, url, destination)

    assert "secret-password" not in ctx.ui.text()
    assert "secret-password" not in ctx.history.list()[0].detail
    assert "https://***@example.com/private-repo.git" in ctx.history.list()[0].detail


def test_clone_failure_redacts_credentials(tmp_path: Path, make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(interactive=False)
    url = "https://alice:secret-password@example.com/private-repo.git"
    monkeypatch.setattr(
        GitEngine,
        "clone",
        lambda self, *args, **kwargs: GitResult(
            ["clone"], 128, "", f"fatal: unable to access '{url}': authentication failed"
        ),
    )

    with pytest.raises(RemoteOperationFailed) as exc:
        clone_service.clone(ctx, url, tmp_path / "private-repo")

    assert "secret-password" not in str(exc.value)
    assert "secret-password" not in ctx.history.list()[0].detail


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://alice:password@example.com/group/project.git?token=secret", "project"),
        ("git@example.com:group/project.git", "project"),
        (r"C:\repos\project.git", "project"),
    ],
)
def test_repo_name_from_url(url: str, expected: str) -> None:
    assert clone_service.repo_name_from_url(url) == expected

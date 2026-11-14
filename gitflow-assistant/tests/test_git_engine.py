"""Tests for the git engine: init, status, commits, branches, remotes, push/pull, clone, conflicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import git
from gitflow_assistant.core.git_engine import GitEngine, GitError, GitNotInstalledError, parse_porcelain_z, redact
from gitflow_assistant.utils.validators import ValidationError


def test_version_and_installed(tmp_path: Path) -> None:
    engine = GitEngine(tmp_path)
    assert engine.is_installed()
    assert engine.version() and engine.version()[0] >= 2


def test_missing_git_executable(tmp_path: Path) -> None:
    engine = GitEngine(tmp_path, git_executable="git-does-not-exist-xyz")
    assert not engine.is_installed()
    with pytest.raises(GitNotInstalledError):
        engine.run(["status"])


def test_init_and_unborn_branch(tmp_path: Path) -> None:
    engine = GitEngine(tmp_path)
    assert not engine.is_repository()
    engine.init("trunk")
    assert engine.is_repository()
    assert engine.current_branch() == "trunk"
    assert not engine.has_commits()
    assert engine.root() == tmp_path.resolve()


def test_status_parsing_special_names(repo: Path) -> None:
    (repo / "with space.txt").write_text("a", encoding="utf-8")
    (repo / "ação.txt").write_text("b", encoding="utf-8")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    engine = GitEngine(repo)
    status = engine.status()
    paths = {f.path: f for f in status.files}
    assert paths["with space.txt"].is_untracked
    assert "ação.txt" in paths
    assert paths["README.md"].is_unstaged
    git(repo, "mv", "README.md", "DOCS.md")
    renamed = [f for f in engine.status().files if f.index == "R"]
    assert renamed and renamed[0].path == "DOCS.md" and renamed[0].orig_path == "README.md"


def test_parse_porcelain_conflict_codes() -> None:
    entries = parse_porcelain_z("UU a.txt\x00AA b.txt\x00?? c.txt\x00")
    assert [e.is_conflicted for e in entries] == [True, True, False]


def test_add_commit_and_no_empty_commit(repo: Path) -> None:
    engine = GitEngine(repo)
    with pytest.raises(GitError):
        engine.commit("nothing")
    (repo / "a.txt").write_text("x", encoding="utf-8")
    engine.add(["a.txt"])
    assert engine.staged_files() == ["a.txt"]
    engine.commit("feat: add a")
    assert engine.log(1)[0].subject == "feat: add a"
    with pytest.raises(ValidationError):
        engine.commit("   ")


def test_unstage_and_untrack_keep_files(repo: Path) -> None:
    engine = GitEngine(repo)
    (repo / "b.txt").write_text("x", encoding="utf-8")
    engine.add(["b.txt"])
    engine.unstage(["b.txt"])
    assert engine.staged_files() == []
    engine.remove(["README.md"], keep_local=True)
    assert (repo / "README.md").exists()
    assert any(f.path == "README.md" and f.index == "D" for f in engine.status().files)


def test_option_injection_rejected(repo: Path) -> None:
    engine = GitEngine(repo)
    with pytest.raises(ValidationError):
        engine.create_branch("--force")
    with pytest.raises(ValidationError):
        engine.set_remote("origin", "--upload-pack=evil")
    with pytest.raises(ValidationError):
        engine.diff(ref_a="--output=/tmp/x")
    (repo / "-n").write_text("dash file", encoding="utf-8")
    engine.add(["-n"])  # paths are passed after "--"
    assert "-n" in engine.staged_files()


def test_branches_create_switch_delete(repo: Path) -> None:
    engine = GitEngine(repo)
    engine.create_branch("feature/x")
    assert engine.branch_exists("feature/x")
    engine.switch_branch("feature/x")
    assert engine.current_branch() == "feature/x"
    engine.switch_branch("main")
    engine.delete_branch("feature/x")
    assert not engine.branch_exists("feature/x")
    names = [b.name for b in engine.branches()]
    assert names == ["main"]


def test_unmerged_branch_not_deleted(repo: Path) -> None:
    engine = GitEngine(repo)
    engine.create_branch("wip", switch=True)
    (repo / "w.txt").write_text("w", encoding="utf-8")
    engine.add(["w.txt"])
    engine.commit("wip")
    engine.switch_branch("main")
    with pytest.raises(GitError):
        engine.delete_branch("wip")
    assert engine.branch_exists("wip")


def test_remotes_push_pull_clone(repo: Path, bare_remote: Path, tmp_path: Path) -> None:
    engine = GitEngine(repo)
    engine.set_remote("origin", str(bare_remote))
    assert engine.remotes()["origin"]["push"] == str(bare_remote)
    assert engine.push("origin", "main", set_upstream=True).ok
    assert engine.upstream() == "origin/main"
    clone_dir = tmp_path / "clone"
    assert engine.clone(str(bare_remote), clone_dir).ok
    other = GitEngine(clone_dir)
    (clone_dir / "new.txt").write_text("n", encoding="utf-8")
    other.add(["new.txt"])
    other.commit("remote change")
    assert other.push().ok
    assert engine.fetch("origin").ok
    assert engine.ahead_behind() == (0, 1)
    assert engine.pull("origin").ok
    assert (repo / "new.txt").exists()


def test_conflict_detection_and_abort(repo: Path) -> None:
    engine = GitEngine(repo)
    engine.create_branch("other", switch=True)
    (repo / "README.md").write_text("other\n", encoding="utf-8")
    engine.add(["README.md"])
    engine.commit("other")
    engine.switch_branch("main")
    (repo / "README.md").write_text("main\n", encoding="utf-8")
    engine.add(["README.md"])
    engine.commit("main")
    assert not engine.run(["merge", "other"]).ok
    assert engine.conflicts() == ["README.md"]
    assert engine.operation_in_progress() == "merge"
    engine.abort_operation("merge")
    assert engine.operation_in_progress() is None
    assert (repo / "README.md").read_text(encoding="utf-8") == "main\n"


def test_timeout_is_reported(repo: Path) -> None:
    engine = GitEngine(repo, timeout=1)
    result = engine.run(["-c", "alias.slow=!sleep 3", "slow"], timeout=1)
    assert result.timed_out and not result.ok


def test_redaction() -> None:
    assert redact("https://user:ghp_abcdefghijklmnopqrstuvwxyz0123456789@github.com/x") == "https://***@github.com/x"
    assert "ghp_" not in redact("token ghp_abcdefghijklmnopqrstuvwxyz0123456789")


def test_log_diff_integrity_bundle(repo: Path, tmp_path: Path) -> None:
    engine = GitEngine(repo)
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")
    assert "+# changed" in engine.diff()
    assert "README.md" in engine.diff(stat=True)
    assert engine.verify_integrity().ok
    engine.bundle(tmp_path / "b.bundle")
    assert (tmp_path / "b.bundle").stat().st_size > 0

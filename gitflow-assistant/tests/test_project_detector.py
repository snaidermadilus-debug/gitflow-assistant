"""Tests for project detection and the recent projects registry."""

from __future__ import annotations

from pathlib import Path

from conftest import git
from gitflow_assistant.core.project_detector import detect_project, find_repositories
from gitflow_assistant.core.repository_manager import RepositoryManager
from gitflow_assistant.services import backup_service
from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.utils.templates import build_gitignore, detect_languages, merge_gitignore


def test_detect_states(repo: Path, tmp_path: Path) -> None:
    assert detect_project(tmp_path / "nope").state == "missing"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert detect_project(plain).state == "not-git"
    assert detect_project(repo).state == "clean"
    (repo / "n.txt").write_text("n", encoding="utf-8")
    info = detect_project(repo / ".." / repo.name)
    assert info.state == "dirty" and info.untracked == 1 and info.branch == "main"


def test_detect_from_subdirectory(repo: Path) -> None:
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    info = detect_project(sub)
    assert info.is_git and info.root == repo.resolve()


def test_find_repositories_bounded(tmp_path: Path) -> None:
    for rel in ("a", "b/c", "d/e/f/g"):
        path = tmp_path / "base" / rel
        path.mkdir(parents=True)
        git(path, "init", "-q")
    (tmp_path / "base" / "node_modules" / "x").mkdir(parents=True)
    git(tmp_path / "base" / "node_modules" / "x", "init", "-q")
    found = find_repositories([tmp_path / "base"], max_depth=2)
    names = sorted(p.name for p in found)
    assert names == ["a", "c"]
    assert len(find_repositories([tmp_path / "base"], max_depth=5, max_directories=2)) <= 1


def test_recent_projects(tmp_path: Path) -> None:
    manager = RepositoryManager(tmp_path / "p.json")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    manager.add(a)
    manager.add(b)
    assert manager.current() == b.resolve()
    manager.add(a)
    assert [p.name for p in manager.list()] == ["a", "b"]
    b.rmdir()
    assert manager.prune_missing() == 1
    assert manager.remove(a) and manager.list() == []


def test_templates(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("", encoding="utf-8")
    langs = detect_languages(tmp_path)
    assert langs == ["node", "python"]
    content = build_gitignore(langs)
    assert "__pycache__/" in content and "node_modules/" in content and ".env" in content
    merged = merge_gitignore("custom/\n.env\n", content)
    assert merged.startswith("custom/\n.env\n") and merged.count("\n.env\n") == 1


def test_backup_is_non_destructive(repo: Path, tmp_path: Path) -> None:
    (repo / "wip.txt").write_text("work in progress", encoding="utf-8")
    before = git(repo, "status", "--porcelain")
    info = backup_service.create_backup(GitEngine(repo), tmp_path / "backups")
    assert (info.path / "repository.bundle").exists() and info.files == 1
    assert git(repo, "status", "--porcelain") == before
    restored = tmp_path / "restored"
    git(tmp_path, "clone", "-q", str(info.path / "repository.bundle"), str(restored))
    assert (restored / "README.md").exists()
    assert backup_service.list_backups(tmp_path / "backups")[0].files == 1

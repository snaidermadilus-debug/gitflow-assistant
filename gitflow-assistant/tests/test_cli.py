"""End-to-end tests of the ``gitflow`` command line (main entry point)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import git
from gitflow_assistant.app import main
from gitflow_assistant.interface.cli_parser import expand_aliases, hoist_global_options
from gitflow_assistant.interface.prompts import parse_selection


def run(capsys, *args: str) -> tuple:  # type: ignore[no-untyped-def]
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0 and "GitFlow Assistant" in capsys.readouterr().out


def test_help_lists_commands(capsys) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for command in ("upload", "update", "clone", "scan", "doctor", "ai"):
        assert command in out


def test_not_a_repository_exit_code(tmp_path: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    code, _, err = run(capsys, "--batch", "--no-color", "status")
    assert code == 4 and "no project selected" in err


def test_init_status_json_commit_flow(tmp_path: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "cli"
    project.mkdir()
    monkeypatch.chdir(project)
    assert run(capsys, "init", "--batch", "--gitignore")[0] == 0
    (project / "a.py").write_text("print(1)\n", encoding="utf-8")
    code, out, _ = run(capsys, "--json", "status")
    data = json.loads(out)
    assert code == 0 and data["branch"] == "main" and {"path": "a.py", "code": "??"} in data["files"]
    code, out, _ = run(capsys, "--json", "commit", "--all", "-m", "feat: a")
    assert code == 0 and json.loads(out)["commit"]
    code, out, _ = run(capsys, "--json", "history", "log")
    assert json.loads(out)[0]["subject"] == "feat: a"
    code, out, _ = run(capsys, "--json", "projects")
    assert json.loads(out)[0]["path"] == str(project.resolve())


def test_scan_exit_code_and_false_positive(repo: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(repo)
    (repo / "creds.py").write_text('password = "abc12345"\n', encoding="utf-8")
    code, out, _ = run(capsys, "--json", "scan")
    findings = json.loads(out)["findings"]
    assert code == 0 and findings[0]["category"] == "suspicious"
    assert run(capsys, "--batch", "scan", "--mark-false-positive", findings[0]["fingerprint"])[0] == 0
    code, out, _ = run(capsys, "--json", "scan")
    assert json.loads(out)["findings"][0]["category"] == "false_positive"
    (repo / ".env").write_text("A=1\n", encoding="utf-8")
    assert run(capsys, "--json", "scan")[0] == 6


def test_config_and_alias(capsys, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert run(capsys, "--batch", "config", "set", "default_branch", "trunk")[0] == 0
    code, out, _ = run(capsys, "--batch", "--no-color", "config", "get", "default_branch")
    assert out.strip() == "trunk"
    assert run(capsys, "--batch", "config", "set", "nope", "1")[0] == 2
    assert run(capsys, "--batch", "config", "alias", "dd", "doctor", "--offline")[0] == 0
    code, out, _ = run(capsys, "--json", "dd")
    assert any(c["name"] == "Git" for c in json.loads(out))
    assert run(capsys, "--batch", "config", "export", str(tmp_path / "e.json"))[0] == 0


def test_generators_and_risky_overwrite(repo: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(repo)
    assert run(capsys, "--batch", "gitignore")[0] == 0
    assert ".env" in (repo / ".gitignore").read_text(encoding="utf-8")
    assert run(capsys, "--batch", "readme")[0] == 2  # README exists
    assert run(capsys, "--batch", "readme", "--overwrite")[0] == 2  # risky needs --yes --allow-risky
    assert run(capsys, "--batch", "--yes", "--allow-risky", "readme", "--overwrite", "--description", "Demo")[0] == 0
    assert "Demo" in (repo / "README.md").read_text(encoding="utf-8")


def test_untrack_and_branch_commands(repo: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(repo)
    assert run(capsys, "--batch", "untrack", "README.md")[0] == 0
    assert (repo / "README.md").exists()
    assert run(capsys, "--batch", "untrack", "README.md", "--delete")[0] == 2
    git(repo, "reset", "-q", "HEAD", "--", "README.md")
    assert run(capsys, "--batch", "branch", "create", "dev", "--switch")[0] == 0
    assert git(repo, "branch", "--show-current").strip() == "dev"
    assert run(capsys, "--batch", "branch", "delete", "main")[0] == 2


def test_upload_and_push_via_cli(tmp_path: Path, bare_remote: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "pub"
    project.mkdir()
    (project / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(project)
    code, out, err = run(capsys, "--json", "upload", "--all", "-m", "feat: x", "--remote", str(bare_remote))
    assert code == 0, err
    assert json.loads(out)["pushed"] is True
    assert run(capsys, "--batch", "push")[0] == 0
    assert run(capsys, "--batch", "pull")[0] == 0
    code, out, _ = run(capsys, "--json", "history", "publications")
    assert json.loads(out)[0]["operation"] in ("push", "upload")


def test_menu_requires_tty(capsys) -> None:  # type: ignore[no-untyped-def]
    assert run(capsys, "--batch", "menu")[0] == 2


def test_argument_helpers() -> None:
    assert hoist_global_options(["init", "-y", "-C", "x", "--", "-y"]) == ["-y", "-C", "x", "init", "--", "-y"]
    assert expand_aliases(["--json", "st"], {"st": "status"}) == ["--json", "status"]
    assert expand_aliases(["status"], {"status": "doctor"}) == ["status"]
    assert parse_selection("1,3-4", 5) == [0, 2, 3]
    assert parse_selection("", 3) == [0, 1, 2] and parse_selection("n", 3) == []
    with pytest.raises(ValueError):
        parse_selection("9", 3)


def test_translations_complete() -> None:
    import string
    from gitflow_assistant.i18n import M, set_language, t
    for key, values in M.items():
        fields = [{f[1] for f in string.Formatter().parse(v) if f[1]} for v in values]
        assert fields[0] == fields[1] == fields[2], key
        assert all(values), key
    set_language("pt")
    assert t("menu.2") == "Publicar projeto"
    set_language("en")


def test_upload_targets_current_folder_not_last_project(repo: Path, tmp_path: Path, bare_remote: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(repo)
    assert run(capsys, "--batch", "select", str(repo))[0] == 0
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "f.txt").write_text("f", encoding="utf-8")
    monkeypatch.chdir(fresh)
    code, out, err = run(capsys, "--json", "upload", "--all", "-m", "feat: f", "--remote", str(bare_remote))
    assert code == 0, err
    assert git(fresh, "ls-files").split() == ["f.txt"]
    assert len(git(repo, "log", "--oneline").splitlines()) == 1


def test_fallback_to_selected_project_is_announced(repo: Path, tmp_path: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(repo)
    run(capsys, "--batch", "select", str(repo))
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "--batch", "--no-color", "status")
    assert code == 0 and "Using the selected project" in out

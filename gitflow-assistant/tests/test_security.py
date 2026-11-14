"""Tests for secret detection, scanner classification, credentials and confirmations."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import git
from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.core.security_scanner import ALLOWED, FALSE_POSITIVE, IGNORED, LARGE, SecurityScanner
from gitflow_assistant.security.confirmation import ConfirmationPolicy, ConfirmationRequired
from gitflow_assistant.security.credential_manager import CredentialManager, CredentialStorageUnavailable, mask_token
from gitflow_assistant.security.secret_detector import CONFIRMED, SUSPICIOUS, check_name, scan_lines

GH_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def test_content_rules_detect_real_patterns() -> None:
    lines = [f'token = "{GH_TOKEN}"', "AKIAIOSFODNN7EXAMPLE", "-----BEGIN OPENSSH PRIVATE KEY-----",
             "url = https://bob:hunter22@example.com/repo"]
    found = {m.rule_id for m in scan_lines("f", lines)}
    assert {"github-token", "aws-access-key", "private-key", "url-credentials"} <= found


def test_placeholders_are_not_flagged() -> None:
    lines = ['password = "changeme"', "api_key = os.environ['API_KEY']", 'secret: "${SECRET}"', "password = <your-password>"]
    assert list(scan_lines("f", lines)) == []


def test_generic_assignment_levels() -> None:
    weak = list(scan_lines("f", ['password = "abc12345"']))
    strong = list(scan_lines("f", ['client_secret = "Zx9Qw8Er7Ty6Ui5Op4As3Df2"']))
    assert weak[0].level == SUSPICIOUS and strong[0].level == CONFIRMED
    assert "abc12345" not in weak[0].excerpt


def test_entropy_and_scan_content_limit(tmp_path: Path) -> None:
    from gitflow_assistant.security.secret_detector import shannon_entropy

    assert shannon_entropy("ab") == 1.0
    content = "x = 1\n" * 200 + f'GITHUB = "{GH_TOKEN}"\n'
    (tmp_path / "large.py").write_text(content, encoding="utf-8")
    report = SecurityScanner(max_content_kb=1).scan_files(tmp_path, ["large.py"])
    assert not report.secrets and report.truncated == ["large.py"]


def test_name_rules() -> None:
    assert check_name("config/.env")[1] == CONFIRMED
    assert check_name("keys/id_ed25519")[1] == CONFIRMED
    assert check_name("db.sqlite")[1] == SUSPICIOUS
    assert check_name(".env.example") is None
    assert check_name("src/main.py") is None


def test_scanner_staged_content(repo: Path) -> None:
    engine = GitEngine(repo)
    (repo / "settings.py").write_text(f'GITHUB = "{GH_TOKEN}"\n', encoding="utf-8")
    (repo / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    engine.add(["settings.py", "ok.py"])
    # the working tree changes after staging: the staged content is what matters
    (repo / "settings.py").write_text("GITHUB = None\n", encoding="utf-8")
    report = SecurityScanner().scan_staged(engine)
    assert report.scanned == 2
    assert [f.path for f in report.secrets] == ["settings.py"]


def test_scanner_large_binary_and_ignored(repo: Path) -> None:
    engine = GitEngine(repo)
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (repo / "big.bin").write_bytes(b"\x00" * (2 * 1024 * 1024))
    (repo / "debug.log").write_text("x", encoding="utf-8")
    scanner = SecurityScanner(max_file_size_mb=1)
    report = scanner.scan_files(repo, ["big.bin", "debug.log"], engine)
    cats = {(f.path, f.category) for f in report.findings}
    assert ("big.bin", LARGE) in cats and ("debug.log", IGNORED) in cats
    assert "big.bin" in report.skipped_binary


def test_scanner_reads_large_text_in_chunks(tmp_path: Path) -> None:
    filler = ("x = 1\n" * 50000)
    (tmp_path / "f.py").write_text(filler + f'T = "{GH_TOKEN}"\n', encoding="utf-8")
    report = SecurityScanner(max_content_kb=2048).scan_files(tmp_path, ["f.py"])
    assert report.secrets and report.secrets[0].line == 50001
    limited = SecurityScanner(max_content_kb=64).scan_files(tmp_path, ["f.py"])
    assert not limited.secrets and "f.py" in limited.truncated


def test_allowed_and_false_positive(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text('password = "abc12345"\n', encoding="utf-8")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "b.py").write_text('password = "abc12345"\n', encoding="utf-8")
    first = SecurityScanner().scan_files(tmp_path, ["a.py"])
    fp = first.findings[0].fingerprint
    second = SecurityScanner(false_positives=[fp], allow_patterns=["fixtures/*"]).scan_files(
        tmp_path, ["a.py", "fixtures/b.py"])
    cats = {f.path: f.category for f in second.findings}
    assert cats == {"a.py": FALSE_POSITIVE, "fixtures/b.py": ALLOWED}
    assert second.is_clean


def test_scan_project_lists_ignored(repo: Path) -> None:
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    report = SecurityScanner().scan_project(GitEngine(repo))
    assert any(f.path == ".env" and f.category == IGNORED for f in report.findings)
    assert not report.secrets


def test_credentials_env_and_mask() -> None:
    manager = CredentialManager(env={"GH_TOKEN": GH_TOKEN}, use_keyring=False, runner=lambda *a, **k: None)
    info = manager.resolve(allow_credential_helper=False)
    assert info and info.source == "env:GH_TOKEN" and GH_TOKEN not in info.masked
    assert mask_token("short") == "****"


def test_credentials_session_and_git_helper() -> None:
    calls = []

    def runner(argv, input_text=None, timeout=15):  # type: ignore[no-untyped-def]
        calls.append(argv)
        return "protocol=https\nhost=github.com\nusername=x\npassword=helper-token\n" if argv[:2] == ["git", "credential"] else None

    manager = CredentialManager(env={}, use_keyring=False, runner=runner)
    found = manager.resolve()
    assert found and found.source == "git-credential" and found.token == "helper-token"
    manager.set_session_token("temp")
    assert manager.resolve().source == "session"
    assert manager.forget()


def test_no_plaintext_storage_fallback() -> None:
    manager = CredentialManager(env={}, use_keyring=False)
    with pytest.raises(CredentialStorageUnavailable):
        manager.store("abc")
    with pytest.raises(CredentialStorageUnavailable):
        manager.store_gemini_key("abc")


def test_confirmation_policy() -> None:
    batch = ConfirmationPolicy(ask=None)
    assert batch.confirm("x")
    with pytest.raises(ConfirmationRequired):
        batch.confirm_risky("delete", ["gone"])
    assert ConfirmationPolicy(ask=None, assume_yes=True, allow_risky=True).confirm_risky("delete", [])
    with pytest.raises(ConfirmationRequired):
        ConfirmationPolicy(ask=None, mode="always").confirm("x")
    interactive = ConfirmationPolicy(ask=lambda q, d: False, ask_phrase=lambda text, p: "gone" in text)
    assert not interactive.confirm("x")
    assert interactive.confirm_risky("delete", ["gone"])

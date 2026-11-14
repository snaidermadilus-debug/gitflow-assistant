"""Shared fixtures: isolated HOME/config and temporary git repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

import pytest

from gitflow_assistant import i18n
from gitflow_assistant.core.configuration import Configuration
from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.core.repository_manager import RepositoryManager
from gitflow_assistant.security.confirmation import ConfirmationPolicy
from gitflow_assistant.security.credential_manager import CredentialManager
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.history_service import OperationHistory


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never touch the real user configuration or repositories."""
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = Test User\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n",
                         encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GITFLOW_HOME", str(tmp_path / "gfhome"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "TERMUX_VERSION", "NO_COLOR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.set_language("en")
    return home


def git(cwd: Path, *args: str) -> str:
    """Run git directly (test helper)."""
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An initialised repository with one commit."""
    path = tmp_path / "project"
    path.mkdir()
    git(path, "init", "-q", "-b", "main") if _git_supports_b() else git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", "refs/heads/main")
    (path / "README.md").write_text("# project\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "initial")
    return path


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(path))
    git(path, "symbolic-ref", "HEAD", "refs/heads/main")
    return path


def _git_supports_b() -> bool:
    engine = GitEngine(Path.cwd())
    version = engine.version() or (0,)
    return version >= (2, 28)


class FakeUI:
    """Scripted ``UserInterface`` for tests. ``answers`` feeds ask/confirm/choose/select_many in order."""

    def __init__(self, answers: Sequence[object] = (), interactive: bool = True, assume_yes: bool = False) -> None:
        self.answers: List[object] = list(answers)
        self.interactive = interactive
        self.messages: List[str] = []
        self.policy = ConfirmationPolicy(ask=(lambda q, d: bool(self._next(d))) if interactive else None,
                                         ask_phrase=(lambda q, p: bool(self._next(False))) if interactive else None,
                                         assume_yes=assume_yes)

    def _next(self, default: object) -> object:
        return self.answers.pop(0) if self.answers else default

    def info(self, m: str) -> None: self.messages.append("i " + m)
    def success(self, m: str) -> None: self.messages.append("ok " + m)
    def warning(self, m: str) -> None: self.messages.append("! " + m)
    def error(self, m: str) -> None: self.messages.append("x " + m)
    def heading(self, m: str) -> None: self.messages.append("# " + m)
    def table(self, title: str, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        self.messages.append(f"table {title} {len(rows)}")
    def text_block(self, text: str, syntax: str = "") -> None: self.messages.append(text)

    def progress(self, message: str):  # type: ignore[no-untyped-def]
        import contextlib
        return contextlib.nullcontext()

    def ask(self, question: str, default: str = "") -> str:
        value = self._next(default)
        return str(value) if value is not None else default

    def confirm(self, question: str, default: bool = True) -> bool:
        return self.policy.confirm(question, default)

    def confirm_risky(self, action: str, consequences: Sequence[str]) -> bool:
        return self.policy.confirm_risky(action, consequences)

    def choose(self, question: str, options: Sequence[str], default: int = 0) -> int:
        return int(self._next(default))  # type: ignore[arg-type]

    def select_many(self, question: str, items: Sequence[str], default_all: bool = True) -> List[int]:
        value = self._next(None)
        return list(range(len(items))) if value is None else list(value)  # type: ignore[arg-type]

    def text(self) -> str:
        return "\n".join(self.messages)


@pytest.fixture
def make_ctx(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Factory building an AppContext with a FakeUI."""

    def factory(answers: Sequence[object] = (), interactive: bool = True, project: Optional[Path] = None,
                assume_yes: bool = False) -> AppContext:
        config = Configuration(path=tmp_path / "gfhome" / "config" / "config.json")
        return AppContext(config=config, ui=FakeUI(answers, interactive, assume_yes),  # type: ignore[arg-type]
                          repos=RepositoryManager(tmp_path / "gfhome" / "data" / "projects.json"),
                          history=OperationHistory(tmp_path / "gfhome" / "data" / "history.jsonl"),
                          credentials=CredentialManager(use_keyring=False, env={}), project_override=project)

    return factory


@pytest.fixture
def engine_for() -> Iterator:
    yield lambda path: GitEngine(path)

"""Shared application context (configuration, UI, stores, factories)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gitflow_assistant.core.configuration import ConfigError, Configuration
from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.core.github_client import GitHubClient
from gitflow_assistant.core.repository_manager import RepositoryManager
from gitflow_assistant.core.security_scanner import SecurityScanner
from gitflow_assistant.security.credential_manager import CredentialManager
from gitflow_assistant.services.errors import ProjectRequired
from gitflow_assistant.services.history_service import OperationHistory
from gitflow_assistant.services.ui import UserInterface

__all__ = ["AppContext", "ProjectRequired"]
@dataclass
class AppContext:
    """Objects shared by all commands during one execution."""

    config: Configuration
    ui: UserInterface
    repos: RepositoryManager
    history: OperationHistory
    credentials: CredentialManager = field(default_factory=CredentialManager)
    project_override: Optional[Path] = None
    _announced: bool = field(default=False, repr=False)

    # ------------------------------------------------------------ factories
    def engine(self, path: Path) -> GitEngine:
        """GitEngine configured with the user's timeouts."""
        return GitEngine(path, timeout=int(self.config.get("timeouts.git", 60)),
                         network_timeout=int(self.config.get("timeouts.network", 300)))

    def scanner(self) -> SecurityScanner:
        """SecurityScanner configured from the security settings."""
        max_file_size_mb = int(self.config.get("security.max_file_size_mb", 50))
        max_content_kb = int(self.config.get("security.max_content_scan_kb", 1024))
        if max_file_size_mb <= 0 or max_content_kb <= 0:
            raise ConfigError("security scan size limits must be greater than zero")
        return SecurityScanner(
            max_file_size_mb=max_file_size_mb,
            max_content_kb=max_content_kb,
            exclude_patterns=self.config.get("security.exclude_patterns") or [],
            allow_patterns=self.config.get("security.allow_patterns") or [],
            false_positives=self.config.get("security.false_positives") or [],
        )

    def github(self, require_token: bool = True) -> GitHubClient:
        """GitHub client using the first available credential."""
        info = self.credentials.resolve()
        token = info.token if info else None
        client = GitHubClient(token, api_url=str(self.config.get("github.api_url")))
        if require_token and not token:
            from gitflow_assistant.core.github_client import GitHubAuthError
            raise GitHubAuthError("no GitHub credentials found")
        return client

    # -------------------------------------------------------------- project
    def project_path(self) -> Optional[Path]:
        """Explicit ``-C`` path, otherwise the current directory if it is a repo, otherwise the last selected."""
        if self.project_override:
            return self.project_override.expanduser().resolve()
        cwd = Path.cwd()
        if self.engine(cwd).is_repository():
            return cwd
        selected = self.repos.current()
        if selected and not self._announced:
            from gitflow_assistant.i18n import t
            self.ui.info(t("project.using_selected", path=str(selected)))
            self._announced = True
        return selected

    def require_repo(self) -> GitEngine:
        """Return an engine rooted at the selected repository or raise :class:`ProjectRequired`."""
        path = self.project_path()
        if not path:
            raise ProjectRequired("no project selected")
        engine = self.engine(path)
        root = engine.root()
        if not root:
            raise ProjectRequired(f"not a git repository: {path}")
        engine.cwd = root
        return engine

    @property
    def remote_name(self) -> str:
        return str(self.config.get("default_remote", "origin"))

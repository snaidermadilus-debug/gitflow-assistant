"""Minimal GitHub REST API client (standard library only).

Features: authentication check, repository listing with pagination, creation
(public/private), information, description update, branches, commits,
permissions, rate-limit handling and OAuth Device Flow (only with a
user-supplied OAuth App client id – no secret is ever embedded).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from gitflow_assistant import __version__

API_VERSION = "2022-11-28"
_GITHUB_REMOTE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$")


class GitHubError(RuntimeError):
    """Generic API error."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class GitHubAuthError(GitHubError):
    """Missing or invalid credentials."""


class GitHubRateLimitError(GitHubError):
    """API rate limit exceeded."""

    def __init__(self, message: str, reset_at: Optional[int]) -> None:
        super().__init__(message, 403)
        self.reset_at = reset_at


class GitHubNetworkError(GitHubError):
    """No connectivity to the GitHub API."""


@dataclass
class Repository:
    """Subset of a GitHub repository resource."""

    full_name: str
    name: str
    owner: str
    private: bool
    description: str
    html_url: str
    clone_url: str
    ssh_url: str
    default_branch: str
    permissions: Dict[str, bool]

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "Repository":
        return cls(
            full_name=data.get("full_name", ""), name=data.get("name", ""),
            owner=(data.get("owner") or {}).get("login", ""), private=bool(data.get("private")),
            description=data.get("description") or "", html_url=data.get("html_url", ""),
            clone_url=data.get("clone_url", ""), ssh_url=data.get("ssh_url", ""),
            default_branch=data.get("default_branch") or "main", permissions=data.get("permissions") or {},
        )


def parse_github_remote(url: str) -> Optional[Tuple[str, str]]:
    """Extract ``(owner, repo)`` from a GitHub HTTPS/SSH remote URL."""
    match = _GITHUB_REMOTE.match(url.strip())
    return (match.group("owner"), match.group("repo")) if match else None


def web_url_for_remote(url: str) -> Optional[str]:
    """Browser URL for a GitHub remote."""
    parsed = parse_github_remote(url)
    return f"https://github.com/{parsed[0]}/{parsed[1]}" if parsed else None


def _next_link(link_header: str) -> Optional[str]:
    for part in link_header.split(","):
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


Opener = Callable[[urllib.request.Request, int], Any]


def _default_opener(request: urllib.request.Request, timeout: int) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https URL built internally


class GitHubClient:
    """Thin wrapper over the GitHub REST API v3."""

    def __init__(self, token: Optional[str], api_url: str = "https://api.github.com", timeout: int = 20,
                 opener: Opener = _default_opener) -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener
        self.rate_remaining: Optional[int] = None

    # ------------------------------------------------------------ transport
    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
                 params: Optional[Dict[str, Any]] = None, auth_required: bool = True,
                 full_url: Optional[str] = None) -> Tuple[Any, Dict[str, str]]:
        if auth_required and not self.token:
            raise GitHubAuthError("GitHub authentication required (gh auth login, GITHUB_TOKEN or gitflow github login)", 401)
        url = full_url or f"{self.api_url}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", API_VERSION)
        request.add_header("User-Agent", f"gitflow-assistant/{__version__}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self._opener(request, self.timeout) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                self._track_rate(headers)
                raw = response.read()
                return (json.loads(raw.decode("utf-8")) if raw else None), headers
        except urllib.error.HTTPError as exc:
            headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
            self._track_rate(headers)
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
            except (ValueError, OSError):
                payload = {}
            message = payload.get("message", exc.reason) if isinstance(payload, dict) else str(exc.reason)
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if errors:
                message += ": " + "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)
            if exc.code in (403, 429) and (headers.get("x-ratelimit-remaining") == "0" or exc.code == 429
                                           or "rate limit" in str(message).lower()):
                reset = headers.get("x-ratelimit-reset")
                raise GitHubRateLimitError(f"GitHub API rate limit exceeded: {message}",
                                           int(reset) if reset and reset.isdigit() else None) from exc
            if exc.code == 401:
                raise GitHubAuthError(f"authentication failed: {message}", 401) from exc
            raise GitHubError(f"GitHub API error {exc.code}: {message}", exc.code) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise GitHubNetworkError(f"cannot reach GitHub API ({getattr(exc, 'reason', exc)})") from exc

    def _track_rate(self, headers: Dict[str, str]) -> None:
        remaining = headers.get("x-ratelimit-remaining")
        if remaining and remaining.isdigit():
            self.rate_remaining = int(remaining)

    def _paginate(self, path: str, params: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        params = {**params, "per_page": min(100, max(1, limit))}
        data, headers = self._request("GET", path, params=params)
        while True:
            items.extend(data or [])
            next_url = _next_link(headers.get("link", ""))
            if len(items) >= limit or not next_url:
                break
            data, headers = self._request("GET", "", full_url=next_url)
        return items[:limit]

    # ------------------------------------------------------------------ API
    def user(self) -> Dict[str, Any]:
        """Authenticated user (validates the token)."""
        data, headers = self._request("GET", "/user")
        data["_scopes"] = headers.get("x-oauth-scopes", "")
        return data

    def rate_limit(self) -> Dict[str, Any]:
        """Current core rate-limit status (works without authentication)."""
        data, _ = self._request("GET", "/rate_limit", auth_required=False)
        return (data or {}).get("resources", {}).get("core", {})

    def list_repos(self, limit: int = 100, visibility: str = "all") -> List[Repository]:
        """Repositories of the authenticated user, most recently updated first."""
        raw = self._paginate("/user/repos", {"sort": "updated", "visibility": visibility}, limit)
        return [Repository.from_api(r) for r in raw]

    def get_repo(self, owner: str, name: str) -> Repository:
        """Information about one repository."""
        data, _ = self._request("GET", f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
                                auth_required=False)
        return Repository.from_api(data)

    def create_repo(self, name: str, private: bool = False, description: str = "", org: Optional[str] = None) -> Repository:
        """Create an empty repository (no auto-init, so the first push is never rejected)."""
        body = {"name": name, "private": private, "description": description, "auto_init": False}
        path = f"/orgs/{urllib.parse.quote(org)}/repos" if org else "/user/repos"
        data, _ = self._request("POST", path, body=body)
        return Repository.from_api(data)

    def update_description(self, owner: str, name: str, description: str) -> Repository:
        """Change the repository description."""
        data, _ = self._request("PATCH", f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
                                body={"description": description})
        return Repository.from_api(data)

    def list_branches(self, owner: str, name: str, limit: int = 100) -> List[str]:
        """Branch names of a repository."""
        raw = self._paginate(f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/branches", {}, limit)
        return [b.get("name", "") for b in raw]

    def list_commits(self, owner: str, name: str, branch: Optional[str] = None, limit: int = 20) -> List[Dict[str, str]]:
        """Recent commits of a repository."""
        params = {"sha": branch} if branch else {}
        raw = self._paginate(f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/commits", params, limit)
        return [{"sha": c.get("sha", "")[:7], "author": ((c.get("commit") or {}).get("author") or {}).get("name", ""),
                 "date": ((c.get("commit") or {}).get("author") or {}).get("date", ""),
                 "message": ((c.get("commit") or {}).get("message") or "").splitlines()[0] if c.get("commit") else ""}
                for c in raw]

    def permissions(self, owner: str, name: str) -> Dict[str, bool]:
        """Permissions of the authenticated user on a repository."""
        return self.get_repo(owner, name).permissions

    # ---------------------------------------------------------- device flow
    def request_device_code(self, client_id: str, scope: str = "repo", web_url: str = "https://github.com") -> Dict[str, Any]:
        """Start OAuth Device Flow (requires the user's own OAuth App client id)."""
        if not client_id:
            raise GitHubAuthError("OAuth Device Flow requires github.oauth_client_id in the configuration")
        data, _ = self._request("POST", "", body={"client_id": client_id, "scope": scope}, auth_required=False,
                                full_url=f"{web_url.rstrip('/')}/login/device/code")
        return data or {}

    def poll_device_token(self, client_id: str, device_code: str, interval: int = 5, expires_in: int = 900,
                          web_url: str = "https://github.com", sleep: Callable[[float], None] = time.sleep) -> str:
        """Poll until the user authorises the device; returns the access token."""
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            sleep(interval)
            data, _ = self._request("POST", "", auth_required=False,
                                    body={"client_id": client_id, "device_code": device_code,
                                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
                                    full_url=f"{web_url.rstrip('/')}/login/oauth/access_token")
            data = data or {}
            if data.get("access_token"):
                return str(data["access_token"])
            error = data.get("error")
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                raise GitHubAuthError(f"device flow failed: {data.get('error_description') or error}")
        raise GitHubAuthError("device flow expired before authorisation")

"""Tests for the GitHub client using a fake transport (no network, no real account)."""

from __future__ import annotations

import io
import json
import os
import urllib.error
from email.message import Message
from typing import Any, Dict, List

import pytest

from gitflow_assistant.core.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubRateLimitError,
    parse_github_remote,
    web_url_for_remote,
)


class FakeResponse:
    def __init__(self, data: Any, headers: Dict[str, str]) -> None:
        self._raw = json.dumps(data).encode()
        self.headers = headers

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeOpener:
    def __init__(self, responses: List[Any]) -> None:
        self.responses = responses
        self.requests: List[Any] = []

    def __call__(self, request, timeout):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def http_error(code: int, body: Dict[str, Any], headers: Dict[str, str]) -> urllib.error.HTTPError:
    msg = Message()
    for k, v in headers.items():
        msg[k] = v
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", msg, io.BytesIO(json.dumps(body).encode()))


def test_parse_remote_urls() -> None:
    assert parse_github_remote("https://github.com/octo/hello.git") == ("octo", "hello")
    assert parse_github_remote("git@github.com:octo/hello.git") == ("octo", "hello")
    assert parse_github_remote("https://user:tok@github.com/octo/hello") == ("octo", "hello")
    assert parse_github_remote("https://gitlab.com/octo/hello") is None
    assert web_url_for_remote("git@github.com:a/b.git") == "https://github.com/a/b"


def test_requires_token() -> None:
    with pytest.raises(GitHubAuthError):
        GitHubClient(None).user()


def test_create_repo_request() -> None:
    opener = FakeOpener([FakeResponse({"full_name": "me/x", "name": "x", "owner": {"login": "me"}, "private": True,
                                       "clone_url": "https://github.com/me/x.git", "html_url": "https://github.com/me/x"},
                                      {"X-RateLimit-Remaining": "4999"})])
    client = GitHubClient("tkn", opener=opener)
    repo = client.create_repo("x", private=True, description="d")
    sent = opener.requests[0]
    assert sent.get_method() == "POST" and sent.full_url.endswith("/user/repos")
    assert json.loads(sent.data) == {"name": "x", "private": True, "description": "d", "auto_init": False}
    assert sent.headers["Authorization"] == "Bearer tkn"
    assert repo.private and client.rate_remaining == 4999


def test_pagination_follows_link_header() -> None:
    page1 = FakeResponse([{"full_name": "me/a", "name": "a"}], {"Link": '<https://api.github.com/user/repos?page=2>; rel="next"'})
    page2 = FakeResponse([{"full_name": "me/b", "name": "b"}], {})
    opener = FakeOpener([page1, page2])
    repos = GitHubClient("t", opener=opener).list_repos(limit=10)
    assert [r.name for r in repos] == ["a", "b"] and len(opener.requests) == 2


def test_rate_limit_and_auth_errors() -> None:
    limited = FakeOpener([http_error(403, {"message": "API rate limit exceeded"},
                                     {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"})])
    with pytest.raises(GitHubRateLimitError) as info:
        GitHubClient("t", opener=limited).user()
    assert info.value.reset_at == 1700000000
    bad = FakeOpener([http_error(401, {"message": "Bad credentials"}, {})])
    with pytest.raises(GitHubAuthError):
        GitHubClient("t", opener=bad).user()


def test_device_flow_polling() -> None:
    opener = FakeOpener([FakeResponse({"error": "authorization_pending"}, {}),
                         FakeResponse({"error": "slow_down"}, {}),
                         FakeResponse({"access_token": "gho_x"}, {})])
    sleeps: List[float] = []
    token = GitHubClient(None, opener=opener).poll_device_token("cid", "dev", interval=1, sleep=sleeps.append)
    assert token == "gho_x" and sleeps == [1, 1, 6]
    with pytest.raises(GitHubAuthError):
        GitHubClient(None).request_device_code("")


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("GITFLOW_NETWORK_TESTS"), reason="set GITFLOW_NETWORK_TESTS=1 and GITHUB_TOKEN")
def test_real_api_user() -> None:
    client = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    assert client.user().get("login")

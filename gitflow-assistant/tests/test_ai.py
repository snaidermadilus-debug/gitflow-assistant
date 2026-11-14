"""Tests for the Gemini integration using a fake transport (no network, no real key)."""

from __future__ import annotations

import io
import json
import os
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any, List

import pytest

from conftest import git
from gitflow_assistant.core.gemini_client import GeminiClient, GeminiError, text_from_response
from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.services.ai_service import AIAssistant, clean_commit_message, sanitize_diff
from gitflow_assistant.services.errors import UsageError
from gitflow_assistant.services.upload_service import PublishOptions, commit_step


def answer(text: str) -> Any:
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def read(self): return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]},
                                                           "finishReason": "STOP"}]}).encode()
    return R()


class Opener:
    def __init__(self, items: List[Any]) -> None:
        self.items, self.requests = items, []

    def __call__(self, request, timeout):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "e", Message(), io.BytesIO(b'{"error":{"message":"quota"}}'))


def test_request_format_and_retry() -> None:
    opener = Opener([http_error(429), answer("feat: add login")])
    client = GeminiClient("KEY", opener=opener, sleep=lambda s: None)
    assert client.generate("diff", "sys") == "feat: add login"
    req = opener.requests[-1]
    assert req.full_url.endswith("/models/gemini-3.1-pro-preview:generateContent")
    assert req.headers["X-goog-api-key"] == "KEY"
    body = json.loads(req.data)
    assert body["contents"][0]["parts"][0]["text"] == "diff"
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "low"
    assert "KEY" not in req.full_url


def test_errors_are_raised() -> None:
    with pytest.raises(GeminiError) as info:
        GeminiClient("K", opener=Opener([http_error(403)]), retries=0).generate("x", "s")
    assert info.value.status == 403
    with pytest.raises(GeminiError):
        text_from_response({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(GeminiError):
        text_from_response({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})
    with pytest.raises(GeminiError):
        GeminiClient("")


def test_sanitize_diff_removes_sensitive_data() -> None:
    diff = ("diff --git a/.env b/.env\n+DB_PASSWORD=supersecretvalue\n"
            "diff --git a/app.py b/app.py\n+token = \"ghp_" + "A" * 36 + "\"\n+print('ok')\n")
    prepared = sanitize_diff(diff, 10_000)
    assert prepared.excluded_files == [".env"] and prepared.files == ["app.py"]
    assert "ghp_" not in prepared.text and "supersecret" not in prepared.text and "print('ok')" in prepared.text
    assert prepared.masked_values == 1
    assert sanitize_diff("diff --git a/x b/x\n" + "+a\n" * 5000, 100).truncated


def test_clean_commit_message() -> None:
    assert clean_commit_message("```\nfeat(cli): add scan\n```") == "feat(cli): add scan"
    assert clean_commit_message('Commit message: "fix: typo"') == "fix: typo"
    with pytest.raises(UsageError):
        clean_commit_message("   ")


def test_ai_commit_flow_with_consent(repo: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    (repo / "login.py").write_text("def login():\n    return True\n", encoding="utf-8")
    opener = Opener([answer("feat: add login helper")])
    ctx = make_ctx(interactive=False, project=repo, assume_yes=True)
    import gitflow_assistant.services.upload_service as upload

    original = upload._ai
    upload._ai = lambda c: AIAssistant(c, GeminiClient("K", opener=opener))  # type: ignore[assignment]
    try:
        outcome = commit_step(ctx, GitEngine(repo), PublishOptions(all_files=True, ai=True))
    finally:
        upload._ai = original
    assert outcome and outcome.message == "feat: add login helper"
    assert git(repo, "log", "-1", "--format=%s").strip() == "feat: add login helper"
    sent = json.loads(opener.requests[0].data)["contents"][0]["parts"][0]["text"]
    assert "login.py" in sent


def test_ai_requires_consent_in_batch_mode(repo: Path, make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(interactive=False, project=repo)
    assistant = AIAssistant(ctx, GeminiClient("K", opener=Opener([])))
    with pytest.raises(UsageError):
        assistant.summarize("diff --git a/a b/a\n+x\n")


def test_ai_unavailable_without_key(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(interactive=False)
    assert not AIAssistant(ctx).available()
    with pytest.raises(UsageError):
        AIAssistant(ctx).client()


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("GITFLOW_NETWORK_TESTS") or not os.environ.get("GEMINI_API_KEY"),
                    reason="set GITFLOW_NETWORK_TESTS=1 and GEMINI_API_KEY")
def test_real_gemini_models() -> None:
    assert GeminiClient(os.environ["GEMINI_API_KEY"]).list_models()

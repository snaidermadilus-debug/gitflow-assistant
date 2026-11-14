"""Tests for the Gemini integration using a fake transport (no network, no real key)."""

from __future__ import annotations

import argparse
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
from gitflow_assistant.interface.commands import cmd_ai
from gitflow_assistant.interface.cli_parser import build_parser
from gitflow_assistant.interface.output import Output
from gitflow_assistant.interface.prompts import ConsoleUI
from gitflow_assistant.interface.tui_menu import Menu
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


def test_generate_chat_sends_full_history() -> None:
    opener = Opener([answer("Você perguntou sobre Python.")])
    client = GeminiClient("KEY", opener=opener, sleep=lambda _: None)
    history = [{"role": "user", "text": "Oi"}, {"role": "model", "text": "Olá!"},
               {"role": "user", "text": "O que eu perguntei?"}]
    assert client.generate_chat(history, "system") == "Você perguntou sobre Python."
    payload = json.loads(opener.requests[0].data)
    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": "Oi"}]},
        {"role": "model", "parts": [{"text": "Olá!"}]},
        {"role": "user", "parts": [{"text": "O que eu perguntei?"}]},
    ]


class ChatClient:
    def __init__(self) -> None:
        self.calls: List[List[dict]] = []

    def generate_chat(self, messages, system):  # type: ignore[no-untyped-def]
        self.calls.append([dict(message) for message in messages])
        return f"Resposta {len(self.calls)}"


class RateLimitedChatClient(ChatClient):
    def generate_chat(self, messages, system):  # type: ignore[no-untyped-def]
        self.calls.append([dict(message) for message in messages])
        if len(self.calls) == 1:
            raise GeminiError(429, "quota")
        return "Agora funcionou."


def _run_chat(ctx, monkeypatch, client: ChatClient) -> int:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(AIAssistant, "client", lambda self: client)
    return cmd_ai(ctx, argparse.Namespace(action="chat"))


def test_chat_keeps_history_and_exits_cleanly(make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(["Oi", "Qual foi a minha primeira mensagem?", "/sair"])
    ctx.config.set("ai.confirm_send", False)
    client = ChatClient()

    assert _run_chat(ctx, monkeypatch, client) == 0
    assert [len(call) for call in client.calls] == [1, 3]
    assert client.calls[1][0]["text"] == "Oi"
    assert client.calls[1][1] == {"role": "model", "text": "Resposta 1"}
    assert "Chat ended." in ctx.ui.text()


def test_chat_clear_discards_history(make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(["antes", "/limpar", "depois", "/sair"])
    ctx.config.set("ai.confirm_send", False)
    client = ChatClient()

    assert _run_chat(ctx, monkeypatch, client) == 0
    assert [len(call) for call in client.calls] == [1, 1]
    assert client.calls[1][0]["text"] == "depois"
    assert "Conversation history cleared." in ctx.ui.text()


def test_chat_recovers_after_rate_limit(make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(["pergunta", "tente novamente", "/sair"])
    ctx.config.set("ai.confirm_send", False)
    client = RateLimitedChatClient()

    assert _run_chat(ctx, monkeypatch, client) == 0
    assert [len(call) for call in client.calls] == [1, 1]
    assert "quota" in ctx.ui.text()
    assert "Agora funcionou." in ctx.ui.text()


def test_chat_file_context_is_confined_and_redacted(repo: Path, make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text(
        'print("safe")\npassword = "this-is-a-high-entropy-secret-value"\n', encoding="utf-8"
    )
    (repo / ".env").write_text("API_KEY=never-send-this\n", encoding="utf-8")
    ctx = make_ctx(["/arquivo src/app.py", "/sair"], project=repo)
    ctx.config.set("ai.confirm_send", False)
    client = ChatClient()

    assert _run_chat(ctx, monkeypatch, client) == 0
    sent = client.calls[0][0]["text"]
    assert 'print("safe")' in sent
    assert "high-entropy-secret-value" not in sent
    assert "never-send-this" not in sent
    assert "src/app.py" in sent


def test_chat_repo_context_includes_structure_and_status_without_env(repo: Path, make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('safe')\n", encoding="utf-8")
    (repo / ".env").write_text("TOKEN=do-not-send\n", encoding="utf-8")
    ctx = make_ctx(["/repo", "/sair"], project=repo)
    ctx.config.set("ai.confirm_send", False)
    client = ChatClient()

    assert _run_chat(ctx, monkeypatch, client) == 0
    sent = client.calls[0][0]["text"]
    assert "Structure" in sent and "src/app.py" in sent
    assert "Git status" in sent and ".env" not in sent
    assert "do-not-send" not in sent


def test_chat_blocks_env_and_outside_paths(repo: Path, make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    outside = repo.parent / "outside.txt"
    outside.write_text("not project data", encoding="utf-8")
    (repo / ".env").write_text("KEY=do-not-send\n", encoding="utf-8")
    ctx = make_ctx(["/arquivo .env", f"/arquivo {outside}", "/sair"], project=repo)
    ctx.config.set("ai.confirm_send", False)
    client = ChatClient()

    assert _run_chat(ctx, monkeypatch, client) == 0
    assert not client.calls
    assert "Sensitive files and Git metadata" in ctx.ui.text()
    assert "outside the project" in ctx.ui.text()


def test_chat_requires_a_configured_gemini_key(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(["/sair"])
    with pytest.raises(UsageError, match="No Gemini API key"):
        cmd_ai(ctx, argparse.Namespace(action="chat"))


def test_chat_parser_and_option_15_label() -> None:
    args = build_parser().parse_args(["ai", "chat"])
    assert args.command == "ai" and args.action == "chat"
    from gitflow_assistant.i18n import set_language, t

    set_language("pt")
    assert t("menu.15") == "Conversar com Gemini"


def test_tui_option_15_starts_chat(repo: Path, make_ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(project=repo)
    stream = io.StringIO()
    answers = iter(["15", "/sair", "", "0"])
    ctx.ui = ConsoleUI(Output(color=False, stream=stream), True, reader=lambda _: next(answers))
    client = ChatClient()
    monkeypatch.setattr(AIAssistant, "client", lambda self: client)

    assert Menu(ctx).loop() == 0
    rendered = stream.getvalue()
    assert "[15] Chat with Gemini" in rendered
    assert "Chat ended." in rendered


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

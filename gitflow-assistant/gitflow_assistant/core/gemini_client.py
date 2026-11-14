"""Google Gemini REST client (standard library only).

* Endpoint: ``POST {base}/models/{model}:generateContent``
* Authentication: ``x-goog-api-key`` header with the *user's own* key
  (``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` or the OS keyring). No key is
  embedded in the code.
* 429 and transient network failures are retried with capped backoff.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.1-pro-preview"
FAST_MODEL = "gemini-3.1-flash-lite"


class GeminiError(RuntimeError):
    """Gemini API failure. ``status`` is 0 for network/configuration errors."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Gemini {('HTTP ' + str(status)) if status else 'error'}: {message}")
        self.status = status


Opener = Callable[[urllib.request.Request, int], Any]


def _default_opener(request: urllib.request.Request, timeout: int) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - fixed https endpoint


def text_from_response(response: Dict[str, Any]) -> str:
    """Extract the final text, raising on blocked prompts or empty answers."""
    feedback = response.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise GeminiError(200, f"prompt blocked: {feedback['blockReason']}")
    candidates = response.get("candidates") or []
    if not candidates:
        raise GeminiError(200, "no candidates returned")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    answer = "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))
    if not answer.strip():
        raise GeminiError(200, f"empty answer (finishReason={candidate.get('finishReason')})")
    return answer.strip()


class GeminiClient:
    """Minimal ``generateContent`` / ``models.list`` client."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: int = 90, retries: int = 3,
                 base_url: str = BASE_URL, opener: Opener = _default_opener,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key:
            raise GeminiError(0, "missing API key (set GEMINI_API_KEY)")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.base_url = base_url.rstrip("/")
        self._opener = opener
        self._sleep = sleep

    def _call(self, method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method,
                                         headers={"Content-Type": "application/json",
                                                  "x-goog-api-key": self.api_key})
        for attempt in range(self.retries + 1):
            try:
                with self._opener(request, self.timeout) as response:
                    raw = response.read()
                    return json.loads(raw.decode("utf-8")) if raw else {}
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace") if exc.fp else ""
                if exc.code in (429, 500, 503) and attempt < self.retries:
                    self._sleep(min(2 ** attempt, 8))
                    continue
                try:
                    message = json.loads(text).get("error", {}).get("message", text[:300])
                except (ValueError, AttributeError):
                    message = text[:300] or str(exc.reason)
                raise GeminiError(exc.code, message) from exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if attempt < self.retries:
                    self._sleep(min(2 ** attempt, 8))
                    continue
                raise GeminiError(0, f"network failure: {getattr(exc, 'reason', exc)}") from exc
        raise GeminiError(0, "request failed after retries")

    def generate(self, prompt: str, system: str, max_output_tokens: int = 512, temperature: float = 0.2,
                 thinking_level: Optional[str] = "low") -> str:
        """Generate text for ``prompt`` with a system instruction."""
        config: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        if thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": thinking_level}
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": system}]}, "generationConfig": config}
        return text_from_response(self._call("POST", f"{self.base_url}/models/{self.model}:generateContent", body))

    def generate_chat(self, messages: Sequence[Dict[str, str]], system: str, max_output_tokens: int = 4096,
                      temperature: float = 0.7, thinking_level: Optional[str] = "low") -> str:
        """Generate a reply from a complete user/model conversation history."""
        if not messages:
            raise GeminiError(0, "chat history is empty")
        contents = []
        for message in messages:
            role, text = message.get("role"), message.get("text", "")
            if role not in ("user", "model") or not text.strip():
                raise GeminiError(0, "invalid chat history")
            contents.append({"role": role, "parts": [{"text": text}]})
        config: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        if thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": thinking_level}
        body = {"contents": contents, "systemInstruction": {"parts": [{"text": system}]},
                "generationConfig": config}
        return text_from_response(self._call("POST", f"{self.base_url}/models/{self.model}:generateContent", body))

    def list_models(self) -> List[str]:
        """Model ids that support ``generateContent``."""
        data = self._call("GET", f"{self.base_url}/models?pageSize=200")
        return sorted((m.get("baseModelId") or m.get("name", "").replace("models/", ""))
                      for m in data.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))

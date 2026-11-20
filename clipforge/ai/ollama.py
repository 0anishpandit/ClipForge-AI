"""Minimal Ollama HTTP client built on the standard library (no extra deps)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from clipforge.errors import OllamaError


class OllamaClient:
    """Talks to a local Ollama server's ``/api/tags`` and ``/api/chat``."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 600,
        num_ctx: int = 8192,
        max_tokens: int = 700,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens

    def list_models(self) -> list[str] | None:
        """Names of installed models, or ``None`` if the server is unreachable."""
        request = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        return [item.get("name", "") for item in data.get("models", [])]

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Send one chat request and return the parsed JSON object reply."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
                "num_ctx": self.num_ctx,
                "num_predict": self.max_tokens,
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama HTTP error {exc.code}: {body[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(f"Could not connect to Ollama: {exc}") from exc
        except (TimeoutError, OSError) as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        text = reply.get("message", {}).get("content", "").strip()
        if not text:
            raise OllamaError("Ollama returned an empty response.")

        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Ollama returned invalid JSON: {text[:500]}") from exc

        if not isinstance(result, dict) or not isinstance(result.get("clips"), list):
            raise OllamaError("Ollama JSON does not contain a valid clips list.")
        return result

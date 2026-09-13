from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


class ChatClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        images: Sequence[str] = (),
        max_tokens: int = 4096,
    ) -> ChatResponse:
        ...


class ZenMuxClient:
    def __init__(self, api_key: str, *, base_url: str = "https://zenmux.ai/api/v1",
                 timeout: float = 180.0) -> None:
        if not api_key:
            raise ProviderError("ZENMUX_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        images: Sequence[str] = (),
        max_tokens: int = 4096,
    ) -> ChatResponse:
        content: list[Mapping[str, object]] = [{"type": "text", "text": user}]
        for image in images:
            content.append({"type": "image_url", "image_url": {"url": image}})
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content if images else user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.time()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ProviderError(self._redact(f"HTTP {error.code}: {detail[:300]}")) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ProviderError(self._redact(f"request failed: {error}")) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderError("provider returned invalid JSON") from error
        latency = time.time() - started
        try:
            choice = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("provider response is missing message content") from error
        if isinstance(choice, list):
            choice = "".join(
                str(part.get("text", "")) for part in choice if isinstance(part, Mapping))
        if choice is None:
            raise ProviderError("provider returned empty content; increase max_tokens")
        usage = data.get("usage") or {}
        return ChatResponse(
            text=str(choice),
            model=str(data.get("model", model)),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_s=latency,
        )

    def _redact(self, text: str) -> str:
        return str(text).replace(self.api_key, "[REDACTED]")

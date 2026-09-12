from __future__ import annotations

from collections.abc import Iterable
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """A provider call failed without exposing credentials."""


def redact(text: str, secrets: Iterable[str]) -> str:
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 20.0,
    *,
    secrets: Iterable[str] = (),
) -> tuple[int, dict]:
    request_headers = {"User-Agent": "codex-multi-model-orchestrator/0.1", **(headers or {})}
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ProviderError(redact(f"HTTP {error.code} from {url}: {detail}", secrets)) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ProviderError(redact(f"request to {url} failed: {error}", secrets)) from error
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ProviderError(redact(f"invalid JSON response from {url}: {error}", secrets)) from error
    if not isinstance(payload, dict):
        raise ProviderError(redact(f"provider response from {url} was not a JSON object", secrets))
    return status, payload

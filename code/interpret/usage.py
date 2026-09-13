from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .providers import ChatClient, ChatResponse


@dataclass
class UsageStats:
    calls: Counter = field(default_factory=Counter)
    prompt_tokens: Counter = field(default_factory=Counter)
    completion_tokens: Counter = field(default_factory=Counter)
    cache_hits: Counter = field(default_factory=Counter)
    total_latency_s: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, model: str, purpose: str, prompt_tokens: int,
               completion_tokens: int, latency_s: float, *, cached: bool) -> None:
        with self._lock:
            self.calls[(model, purpose)] += 1
            if cached:
                self.cache_hits[(model, purpose)] += 1
            else:
                self.prompt_tokens[(model, purpose)] += prompt_tokens
                self.completion_tokens[(model, purpose)] += completion_tokens
                self.total_latency_s += latency_s

    def summary(self) -> dict:
        rows = []
        for key in sorted(self.calls):
            model, purpose = key
            rows.append({
                "model": model,
                "purpose": purpose,
                "calls": self.calls[key],
                "cache_hits": self.cache_hits[key],
                "prompt_tokens": self.prompt_tokens[key],
                "completion_tokens": self.completion_tokens[key],
            })
        return {
            "rows": rows,
            "cached_calls": sum(self.cache_hits.values()),
            "total_calls": sum(self.calls.values()),
            "total_prompt_tokens": sum(self.prompt_tokens.values()),
            "total_completion_tokens": sum(self.completion_tokens.values()),
        }


@dataclass(frozen=True)
class Pricing:
    input_per_million: float
    output_per_million: float


FALLBACK_PRICING = {
    "meta/muse-spark-1.3-contributor": Pricing(0.10, 0.20),
    "google/gemini-3.8-flash": Pricing(0.75, 3.75),
}


def estimate_cost(stats: UsageStats, pricing: Mapping[str, Pricing]) -> dict:
    rows = {}
    for (model, purpose), calls in stats.calls.items():
        rate = pricing.get(model, Pricing(0.0, 0.0))
        prompt = stats.prompt_tokens[(model, purpose)]
        completion = stats.completion_tokens[(model, purpose)]
        cost = prompt / 1_000_000 * rate.input_per_million \
            + completion / 1_000_000 * rate.output_per_million
        rows[f"{model}|{purpose}"] = round(cost, 6)
    return {
        "by_model_purpose": rows,
        "total_usd": round(sum(rows.values()), 6),
        "cache_hits": sum(stats.cache_hits.values()),
    }


class CachingChatClient:
    def __init__(self, inner: ChatClient, *, purpose: str, stats: UsageStats,
                 cache_dir: Path | None = None) -> None:
        self.inner = inner
        self.purpose = purpose
        self.stats = stats
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def complete(self, *, model: str, system: str, user: str,
                 images: Sequence[str] = (), max_tokens: int = 4096) -> ChatResponse:
        key = self._key(model, system, user, images, max_tokens)
        cached = self._load(key)
        if cached is not None:
            response = ChatResponse(
                text=cached["text"], model=cached.get("model", model),
                prompt_tokens=int(cached.get("prompt_tokens", 0)),
                completion_tokens=int(cached.get("completion_tokens", 0)),
                latency_s=0.0)
            self.stats.record(model, self.purpose, response.prompt_tokens,
                              response.completion_tokens, 0.0, cached=True)
            return response
        response = self.inner.complete(
            model=model, system=system, user=user, images=images,
            max_tokens=max_tokens)
        self._store(key, response)
        self.stats.record(model, self.purpose, response.prompt_tokens,
                          response.completion_tokens, response.latency_s, cached=False)
        return response

    def _key(self, model: str, system: str, user: str,
             images: Sequence[str], max_tokens: int) -> str:
        digest = hashlib.sha256()
        digest.update(model.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(system.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(user.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(max_tokens).encode("utf-8"))
        for image in images:
            digest.update(b"\x00")
            digest.update(image.encode("utf-8"))
        return digest.hexdigest()

    def _path(self, key: str) -> Path | None:
        return self.cache_dir / f"{key}.json" if self.cache_dir else None

    def _load(self, key: str) -> dict | None:
        path = self._path(key)
        if path is None or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _store(self, key: str, response: ChatResponse) -> None:
        path = self._path(key)
        if path is None:
            return
        payload = {
            "text": response.text,
            "model": response.model,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

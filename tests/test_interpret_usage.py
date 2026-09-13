import json
import tempfile
import unittest
from pathlib import Path

from interpret.providers import ChatResponse
from interpret.usage import CachingChatClient, Pricing, UsageStats, estimate_cost


class FakeInner:
    def __init__(self):
        self.calls = 0

    def complete(self, *, model, system, user, images=(), max_tokens=4096):
        self.calls += 1
        return ChatResponse(
            text=json.dumps({"claims": []}), model=model, prompt_tokens=100,
            completion_tokens=50, latency_s=0.5)


class UsageTests(unittest.TestCase):
    def test_cache_hit_avoids_second_provider_call_and_records_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            stats = UsageStats()
            inner = FakeInner()
            client = CachingChatClient(
                inner, purpose="test", stats=stats, cache_dir=Path(directory))
            first = client.complete(model="m", system="s", user="u")
            second = client.complete(model="m", system="s", user="u")
            self.assertEqual(inner.calls, 1)
            self.assertEqual(first.text, second.text)
            self.assertEqual(stats.calls[("m", "test")], 2)
            self.assertEqual(stats.cache_hits[("m", "test")], 1)
            self.assertEqual(stats.prompt_tokens[("m", "test")], 100)

    def test_different_inputs_miss_the_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            stats = UsageStats()
            inner = FakeInner()
            client = CachingChatClient(
                inner, purpose="test", stats=stats, cache_dir=Path(directory))
            client.complete(model="m", system="s", user="one")
            client.complete(model="m", system="s", user="two")
            self.assertEqual(inner.calls, 2)

    def test_estimate_cost_uses_model_rates(self):
        stats = UsageStats()
        stats.record("a", "extract", 1_000_000, 1_000_000, 1.0, cached=False)
        report = estimate_cost(stats, {"a": Pricing(0.10, 0.20)})
        self.assertEqual(report["by_model_purpose"]["a|extract"], 0.3)
        self.assertEqual(report["total_usd"], 0.3)


if __name__ == "__main__":
    unittest.main()

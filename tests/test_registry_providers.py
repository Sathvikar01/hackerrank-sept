import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.providers import _extract_codex_output, discover_apinex, smoke_record
from orchestrator.registry import save_registry
from orchestrator.registry import ModelRecord


class FakeSettings:
    apinex_api_key = "secret"
    apinex_base_url = "http://127.0.0.1:9/v1"


class RegistryProviderTests(unittest.TestCase):
    def test_apinex_keeps_exact_live_id_from_models_payload(self):
        payload = {"data": [
            {"id": "gemini-3.8-flash-live-2026", "name": "Gemini 3.8 Flash"},
            {"id": "gpt-5.6-luna-live", "name": "GPT-5.6 Luna"},
            {"id": "glm-5.3-flash-live", "name": "GLM-5.3 Flash"},
        ]}
        records = discover_apinex(
            FakeSettings(),
            request_json=lambda *args, **kwargs: (200, payload),
        )
        self.assertEqual(
            {record.exact_id for record in records},
            {"gemini-3.8-flash-live-2026", "gpt-5.6-luna-live", "glm-5.3-flash-live"},
        )

    def test_registry_serialization_contains_no_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "models.json")
            save_registry(
                path,
                [{"model": "Gemini 3.8 Flash", "exact_id": "gemini-live", "reason": "ok"}],
            )
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", raw)
            self.assertEqual(json.loads(raw)[0]["exact_id"], "gemini-live")

    def test_codex_json_events_yield_the_completed_agent_message(self):
        events = "\n".join([
            '{"type":"thread.started"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"ASTRA_OUTPUT_CHECK"}}',
            '{"type":"turn.completed"}',
        ])
        self.assertEqual(_extract_codex_output(events), "ASTRA_OUTPUT_CHECK")

    def test_opencode_smoke_allows_the_live_cli_response_window(self):
        record = ModelRecord(
            "Muse Spark 1.3 Contributor", "OpenCode Go", "opencode/muse-live",
            "repo/data/task reconnaissance", "cli", False, None,
        )
        settings = type("Settings", (), {"timeout": 20.0})()
        with patch("orchestrator.providers._run_command", return_value=(0, "SMOKE_OK", "")) as run:
            result = smoke_record(record, settings, {"opencode": "opencode"})
        self.assertTrue(result.verified)
        self.assertEqual(run.call_args.kwargs["timeout"], 90.0)


if __name__ == "__main__":
    unittest.main()

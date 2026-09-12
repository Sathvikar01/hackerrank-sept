import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.config import Settings
from orchestrator.__main__ import _build_clients


class CliTests(unittest.TestCase):
    def test_help_is_json_safe_and_does_not_print_environment_values(self):
        completed = subprocess.run(
            [sys.executable, "-m", "orchestrator", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("discover", completed.stdout)
        self.assertNotIn("APINEX_API_KEY=", completed.stdout)

    def test_invalid_command_returns_nonzero_json_error(self):
        completed = subprocess.run(
            [sys.executable, "-m", "orchestrator", "unknown"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["status"], "error")

    def test_gemini_client_uses_longer_orchestration_timeout(self):
        records = [{
            "model": "Gemini 3.8 Flash", "provider": "APInex", "exact_id": "free/gemini",
            "role": "orchestration", "transport": "https", "verified": True, "reason": None,
        }]
        settings = Settings(Path.cwd(), "secret", "https://example.test/v1", timeout=20.0)
        with patch("orchestrator.__main__._post_chat", return_value="ok") as posted:
            _build_clients(records, settings).gemini("system", "user")
        self.assertEqual(posted.call_args.args[0].timeout, 90.0)

    def test_apinex_specialists_use_longer_response_window(self):
        records = [{
            "model": "Gemini 3.8 Flash", "provider": "APInex", "exact_id": "free/gemini",
            "role": "orchestration", "transport": "https", "verified": True, "reason": None,
        }, {
            "model": "GPT-5.6 Luna", "provider": "APInex", "exact_id": "free/luna",
            "role": "independent evaluation", "transport": "https", "verified": True, "reason": None,
        }]
        settings = Settings(Path.cwd(), "secret", "https://example.test/v1", timeout=20.0)
        with patch("orchestrator.__main__._post_chat", return_value="ok") as posted:
            _build_clients(records, settings).specialists["free/luna"]({"instruction": "evaluate"})
        self.assertEqual(posted.call_args.args[0].timeout, 90.0)


if __name__ == "__main__":
    unittest.main()

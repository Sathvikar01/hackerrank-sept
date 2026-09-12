from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.config import load_settings
from orchestrator.transport import redact, request_json


class ConfigTransportTests(unittest.TestCase):
    def test_process_environment_wins_over_dotenv_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "apinex_api_key=file-secret\napinex_base_url=https://file.example/v1\n",
                encoding="utf-8",
            )
            old = os.environ.get("APINEX_API_KEY")
            os.environ["APINEX_API_KEY"] = "process-secret"
            try:
                settings = load_settings(Path(directory))
                self.assertEqual(settings.apinex_api_key, "process-secret")
                self.assertNotIn("process-secret", repr(settings))
            finally:
                if old is None:
                    os.environ.pop("APINEX_API_KEY", None)
                else:
                    os.environ["APINEX_API_KEY"] = old

    def test_redact_removes_secret_from_provider_error(self):
        self.assertEqual(
            redact("token=abc body=abc", ["abc"]),
            "token=[REDACTED] body=[REDACTED]",
        )

    def test_http_transport_sets_a_normal_user_agent(self):
        class Response:
            status = 200

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("orchestrator.transport.urlopen", return_value=Response()) as opened:
            request_json("GET", "https://example.test/models")
        self.assertEqual(
            opened.call_args.args[0].get_header("User-agent"),
            "codex-multi-model-orchestrator/0.1",
        )


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from interpret.extractor import EvidenceExtractor
from interpret.providers import ZenMuxClient

from tests import finance_fixtures as ff

REPO_ROOT = Path(__file__).parents[1]


def _load_key() -> str | None:
    key = os.environ.get("ZENMUX_API_KEY")
    if key:
        return key
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ZENMUX_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


KEY = _load_key()
LIVE = os.environ.get("RUN_LIVE_MODEL_TESTS") == "1" and bool(KEY)


@unittest.skipUnless(LIVE, "set RUN_LIVE_MODEL_TESTS=1 and ZENMUX_API_KEY to run")
class LiveExtractionTests(unittest.TestCase):
    def _client(self) -> ZenMuxClient:
        return ZenMuxClient(
            KEY, base_url=os.environ.get("ZENMUX_BASE_URL", "https://zenmux.ai/api/v1"))

    def test_live_payslip_image_amount(self):
        scope = ff.scope(
            images=[ff.image(
                image_id="image_01", user_id="user_03", request_id=None,
                related_event_id="event_253")],
            dataset_root=REPO_ROOT / "dataset")
        link = scope.images[0]
        extractor = EvidenceExtractor(
            self._client(), model="meta/muse-spark-1.3-contributor", max_tokens=8192)
        extraction = extractor.extract_image(scope, link, event_ref="event_253")
        amounts = [claim.value for claim in extraction.claims if claim.field == "amount"]
        self.assertTrue(
            any(value == Decimal("4365000") for value in amounts),
            f"claims={extraction.claims}")

    def test_live_message_extraction(self):
        message = ff.message(
            message_id="message_01",
            text="Your scheduled payment has been amended to ZAR 50000 on 2026-01-10.")
        scope = ff.scope(messages=[message])
        extractor = EvidenceExtractor(
            self._client(), model="meta/muse-spark-1.3-contributor", max_tokens=8192)
        extraction = extractor.extract_message(scope, message)
        amounts = [claim.value for claim in extraction.claims if claim.field == "amount"]
        self.assertTrue(
            any(value == Decimal("50000") for value in amounts),
            f"claims={extraction.claims}")


if __name__ == "__main__":
    unittest.main()

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "code"))

from evaluation.reports import build_evaluation_result, write_artifacts


class EvaluationReportTests(unittest.TestCase):
    def test_artifacts_are_machine_readable_human_readable_and_deterministic(self):
        metrics = {"amount": {"exact_accuracy": 1.0}}
        with tempfile.TemporaryDirectory() as directory:
            first = build_evaluation_result("candidate.csv", metrics, [], {"status": "unavailable"})
            paths = write_artifacts(first, Path(directory))
            second = build_evaluation_result("candidate.csv", metrics, [], {"status": "unavailable"})
            self.assertEqual(first, second)
            self.assertEqual(json.loads(paths.results.read_text(encoding="utf-8")), first)
            self.assertIn("unavailable", paths.usage_report.read_text(encoding="utf-8"))
            self.assertIn("Evaluation report", paths.report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

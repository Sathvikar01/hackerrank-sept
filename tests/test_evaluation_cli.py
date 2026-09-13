import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation",
]


class EvaluationCliTests(unittest.TestCase):
    def _write_output_only_candidate(self, path, malformed=False):
        with Path(ROOT, "dataset", "sample_requests.csv").open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        with Path(path).open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for row in rows:
                output = {key: row[key] for key in OUTPUT_COLUMNS}
                if malformed and output["amount_safe_to_pay"] == "25256":
                    output["amount_safe_to_pay"] = "NaN"
                writer.writerow(output)

    def test_public_self_comparison_does_not_bypass_unresolved_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory, "candidate.csv")
            artifacts = Path(directory, "artifacts")
            self._write_output_only_candidate(candidate)
            completed = subprocess.run([
                sys.executable, str(ROOT / "code" / "evaluation" / "main.py"),
                "--candidate", str(candidate), "--gold", str(ROOT / "dataset" / "sample_requests.csv"),
                "--artifact-dir", str(artifacts), "--dataset-dir", str(ROOT / "dataset"), "--strict",
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
            result = json.loads((artifacts / "results.json").read_text(encoding="utf-8"))
            self.assertTrue(result["validation"]["valid"])
            self.assertEqual(result["metrics"]["structured"]["first_seven_field_exact_accuracy"], 1.0)
            self.assertFalse(result["hard_targets"]["hard_safety_target_met"])
            self.assertTrue((artifacts / "results.json").exists())
            self.assertTrue((artifacts / "report.md").exists())
            self.assertTrue((artifacts / "evaluator_usage_report.md").exists())

    def test_dataset_runner_order_helper_preserves_csv_order(self):
        sys.path.insert(0, str(ROOT / "code"))
        from evaluation.dataset_run import ordered_request_ids

        class DatasetOrder:
            requests = {"request_02": object(), "request_01": object()}

        self.assertEqual(
            ordered_request_ids(DatasetOrder()), ["request_02", "request_01"])

    def test_malformed_candidate_returns_nonzero_without_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory, "candidate.csv")
            artifacts = Path(directory, "artifacts")
            self._write_output_only_candidate(candidate, malformed=True)
            completed = subprocess.run([
                sys.executable, str(ROOT / "code" / "evaluation" / "main.py"),
                "--candidate", str(candidate), "--gold", str(ROOT / "dataset" / "sample_requests.csv"),
                "--artifact-dir", str(artifacts), "--dataset-dir", str(ROOT / "dataset"),
            ], capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("invalid", completed.stdout.lower())

    def test_named_baseline_comparison_is_written_to_results(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory, "candidate.csv")
            artifacts = Path(directory, "artifacts")
            self._write_output_only_candidate(candidate)
            completed = subprocess.run([
                sys.executable, str(ROOT / "code" / "evaluation" / "main.py"),
                "--candidate", str(candidate), "--gold", str(ROOT / "dataset" / "sample_requests.csv"),
                "--comparison", f"baseline={candidate}", "--artifact-dir", str(artifacts),
                "--dataset-dir", str(ROOT / "dataset"), "--strict",
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
            self.assertIn("baseline", (artifacts / "results.json").read_text(encoding="utf-8"))

    def test_gold_mismatches_receive_frozen_failure_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory, "candidate.csv")
            artifacts = Path(directory, "artifacts")
            self._write_output_only_candidate(candidate)
            rows = []
            with candidate.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["amount_safe_to_pay"] = "25255"
            with candidate.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            completed = subprocess.run([
                sys.executable, str(ROOT / "code" / "evaluation" / "main.py"),
                "--candidate", str(candidate), "--gold", str(ROOT / "dataset" / "sample_requests.csv"),
                "--artifact-dir", str(artifacts), "--dataset-dir", str(ROOT / "dataset"),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads((artifacts / "results.json").read_text(encoding="utf-8"))
            mismatch = next(item for item in result["failures"] if item["request_id"] == "request_01")
            self.assertIn("State reconstruction", mismatch["categories"])


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "code"))

from evaluation.failures import classify_failures
from evaluation.schema import ValidationIssue
from evaluation.safety import SafetyIssue


class EvaluationFailureTests(unittest.TestCase):
    def test_failure_codes_map_to_frozen_taxonomy(self):
        self.assertEqual(classify_failures([ValidationIssue("schema", "invalid_plan", "bad")]), ["Formatting/schema"])
        self.assertEqual(classify_failures([SafetyIssue("minimum_balance", "below floor")]), ["Forecasting"])
        self.assertEqual(classify_failures([SafetyIssue("unresolved_fx_positive", "missing rate")]), ["FX"])
        self.assertEqual(classify_failures([SafetyIssue("protected_category", "protected")]), ["Spending changes"])


if __name__ == "__main__":
    unittest.main()

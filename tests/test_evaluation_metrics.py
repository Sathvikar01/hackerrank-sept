import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "code"))

from evaluation.metrics import calculate_metrics
from evaluation.safety import SafetyResult
from evaluation.schema import ValidationResult


def row(request_id, safe, status, method, plan, earliest, changes="none", explanation="Pay USD 10 and keep USD 50 minimum."):
    return {
        "request_id": request_id, "amount_safe_to_pay": str(safe),
        "affordability_status": status, "recommended_payment_method": method,
        "payment_plan": plan, "earliest_date_for_full_payment": earliest,
        "spending_changes_needed": changes, "decision_explanation": explanation,
    }


class EvaluationMetricTests(unittest.TestCase):
    def test_amount_accuracy_errors_and_macro_f1_are_computed_from_literals(self):
        gold = [
            row("request_01", 10, "affordable_now", "full_payment", "2026-01-01:10", "2026-01-01"),
            row("request_02", 20, "not_affordable", "not_recommended", "none", ""),
        ]
        candidate = [
            row("request_01", 12, "affordable_now", "full_payment", "2026-01-01:12", "2026-01-01"),
            row("request_02", 20, "affordable_later", "wait", "2026-01-05:20", "2026-01-05"),
        ]
        safety = [SafetyResult(valid=True, plan_safe=True, minimum_balance_valid=True, deadline_valid=True)] * 2
        result = calculate_metrics(candidate, gold, ValidationResult(valid=True), safety)
        self.assertEqual(result["amount"]["exact_accuracy"], 0.5)
        self.assertEqual(result["amount"]["mean_absolute_error"], 1.0)
        self.assertEqual(result["status"]["accuracy"], 0.5)
        self.assertAlmostEqual(result["payment_method"]["macro_f1"], 1 / 3)

    def test_plan_and_structured_metrics_distinguish_syntax_safety_and_exactness(self):
        gold = [row("request_01", 10, "affordable_now", "full_payment", "2026-01-01:10", "2026-01-01")]
        candidate = [row("request_01", 10, "affordable_now", "full_payment", "2026-01-01:10", "2026-01-01")]
        safety = [SafetyResult(valid=True, plan_safe=True, minimum_balance_valid=True, deadline_valid=True,
                               supplied_option_match=True, partial_constraints_valid=True)]
        result = calculate_metrics(candidate, gold, ValidationResult(valid=True), safety)
        self.assertEqual(result["payment_plan"]["syntax_valid_rate"], 1.0)
        self.assertEqual(result["payment_plan"]["safety_valid_rate"], 1.0)
        self.assertEqual(result["structured"]["first_seven_field_exact_accuracy"], 1.0)
        self.assertEqual(result["complete_row"]["exact_match_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "code"))

from evaluation.schema import OUTPUT_COLUMNS, parse_changes, parse_plan, validate_candidate_rows


REQUESTS = [{
    "request_id": "request_01",
    "requested_amount": "100",
    "request_date": "2026-01-01",
}]


def candidate(**overrides):
    row = {
        "request_id": "request_01",
        "amount_safe_to_pay": "25",
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "partial_payment",
        "payment_plan": "2026-01-01:25|2026-01-05:75",
        "earliest_date_for_full_payment": "2026-01-05",
        "spending_changes_needed": "none",
        "decision_explanation": "Pay a part now and the remainder later.",
    }
    row.update(overrides)
    return row


class EvaluationSchemaTests(unittest.TestCase):
    def test_valid_row_parses_strict_plan_and_changes(self):
        result = validate_candidate_rows([candidate()], REQUESTS)
        self.assertTrue(result.valid)
        self.assertEqual(parse_plan(candidate()["payment_plan"])[1].amount, 75)
        self.assertEqual(parse_changes("stop:event_1|reduce_to:event_2:10")[1].amount, 10)

    def test_duplicate_request_ids_are_rejected_without_repair(self):
        result = validate_candidate_rows([candidate(), candidate()], REQUESTS)
        self.assertFalse(result.valid)
        self.assertTrue(any(issue.code == "duplicate_request_id" for issue in result.issues))

    def test_missing_and_extra_request_ids_are_rejected(self):
        result = validate_candidate_rows(
            [candidate(request_id="request_missing")], REQUESTS
        )
        codes = {issue.code for issue in result.issues}
        self.assertIn("extra_request_id", codes)
        self.assertIn("missing_request_id", codes)

    def test_invalid_amount_enum_date_and_plan_are_rejected(self):
        result = validate_candidate_rows([candidate(
            amount_safe_to_pay="NaN",
            affordability_status="maybe",
            recommended_payment_method="cash",
            payment_plan="2026-01-02:0|2026-01-01:100",
            earliest_date_for_full_payment="2026/01/05",
        )], REQUESTS)
        codes = {issue.code for issue in result.issues}
        self.assertTrue({"invalid_amount", "invalid_status", "invalid_method", "invalid_plan", "invalid_date"} <= codes)

    def test_parser_rejects_whitespace_empty_and_duplicate_change_actions(self):
        with self.assertRaises(ValueError):
            parse_plan("2026-01-01:10 |2026-01-02:90")
        with self.assertRaises(ValueError):
            parse_changes("none|stop:event_1")
        with self.assertRaises(ValueError):
            parse_changes("stop:event_1|reduce_to:event_1:5")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "code"))

from evaluation.safety import EvaluationContext, evaluate_row_safety


def context(**kwargs):
    defaults = {
        "profiles": {
            "user_01": {
                "user_id": "user_01", "home_currency": "USD",
                "current_available_balance": "100", "minimum_balance_to_keep": "50",
                "expense_categories_to_protect": "rent",
                "expense_categories_user_is_willing_to_reduce": "dining",
                "expense_categories_user_is_willing_to_stop": "streaming",
                "payment_methods_user_will_consider": "full_payment|installments|partial_payment",
                "max_installment_months": "3",
            }
        },
        "events": {},
        "options": {
            "request_01": [{
                "payment_option_id": "option_1", "request_id": "request_01",
                "payment_method": "installments", "payment_amount": "25",
                "number_of_payments": "2", "first_payment_date": "2026-01-01",
                "payment_frequency_days": "30", "financing_fee": "0", "total_payable_amount": "50",
            }]
        },
        "rates": {}, "messages": {}, "images": {}, "requests": {},
    }
    defaults.update(kwargs)
    return EvaluationContext(**defaults)


REQUEST = {
    "request_id": "request_01", "user_id": "user_01", "request_date": "2026-01-01",
    "requested_amount": "50", "desired_completion_date": "2026-02-15",
    "allows_partial_payment": "true",
}


class EvaluationSafetyTests(unittest.TestCase):
    def test_installment_plan_must_match_supplied_option_exactly(self):
        row = {
            "request_id": "request_01", "amount_safe_to_pay": "50",
            "affordability_status": "affordable_with_plan", "recommended_payment_method": "installments",
            "payment_plan": "2026-01-01:25|2026-01-31:25",
            "earliest_date_for_full_payment": "2026-01-01", "spending_changes_needed": "none",
            "decision_explanation": "Use the supplied installment option.",
        }
        result = evaluate_row_safety(row, REQUEST, context())
        self.assertTrue(result.supplied_option_match)
        self.assertTrue(result.plan_safe)

        row["payment_plan"] = "2026-01-01:24|2026-01-31:26"
        result = evaluate_row_safety(row, REQUEST, context())
        self.assertFalse(result.supplied_option_match)
        self.assertFalse(result.valid)

    def test_minimum_balance_breach_is_a_hard_safety_failure(self):
        row = {
            "request_id": "request_01", "amount_safe_to_pay": "60",
            "affordability_status": "affordable_now", "recommended_payment_method": "full_payment",
            "payment_plan": "2026-01-01:60", "earliest_date_for_full_payment": "2026-01-01",
            "spending_changes_needed": "none", "decision_explanation": "Pay in full today.",
        }
        result = evaluate_row_safety(row, REQUEST, context())
        self.assertFalse(result.minimum_balance_valid)
        self.assertIn("minimum_balance", {issue.code for issue in result.issues})

    def test_protected_or_ineligible_spending_change_fails_closed(self):
        row = {
            "request_id": "request_01", "amount_safe_to_pay": "50",
            "affordability_status": "affordable_with_plan", "recommended_payment_method": "full_payment",
            "payment_plan": "2026-01-01:50", "earliest_date_for_full_payment": "2026-01-01",
            "spending_changes_needed": "stop:event_1", "decision_explanation": "Stop rent first.",
        }
        ctx = context(events={"user_01": [{
            "event_id": "event_1", "user_id": "user_01", "event_type": "expense",
            "category": "rent", "amount": "20", "currency": "USD", "direction": "debit",
            "event_date": "2025-12-01", "settlement_date": "2025-12-01", "status": "settled",
            "flexibility": "stoppable", "minimum_allowed_amount": "",
        }]})
        result = evaluate_row_safety(row, REQUEST, ctx)
        self.assertFalse(result.change_validation.valid)
        self.assertIn("protected_category", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()

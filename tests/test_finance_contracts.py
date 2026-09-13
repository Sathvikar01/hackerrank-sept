import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance.contracts import (
    ChangeAction,
    ContractError,
    Decision,
    FinancialEvent,
    MissingAmountError,
    PaymentPlan,
    PlanEntry,
    Profile,
    ScopedRequest,
    money_to_string,
    parse_bool,
    parse_date,
    parse_decimal,
)


class ParserTests(unittest.TestCase):
    def test_missing_amount_is_never_coerced_to_zero(self):
        with self.assertRaises(MissingAmountError):
            parse_decimal("", "amount")
        with self.assertRaises(MissingAmountError):
            parse_decimal(None, "amount")
        event = FinancialEvent.from_row({
            "event_id": "event_01", "user_id": "user_01", "event_type": "expense",
            "description": "Unknown bill", "category": "utilities", "direction": "debit",
            "amount": "", "currency": "ZAR", "event_date": "2026-01-01",
            "settlement_date": "", "status": "pending", "linked_event_id": "",
            "flexibility": "fixed", "minimum_allowed_amount": "",
        })
        self.assertIsNone(event.amount)
        self.assertNotEqual(event.amount, Decimal(0))

    def test_malformed_values_fail_closed(self):
        with self.assertRaises(ContractError):
            parse_decimal("12,50", "amount")
        with self.assertRaises(ContractError):
            parse_decimal("NaN", "amount")
        with self.assertRaises(ContractError):
            parse_decimal("12.5.6", "amount")
        with self.assertRaises(ContractError):
            parse_date("01-02-2026", "request_date")
        with self.assertRaises(ContractError):
            parse_date("2026-13-01", "request_date")
        with self.assertRaises(ContractError):
            parse_bool("yes", "allows_partial_payment")
        with self.assertRaises(ContractError):
            parse_bool("1", "allows_partial_payment")

    def test_ids_currencies_and_enums_validated(self):
        base = {
            "event_id": "event_01", "user_id": "user_01", "event_type": "expense",
            "description": "Test", "category": "utilities", "direction": "debit",
            "amount": "10", "currency": "ZAR", "event_date": "2026-01-01",
            "settlement_date": "", "status": "pending", "linked_event_id": "",
            "flexibility": "fixed", "minimum_allowed_amount": "",
        }
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "event_id": "eventX"})
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "user_id": "User_01"})
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "currency": "GBP"})
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "status": "done"})
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "direction": "out"})
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "amount": "-5"})
        with self.assertRaises(ContractError):
            FinancialEvent.from_row({**base, "linked_event_id": "event_01"})

    def test_profile_and_request_scope_validation(self):
        with self.assertRaises(ContractError):
            Profile(
                user_id="user_01", home_currency="GBP",
                current_available_balance=Decimal(10),
                minimum_balance_to_keep=Decimal(1))
        with self.assertRaises(ContractError):
            Profile(
                user_id="user_01", home_currency="ZAR",
                current_available_balance=Decimal(10),
                minimum_balance_to_keep=Decimal(1),
                payment_methods=("crypto",))
        with self.assertRaises(ContractError):
            ScopedRequest(
                request_id="request_01", user_id="user_01",
                request_date=date(2026, 2, 1), request_type="purchase",
                requested_amount=Decimal(10),
                desired_completion_date=date(2026, 1, 1),
                allows_partial_payment=True, request_text="x")
        with self.assertRaises(ContractError):
            ScopedRequest(
                request_id="request_01", user_id="user_01",
                request_date=date(2026, 2, 1), request_type="gambling",
                requested_amount=Decimal(10),
                desired_completion_date=date(2026, 2, 2),
                allows_partial_payment=True, request_text="x")

    def test_plan_and_change_validation(self):
        with self.assertRaises(ContractError):
            ChangeAction(kind="reduce_to", event_id="event_01")
        with self.assertRaises(ContractError):
            ChangeAction(kind="stop", event_id="event_01", new_amount=Decimal(5))
        with self.assertRaises(ContractError):
            PaymentPlan(
                method="partial_payment", status="affordable_with_plan",
                entries=(
                    PlanEntry(date(2026, 2, 1), Decimal(5)),
                    PlanEntry(date(2026, 1, 1), Decimal(5)),
                ))
        with self.assertRaises(ContractError):
            PaymentPlan(
                method="wait", status="affordable_later",
                changes=(
                    ChangeAction.stop("event_01"),
                    ChangeAction.reduce_to("event_01", Decimal(5)),
                ))

    def test_money_formatting_trims_trailing_zeros(self):
        self.assertEqual(money_to_string(Decimal("603.30")), "603.3")
        self.assertEqual(money_to_string(Decimal("1000")), "1000")
        self.assertEqual(money_to_string(Decimal("0")), "0")
        self.assertEqual(money_to_string(Decimal("1234.567")), "1234.57")
        self.assertEqual(money_to_string(Decimal("0.5")), "0.5")

    def test_decision_serializes_the_eight_output_fields(self):
        decision = Decision(
            request_id="request_01",
            amount_safe_to_pay=Decimal("2500.50"),
            plan=PaymentPlan(
                method="partial_payment", status="affordable_with_plan",
                entries=(
                    PlanEntry(date(2026, 1, 1), Decimal("2500.50")),
                    PlanEntry(date(2026, 1, 20), Decimal("2499.50")),
                ),
                changes=(ChangeAction.stop("event_09"),),
            ),
            earliest_date_for_full_payment=date(2026, 1, 20),
            decision_explanation="Grounded explanation.",
        )
        row = decision.to_row()
        self.assertEqual(sorted(row), sorted([
            "request_id", "amount_safe_to_pay", "affordability_status",
            "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
            "spending_changes_needed", "decision_explanation",
        ]))
        self.assertEqual(row["payment_plan"], "2026-01-01:2500.5|2026-01-20:2499.5")
        self.assertEqual(row["spending_changes_needed"], "stop:event_09")

    def test_decision_with_no_plan_serializes_none_and_empty_date(self):
        decision = Decision(
            request_id="request_02",
            amount_safe_to_pay=Decimal(0),
            plan=PaymentPlan(method="not_recommended", status="not_affordable"),
            earliest_date_for_full_payment=None,
            decision_explanation="No safe plan.",
        )
        row = decision.to_row()
        self.assertEqual(row["payment_plan"], "none")
        self.assertEqual(row["spending_changes_needed"], "none")
        self.assertEqual(row["earliest_date_for_full_payment"], "")


if __name__ == "__main__":
    unittest.main()

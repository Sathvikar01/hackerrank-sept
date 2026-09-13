import unittest
from datetime import date, timedelta
from decimal import Decimal

from tests.test_evaluation_regressions import BASE, REQUEST, context, event
from evaluation.forecast import build_forecast, capacities, replay
from evaluation.safety import _future_cashflows, evaluate_row_safety
from evaluation.schema import PlanEntry


class EvaluationForecastTests(unittest.TestCase):
    def test_failed_retry_and_explicit_duplicate_are_counted_once(self):
        events = [event(event_id="failed", status="failed"),
                  event(event_id="retry", linked_event_id="failed", description="Scheduled retry"),
                  event(event_id="dup", linked_event_id="retry", description="Explicit duplicate pending charge")]
        forecast = build_forecast(REQUEST, context(events))
        self.assertEqual(sum(amount for _, amount in forecast.flows), -20)

    def test_settled_replacement_supersedes_pending_authorization(self):
        events = [event(event_id="auth", status="pending"),
                  event(event_id="settled", linked_event_id="auth", status="settled",
                        description="Settled replacement for authorization")]
        self.assertEqual(sum(amount for _, amount in build_forecast(REQUEST, context(events)).flows), -20)

    def test_link_without_lifecycle_marker_does_not_suppress_cash(self):
        events = [event(event_id="a"), event(event_id="b", linked_event_id="a", description="Another bill")]
        self.assertEqual(sum(amount for _, amount in build_forecast(REQUEST, context(events)).flows), -40)

    def test_balanced_explicit_internal_transfer_is_net_zero(self):
        events = [event(event_id="debit", category="transfer", amount="500", description="Same-holder internal transfer"),
                  event(event_id="credit", category="transfer", direction="credit", amount="500", status="settled",
                        linked_event_id="debit", description="Same-holder internal transfer")]
        self.assertTrue(evaluate_row_safety(BASE, REQUEST, context(events)).valid)

    def test_lone_internal_transfer_debit_is_reserved(self):
        ctx = context([event(category="transfer", amount="100", description="Internal transfer")])
        self.assertFalse(evaluate_row_safety(BASE, REQUEST, ctx).valid)

    def test_month_end_salary_does_not_drift_to_28_day_cadence(self):
        request = dict(REQUEST, request_date="2026-03-01")
        events = [event(event_id="jan", category="salary", direction="credit", status="settled",
                        settlement_date="2026-01-31", amount="100", description="Salary"),
                  event(event_id="feb", category="salary", direction="credit", status="settled",
                        settlement_date="2026-02-28", amount="100", description="Salary")]
        days = [day for day, _ in build_forecast(request, context(events)).flows]
        self.assertIn(date(2026, 3, 31), days)
        self.assertIn(date(2026, 4, 30), days)
        self.assertNotIn(date(2026, 3, 28), days)

    def test_pending_foreign_refund_needs_no_rate(self):
        ctx = context([event(category="refund", direction="credit", status="pending", currency="EUR", amount="")])
        self.assertEqual(_future_cashflows(REQUEST, ctx), ([], [], False))

    def test_foreign_debit_requires_exact_date_and_direction(self):
        ctx = context([event(currency="EUR", amount="10")])
        ctx.rates = {("2026-01-04", "EUR", "USD"): Decimal("2"),
                     ("2026-01-05", "USD", "EUR"): Decimal("0.5")}
        self.assertFalse(evaluate_row_safety(BASE, REQUEST, ctx).valid)
        ctx.rates[("2026-01-05", "EUR", "USD")] = Decimal("2")
        self.assertEqual(sum(amount for _, amount in _future_cashflows(REQUEST, ctx)[0]), -20)

    def test_irregular_essentials_reserve_observed_spending(self):
        events = [event(event_id=f"food_{i}", category="groceries", description="Food", amount="10",
                        status="settled", settlement_date=d)
                  for i, d in enumerate(["2025-12-08", "2025-12-10", "2025-12-30"])]
        forecast = build_forecast(REQUEST, context(events))
        self.assertEqual(forecast.flows, [(date(2026, 1, 1), Decimal(-30)),
                                          (date(2026, 1, 31), Decimal(-30)),
                                          (date(2026, 3, 2), Decimal(-30))])

    def test_capacities_agree_with_independent_payment_replay(self):
        start = date(2026, 1, 1)
        flows = [(start + timedelta(days=4), Decimal(70)),
                 (start + timedelta(days=5), Decimal(-80)),
                 (start + timedelta(days=14), Decimal(30))]
        capacity = capacities(Decimal(100), Decimal(50), start, flows)
        self.assertEqual(capacity[start], 40)
        self.assertEqual(capacity[start + timedelta(days=14)], 70)
        for day, amount in capacity.items():
            self.assertTrue(replay(Decimal(100), Decimal(50), start, flows, [PlanEntry(day, amount)])[0])
            self.assertFalse(replay(Decimal(100), Decimal(50), start, flows, [PlanEntry(day, amount + 1)])[0])

    def test_valid_partial_schedule_passes(self):
        ctx = context([event(category="salary", direction="credit", amount="70")])
        ctx.profiles["user_review"]["current_available_balance"] = "80"
        row = dict(BASE, amount_safe_to_pay="30", affordability_status="affordable_with_plan",
                   recommended_payment_method="partial_payment", earliest_date_for_full_payment="2026-01-05",
                   payment_plan="2026-01-01:30|2026-01-05:20")
        self.assertTrue(evaluate_row_safety(row, REQUEST, ctx).valid)

    def test_valid_exact_installments_pass(self):
        ctx = context()
        ctx.options[REQUEST["request_id"]] = [dict(payment_method="installments", number_of_payments="2",
            payment_amount="25", payment_frequency_days="30", first_payment_date="2026-01-01")]
        row = dict(BASE, affordability_status="affordable_with_plan", recommended_payment_method="installments",
                   payment_plan="2026-01-01:25|2026-01-31:25")
        self.assertTrue(evaluate_row_safety(row, REQUEST, ctx).valid)

    def test_negative_witness_must_use_an_eligible_method_with_changes(self):
        ctx = context([event(category="salary", direction="credit", amount="50"),
                       event(event_id="stream", category="streaming", amount="40", settlement_date="2026-01-10",
                             description="Monthly streaming", flexibility="stoppable")])
        ctx.profiles["user_review"].update(current_available_balance="80", payment_methods_user_will_consider="full_payment")
        row = dict(BASE, amount_safe_to_pay="30", affordability_status="not_affordable",
                   recommended_payment_method="not_recommended", payment_plan="none", earliest_date_for_full_payment="",
                   decision_explanation="No eligible completing plan.")
        # Full-with-changes must start today; wait cannot require changes. Inventing a
        # later full-with-changes schedule is not a valid witness against this row.
        self.assertTrue(evaluate_row_safety(row, REQUEST, ctx).valid)


if __name__ == "__main__":
    unittest.main()

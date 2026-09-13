import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from evaluation.forecast import build_forecast, capacities
from evaluation.safety import load_context
from evaluation.schema import load_csv
from finance.contracts import ChangeAction
from finance.forecast import ForecastPolicy, collect_flows, detect_recurrence, project
from finance.ingest import Dataset
from finance.planning import compute_capacity

from tests import finance_fixtures as fixtures

D = fixtures.D
POLICY = ForecastPolicy()


def totals(flows):
    result = {}
    for item in flows:
        if isinstance(item, tuple):
            day, amount = item
        else:
            day, amount = item.day, item.amount
        result[day] = result.get(day, Decimal(0)) + amount
    return result


class LifecycleTests(unittest.TestCase):
    def test_overdue_pending_debit_is_reserved_on_request_date(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="pending", amount=D("500"),
                event_date=date(2025, 12, 20), settlement_date=date(2025, 12, 20)),
        ])
        flows = totals(collect_flows(scope, POLICY))
        self.assertEqual(flows.get(date(2026, 1, 1)), D("-500"))

    def test_settled_history_is_not_replayed(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="settled", amount=D("500"),
                category="dining", description="Family dinner", flexibility="reducible",
                event_date=date(2025, 12, 20), settlement_date=date(2025, 12, 20)),
        ])
        self.assertEqual(totals(collect_flows(scope, POLICY)), {})

    def test_scheduled_unconfirmed_credit_is_not_cash(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="scheduled", direction="credit",
                event_type="income", category="windfall", description="Lucky bonus",
                amount=D("1000"), event_date=date(2026, 1, 10),
                settlement_date=date(2026, 1, 10)),
        ])
        self.assertNotIn(date(2026, 1, 10), totals(collect_flows(scope, POLICY)))

    def test_scheduled_salary_is_reserved_on_settlement_date(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="scheduled", direction="credit",
                event_type="income", category="salary", description="Confirmed salary",
                amount=D("1000"), event_date=date(2026, 1, 10),
                settlement_date=date(2026, 1, 10)),
        ])
        self.assertEqual(totals(collect_flows(scope, POLICY)).get(date(2026, 1, 10)), D("1000"))

    def test_duplicate_pending_debit_is_counted_once(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="settled", amount=D("40"),
                description="Possible duplicate card charge",
                event_date=date(2026, 1, 20), settlement_date=date(2026, 1, 20),
                linked_event_id="event_02"),
            fixtures.event(
                event_id="event_02", status="pending", amount=D("40"),
                description="Card charge", linked_event_id="event_01",
                event_date=date(2026, 1, 20), settlement_date=date(2026, 1, 20)),
        ])
        flows = totals(collect_flows(scope, POLICY))
        self.assertEqual(flows.get(date(2026, 1, 20)), D("-40"))

    def test_same_holder_internal_transfer_is_net_zero(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="scheduled", amount=D("500"),
                description="Same-holder internal transfer",
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
                linked_event_id="event_02"),
            fixtures.event(
                event_id="event_02", status="scheduled", direction="credit",
                event_type="income", amount=D("500"),
                description="Same-holder internal transfer",
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
                linked_event_id="event_01"),
        ])
        self.assertEqual(totals(collect_flows(scope, POLICY)), {})

    def test_cancelled_replacement_suppresses_linked_pending(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="settled", amount=D("75"),
                description="Settled replacement authorization",
                event_date=date(2026, 1, 8), settlement_date=date(2026, 1, 8),
                linked_event_id="event_02"),
            fixtures.event(
                event_id="event_02", status="pending", amount=D("75"),
                description="Authorization hold", linked_event_id="event_01",
                event_date=date(2026, 1, 8), settlement_date=date(2026, 1, 8)),
        ])
        flows = totals(collect_flows(scope, POLICY))
        self.assertEqual(flows.get(date(2026, 1, 8)), D("-75"))

    def test_spending_change_does_not_release_pending_debit(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="pending", amount=D("100"),
                description="Monthly rent", category="rent",
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5)),
        ])
        flows = totals(collect_flows(scope, POLICY, changes=(ChangeAction.stop("event_01"),)))
        self.assertEqual(flows.get(date(2026, 1, 5)), D("-100"))


class RecurrenceTests(unittest.TestCase):
    def _history(self, days, description="Apartment rent", category="rent", amount="1000"):
        return [
            fixtures.event(
                event_id=f"event_{index:02d}", status="settled", amount=D(amount),
                category=category, description=description,
                event_date=day, settlement_date=day)
            for index, day in enumerate(days, start=1)
        ]

    def test_two_occurrences_do_not_establish_recurrence(self):
        scope = fixtures.scope(events=self._history([date(2025, 11, 5), date(2025, 12, 5)]))
        self.assertEqual(detect_recurrence(scope, POLICY), ())

    def test_three_occurrences_project_future_occurrences(self):
        scope = fixtures.scope(events=self._history(
            [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)]))
        series = detect_recurrence(scope, POLICY)
        self.assertEqual(len(series), 1)
        self.assertIn(date(2026, 1, 5), series[0].projected_dates)

    def test_monthly_series_anchors_to_calendar_dates(self):
        scope = fixtures.scope(
            request=fixtures.request(
                request_date=date(2026, 4, 1), desired_completion_date=date(2026, 6, 1)),
            events=self._history([date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]))
        series = detect_recurrence(scope, POLICY)
        self.assertEqual(len(series), 1)
        self.assertIn(date(2026, 4, 30), series[0].projected_dates)
        self.assertNotIn(date(2026, 4, 28), series[0].projected_dates)

    def test_one_time_arrears_does_not_break_a_salary_series(self):
        history = [
            fixtures.event(
                event_id=f"event_{index:02d}", status="settled", direction="credit",
                event_type="income", category="salary", description="Payroll credit",
                amount=D("1000"), event_date=day, settlement_date=day)
            for index, day in enumerate(
                [date(2025, 10, 15), date(2025, 11, 15), date(2025, 12, 15)], start=1)
        ]
        history.append(fixtures.event(
            event_id="event_04", status="settled", direction="credit",
            event_type="income", category="salary", description="Promotion arrears payment",
            amount=D("400"), event_date=date(2025, 12, 20),
            settlement_date=date(2025, 12, 20)))
        series = detect_recurrence(fixtures.scope(events=history), POLICY)
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].typical_amount, D("1000"))
        self.assertIn(date(2026, 1, 15), series[0].projected_dates)

    def test_cancelled_occurrence_consumes_the_projection_slot(self):
        history = self._history([date(2025, 10, 15), date(2025, 11, 15), date(2025, 12, 15)])
        cancelled = fixtures.event(
            event_id="event_04", status="cancelled", amount=D("1000"),
            category="rent", description="Apartment rent",
            event_date=date(2026, 1, 15), settlement_date=date(2026, 1, 15))
        flows = totals(collect_flows(fixtures.scope(events=history + [cancelled]), POLICY))
        self.assertNotIn(date(2026, 1, 15), flows)

    def test_concrete_occurrence_consumes_the_projection_slot(self):
        history = self._history([date(2025, 10, 15), date(2025, 11, 15), date(2025, 12, 15)])
        concrete = fixtures.event(
            event_id="event_04", status="scheduled", amount=D("1000"),
            category="rent", description="Apartment rent",
            event_date=date(2026, 1, 15), settlement_date=date(2026, 1, 15))
        flows = totals(collect_flows(fixtures.scope(events=history + [concrete]), POLICY))
        self.assertEqual(flows.get(date(2026, 1, 15)), D("-1000"))


class VariableSpendingTests(unittest.TestCase):
    def test_irregular_essentials_reserve_per_category(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="settled", amount=D("200"),
                category="groceries", description="Fresh food shop",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_02", status="settled", amount=D("300"),
                category="groceries", description="Bulk pantry shop",
                event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10)),
        ])
        flows = totals(collect_flows(scope, POLICY))
        self.assertEqual(flows.get(date(2026, 1, 1)), D("-500"))
        self.assertEqual(flows.get(date(2026, 1, 31)), D("-500"))

    def test_covered_recurring_series_is_not_reserved_again(self):
        history = [
            fixtures.event(
                event_id=f"event_{index:02d}", status="settled", amount=D("1000"),
                category="rent", description="Apartment rent",
                event_date=day, settlement_date=day)
            for index, day in enumerate(
                [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)], start=1)
        ]
        flows = collect_flows(fixtures.scope(events=history), POLICY)
        self.assertFalse(any(flow.label == "variable:reserve" for flow in flows))
        self.assertTrue(any(flow.label.startswith("recurrence:") for flow in flows))

    def test_non_essential_irregular_spending_is_not_reserved(self):
        scope = fixtures.scope(events=[
            fixtures.event(
                event_id="event_01", status="settled", amount=D("200"),
                category="dining", description="Family dinner", flexibility="reducible",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_02", status="settled", amount=D("100"),
                category="dining", description="Coffee shop", flexibility="reducible",
                event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10)),
        ])
        self.assertFalse(
            any(flow.label == "variable:reserve" for flow in collect_flows(scope, POLICY)))


class CapacityTests(unittest.TestCase):
    def test_safe_amount_floors_to_two_decimals(self):
        scope = fixtures.scope(
            profile=fixtures.profile(
                current_available_balance=D("100.005"), minimum_balance_to_keep=D("0")),
            request=fixtures.request(requested_amount=D("200")))
        capacity = compute_capacity(scope, POLICY)
        self.assertEqual(capacity.amount_safe_to_pay, D("100.00"))

    def test_same_day_credit_precedes_the_planned_payment(self):
        scope = fixtures.scope(
            profile=fixtures.profile(
                current_available_balance=D("60000"), minimum_balance_to_keep=D("10000")),
            request=fixtures.request(requested_amount=D("60000")),
            events=[fixtures.event(
                event_id="event_01", status="scheduled", direction="credit",
                event_type="income", category="salary", description="Confirmed salary",
                amount=D("45000"), event_date=date(2026, 1, 10),
                settlement_date=date(2026, 1, 10))])
        capacity = compute_capacity(scope, POLICY)
        self.assertEqual(capacity.amount_safe_to_pay, D("50000"))
        self.assertEqual(capacity.earliest_full_payment_date, date(2026, 1, 10))


class EngineEvaluatorParityTests(unittest.TestCase):
    def _dataset(self, root):
        events = [
            fixtures.event(
                event_id="event_01", status="settled", amount=D("1000"),
                category="rent", description="Apartment rent",
                event_date=date(2025, 10, 5), settlement_date=date(2025, 10, 5)),
            fixtures.event(
                event_id="event_02", status="settled", amount=D("1000"),
                category="rent", description="Apartment rent",
                event_date=date(2025, 11, 5), settlement_date=date(2025, 11, 5)),
            fixtures.event(
                event_id="event_03", status="settled", amount=D("1000"),
                category="rent", description="Apartment rent",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_04", status="settled", amount=D("200"),
                category="groceries", description="Fresh food shop",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_05", status="settled", amount=D("300"),
                category="groceries", description="Bulk pantry shop",
                event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10)),
            fixtures.event(
                event_id="event_06", status="pending", amount=D("500"),
                category="utilities", description="Overdue utility bill",
                event_date=date(2025, 12, 20), settlement_date=date(2025, 12, 20)),
            fixtures.event(
                event_id="event_07", status="scheduled", direction="credit",
                event_type="income", category="windfall", description="Lottery proceeds",
                amount=D("900"), event_date=date(2026, 1, 10),
                settlement_date=date(2026, 1, 10)),
            fixtures.event(
                event_id="event_08", status="scheduled", amount=D("700"),
                description="Same-holder internal transfer",
                event_date=date(2026, 1, 12), settlement_date=date(2026, 1, 12),
                linked_event_id="event_09"),
            fixtures.event(
                event_id="event_09", status="scheduled", direction="credit",
                event_type="income", amount=D("700"),
                description="Same-holder internal transfer",
                event_date=date(2026, 1, 12), settlement_date=date(2026, 1, 12),
                linked_event_id="event_08"),
        ]
        return fixtures.write_dataset(
            Path(root),
            profiles=[fixtures.profile()],
            requests=[fixtures.request()],
            events=events)

    def test_engine_and_evaluator_forecasts_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._dataset(directory)
            dataset = Dataset.load(root)
            rows = load_csv(root / "requests.csv")
            context = load_context(root, rows)
            engine = totals(collect_flows(dataset.scope("request_01"), POLICY))
            evaluator = build_forecast(rows[0], context)
            self.assertEqual(sorted(evaluator.problems), [])
            self.assertEqual(engine, totals(evaluator.flows))

    def test_engine_and_evaluator_capacities_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._dataset(directory)
            dataset = Dataset.load(root)
            rows = load_csv(root / "requests.csv")
            context = load_context(root, rows)
            request = rows[0]
            scope = dataset.scope("request_01")
            capacity = compute_capacity(scope, POLICY)
            forecast = build_forecast(request, context)
            schedule = capacities(
                scope.profile.current_available_balance,
                scope.profile.minimum_balance_to_keep,
                scope.request.request_date,
                forecast.flows)
            expected_safe = min(
                scope.request.requested_amount,
                schedule[scope.request.request_date]).quantize(Decimal("0.01"))
            self.assertEqual(capacity.amount_safe_to_pay, expected_safe)
            expected_earliest = next(
                (day for day in sorted(schedule)
                 if schedule[day] >= scope.request.requested_amount), None)
            self.assertEqual(capacity.earliest_full_payment_date, expected_earliest)


if __name__ == "__main__":
    unittest.main()

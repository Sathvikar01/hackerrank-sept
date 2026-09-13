import unittest
from datetime import date
from decimal import Decimal
from typing import Mapping

from finance.contracts import MissingAmountError, MissingRateError
from finance.forecast import (
    CashFlow,
    ForecastPolicy,
    project,
    series_key,
)

from tests import finance_fixtures as fixtures

D = fixtures.D


class StubVariableModel:
    def __init__(self, flows):
        self.flows = flows
        self.calls = 0

    def reserve_flows(self, scope, policy):
        self.calls += 1
        return self.flows


class ForecastTests(unittest.TestCase):
    def test_settled_history_is_already_in_starting_balance(self):
        result = project(
            fixtures.scope(events=[
                fixtures.event(
                    event_id="event_01", status="settled", direction="credit",
                    amount=D("90000"), event_date=date(2025, 12, 1),
                    settlement_date=date(2025, 12, 1)),
                fixtures.event(
                    event_id="event_02", status="settled", direction="debit",
                    amount=D("20000"), event_date=date(2025, 12, 2),
                    settlement_date=date(2025, 12, 2)),
            ]),
            fixtures.no_variable_policy())
        self.assertEqual(result.start_balance, D("100000"))
        self.assertEqual(result.minimum, D("100000"))
        self.assertEqual(result.end_balance, D("100000"))

    def test_pending_debit_reserved_and_pending_credit_excluded(self):
        result = project(
            fixtures.scope(events=[
                fixtures.event(
                    event_id="event_01", status="pending", direction="debit",
                    amount=D("5000"), event_date=date(2026, 1, 5),
                    settlement_date=date(2026, 1, 5)),
                fixtures.event(
                    event_id="event_02", status="pending", direction="credit",
                    event_type="income", amount=D("7000"), event_date=date(2026, 1, 5),
                    settlement_date=date(2026, 1, 5)),
            ]),
            fixtures.no_variable_policy())
        self.assertEqual(result.minimum, D("95000"))
        self.assertEqual(result.end_balance, D("95000"))
        self.assertEqual(result.balance_on(date(2026, 1, 5)), D("95000"))

    def test_failed_cancelled_and_unrealized_events_do_not_move_cash(self):
        result = project(
            fixtures.scope(events=[
                fixtures.event(
                    event_id="event_01", status="failed", amount=D("5000"),
                    event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5)),
                fixtures.event(
                    event_id="event_02", status="cancelled", amount=D("5000"),
                    event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5)),
                fixtures.event(
                    event_id="event_03", status="unrealized", direction="non_cash",
                    event_type="investment_valuation", amount=D("5000"),
                    event_date=date(2026, 1, 5), settlement_date=None),
                fixtures.event(
                    event_id="event_04", status="scheduled", amount=D("1000"),
                    event_date=date(2026, 1, 6), settlement_date=date(2026, 1, 6)),
            ]),
            fixtures.no_variable_policy())
        self.assertEqual(result.minimum, D("99000"))

    def test_scheduled_salary_moves_on_its_settlement_date(self):
        debit = project(
            fixtures.scope(events=[fixtures.event(
                event_id="event_01", status="scheduled", amount=D("5000"),
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 10))]),
            fixtures.no_variable_policy())
        self.assertEqual(debit.balance_on(date(2026, 1, 9)), D("100000"))
        self.assertEqual(debit.balance_on(date(2026, 1, 10)), D("95000"))
        credit = project(
            fixtures.scope(events=[fixtures.event(
                event_id="event_02", status="scheduled", direction="credit",
                event_type="income", category="salary", description="Confirmed salary",
                amount=D("5000"),
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 10))]),
            fixtures.no_variable_policy())
        self.assertEqual(credit.balance_on(date(2026, 1, 9)), D("100000"))
        self.assertEqual(credit.balance_on(date(2026, 1, 10)), D("105000"))

    def test_recurrence_projects_only_with_supported_history(self):
        history = [
            fixtures.event(
                event_id=f"event_0{index}", status="settled", amount=D("1000"),
                category="rent", description="Apartment rent",
                event_date=day, settlement_date=day)
            for index, day in enumerate(
                [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)], start=1)
        ]
        result = project(
            fixtures.scope(events=history),
            fixtures.no_variable_policy())
        self.assertEqual(result.minimum, D("97000"))
        self.assertEqual(result.balance_on(date(2026, 1, 5)), D("99000"))
        threshold = project(
            fixtures.scope(events=history),
            fixtures.no_variable_policy(recurrence_min_occurrences=4))
        self.assertEqual(threshold.minimum, D("100000"))

    def test_supplied_future_occurrence_suppresses_recurrence_projection(self):
        history = [
            fixtures.event(
                event_id=f"event_0{index}", status="settled", amount=D("1000"),
                category="rent", description="Apartment rent",
                event_date=day, settlement_date=day)
            for index, day in enumerate(
                [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)], start=1)
        ]
        matching = fixtures.event(
            event_id="event_04", status="scheduled", amount=D("1000"),
            category="rent", description="Apartment rent",
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5))
        suppressed = project(
            fixtures.scope(events=history + [matching]),
            fixtures.no_variable_policy())
        self.assertEqual(suppressed.minimum, D("97000"))
        distant = fixtures.event(
            event_id="event_05", status="scheduled", amount=D("1000"),
            category="rent", description="Apartment rent",
            event_date=date(2026, 1, 9), settlement_date=date(2026, 1, 9))
        double_counted = project(
            fixtures.scope(events=history + [distant]),
            fixtures.no_variable_policy())
        self.assertEqual(double_counted.minimum, D("96000"))

    def test_foreign_currency_uses_the_dated_rate_of_the_cash_date(self):
        rates = [
            fixtures.ExchangeRate(
                rate_date=date(2026, 1, 15), from_currency="USD", to_currency="ZAR",
                rate=D("18")),
            fixtures.ExchangeRate(
                rate_date=date(2026, 2, 1), from_currency="USD", to_currency="ZAR",
                rate=D("19")),
        ]
        result = project(
            fixtures.scope(events=[fixtures.event(
                event_id="event_01", status="scheduled", amount=D("100"),
                currency="USD", event_date=date(2026, 1, 20),
                settlement_date=date(2026, 2, 1))], rates=rates),
            fixtures.no_variable_policy())
        self.assertEqual(result.balance_on(date(2026, 1, 15)), D("100000"))
        self.assertEqual(result.minimum, D("98100"))

    def test_missing_rate_and_missing_amount_fail_closed(self):
        with self.assertRaises(MissingRateError):
            project(
                fixtures.scope(events=[fixtures.event(
                    event_id="event_01", status="scheduled", amount=D("100"),
                    currency="USD", event_date=date(2026, 1, 20),
                    settlement_date=date(2026, 1, 20))]),
                fixtures.no_variable_policy())
        with self.assertRaises(MissingAmountError):
            project(
                fixtures.scope(events=[fixtures.event(
                    event_id="event_01", status="pending", amount=None,
                    event_date=date(2026, 1, 20), settlement_date=date(2026, 1, 20))]),
                fixtures.no_variable_policy())
        historical = project(
            fixtures.scope(events=[fixtures.event(
                event_id="event_02", status="settled", amount=None,
                event_date=date(2025, 12, 1), settlement_date=date(2025, 12, 1))]),
            fixtures.no_variable_policy())
        self.assertEqual(historical.minimum, D("100000"))

    def test_inverse_rate_fallback_is_a_policy_switch(self):
        rates = [fixtures.ExchangeRate(
            rate_date=date(2026, 2, 1), from_currency="ZAR", to_currency="USD",
            rate=D("0.05"))]
        allowed = project(
            fixtures.scope(events=[fixtures.event(
                event_id="event_01", status="scheduled", amount=D("100"),
                currency="USD", event_date=date(2026, 2, 1),
                settlement_date=date(2026, 2, 1))], rates=rates),
            fixtures.no_variable_policy(allow_inverse_rates=True))
        self.assertEqual(allowed.minimum, D("98000"))
        with self.assertRaises(MissingRateError):
            project(
                fixtures.scope(events=[fixtures.event(
                    event_id="event_01", status="scheduled", amount=D("100"),
                    currency="USD", event_date=date(2026, 2, 1),
                    settlement_date=date(2026, 2, 1))], rates=rates),
                fixtures.no_variable_policy(allow_inverse_rates=False))

        with self.assertRaises(MissingRateError):
            project(
                fixtures.scope(events=[fixtures.event(
                    event_id="event_01", status="scheduled", amount=D("100"),
                    currency="USD", event_date=date(2026, 2, 1),
                    settlement_date=date(2026, 2, 1))], rates=rates),
                fixtures.no_variable_policy())

    def test_horizon_endpoint_inclusion_is_a_policy_switch(self):
        event = fixtures.event(
            event_id="event_01", status="scheduled", amount=D("1000"),
            event_date=date(2026, 1, 31), settlement_date=date(2026, 1, 31))
        included = project(
            fixtures.scope(events=[event]),
            fixtures.no_variable_policy(horizon_days=30, include_horizon_end=True))
        self.assertEqual(included.minimum, D("99000"))
        excluded = project(
            fixtures.scope(events=[event]),
            fixtures.no_variable_policy(horizon_days=30, include_horizon_end=False))
        self.assertEqual(excluded.minimum, D("100000"))

    def test_same_day_ordering_is_a_policy_switch(self):
        events = [
            fixtures.event(
                event_id="event_01", status="scheduled", amount=D("5000"),
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5)),
            fixtures.event(
                event_id="event_02", status="scheduled", direction="credit",
                event_type="income", category="salary", description="Confirmed salary",
                amount=D("6000"),
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5)),
        ]
        outflows_first = project(
            fixtures.scope(events=events),
            fixtures.no_variable_policy(same_day_order="outflows_first"))
        inflows_first = project(
            fixtures.scope(events=events),
            fixtures.no_variable_policy(same_day_order="inflows_first"))
        self.assertEqual(outflows_first.minimum, D("95000"))
        self.assertEqual(inflows_first.minimum, D("100000"))

    def test_variable_spending_interface_is_pluggable(self):
        policy = fixtures.no_variable_policy(variable_spending_enabled=True)
        model = StubVariableModel([(date(2026, 1, 1), D("300"), "ZAR")])
        result = project(fixtures.scope(), policy, variable_model=model)
        self.assertEqual(result.minimum, D("99700"))
        self.assertEqual(model.calls, 1)

    def test_non_essential_irregular_spending_is_not_reserved(self):
        events = [
            fixtures.event(
                event_id="event_01", status="settled", amount=D("200"),
                category="dining", description="Dining out", flexibility="reducible",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_02", status="settled", amount=D("100"),
                category="dining", description="Dining out", flexibility="reducible",
                event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10)),
        ]
        result = project(
            fixtures.scope(events=events),
            ForecastPolicy(variable_spending_enabled=True))
        self.assertEqual(result.minimum, D("100000"))

    def test_fixed_unprotected_spending_is_not_reserved_as_variable(self):
        profile = fixtures.profile(protected_categories=("groceries",))
        events = [
            fixtures.event(
                event_id="event_01", status="settled", amount=D("200"),
                category="dining", description="Dining out", flexibility="fixed",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_02", status="settled", amount=D("100"),
                category="transport", description="Ride hail", flexibility="fixed",
                event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10)),
        ]
        result = project(
            fixtures.scope(events=events, profile=profile),
            ForecastPolicy(variable_spending_enabled=True))
        self.assertEqual(result.minimum, D("100000"))

    def test_protected_variable_spending_is_still_reserved(self):
        profile = fixtures.profile(protected_categories=("groceries",))
        events = [
            fixtures.event(
                event_id="event_01", status="settled", amount=D("200"),
                category="groceries", description="Grocery run", flexibility="fixed",
                event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            fixtures.event(
                event_id="event_02", status="settled", amount=D("100"),
                category="groceries", description="Grocery run", flexibility="fixed",
                event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10)),
        ]
        result = project(
            fixtures.scope(events=events, profile=profile),
            ForecastPolicy(variable_spending_enabled=True))
        self.assertEqual(result.minimum, D("99100"))

    def test_recurring_income_is_projected_conservatively(self):
        history = [
            fixtures.event(
                event_id=f"event_0{index}", status="settled", direction="credit",
                event_type="income", category="salary", description="Payroll credit",
                amount=D("5000"), event_date=day, settlement_date=day)
            for index, day in enumerate(
                [date(2025, 10, 15), date(2025, 11, 15), date(2025, 12, 15)], start=1)
        ]
        result = project(
            fixtures.scope(events=history),
            fixtures.no_variable_policy())
        self.assertEqual(result.end_balance, D("115000"))
        self.assertEqual(result.balance_on(date(2026, 1, 15)), D("105000"))
        self.assertEqual(result.minimum, D("100000"))

    def test_recurring_income_uses_the_minimum_amount_and_respects_confirmed_rows(self):
        history = [
            fixtures.event(
                event_id="event_01", status="settled", direction="credit",
                event_type="income", category="salary", description="Payroll credit",
                amount=D("5000"), event_date=date(2025, 10, 15),
                settlement_date=date(2025, 10, 15)),
            fixtures.event(
                event_id="event_02", status="settled", direction="credit",
                event_type="income", category="salary", description="Payroll credit",
                amount=D("6000"), event_date=date(2025, 11, 15),
                settlement_date=date(2025, 11, 15)),
            fixtures.event(
                event_id="event_03", status="settled", direction="credit",
                event_type="income", category="salary", description="Payroll credit",
                amount=D("7000"), event_date=date(2025, 12, 15),
                settlement_date=date(2025, 12, 15)),
        ]
        confirmed = fixtures.event(
            event_id="event_04", status="scheduled", direction="credit",
            event_type="income", category="salary", description="Next confirmed salary",
            amount=D("4500"), event_date=date(2026, 1, 15),
            settlement_date=date(2026, 1, 15))
        result = project(
            fixtures.scope(events=history + [confirmed]),
            fixtures.no_variable_policy())
        self.assertEqual(result.balance_on(date(2026, 1, 15)), D("104500"))
        self.assertEqual(result.end_balance, D("114500"))

    def test_scheduled_unconfirmed_credit_is_not_cash(self):
        history = [
            fixtures.event(
                event_id=f"event_0{index}", status="settled", direction="credit",
                event_type="income", category="salary", description="Payroll credit",
                amount=D("5000"), event_date=day, settlement_date=day)
            for index, day in enumerate(
                [date(2025, 10, 15), date(2025, 11, 15), date(2025, 12, 15)], start=1)
        ]
        materialized = fixtures.event(
            event_id="event_04", status="scheduled", direction="credit",
            event_type="income", category="other",
            description="obligation from obligation_message_01",
            amount=D("4500"), event_date=date(2026, 1, 15),
            settlement_date=date(2026, 1, 15))
        result = project(
            fixtures.scope(events=history + [materialized]),
            fixtures.no_variable_policy())
        self.assertEqual(result.balance_on(date(2026, 1, 15)), D("105000"))
        self.assertEqual(result.end_balance, D("115000"))

    def test_minimum_balance_breach_marks_the_forecast_unsafe(self):
        result = project(
            fixtures.scope(events=[fixtures.event(
                event_id="event_01", status="scheduled", amount=D("95000"),
                event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5))]),
            fixtures.no_variable_policy())
        self.assertFalse(result.safe)
        self.assertEqual(result.minimum, D("5000"))
        self.assertEqual(result.minimum_date, date(2026, 1, 5))


if __name__ == "__main__":
    unittest.main()

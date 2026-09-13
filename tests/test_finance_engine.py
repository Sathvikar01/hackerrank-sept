import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance.contracts import OUTPUT_COLUMNS
from finance.engine import FinancialEngine, write_output_csv
from finance.forecast import ForecastPolicy
from finance.ingest import Dataset

from tests import finance_fixtures as fixtures

D = fixtures.D
REPO_ROOT = Path(__file__).parents[1]


class EngineTests(unittest.TestCase):
    def _load(self, directory) -> Dataset:
        fixtures.write_dataset(
            directory,
            profiles=[
                fixtures.profile(
                    user_id="user_01", current_available_balance=D("100000"),
                    minimum_balance_to_keep=D("10000"),
                    payment_methods=("full_payment", "partial_payment")),
            ],
            requests=[
                fixtures.request(
                    request_id="request_01", user_id="user_01",
                    request_date=date(2026, 1, 1), requested_amount=D("5000"),
                    desired_completion_date=date(2026, 2, 1)),
            ],
            events=[
                fixtures.event(
                    event_id="event_01", user_id="user_01", status="scheduled",
                    amount=D("100"), event_date=date(2026, 1, 5),
                    settlement_date=date(2026, 1, 5)),
            ],
        )
        return Dataset.load(directory)

    def test_full_payment_decision_is_grounded_and_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FinancialEngine(self._load(directory))
            decision = engine.decide("request_01")
            self.assertEqual(decision.affordability_status, "affordable_now")
            self.assertEqual(decision.recommended_payment_method, "full_payment")
            self.assertEqual(decision.amount_safe_to_pay, D("5000"))
            self.assertEqual(
                decision.earliest_date_for_full_payment, date(2026, 1, 1))
            self.assertEqual(decision.payment_plan, "2026-01-01:5000")
            self.assertEqual(decision.spending_changes_needed, "none")
            self.assertTrue(decision.decision_explanation)

    def test_settled_history_is_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixtures.write_dataset(
                Path(directory),
                profiles=[fixtures.profile(
                    user_id="user_01", current_available_balance=D("100000"),
                    minimum_balance_to_keep=D("10000"),
                    payment_methods=("full_payment",))],
                requests=[fixtures.request(
                    request_id="request_01", user_id="user_01",
                    requested_amount=D("95000"))],
                events=[fixtures.event(
                    event_id="event_01", user_id="user_01", status="settled",
                    direction="credit", event_type="income", amount=D("90000"),
                    event_date=date(2025, 12, 1), settlement_date=date(2025, 12, 1))],
            )
            engine = FinancialEngine(Dataset.load(root))
            decision = engine.decide("request_01")
            self.assertEqual(decision.amount_safe_to_pay, D("90000"))
            self.assertNotEqual(decision.affordability_status, "affordable_now")
            self.assertEqual(decision.payment_plan, "none")

    def test_missing_amount_produces_a_conservative_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixtures.write_dataset(
                Path(directory),
                profiles=[fixtures.profile(user_id="user_01")],
                requests=[fixtures.request(
                    request_id="request_01", user_id="user_01")],
                events=[fixtures.event(
                    event_id="event_01", user_id="user_01", status="scheduled",
                    amount=None, event_date=date(2026, 1, 20),
                    settlement_date=date(2026, 1, 20))],
            )
            engine = FinancialEngine(Dataset.load(root))
            decision = engine.decide("request_01")
            self.assertEqual(decision.amount_safe_to_pay, D("0"))
            self.assertEqual(decision.affordability_status, "not_affordable")
            self.assertEqual(decision.recommended_payment_method, "not_recommended")
            self.assertIn("Unresolved evidence", decision.decision_explanation)
            self.assertTrue(decision.unresolved)

    def test_no_completing_plan_is_not_affordable_even_when_money_arrives_later(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixtures.write_dataset(
                Path(directory),
                profiles=[fixtures.profile(
                    user_id="user_01", current_available_balance=D("12000"),
                    minimum_balance_to_keep=D("10000"),
                    payment_methods=("full_payment",))],
                requests=[fixtures.request(
                    request_id="request_01", user_id="user_01",
                    request_date=date(2026, 1, 1), requested_amount=D("5000"),
                    desired_completion_date=date(2026, 1, 5),
                    allows_partial_payment=False)],
                events=[fixtures.event(
                    event_id="event_01", user_id="user_01", status="scheduled",
                    direction="credit", event_type="income", category="salary",
                    description="Payroll credit", amount=D("50000"),
                    event_date=date(2026, 1, 10),
                    settlement_date=date(2026, 1, 10))],
            )
            engine = FinancialEngine(Dataset.load(root))
            decision = engine.decide("request_01")
            self.assertEqual(decision.affordability_status, "not_affordable")
            self.assertEqual(decision.recommended_payment_method, "not_recommended")
            self.assertEqual(decision.payment_plan, "none")
            # The first safe full-payment date within the forecast is preserved
            # even though the deadline makes every plan ineligible.
            self.assertEqual(
                decision.earliest_date_for_full_payment, date(2026, 1, 10))
            self.assertIn(
                "first becomes possible on 2026-01-10",
                decision.decision_explanation)
            self.assertEqual(decision.amount_safe_to_pay, D("2000"))

    def test_installment_plan_with_spending_change_flows_through_the_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            history = []
            for index, day in enumerate(
                    [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)], start=1):
                history.append(fixtures.event(
                    event_id=f"event_1{index}", user_id="user_01", status="settled",
                    amount=D("4000"), category="dining", description="Dining out",
                    flexibility="stoppable", event_date=day, settlement_date=day))
            root = fixtures.write_dataset(
                Path(directory),
                profiles=[fixtures.profile(
                    user_id="user_01", current_available_balance=D("20000"),
                    minimum_balance_to_keep=D("10000"),
                    payment_methods=("installments",), stop_categories=("dining",),
                    max_installment_months=12)],
                requests=[fixtures.request(
                    request_id="request_01", user_id="user_01",
                    requested_amount=D("30000"), allows_partial_payment=False,
                    desired_completion_date=date(2026, 3, 31))],
                events=history + [fixtures.event(
                    event_id="event_01", user_id="user_01", status="scheduled",
                    direction="credit", event_type="income", category="salary",
                    description="Confirmed salary", amount=D("40000"),
                    event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))],
                options=[fixtures.option(
                    option_id="payment_option_01", request_id="request_01",
                    payment_amount=D("10000"), number_of_payments=3,
                    first_payment_date=date(2026, 1, 1), payment_frequency_days=30,
                    total_payable_amount=D("30000"))],
            )
            engine = FinancialEngine(Dataset.load(root))
            decision = engine.decide("request_01")
            self.assertEqual(decision.recommended_payment_method, "installments")
            self.assertEqual(decision.affordability_status, "affordable_with_plan")
            self.assertEqual(decision.spending_changes_needed, "stop:event_13")
            self.assertEqual(decision.amount_safe_to_pay, D("6000"))
            self.assertEqual(decision.earliest_date_for_full_payment, date(2026, 1, 10))
            certificate = engine.verify(decision)
            self.assertTrue(certificate.checks)
            self.assertGreaterEqual(
                certificate.minimum_projected_balance, certificate.minimum_required)

    def test_write_output_csv_round_trips_the_contract_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FinancialEngine(self._load(directory))
            decision = engine.decide("request_01")
            target = Path(directory) / "output.csv"
            write_output_csv(target, [decision])
            with target.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                self.assertEqual(reader.fieldnames, OUTPUT_COLUMNS)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request_id"], "request_01")
            self.assertEqual(rows[0]["payment_plan"], "2026-01-01:5000")

    def test_decide_all_preserves_dataset_request_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixtures.write_dataset(
                Path(directory),
                profiles=[fixtures.profile()],
                requests=[
                    fixtures.request(request_id="request_02"),
                    fixtures.request(request_id="request_01"),
                ],
            )
            engine = FinancialEngine(Dataset.load(root))
            self.assertEqual(
                [decision.request_id for decision in engine.decide_all()],
                ["request_02", "request_01"],
            )

    @unittest.skipUnless(
        (REPO_ROOT / "dataset" / "requests.csv").is_file(), "dataset not present")
    def test_real_dataset_request_obeys_the_output_contract(self):
        dataset = Dataset.load(REPO_ROOT / "dataset")
        engine = FinancialEngine(
            dataset, ForecastPolicy(variable_spending_enabled=False))
        decision = engine.decide("request_26")
        request = dataset.requests["request_26"]
        self.assertGreaterEqual(decision.amount_safe_to_pay, Decimal(0))
        self.assertLessEqual(decision.amount_safe_to_pay, request.requested_amount)
        row = decision.to_row()
        self.assertEqual(list(row), OUTPUT_COLUMNS)
        self.assertIn(decision.affordability_status, {
            "affordable_now", "affordable_with_plan", "affordable_later",
            "not_affordable"})
        if decision.plan.entries:
            certificate = engine.verify(decision)
            self.assertGreaterEqual(
                certificate.minimum_projected_balance, certificate.minimum_required)


if __name__ == "__main__":
    unittest.main()

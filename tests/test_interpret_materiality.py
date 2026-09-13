import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from interpret.materiality import MaterialityPolicy, evaluate_materiality
from interpret.schemas import InterpretationSet

from tests import finance_fixtures as ff
from tests import interpret_fixtures as fx


def iset(event_ref, field, accepted, values=(), unresolved=False) -> InterpretationSet:
    return InterpretationSet(
        event_ref=event_ref, field=field, accepted=accepted, values=tuple(values),
        unresolved=unresolved, claims=())


class MaterialityTests(unittest.TestCase):
    def test_immaterial_ambiguity_on_historical_settled_event(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="settled", amount=5000,
                event_date=date(2025, 12, 1), settlement_date=date(2025, 12, 1))
            root = fx.simple_dataset(Path(directory), events=[event])
            dataset, engine = fx.make_engine(root)
            result = evaluate_materiality(
                dataset.scope("request_01"), engine,
                (iset("event_01", "amount", Decimal("5000"),
                      (Decimal("5000"), Decimal("9000"))),))
            self.assertEqual(result.status, "immaterial")
            self.assertEqual(result.differing_fields, ())
            self.assertEqual(len(result.baseline_row), 8)

    def test_material_ambiguity_changes_core_output_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="pending", amount=5000,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000", events=[event])
            dataset, engine = fx.make_engine(root)
            result = evaluate_materiality(
                dataset.scope("request_01"), engine,
                (iset("event_01", "amount", Decimal("5000"),
                      (Decimal("5000"), Decimal("50000"))),))
            self.assertEqual(result.status, "material")
            for field in (
                "amount_safe_to_pay", "affordability_status",
                "recommended_payment_method", "payment_plan",
                "earliest_date_for_full_payment", "decision_explanation",
            ):
                self.assertIn(field, result.differing_fields)
            self.assertEqual(result.baseline_row["amount_safe_to_pay"], "45000")
            self.assertEqual(
                next(row for row in result.variant_rows)["amount_safe_to_pay"], "0")

    def test_material_ambiguity_changes_spending_changes_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            history = [
                ff.event(
                    event_id="event_11", status="settled", amount=1000,
                    category="dining", description="Dining out", flexibility="stoppable",
                    event_date=date(2025, 10, 5), settlement_date=date(2025, 10, 5)),
                ff.event(
                    event_id="event_12", status="settled", amount=1000,
                    category="dining", description="Dining out", flexibility="stoppable",
                    event_date=date(2025, 11, 5), settlement_date=date(2025, 11, 5)),
                ff.event(
                    event_id="event_13", status="settled", amount=1000,
                    category="dining", description="Dining out", flexibility="stoppable",
                    event_date=date(2025, 12, 5), settlement_date=date(2025, 12, 5)),
            ]
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="30000",
                methods=("installments",), allows_partial=False,
                desired=date(2026, 3, 31), events=history,
                stop_categories=("dining",),
                options=[ff.option(
                    option_id="payment_option_01", request_id="request_01",
                    payment_amount=ff.D("10000"), number_of_payments=3,
                    first_payment_date=date(2026, 1, 1), payment_frequency_days=30,
                    total_payable_amount=ff.D("30000"))])
            dataset, engine = fx.make_engine(root)
            result = evaluate_materiality(
                dataset.scope("request_01"), engine,
                (iset("event_13", "amount", Decimal("1000"),
                      (Decimal("1000"), Decimal("20000"))),))
            self.assertEqual(result.status, "material")
            self.assertIn("spending_changes_needed", result.differing_fields)
            self.assertEqual(result.baseline_row["spending_changes_needed"], "none")
            self.assertNotEqual(
                next(row for row in result.variant_rows)["spending_changes_needed"],
                "none")

    def test_combination_cap_returns_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(event_id="event_01", status="pending", amount=5000,
                             event_date=date(2026, 1, 10),
                             settlement_date=date(2026, 1, 10))
            root = fx.simple_dataset(Path(directory), events=[event])
            dataset, engine = fx.make_engine(root)
            axes = tuple(
                iset("event_01", field, Decimal("5000"),
                     (Decimal("5000"), Decimal("6000"), Decimal("7000")))
                for field in ("amount", "settlement_date", "description"))
            result = evaluate_materiality(
                dataset.scope("request_01"), engine, axes,
                policy=MaterialityPolicy(max_combinations=8))
            self.assertEqual(result.status, "unknown")
            self.assertTrue(result.truncated)
            self.assertEqual(result.combinations_examined, 0)

    def test_unresolved_field_without_values_returns_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(event_id="event_01", status="pending", amount=None,
                             event_date=date(2026, 1, 10),
                             settlement_date=date(2026, 1, 10))
            root = fx.simple_dataset(Path(directory), events=[event])
            dataset, engine = fx.make_engine(root)
            result = evaluate_materiality(
                dataset.scope("request_01"), engine,
                (iset("event_01", "amount", None, (), unresolved=True),))
            self.assertEqual(result.status, "unknown")
            self.assertTrue(result.unresolved_axes)

    def test_non_overridable_recurrence_claim_is_immaterial(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            root = fx.simple_dataset(Path(directory), events=[event])
            dataset, engine = fx.make_engine(root)
            from interpret.interpretations import build_interpretation_sets

            claims = fx.claims_from([{
                "field": "recurrence", "value": "recurring", "lifecycle": "confirm",
                "event_ref": "event_01", "evidence_span": "charged every month"}])
            sets = build_interpretation_sets(claims, directions={"event_01": "debit"})
            result = evaluate_materiality(dataset.scope("request_01"), engine, sets)
            self.assertEqual(result.status, "immaterial")

    def test_image_multiple_amounts_create_an_interpretation_axis(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000", events=[event])
            dataset, engine = fx.make_engine(root)
            from interpret.interpretations import build_interpretation_sets

            claims = fx.claims_from([
                {"field": "amount", "value": 5000, "lifecycle": "amend",
                 "event_ref": "event_01", "evidence_span": "subtotal 5000"},
                {"field": "amount", "value": 50000, "lifecycle": "amend",
                 "event_ref": "event_01", "evidence_span": "total due 50000"},
            ], source_kind="image", source_id="image_01")
            sets = build_interpretation_sets(
                claims, directions={"event_01": "debit"})
            amount = next(item for item in sets if item.field == "amount")
            self.assertTrue(amount.ambiguous)
            self.assertIn(Decimal("5000"), amount.values)
            self.assertIn(Decimal("50000"), amount.values)
            result = evaluate_materiality(dataset.scope("request_01"), engine, sets)
            self.assertEqual(result.status, "material")

    def test_no_axes_is_immaterial_with_one_run(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(event_id="event_01", status="scheduled", amount=100,
                             event_date=date(2026, 1, 5),
                             settlement_date=date(2026, 1, 5))
            root = fx.simple_dataset(Path(directory), events=[event])
            dataset, engine = fx.make_engine(root)
            result = evaluate_materiality(
                dataset.scope("request_01"), engine,
                (iset("event_01", "amount", Decimal("100"),
                      (Decimal("100"),)),))
            self.assertEqual(result.status, "immaterial")
            self.assertEqual(result.combinations_examined, 1)


if __name__ == "__main__":
    unittest.main()

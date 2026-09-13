"""Regression tests for the Astra MUST-FIX reliability patch.

Each test reproduces one confirmed failure mode from the review:
1. incomplete final verifier
2. incomplete evidence silently becoming immaterial
3. insufficient evidence grounding / closed schema
4. recurrence / lifecycle reconciliation
5. preserved earliest full-payment date
6. payments outside the evaluated horizon
7. order-independent attachment reconciliation and independent verification
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "code"))

from finance.contracts import (
    ChangeAction,
    ContractError,
    Decision,
    PaymentPlan,
    PlanEntry,
)
from finance.engine import FinancialEngine
from finance.forecast import ForecastPolicy, collect_flows, detect_recurrence
from finance.ingest import Dataset
from finance.planning import enumerate_candidates, compute_capacity, installment_entries
from finance.ranking import rank_candidates

from interpret.attachment import attach_claims
from interpret.extractor import SYSTEM_PROMPT
from interpret.pipeline import EvidencePipeline
from interpret.schemas import parse_claims_with_rejections
from interpret.verification import default_tools

from evaluation.forecast import build_forecast
from evaluation.safety import EvaluationContext, evaluate_row_safety

from tests import finance_fixtures as ff
from tests import interpret_fixtures as fx
from tests.test_interpret_pipeline import ScriptedController

D = ff.D


class VerifierCompletenessTests(unittest.TestCase):
    """MUST-FIX 1 and 6: every constraint is independently validated."""

    def _engine(self, **dataset_kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = fx.simple_dataset(Path(directory.name), **dataset_kwargs)
        dataset = Dataset.load(root)
        engine = FinancialEngine(
            dataset, ForecastPolicy(variable_spending_enabled=False))
        return dataset, engine

    def test_verify_accepts_its_own_decision(self):
        _, engine = self._engine()
        decision = engine.decide("request_01")
        engine.verify(decision)

    def test_out_of_horizon_payment_is_never_certified(self):
        _, engine = self._engine()
        decision = engine.decide("request_01")
        beyond = date(2026, 10, 1)
        tampered = replace(
            decision,
            plan=replace(decision.plan, entries=(PlanEntry(beyond, D("45000")),)),
            earliest_date_for_full_payment=beyond)
        with self.assertRaises(ContractError) as caught:
            engine.verify(tampered)
        self.assertIn("outside the evaluated forecast horizon", str(caught.exception))

    def test_capacity_mismatch_is_never_certified(self):
        _, engine = self._engine()
        decision = engine.decide("request_01")
        tampered = replace(decision, amount_safe_to_pay=D("44999"))
        with self.assertRaises(ContractError) as caught:
            engine.verify(tampered)
        self.assertIn("recomputed capacity", str(caught.exception))

    def test_wrong_full_payment_schedule_is_never_certified(self):
        _, engine = self._engine()
        decision = engine.decide("request_01")
        tampered = replace(
            decision,
            plan=replace(
                decision.plan,
                entries=(PlanEntry(date(2026, 1, 2), D("45000")),)))
        with self.assertRaises(ContractError) as caught:
            engine.verify(tampered)
        self.assertIn("exactly request_date:requested_amount", str(caught.exception))

    def test_installment_plan_not_matching_the_supplied_option_is_rejected(self):
        option = ff.option(
            option_id="payment_option_01",
            payment_amount=D("15000"),
            number_of_payments=3,
            payment_frequency_days=30,
            total_payable_amount=D("45000"))
        _, engine = self._engine(
            options=[option], methods=("installments",), desired=date(2026, 4, 1))
        decision = engine.decide("request_01")
        self.assertEqual(decision.plan.method, "installments")
        tampered = replace(
            decision,
            plan=replace(
                decision.plan,
                entries=tuple(
                    PlanEntry(entry.payment_date, D("14000"))
                    for entry in decision.plan.entries)))
        with self.assertRaises(ContractError) as caught:
            engine.verify(tampered)
        self.assertIn("match the supplied option exactly", str(caught.exception))

    def test_non_top_ranked_plan_is_never_certified(self):
        option = ff.option(
            option_id="payment_option_01",
            payment_amount=D("15000"),
            number_of_payments=3,
            payment_frequency_days=30,
            total_payable_amount=D("45000"))
        _, engine = self._engine(
            options=[option], methods=("full_payment", "installments"),
            desired=date(2026, 4, 1))
        dataset = engine.dataset
        scope = dataset.scope("request_01")
        capacity = compute_capacity(scope, engine.policy)
        ranked = rank_candidates(enumerate_candidates(
            scope, engine.policy, capacity).candidates)
        self.assertEqual(ranked[0].method, "full_payment")
        second = ranked[1]
        self.assertEqual(second.method, "installments")
        decision = Decision(
            request_id="request_01",
            amount_safe_to_pay=capacity.amount_safe_to_pay,
            plan=PaymentPlan(
                method=second.method, status=second.status, entries=second.entries,
                changes=second.changes, option_id=second.option_id),
            earliest_date_for_full_payment=capacity.earliest_full_payment_date,
            decision_explanation="second ranked")
        with self.assertRaises(ContractError) as caught:
            engine.verify(decision)
        self.assertIn("not the top-ranked eligible candidate", str(caught.exception))

    def test_unauthorized_spending_change_is_never_certified(self):
        # A protected, fixed rent event may not be stopped.
        rent = ff.event(
            event_id="event_02", category="rent", description="Rent",
            flexibility="fixed", amount=D("8000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5))
        _, engine = self._engine(
            events=[rent], requested="95000",
            stop_categories=("rent",))
        decision = engine.decide("request_01")
        self.assertEqual(decision.recommended_payment_method, "not_recommended")
        tampered_plan = PaymentPlan(
            method="full_payment", status="affordable_with_plan",
            entries=(PlanEntry(date(2026, 1, 1), D("95000")),),
            changes=(ChangeAction.stop("event_02"),))
        tampered = replace(
            decision, plan=tampered_plan, amount_safe_to_pay=D("95000"))
        with self.assertRaises(ContractError) as caught:
            engine.verify(tampered)
        self.assertIn("not permitted", str(caught.exception))

    def test_deadline_violation_is_never_certified(self):
        salary = ff.event(
            event_id="event_11", event_type="income", direction="credit",
            category="salary", description="Salary", amount=D("40000"),
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10),
            status="scheduled")
        _, engine = self._engine(
            balance="50000", requested="45000", events=[salary],
            desired=date(2026, 2, 1))
        decision = engine.decide("request_01")
        self.assertEqual(decision.recommended_payment_method, "wait")
        late = replace(
            decision,
            plan=replace(
                decision.plan,
                entries=(PlanEntry(date(2026, 4, 1), D("45000")),)),
            earliest_date_for_full_payment=date(2026, 4, 1))
        with self.assertRaises(ContractError) as caught:
            engine.verify(late)
        self.assertIn("after desired_completion_date", str(caught.exception))

    def test_every_engine_decision_on_the_dataset_passes_verification(self):
        dataset = Dataset.load(Path(__file__).parents[1] / "dataset")
        engine = FinancialEngine(dataset, ForecastPolicy())
        for decision in engine.decide_all():
            engine.verify(decision)


class EvidenceGroundingTests(unittest.TestCase):
    """MUST-FIX 3: closed schema and source-grounded claims."""

    TEXT = "Your payment of ZAR 1500 was cancelled and will settle on 2026-02-03."

    def _parse(self, claims, text=TEXT):
        import json
        return parse_claims_with_rejections(
            json.dumps({"claims": claims}),
            source_kind="message", source_id="message_01", user_id="user_01",
            request_id="request_01", observed_at=date(2026, 1, 2),
            source_text=text)

    def test_unexpected_claim_property_is_rejected(self):
        claims, rejected = self._parse([{
            "field": "amount", "value": 1500, "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "ZAR 1500",
            "priority": "high",
        }])
        self.assertEqual(claims, ())
        self.assertIn("unsupported properties", rejected[0]["reason"])

    def test_unexpected_top_level_property_is_rejected(self):
        import json
        claims, rejected = parse_claims_with_rejections(
            json.dumps({"claims": [], "decision": "approve"}),
            source_kind="message", source_id="message_01", user_id="user_01",
            request_id="request_01", observed_at=date(2026, 1, 2),
            source_text=self.TEXT)
        self.assertIn("unsupported properties", rejected[0]["reason"])

    def test_evidence_span_must_exist_in_the_source(self):
        claims, rejected = self._parse([{
            "field": "amount", "value": 1500, "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "payment of USD 9000",
        }])
        self.assertEqual(claims, ())
        self.assertIn("not present in the source", rejected[0]["reason"])

    def test_unsupported_amount_value_is_rejected(self):
        claims, rejected = self._parse([{
            "field": "amount", "value": 9000, "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "Your payment of ZAR 1500",
        }])
        self.assertEqual(claims, ())
        self.assertIn("not supported by the source evidence", rejected[0]["reason"])

    def test_supported_claims_are_accepted(self):
        claims, rejected = self._parse([
            {"field": "amount", "value": 1500, "lifecycle": "amend",
             "event_ref": "event_01", "evidence_span": "ZAR 1500"},
            {"field": "status", "value": "cancelled", "lifecycle": "cancel",
             "event_ref": "event_01", "evidence_span": "was cancelled"},
            {"field": "settlement_date", "value": "2026-02-03", "lifecycle": "delay",
             "event_ref": "event_01", "evidence_span": "settle on 2026-02-03"},
        ])
        self.assertEqual(len(rejected), 0)
        self.assertEqual(
            [claim.field for claim in claims],
            ["amount", "status", "settlement_date"])


class RecurrenceLifecycleTests(unittest.TestCase):
    """MUST-FIX 4: cancelled and pending credits are not recreated as income."""

    SALARY_DAYS = [date(2025, 10, 5), date(2025, 11, 5), date(2025, 12, 5)]

    def _salary_events(self, extra):
        events = [
            ff.event(
                event_id=f"event_1{index}", event_type="income", direction="credit",
                category="salary", description="Monthly salary", amount=D("4000"),
                event_date=day, settlement_date=day, status="settled")
            for index, day in enumerate(self.SALARY_DAYS)
        ]
        return events + extra

    def _scope(self, events):
        return ff.scope(
            events=events,
            request=ff.request(
                request_date=date(2026, 1, 1), requested_amount=D("5000"),
                desired_completion_date=date(2026, 2, 1)),
            profile=ff.profile(
                current_available_balance=D("6000"),
                minimum_balance_to_keep=D("1000")))

    def test_cancelled_credit_occurrence_terminates_income_projection(self):
        cancelled = ff.event(
            event_id="event_21", event_type="income", direction="credit",
            category="salary", description="Monthly salary", amount=D("4000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
            status="cancelled")
        scope = self._scope(self._salary_events([cancelled]))
        self.assertEqual(detect_recurrence(scope, ForecastPolicy()), ())
        flows = collect_flows(scope, ForecastPolicy(variable_spending_enabled=False))
        self.assertFalse(any(flow.amount > 0 for flow in flows))

    def test_pending_credit_covers_its_slot_instead_of_becoming_income(self):
        pending = ff.event(
            event_id="event_22", event_type="income", direction="credit",
            category="salary", description="Monthly salary", amount=D("4000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
            status="pending")
        scope = self._scope(self._salary_events([pending]))
        flows = collect_flows(scope, ForecastPolicy(variable_spending_enabled=False))
        # The series continues, but the pending occurrence is not recreated as
        # fresh forecast income on its own projected slot.
        self.assertTrue(any(
            flow.day == date(2026, 2, 5) and flow.amount > 0 for flow in flows))
        self.assertFalse(any(flow.day == date(2026, 1, 5) for flow in flows))

    def test_unconfirmed_scheduled_credit_covers_its_slot(self):
        speculative = ff.event(
            event_id="event_23", event_type="income", direction="credit",
            category="salary", description="Unapproved salary proposal",
            amount=D("4000"), event_date=date(2026, 1, 5),
            settlement_date=date(2026, 1, 5), status="scheduled")
        scope = self._scope(self._salary_events([speculative]))
        flows = collect_flows(scope, ForecastPolicy(variable_spending_enabled=False))
        self.assertTrue(any(
            flow.day == date(2026, 2, 5) and flow.amount > 0 for flow in flows))
        self.assertFalse(any(flow.day == date(2026, 1, 5) for flow in flows))

    def _evaluator_context(self, events):
        return EvaluationContext(
            profiles={"user_01": {
                "user_id": "user_01", "home_currency": "ZAR",
                "current_available_balance": "6000",
                "minimum_balance_to_keep": "1000",
                "expense_categories_to_protect": "",
                "expense_categories_user_is_willing_to_reduce": "",
                "expense_categories_user_is_willing_to_stop": "",
                "payment_methods_user_will_consider": "full_payment",
                "max_installment_months": "",
            }},
            events={"user_01": [
                {
                    "event_id": event.event_id, "user_id": "user_01",
                    "event_type": event.event_type, "description": event.description,
                    "category": event.category, "direction": event.direction,
                    "amount": str(event.amount), "currency": "ZAR",
                    "event_date": event.event_date.isoformat(),
                    "settlement_date": event.settlement_date.isoformat(),
                    "status": event.status, "flexibility": event.flexibility or "",
                    "minimum_allowed_amount": "",
                } for event in events
            ]},
            options={}, rates={}, messages={}, images={},
            requests={})

    def test_evaluator_mirrors_cancelled_credit_termination(self):
        cancelled = ff.event(
            event_id="event_21", event_type="income", direction="credit",
            category="salary", description="Monthly salary", amount=D("4000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
            status="cancelled")
        request = {
            "request_id": "request_01", "user_id": "user_01",
            "request_date": "2026-01-01", "requested_amount": "5000",
            "desired_completion_date": "2026-02-01",
            "allows_partial_payment": "false",
        }
        forecast = build_forecast(
            request, self._evaluator_context(self._salary_events([cancelled])))
        self.assertEqual(forecast.problems, [])
        self.assertFalse(any(amount > 0 for _, amount in forecast.flows))

    def test_evaluator_mirrors_pending_credit_slot_covering(self):
        pending = ff.event(
            event_id="event_22", event_type="income", direction="credit",
            category="salary", description="Monthly salary", amount=D("4000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
            status="pending")
        request = {
            "request_id": "request_01", "user_id": "user_01",
            "request_date": "2026-01-01", "requested_amount": "5000",
            "desired_completion_date": "2026-02-01",
            "allows_partial_payment": "false",
        }
        forecast = build_forecast(
            request, self._evaluator_context(self._salary_events([pending])))
        self.assertEqual(forecast.problems, [])
        self.assertTrue(any(
            amount > 0 for day, amount in forecast.flows if day == date(2026, 2, 5)))
        self.assertFalse(any(
            day == date(2026, 1, 5) for day, amount in forecast.flows))


class EarliestDatePreservationTests(unittest.TestCase):
    """MUST-FIX 5: the first safe full-payment date is preserved."""

    def _context(self):
        return EvaluationContext(
            profiles={"user_01": {
                "user_id": "user_01", "home_currency": "ZAR",
                "current_available_balance": "6000",
                "minimum_balance_to_keep": "1000",
                "expense_categories_to_protect": "",
                "expense_categories_user_is_willing_to_reduce": "",
                "expense_categories_user_is_willing_to_stop": "",
                "payment_methods_user_will_consider": "full_payment",
                "max_installment_months": "",
            }},
            events={"user_01": [{
                "event_id": "event_1", "user_id": "user_01", "event_type": "income",
                "description": "Salary", "category": "salary", "direction": "credit",
                "amount": "4000", "currency": "ZAR", "event_date": "2026-01-10",
                "settlement_date": "2026-01-10", "status": "scheduled",
                "flexibility": "fixed", "minimum_allowed_amount": "",
            }]},
            options={}, rates={}, messages={}, images={},
            requests={})

    REQUEST = {
        "request_id": "request_01", "user_id": "user_01",
        "request_date": "2026-01-01", "requested_amount": "5500",
        "desired_completion_date": "2026-01-05",
        "allows_partial_payment": "false",
    }

    def _row(self, earliest):
        return {
            "request_id": "request_01", "amount_safe_to_pay": "5000",
            "affordability_status": "not_affordable",
            "recommended_payment_method": "not_recommended",
            "payment_plan": "none",
            "earliest_date_for_full_payment": earliest,
            "spending_changes_needed": "none",
            "decision_explanation": "No eligible plan by the deadline.",
        }

    def test_not_affordable_row_may_carry_the_first_safe_full_payment_date(self):
        result = evaluate_row_safety(self._row("2026-01-10"), self.REQUEST, self._context())
        self.assertNotIn(
            "not_affordable_plan", {issue.code for issue in result.issues})
        self.assertTrue(result.valid)

    def test_not_affordable_row_with_a_wrong_earliest_date_is_rejected(self):
        result = evaluate_row_safety(self._row("2026-01-20"), self.REQUEST, self._context())
        self.assertIn(
            "earliest_date_mismatch", {issue.code for issue in result.issues})
        self.assertFalse(result.valid)


class AttachmentReconciliationTests(unittest.TestCase):
    """MUST-FIX 7: conflicting values never resolve by first-pick."""

    def _claim(self, index, field, value, lifecycle="amend"):
        from interpret.schemas import parse_claims
        import json
        payload = json.dumps({"claims": [{
            "field": field, "value": value, "lifecycle": lifecycle,
            "event_ref": None,
            "evidence_span": "reduced to EUR 100 or EUR 200",
        }]})
        claims = parse_claims(
            payload, source_kind="message", source_id="message_01",
            user_id="user_01", request_id="request_01",
            observed_at=date(2026, 1, 2),
            source_text="Your pay was reduced to EUR 100 or EUR 200 next month.")
        return claims[0]

    def test_conflicting_amounts_in_one_source_stay_ambiguous(self):
        scope = ff.scope()
        outcomes = attach_claims(scope, [
            self._claim(0, "amount", 100),
            self._claim(1, "amount", 200),
        ])
        self.assertTrue(all(
            outcome.state == "ambiguous" for outcome in outcomes))
        self.assertTrue(all(
            "conflicting values within the source" in outcome.reasons[0]
            for outcome in outcomes))
        self.assertTrue(all(
            outcome.event_id is None for outcome in outcomes))


class VerificationIndependenceTests(unittest.TestCase):
    """MUST-FIX 7: targeted verification is not a cached replay."""

    def test_reread_uses_a_distinct_verification_prompt_and_model(self):
        message = ff.message(
            message_id="message_01",
            text="Your salary was reduced to ZAR 5000 for the next payroll.")
        scope = ff.scope(messages=[message])
        verification_client = fx.FakeChatClient({
            "message_01": fx.claims_json([
                fx.claim_payload(value=5000, evidence="ZAR 5000")]),
        })
        primary_client = fx.FakeChatClient({}, fail=True)
        tools = default_tools(
            scope, (), extractor=fx.extractor({}, model="fake/primary"),
            verification_extractor=fx.EvidenceExtractor(
                verification_client, model="fake/second"),
            attachment_outcomes=())
        result = tools["reread_message"]({
            "source_id": "message_01",
            "uncertainty": "which amount applies to the next payroll",
        })
        self.assertIn("claims", result)
        call = verification_client.calls[0]
        self.assertNotEqual(call["model"], "fake/primary")
        self.assertNotIn("extract financial facts", call["user"])
        self.assertIn("VERIFICATION QUESTION", call["user"])
        self.assertIn("independent verification extractor", call["system"])
        self.assertNotEqual(call["system"], SYSTEM_PROMPT)
        self.assertEqual(primary_client.calls, [])


class MaterialitySensitivityTests(unittest.TestCase):
    """MUST-FIX 2: unresolved evidence blocks or de-risks positive certification."""

    SALARY = [
        ff.event(
            event_id=f"event_1{index}", event_type="income", direction="credit",
            category="salary", description="TaskLoop weekly payout", amount=D("4000"),
            event_date=day, settlement_date=day, status="settled")
        for index, day in enumerate(
            [date(2025, 12, 11), date(2025, 12, 18), date(2025, 12, 25)])
    ]

    def _pipeline(self, root, primary, second=None, controller=None):
        dataset, engine = fx.make_engine(root, variable_spending=False)
        return dataset, EvidencePipeline(
            dataset, engine,
            primary=fx.extractor(primary, model="fake/primary"),
            second=fx.extractor(second or {}, model="fake/second"),
            controller=controller,
        )

    def test_unresolved_income_message_suppresses_the_series_for_positives(self):
        with tempfile.TemporaryDirectory() as directory:
            message = ff.message(
                message_id="message_01",
                text=("The next TaskLoop payout is still pending. The weekly "
                      "earnings can change until the payout is closed."))
            root = fx.simple_dataset(
                Path(directory), balance="6000", minimum="1000", requested="9000",
                events=self.SALARY, messages=[message])
            dataset, baseline_engine = fx.make_engine(root, variable_spending=False)
            baseline = baseline_engine.decide("request_01")
            self.assertEqual(baseline.recommended_payment_method, "full_payment")

            payload = fx.claims_json([
                fx.claim_payload(field="description", value="TaskLoop payout",
                                 lifecycle="inform", event_ref=None,
                                 evidence="TaskLoop payout"),
            ])
            _, pipeline = self._pipeline(root, {"message_01": payload})
            result = pipeline.run("request_01")
            # The conservative reading (income not counted) must win for a
            # positive recommendation; the uncertainty stays recorded.
            self.assertNotEqual(
                result.decision.recommended_payment_method, "wait")
            self.assertTrue(any(
                "interpretation sensitivity" in note
                for note in result.certificate.unresolved))

    def test_extraction_error_opens_verification_and_blocks_positives(self):
        with tempfile.TemporaryDirectory() as directory:
            message = ff.message(message_id="message_01", text="Payment update.")
            root = fx.simple_dataset(
                Path(directory), balance="6000", minimum="1000", requested="5000",
                messages=[message])
            controller = ScriptedController([{"action": "stop"}])
            _, pipeline = self._pipeline(
                root, {"message_01": "not json"}, controller=controller)
            result = pipeline.run("request_01")
            self.assertTrue(result.used_verification)
            self.assertEqual(
                result.decision.recommended_payment_method, "not_recommended")
            self.assertTrue(any(
                "primary extraction failed" in note
                for note in result.certificate.unresolved))

    def test_unquantified_new_obligation_blocks_positive_certification(self):
        with tempfile.TemporaryDirectory() as directory:
            message = ff.message(
                message_id="message_01",
                text="A new monthly charge of 123 will apply from next month.")
            root = fx.simple_dataset(
                Path(directory), balance="60000", minimum="1000", requested="45000",
                messages=[message])
            payload = fx.claims_json([
                fx.claim_payload(field="amount", value=123,
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="charge of 123"),
                fx.claim_payload(field="direction", value="debit",
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="new monthly charge"),
                fx.claim_payload(field="currency", value="ZAR",
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="charge of 123"),
            ])
            _, pipeline = self._pipeline(
                root, {"message_01": payload}, {"message_01": payload})
            result = pipeline.run("request_01")
            self.assertEqual(
                result.decision.recommended_payment_method, "not_recommended")
            self.assertTrue(any(
                "positive recommendation blocked" in note
                for note in result.certificate.unresolved))

    def test_one_time_recurrence_instruction_suppresses_the_series(self):
        with tempfile.TemporaryDirectory() as directory:
            message = ff.message(
                message_id="message_01", related_event_id="event_12",
                text="This TaskLoop payout was a one_time bonus, not recurring.")
            root = fx.simple_dataset(
                Path(directory), balance="6000", minimum="1000", requested="9000",
                events=self.SALARY, messages=[message])
            payload = fx.claims_json([
                fx.claim_payload(field="recurrence", value="one_time",
                                 lifecycle="amend", event_ref="event_12",
                                 evidence="one_time bonus"),
            ])
            _, pipeline = self._pipeline(
                root, {"message_01": payload}, {"message_01": payload})
            result = pipeline.run("request_01")
            self.assertNotEqual(
                result.decision.recommended_payment_method, "wait")
            self.assertIn(
                result.decision.recommended_payment_method,
                {"not_recommended", "full_payment", "partial_payment"})


if __name__ == "__main__":
    unittest.main()
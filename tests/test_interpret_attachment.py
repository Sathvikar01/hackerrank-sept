import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance.forecast import ForecastPolicy
from finance.overlay import apply_overrides
from interpret.attachment import (
    ATTACHMENT_STATES,
    AttachmentPolicy,
    attach_claims,
    build_attachment_axes,
    evaluate_attachment_materiality,
    materialize_obligation,
)
from interpret.verification import TOOL_NAMES, ScriptedController, default_tools, run_verification

from tests import finance_fixtures as ff
from tests import interpret_fixtures as fx

D = ff.D


def defer_claim(value=5000, *, lifecycle="amend", field="amount", evidence="ZAR 5000"):
    return fx.claims_from([{
        "field": field, "value": value, "lifecycle": lifecycle,
        "event_ref": None, "evidence_span": evidence,
    }])


class AttachmentTests(unittest.TestCase):
    def test_chronology_attachment_when_dates_differ(self):
        event = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            category="utilities", event_date=date(2026, 2, 10),
            settlement_date=date(2026, 2, 10))
        scope = ff.scope(events=[event])
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "ZAR 5000"},
            {"field": "currency", "value": "ZAR", "lifecycle": "amend",
             "evidence_span": "ZAR"},
            {"field": "settlement_date", "value": "2026-03-15",
             "lifecycle": "amend", "evidence_span": "from 2026-03-15"},
        ], source_id="message_60", observed_at=date(2026, 1, 2))
        outcomes = attach_claims(scope, claims)
        self.assertEqual({outcome.state for outcome in outcomes}, {"attached"})
        self.assertTrue(all(outcome.event_id == "event_01" for outcome in outcomes))
        self.assertTrue(any(
            "chronology" in reason for outcome in outcomes
            for reason in outcome.reasons))

    def test_chronology_with_two_candidates_is_ambiguous(self):
        first = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 2, 10), settlement_date=date(2026, 2, 10))
        second = ff.event(
            event_id="event_02", status="scheduled", amount=5000,
            event_date=date(2026, 2, 20), settlement_date=date(2026, 2, 20))
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "ZAR 5000"},
            {"field": "currency", "value": "ZAR", "lifecycle": "amend",
             "evidence_span": "ZAR"},
            {"field": "settlement_date", "value": "2026-03-15",
             "lifecycle": "amend", "evidence_span": "from 2026-03-15"},
        ], source_id="message_61", observed_at=date(2026, 1, 2))
        outcomes = attach_claims(ff.scope(events=[first, second]), claims)
        self.assertEqual(outcomes[0].state, "ambiguous")
        self.assertEqual(outcomes[0].candidates, ("event_01", "event_02"))

    def test_chronology_conflict_is_unresolved(self):
        event = ff.event(
            event_id="event_01", status="settled", amount=5000,
            event_date=date(2025, 12, 1), settlement_date=date(2025, 12, 1))
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "ZAR 5000"},
            {"field": "currency", "value": "ZAR", "lifecycle": "amend",
             "evidence_span": "ZAR"},
            {"field": "settlement_date", "value": "2026-01-15",
             "lifecycle": "amend", "evidence_span": "from 2026-01-15"},
        ], source_id="message_62", observed_at=date(2026, 1, 2))
        outcomes = attach_claims(ff.scope(events=[event]), claims)
        self.assertEqual({outcome.state for outcome in outcomes}, {"unresolved"})

    def test_nearest_event_does_not_win_without_an_anchor(self):
        near = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        far = ff.event(
            event_id="event_02", status="scheduled", amount=7777,
            event_date=date(2026, 3, 10), settlement_date=date(2026, 3, 10))
        claims = fx.claims_from([
            {"field": "event_date", "value": "2026-01-10", "lifecycle": "confirm",
             "evidence_span": "due 2026-01-10"},
        ], source_id="message_63", observed_at=date(2026, 1, 2))
        outcomes = attach_claims(ff.scope(events=[near, far]), claims)
        self.assertEqual({outcome.state for outcome in outcomes}, {"unresolved"})

    def test_unique_deterministic_attachment(self):
        first = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            category="utilities", description="Utility payment",
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        second = ff.event(
            event_id="event_02", status="scheduled", amount=7777,
            category="dining", description="Dining out",
            event_date=date(2026, 1, 12), settlement_date=date(2026, 1, 12))
        scope = ff.scope(events=[first, second])
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "ZAR 5000"},
            {"field": "currency", "value": "ZAR", "lifecycle": "amend",
             "evidence_span": "ZAR"},
            {"field": "event_date", "value": "2026-01-10", "lifecycle": "amend",
             "evidence_span": "due 2026-01-10"},
            {"field": "category", "value": "utilities", "lifecycle": "amend",
             "evidence_span": "utility bill"},
        ])
        outcomes = attach_claims(scope, claims)
        self.assertEqual({outcome.state for outcome in outcomes}, {"attached"})
        self.assertTrue(all(outcome.event_id == "event_01" for outcome in outcomes))
        self.assertEqual(len(outcomes), len(claims))

    def test_multiple_plausible_events_become_ambiguity(self):
        first = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        second = ff.event(
            event_id="event_02", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[first, second])
        outcomes = attach_claims(scope, defer_claim(5000))
        self.assertEqual(outcomes[0].state, "ambiguous")
        self.assertEqual(outcomes[0].candidates, ("event_01", "event_02"))
        self.assertIn(outcomes[0].state, ATTACHMENT_STATES)

    def test_amount_match_with_incompatible_currency_is_unresolved(self):
        event = ff.event(
            event_id="event_01", status="scheduled", amount=5000, currency="ZAR",
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event])
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "USD 5000"},
            {"field": "currency", "value": "USD", "lifecycle": "amend",
             "evidence_span": "USD"},
        ])
        outcomes = attach_claims(scope, claims)
        self.assertEqual({outcome.state for outcome in outcomes}, {"unresolved"})
        self.assertTrue(all(
            "currency" in " ".join(outcome.reasons) for outcome in outcomes))

    def test_lifecycle_mismatch_is_unresolved(self):
        event = ff.event(
            event_id="event_01", status="settled", amount=5000,
            event_date=date(2025, 12, 10), settlement_date=date(2025, 12, 10))
        scope = ff.scope(events=[event])
        outcomes = attach_claims(scope, defer_claim(5000, lifecycle="cancel"))
        self.assertEqual(outcomes[0].state, "unresolved")
        self.assertIn("lifecycle", " ".join(outcomes[0].reasons))

    def test_date_proximity_selects_or_degrades_to_ambiguity(self):
        near = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        far = ff.event(
            event_id="event_02", status="scheduled", amount=5000,
            event_date=date(2026, 2, 20), settlement_date=date(2026, 2, 20))
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "ZAR 5000"},
            {"field": "event_date", "value": "2026-01-11", "lifecycle": "amend",
             "evidence_span": "due 2026-01-11"},
        ])
        selected = attach_claims(ff.scope(events=[near, far]), claims)
        self.assertEqual({outcome.state for outcome in selected}, {"attached"})
        self.assertEqual(selected[0].event_id, "event_01")

        tie_left = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        tie_right = ff.event(
            event_id="event_02", status="scheduled", amount=5000,
            event_date=date(2026, 1, 12), settlement_date=date(2026, 1, 12))
        tied = attach_claims(ff.scope(events=[tie_left, tie_right]), claims)
        self.assertEqual(tied[0].state, "ambiguous")

    def test_explicit_event_reference_attaches_without_amount_match(self):
        event = ff.event(
            event_id="event_02", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event])
        claims = fx.claims_from([{
            "field": "amount", "value": 999, "lifecycle": "amend",
            "evidence_span": "as agreed for event_02",
        }])
        outcomes = attach_claims(scope, claims)
        self.assertEqual(outcomes[0].state, "attached")
        self.assertEqual(outcomes[0].event_id, "event_02")
        self.assertIn("explicit", " ".join(outcomes[0].reasons))

    def test_new_obligation_creation_and_incomplete_rejection(self):
        event = ff.event(
            event_id="event_01", status="scheduled", amount=5000, category="groceries",
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5))
        scope = ff.scope(events=[event])
        complete = fx.claims_from([
            {"field": "amount", "value": 1234, "lifecycle": "new_obligation",
             "evidence_span": "new gym membership ZAR 1234"},
            {"field": "currency", "value": "ZAR", "lifecycle": "new_obligation",
             "evidence_span": "ZAR"},
            {"field": "event_date", "value": "2026-02-01",
             "lifecycle": "new_obligation", "evidence_span": "from 2026-02-01"},
            {"field": "direction", "value": "debit", "lifecycle": "new_obligation",
             "evidence_span": "you will be charged"},
        ], source_id="message_55")
        outcomes = attach_claims(scope, complete)
        self.assertEqual(outcomes[0].state, "new_obligation")
        obligation = outcomes[0].obligation
        self.assertIsNotNone(obligation)
        self.assertTrue(obligation.complete)
        self.assertEqual(obligation.amount, D("1234"))
        self.assertEqual(obligation.currency, "ZAR")
        self.assertTrue(obligation.provenance)
        materialized = materialize_obligation(obligation)
        self.assertEqual(materialized.amount, D("1234"))
        self.assertEqual(materialized.direction, "debit")
        self.assertEqual(materialized.user_id, "user_01")

        incomplete = fx.claims_from([
            {"field": "amount", "value": 1234, "lifecycle": "new_obligation",
             "evidence_span": "new gym membership ZAR 1234"},
        ], source_id="message_56")
        outcomes = attach_claims(scope, incomplete)
        self.assertEqual(outcomes[0].state, "unresolved")
        self.assertIn("incomplete", " ".join(outcomes[0].reasons))

    def test_merged_new_obligation_uses_the_merged_lifecycle(self):
        scope = ff.scope(events=[])
        claims = fx.claims_from([
            {"field": "amount", "value": 1234, "lifecycle": "confirm",
             "evidence_span": "the membership costs ZAR 1234"},
            {"field": "currency", "value": "ZAR", "lifecycle": "confirm",
             "evidence_span": "ZAR"},
            {"field": "event_date", "value": "2026-02-01", "lifecycle": "confirm",
             "evidence_span": "from 2026-02-01"},
            {"field": "direction", "value": "debit", "lifecycle": "new_obligation",
             "evidence_span": "you will be charged"},
        ], source_id="message_57")
        outcomes = attach_claims(scope, claims)
        self.assertEqual(outcomes[0].state, "new_obligation")
        self.assertIsNotNone(outcomes[0].obligation)
        self.assertEqual(outcomes[0].obligation.lifecycle, "new_obligation")

    def test_inform_claims_never_become_new_obligations(self):
        event = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event])
        claims = fx.claims_from([
            {"field": "amount", "value": 7777, "lifecycle": "inform",
             "evidence_span": "ZAR 7777"},
            {"field": "currency", "value": "ZAR", "lifecycle": "inform",
             "evidence_span": "ZAR"},
            {"field": "event_date", "value": "2026-02-01", "lifecycle": "inform",
             "evidence_span": "on 2026-02-01"},
            {"field": "direction", "value": "debit", "lifecycle": "inform",
             "evidence_span": "charged"},
        ], source_id="message_77")
        outcomes = attach_claims(scope, claims)
        self.assertEqual({outcome.state for outcome in outcomes}, {"unresolved"})

    def test_no_consequential_claim_is_silently_dropped(self):
        event = ff.event(event_id="event_01", status="scheduled", amount=5000)
        claims = fx.claims_from([
            {"field": "amount", "value": 5000, "lifecycle": "amend",
             "evidence_span": "ZAR 5000"},
            {"field": "currency", "value": "ZAR", "lifecycle": "amend",
             "evidence_span": "ZAR"},
            {"field": "description", "value": "updated utility charge",
             "lifecycle": "amend", "evidence_span": "utility charge"},
        ])
        outcomes = attach_claims(ff.scope(events=[event]), claims)
        self.assertEqual(
            sorted(outcome.claim.claim_id for outcome in outcomes),
            sorted(claim.claim_id for claim in claims))


class AttachmentMaterialityTests(unittest.TestCase):
    def _axes(self, root, events, claims):
        dataset, engine = fx.make_engine(root)
        scope = dataset.scope("request_01")
        outcomes = attach_claims(scope, claims)
        axes = build_attachment_axes(scope, outcomes)
        return dataset, engine, scope, outcomes, axes

    def test_attachment_alternatives_can_be_material(self):
        with tempfile.TemporaryDirectory() as directory:
            events = [
                ff.event(
                    event_id="event_01", status="scheduled", amount=5000,
                    category="utilities", event_date=date(2026, 1, 5),
                    settlement_date=date(2026, 1, 5)),
                ff.event(
                    event_id="event_02", status="scheduled", amount=5000,
                    category="utilities", event_date=date(2026, 3, 20),
                    settlement_date=date(2026, 3, 20)),
                ff.event(
                    event_id="event_03", status="scheduled", direction="credit",
                    event_type="income", amount=60000,
                    event_date=date(2026, 2, 1), settlement_date=date(2026, 2, 1)),
            ]
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                desired=date(2026, 3, 25), events=events)
            claims = fx.claims_from([
                {"field": "amount", "value": 50000, "lifecycle": "amend",
                 "evidence_span": "now ZAR 50000"},
                {"field": "currency", "value": "ZAR", "lifecycle": "amend",
                 "evidence_span": "ZAR"},
                {"field": "category", "value": "utilities", "lifecycle": "amend",
                 "evidence_span": "utility payment"},
            ])
            dataset, engine, scope, outcomes, axes = self._axes(root, events, claims)
            self.assertEqual(outcomes[0].state, "ambiguous")
            result = evaluate_attachment_materiality(scope, engine, axes)
            self.assertEqual(result.status, "material")
            self.assertTrue(result.differing_fields)

    def test_attachment_ambiguity_can_remain_immaterial(self):
        with tempfile.TemporaryDirectory() as directory:
            events = [
                ff.event(
                    event_id="event_01", status="settled", amount=5000,
                    category="utilities", event_date=date(2025, 12, 1),
                    settlement_date=date(2025, 12, 1)),
                ff.event(
                    event_id="event_02", status="settled", amount=5000,
                    category="utilities", event_date=date(2025, 12, 2),
                    settlement_date=date(2025, 12, 2)),
            ]
            root = fx.simple_dataset(Path(directory), events=events)
            claims = fx.claims_from([
                {"field": "amount", "value": 90000, "lifecycle": "amend",
                 "evidence_span": "now ZAR 90000"},
                {"field": "currency", "value": "ZAR", "lifecycle": "amend",
                 "evidence_span": "ZAR"},
                {"field": "category", "value": "utilities", "lifecycle": "amend",
                 "evidence_span": "utility payment"},
            ])
            dataset, engine, scope, outcomes, axes = self._axes(root, events, claims)
            self.assertEqual(outcomes[0].state, "ambiguous")
            result = evaluate_attachment_materiality(scope, engine, axes)
            self.assertEqual(result.status, "immaterial")
            self.assertEqual(result.differing_fields, ())

    def test_existing_attachment_versus_new_obligation_is_material(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                category="groceries", event_date=date(2026, 1, 5),
                settlement_date=date(2026, 1, 5))
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000", events=[event])
            claims = fx.claims_from([
                {"field": "amount", "value": 5000, "lifecycle": "new_obligation",
                 "evidence_span": "another ZAR 5000 charge"},
                {"field": "currency", "value": "ZAR", "lifecycle": "new_obligation",
                 "evidence_span": "ZAR"},
                {"field": "event_date", "value": "2026-01-05",
                 "lifecycle": "new_obligation", "evidence_span": "on 2026-01-05"},
                {"field": "direction", "value": "debit",
                 "lifecycle": "new_obligation", "evidence_span": "charged"},
            ])
            dataset, engine, scope, outcomes, axes = self._axes(root, [event], claims)
            kinds = {option.kind for axis in axes for option in axis.options}
            self.assertIn("attached", kinds)
            self.assertIn("new_obligation", kinds)
            result = evaluate_attachment_materiality(scope, engine, axes)
            self.assertEqual(result.status, "material")

    def test_combination_cap_returns_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            events = [
                ff.event(
                    event_id=f"event_0{index}", status="scheduled", amount=5000,
                    event_date=date(2026, 1, 5 + index),
                    settlement_date=date(2026, 1, 5 + index))
                for index in range(1, 4)
            ]
            root = fx.simple_dataset(Path(directory), events=events)
            dataset, engine, scope, outcomes, axes = self._axes(
                root, events, defer_claim(5000))
            self.assertTrue(all(len(axis.options) > 1 for axis in axes))
            from interpret.materiality import MaterialityPolicy

            result = evaluate_attachment_materiality(
                scope, engine, axes, policy=MaterialityPolicy(max_combinations=2))
            self.assertEqual(result.status, "unknown")
            self.assertTrue(result.truncated)


class AttachmentVerificationTests(unittest.TestCase):
    def test_verifier_cannot_force_an_attachment(self):
        event = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event])
        outcomes = attach_claims(scope, defer_claim(5000))
        self.assertNotIn("attach_claim", TOOL_NAMES)
        tools = default_tools(scope, (), attachment_outcomes=outcomes)
        self.assertIn("inspect_attachment_candidates", tools)
        controller = ScriptedController([{
            "action": "attach_claim", "claim_id": outcomes[0].claim.claim_id,
            "event_id": "event_01"}])
        outcome = run_verification(
            scope, (), controller=controller, tools=tools)
        self.assertEqual(outcome.actions, 0)
        self.assertTrue(all(check["status"] == "invalid" for check in outcome.checks))

    def test_verification_can_inspect_candidates_but_not_assign(self):
        event = ff.event(
            event_id="event_01", status="scheduled", amount=5000,
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event])
        claims = defer_claim(5000)
        outcomes = attach_claims(scope, claims)
        tools = default_tools(scope, claims, attachment_outcomes=outcomes)
        result = tools["inspect_attachment_candidates"]({
            "action": "inspect_attachment_candidates",
            "claim_id": claims[0].claim_id,
        })
        self.assertEqual(result["state"], outcomes[0].state)
        self.assertEqual(result["candidates"], list(outcomes[0].candidates))


if __name__ == "__main__":
    unittest.main()

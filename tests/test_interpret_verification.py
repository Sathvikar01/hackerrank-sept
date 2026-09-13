import json
import unittest
from datetime import date
from decimal import Decimal

from interpret.schemas import InterpretationSet, parse_claims
from interpret.verification import (
    TOOL_NAMES,
    ScriptedController,
    VerificationPolicy,
    default_tools,
    run_verification,
)

from tests import finance_fixtures as ff
from tests import interpret_fixtures as fx


def ambiguous_set() -> InterpretationSet:
    claims = parse_claims(
        fx.claims_json([fx.claim_payload(value=5000)]),
        source_kind="message", source_id="message_01", user_id="user_01",
        request_id="request_01", observed_at=date(2026, 1, 2))
    return InterpretationSet(
        event_ref="event_01", field="amount", accepted=Decimal("5000"),
        values=(Decimal("5000"), Decimal("50000")), unresolved=False,
        claims=claims)


class VerificationTests(unittest.TestCase):
    def _run(self, controller, tools, policy=None):
        event = ff.event(event_id="event_01", status="pending", amount=5000,
                         event_date=date(2026, 1, 10),
                         settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event])
        return run_verification(
            scope, (ambiguous_set(),), controller=controller, tools=tools,
            policy=policy or VerificationPolicy())

    def test_controller_stop_ends_immediately(self):
        controller = ScriptedController([{"action": "stop"}])
        outcome = self._run(controller, {})
        self.assertTrue(outcome.ran)
        self.assertEqual(outcome.turns, 1)
        self.assertEqual(outcome.actions, 0)
        self.assertFalse(outcome.hard_stop)

    def test_action_cap_hard_stop(self):
        controller = ScriptedController([
            {"action": "missing_field_check", "event_id": "event_01"},
            {"action": "missing_field_check", "event_id": "event_01"},
            {"action": "missing_field_check", "event_id": "event_01"},
            {"action": "missing_field_check", "event_id": "event_01"},
        ])
        tools = {"missing_field_check": lambda action: {"result": "no new evidence"}}
        outcome = self._run(controller, tools, VerificationPolicy(max_turns=3, max_actions=3))
        self.assertTrue(outcome.hard_stop)
        self.assertEqual(outcome.actions, 3)
        self.assertEqual(len(outcome.checks), 3)
        self.assertEqual(controller.calls, 3)

    def test_unknown_action_is_rejected_and_consumes_budget(self):
        executed = []
        controller = ScriptedController([
            {"action": "run_arbitrary_code"},
            {"action": "shell"},
            {"action": "execute_sql"},
        ])
        tools = {"missing_field_check": lambda action: executed.append(True)}
        outcome = self._run(controller, tools, VerificationPolicy(max_turns=3, max_actions=3))
        self.assertEqual(executed, [])
        self.assertEqual(outcome.actions, 0)
        self.assertEqual(outcome.turns, 3)
        self.assertTrue(outcome.hard_stop)
        self.assertTrue(all(check["status"] == "invalid" for check in outcome.checks))

    def test_malformed_controller_response_fails_closed(self):
        controller = ScriptedController(["not a mapping", 42, {"no_action": True}])
        outcome = self._run(controller, {}, VerificationPolicy(max_turns=3, max_actions=3))
        self.assertTrue(outcome.hard_stop)
        self.assertEqual(outcome.actions, 0)
        self.assertTrue(outcome.unresolved)

    def test_specialist_tool_can_add_claims(self):
        claims = parse_claims(
            fx.claims_json([fx.claim_payload(value=5000)]),
            source_kind="image", source_id="image_01", user_id="user_01",
            request_id="request_01", observed_at=date(2026, 1, 2))

        def reinspect(action):
            return {"result": "re-read image", "claims": claims}

        controller = ScriptedController([
            {"action": "reinspect_image", "source_id": "image_01", "field": "amount"},
            {"action": "stop"},
        ])
        outcome = self._run(controller, {"reinspect_image": reinspect})
        self.assertEqual(outcome.actions, 1)
        self.assertEqual(len(outcome.new_claims), 1)
        json.dumps(outcome.checks)

    def test_default_tools_are_allowlisted_and_deterministic(self):
        message = ff.message(message_id="message_01", text="Payment confirmation.")
        event = ff.event(event_id="event_01", status="pending", amount=None,
                         event_date=date(2026, 1, 10),
                         settlement_date=date(2026, 1, 10))
        scope = ff.scope(events=[event], messages=[message])
        tools = default_tools(scope, ())
        self.assertLessEqual(set(tools), set(TOOL_NAMES))
        self.assertIn("missing_field_check", tools)
        self.assertIn("contradiction_check", tools)
        result = tools["missing_field_check"]({"action": "missing_field_check",
                                               "event_id": "event_01"})
        self.assertEqual(result["missing_fields"], ["amount"])

    def test_hard_stop_preserves_uncertainty(self):
        controller = ScriptedController([{"action": "missing_field_check",
                                          "event_id": "event_01"}] * 4)
        tools = {"missing_field_check": lambda action: {"result": "nothing new"}}
        outcome = self._run(controller, tools)
        self.assertTrue(outcome.hard_stop)
        self.assertTrue(outcome.unresolved)


if __name__ == "__main__":
    unittest.main()

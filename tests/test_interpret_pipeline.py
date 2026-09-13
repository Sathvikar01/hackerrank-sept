import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance.contracts import ContractError
from interpret.pipeline import EvidencePipeline
from interpret.verification import ScriptedController

from tests import finance_fixtures as ff
from tests import interpret_fixtures as fx

AMENDMENT = fx.claims_json([fx.claim_payload(value=50000)])
AGREEMENT = fx.claims_json([fx.claim_payload(value=50000)])
IMAGE_AMOUNT = fx.claims_json([fx.claim_payload(
    field="amount", value=30000, lifecycle="confirm", event_ref="event_01")])


class PipelineTests(unittest.TestCase):
    def _pipeline(self, root, primary_responses, second_responses=None, *, controller=None):
        dataset, engine = fx.make_engine(root)
        pipeline = EvidencePipeline(
            dataset, engine,
            primary=fx.extractor(primary_responses, model="fake/primary"),
            second=fx.extractor(second_responses or {}, model="fake/second"),
            controller=controller,
        )
        return pipeline, dataset, engine

    def test_unattached_message_attaches_deterministically_and_changes_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                category="utilities", description="Utility payment",
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            message = ff.message(
                message_id="message_01",
                text="Your utility payment is now ZAR 50000, due 2026-01-10.")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], messages=[message])
            payload = fx.claims_json([
                fx.claim_payload(field="amount", value=50000, lifecycle="amend",
                                 event_ref=None, evidence="now ZAR 50000"),
                fx.claim_payload(field="currency", value="ZAR", lifecycle="amend",
                                 event_ref=None, evidence="ZAR"),
                fx.claim_payload(field="category", value="utilities",
                                 lifecycle="amend", event_ref=None,
                                 evidence="utility payment"),
                fx.claim_payload(field="event_date", value="2026-01-10",
                                 lifecycle="amend", event_ref=None,
                                 evidence="due 2026-01-10"),
            ])
            pipeline, _, _ = self._pipeline(
                root, {"message_01": payload}, {"message_01": payload})
            result = pipeline.run("request_01")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertEqual(len(result.attachments), 8)
            self.assertTrue(all(
                outcome.state == "attached" and outcome.event_id == "event_01"
                for outcome in result.attachments))
            payload_dict = result.certificate.to_dict()
            self.assertEqual(
                payload_dict["attachments"][0]["event_id"], "event_01")

    def test_new_obligation_message_is_applied_without_mutating_the_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                category="groceries", event_date=date(2026, 1, 5),
                settlement_date=date(2026, 1, 5))
            message = ff.message(
                message_id="message_01",
                text="You will be charged ZAR 9999 on 2026-02-01 for the new plan.")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], messages=[message])
            payload = fx.claims_json([
                fx.claim_payload(field="amount", value=9999,
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="ZAR 9999"),
                fx.claim_payload(field="currency", value="ZAR",
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="ZAR"),
                fx.claim_payload(field="event_date", value="2026-02-01",
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="on 2026-02-01"),
                fx.claim_payload(field="direction", value="debit",
                                 lifecycle="new_obligation", event_ref=None,
                                 evidence="you will be charged"),
            ])
            pipeline, dataset, _ = self._pipeline(
                root, {"message_01": payload}, {"message_01": payload})
            result = pipeline.run("request_01")
            self.assertEqual(result.attachments[0].state, "new_obligation")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("35001"))
            self.assertEqual(
                {event.event_id for event in dataset.scope("request_01").events},
                {"event_01"})

    def test_unresolved_attachment_is_recorded_not_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            message = ff.message(
                message_id="message_01",
                text="There may be a small charge of 123 soon.")
            root = fx.simple_dataset(Path(directory), messages=[message])
            payload = fx.claims_json([
                fx.claim_payload(field="amount", value=123, lifecycle="inform",
                                 event_ref=None, evidence="a small charge of 123"),
            ])
            pipeline, _, _ = self._pipeline(
                root, {"message_01": payload}, {"message_01": payload})
            result = pipeline.run("request_01")
            self.assertEqual(result.attachments[0].state, "unresolved")
            self.assertEqual(result.decision.affordability_status, "affordable_now")
            self.assertEqual(
                len(result.certificate.to_dict()["attachments"]), 2)

    def test_image_without_an_amount_leaves_the_blank_event_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="pending", amount=None,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            link = ff.image(
                image_id="image_01", request_id="request_01",
                related_event_id="event_01")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], images=[link])
            payload = fx.claims_json([fx.claim_payload(
                field="currency", value="ZAR", lifecycle="confirm",
                event_ref=None, evidence="ZAR")])
            pipeline, _, _ = self._pipeline(
                root, {"image_01": payload}, {"image_01": payload})
            result = pipeline.run("request_01")
            self.assertEqual(result.materiality.status, "unknown")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertEqual(result.decision.affordability_status, "not_affordable")

    def test_rejected_claim_with_unknown_event_ref_does_not_gate(self):
        from interpret.pipeline import _required_fields
        from interpret.schemas import ModelCallRecord, Extraction

        call = ModelCallRecord(
            model="fake", purpose="extraction", prompt_tokens=0,
            completion_tokens=0, latency_s=0.0, source_id="message_01")
        extraction = Extraction(
            model="fake", source_kind="message", source_id="message_01", claims=(),
            call=call,
            rejected=({"field": "status", "event_ref": "event_99",
                       "reason": "invalid status value 'closed'"} ,))
        scope = ff.scope(events=[ff.event(
            event_id="event_01", status="scheduled", amount=100,
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5))])
        self.assertEqual(_required_fields(scope, [extraction]), ())

    def test_clean_request_skips_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fx.simple_dataset(Path(directory))
            controller = ScriptedController([])
            pipeline, _, _ = self._pipeline(root, {}, controller=controller)
            result = pipeline.run("request_01")
            self.assertFalse(result.used_verification)
            self.assertEqual(controller.calls, 0)
            self.assertEqual(result.materiality.status, "immaterial")
            self.assertEqual(result.decision.affordability_status, "affordable_now")
            self.assertTrue(result.certificate.verified)

    def test_message_amendment_changes_the_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            message = ff.message(
                message_id="message_01", related_event_id="event_01",
                text="Your scheduled payment has been amended to ZAR 50000.")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], messages=[message])
            pipeline, _, _ = self._pipeline(
                root, {"message_01": AMENDMENT}, {"message_01": AGREEMENT})
            result = pipeline.run("request_01")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertEqual(result.decision.affordability_status, "not_affordable")
            self.assertFalse(result.used_verification)
            facts = result.certificate.to_dict()["facts"]
            self.assertTrue(any(
                fact["value"] == "50000" and fact["provenance"][0]["record_id"] == "message_01"
                for fact in facts))

    def test_image_backed_missing_amount_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="pending", amount=None,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            link = ff.image(
                image_id="image_01", request_id="request_01",
                related_event_id="event_01")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], images=[link])
            pipeline, _, _ = self._pipeline(
                root, {"image_01": IMAGE_AMOUNT}, {"image_01": IMAGE_AMOUNT})
            result = pipeline.run("request_01")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("20000"))
            self.assertFalse(result.used_verification)
            self.assertEqual(len(result.certificate.model_calls), 2)
            facts = result.certificate.to_dict()["facts"]
            self.assertTrue(any(
                fact["provenance"][0]["record_id"] == "image_01" for fact in facts))

    def test_primary_extraction_failure_fails_closed_on_blank_amount(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="pending", amount=None,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            link = ff.image(
                image_id="image_01", request_id="request_01",
                related_event_id="event_01")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], images=[link])
            pipeline, _, _ = self._pipeline(
                root, {"image_01": "not json"}, {"image_01": IMAGE_AMOUNT})
            result = pipeline.run("request_01")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertEqual(result.decision.affordability_status, "not_affordable")
            self.assertTrue(any(
                "image_01" in error for error in result.certificate.extraction_errors))

    def test_independent_disagreement_is_material_and_uses_the_safer_value(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            message = ff.message(
                message_id="message_01", related_event_id="event_01",
                text="Your scheduled payment has been amended to ZAR 50000.")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], messages=[message])
            controller = ScriptedController([{"action": "stop"}])
            pipeline, _, _ = self._pipeline(
                root, {"message_01": AMENDMENT},
                {"message_01": fx.claims_json([fx.claim_payload(value=5000)])},
                controller=controller)
            result = pipeline.run("request_01")
            self.assertTrue(result.used_verification)
            self.assertGreaterEqual(controller.calls, 1)
            self.assertEqual(result.materiality.status, "material")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertTrue(any("disagree" in note for note in result.certificate.unresolved))

    def test_unknown_missing_amount_gates_verification_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="pending", amount=None,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000", events=[event])
            controller = ScriptedController([
                {"action": "missing_field_check", "event_id": "event_01"},
                {"action": "stop"},
            ])
            pipeline, _, _ = self._pipeline(root, {}, controller=controller)
            result = pipeline.run("request_01")
            self.assertTrue(result.used_verification)
            self.assertEqual(result.materiality.status, "unknown")
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertEqual(result.decision.affordability_status, "not_affordable")
            self.assertTrue(result.certificate.unresolved)

    def test_malformed_model_output_falls_back_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            message = ff.message(message_id="message_01", text="Payment update.")
            root = fx.simple_dataset(Path(directory), messages=[message])
            pipeline, _, _ = self._pipeline(root, {"message_01": "not json"})
            result = pipeline.run("request_01")
            # An unreadable source never silently disappears: the extraction
            # failure stays unresolved and blocks positive certification.
            self.assertTrue(any(
                "message_01" in error for error in result.certificate.extraction_errors))
            self.assertTrue(any(
                "primary extraction failed for message:message_01" in note
                for note in result.certificate.unresolved))
            self.assertEqual(
                result.decision.recommended_payment_method, "not_recommended")
            self.assertEqual(
                result.decision.affordability_status, "not_affordable")
            self.assertTrue(any(
                "positive recommendation blocked" in note
                or "unresolved extraction errors remain" in note
                for note in result.certificate.unresolved))

    def test_verify_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fx.simple_dataset(Path(directory))
            dataset, engine = fx.make_engine(root)
            pipeline = EvidencePipeline(
                dataset, engine,
                primary=fx.extractor({}), second=fx.extractor({}),
                controller=None)
            pipeline.engine.verify = lambda *args, **kwargs: (_ for _ in ()).throw(
                ContractError("forced verify failure"))
            result = pipeline.run("request_01")
            self.assertFalse(result.certificate.verified)
            self.assertEqual(result.decision.amount_safe_to_pay, Decimal("0"))
            self.assertEqual(result.decision.affordability_status, "not_affordable")

    def test_certificate_is_machine_readable_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            event = ff.event(
                event_id="event_01", status="scheduled", amount=5000,
                event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
            message = ff.message(
                message_id="message_01", related_event_id="event_01",
                text="Your scheduled payment has been amended to ZAR 50000.")
            root = fx.simple_dataset(
                Path(directory), balance="60000", requested="45000",
                events=[event], messages=[message])
            pipeline, _, _ = self._pipeline(
                root, {"message_01": AMENDMENT}, {"message_01": AGREEMENT})
            result = pipeline.run("request_01")
            payload = result.certificate.to_dict()
            json.dumps(payload)
            self.assertEqual(payload["request_id"], "request_01")
            self.assertIn("facts", payload)
            self.assertIn("interpretations", payload)
            self.assertIn("disagreements", payload)
            self.assertIn("verification_checks", payload)
            self.assertIn("materiality", payload)
            self.assertIn("attachment_differing_fields", payload["materiality"])
            self.assertIn("decision", payload)
            self.assertIn("verified", payload)
            self.assertIn("unresolved", payload)
            self.assertIn("model_calls", payload)
            for fact in payload["facts"]:
                self.assertTrue(fact["provenance"])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date
from decimal import Decimal

from interpret.extractor import EvidenceExtractor
from interpret.independent import compare_extractions, required_reviews
from interpret.interpretations import build_interpretation_sets
from interpret.schemas import ExtractionError

from tests import finance_fixtures as ff
from tests import interpret_fixtures as fx


class ExtractorTests(unittest.TestCase):
    def test_extract_message_returns_typed_claims_with_provenance(self):
        message = ff.message(
            message_id="message_01",
            text="Your scheduled payment was amended to ZAR 50000 effective 2026-01-10.")
        scope = ff.scope(messages=[message])
        extractor = fx.extractor({
            "message_01": fx.claims_json([fx.claim_payload(value=50000)]),
        })
        extraction = extractor.extract_message(scope, message)
        self.assertEqual(extraction.source_kind, "message")
        self.assertEqual(extraction.source_id, "message_01")
        self.assertEqual(len(extraction.claims), 1)
        claim = extraction.claims[0]
        self.assertEqual(claim.value, Decimal("50000"))
        self.assertEqual(claim.provenance.source, "messages.csv")
        self.assertEqual(claim.provenance.record_id, "message_01")
        self.assertEqual(claim.provenance.locator, "message_text")
        self.assertEqual(extraction.call.model, "fake/primary")
        self.assertIsNone(extraction.error)

    def test_extract_image_sends_the_original_image(self):
        link = ff.image(image_id="image_01", request_id="request_01",
                        related_event_id="event_01")
        scope = ff.scope(images=[link])
        client = fx.FakeChatClient({
            "image_01": fx.claims_json([fx.claim_payload(
                field="amount", value=4365000, lifecycle="confirm",
                event_ref="event_01", evidence="Net Pay IDR 4,365,000")]),
        })
        extractor = EvidenceExtractor(client, model="fake/primary")
        extraction = extractor.extract_image(scope, link, event_ref="event_01")
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(client.calls[0]["images"])
        self.assertTrue(client.calls[0]["images"][0].startswith("data:image/png;base64,"))
        self.assertEqual(extraction.claims[0].value, Decimal("4365000"))
        self.assertEqual(extraction.claims[0].provenance.locator, "image_region")

    def test_missing_image_file_fails_closed(self):
        link = ff.image(image_id="image_99", request_id="request_01",
                        related_event_id="event_01")
        scope = ff.scope(images=[link])
        extractor = fx.extractor({"image_99": fx.claims_json([])})
        with self.assertRaises(ExtractionError):
            extractor.extract_image(scope, link, event_ref="event_01")

    def test_extract_scope_targets_blank_amount_images_and_messages(self):
        event = ff.event(
            event_id="event_01", amount=None, status="pending",
            event_date=date(2026, 1, 10), settlement_date=date(2026, 1, 10))
        link = ff.image(image_id="image_01", request_id="request_01",
                        related_event_id="event_01")
        message = ff.message(message_id="message_01", text="Payment confirmation attached.")
        scope = ff.scope(events=[event], images=[link], messages=[message])
        extractor = fx.extractor({
            "image_01": fx.claims_json([fx.claim_payload(
                field="amount", value=30000, lifecycle="confirm", event_ref="event_01")]),
            "message_01": fx.claims_json([]),
        })
        extractions = extractor.extract_scope(scope)
        keys = {(item.source_kind, item.source_id) for item in extractions}
        self.assertIn(("image", "image_01"), keys)
        self.assertIn(("message", "message_01"), keys)

    def test_hallucinated_event_ref_is_detached_and_recorded(self):
        message = ff.message(message_id="message_01")
        scope = ff.scope(events=[ff.event(event_id="event_77")], messages=[message])
        payload = fx.claims_json([{
            "field": "amount", "value": 5000, "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "ZAR 5000"}])
        extraction = fx.extractor({"message_01": payload}).extract_message(scope, message)
        self.assertIsNone(extraction.claims[0].event_ref)
        self.assertTrue(
            any("event_01" in item["reason"] for item in extraction.rejected))

    def test_truncated_json_is_retried_once_with_more_budget(self):
        message = ff.message(message_id="message_01")
        scope = ff.scope(messages=[message])
        client = fx.FakeChatClient(
            {},
            sequence=[
                '```json\n{"claims": [',
                fx.claims_json([fx.claim_payload(value=828)]),
            ])
        extractor = EvidenceExtractor(client, model="fake/primary", max_tokens=8192)
        extraction = extractor.extract_message(scope, message)
        self.assertEqual(len(extraction.claims), 1)
        self.assertEqual(len(client.calls), 2)
        self.assertGreater(client.calls[1]["max_tokens"], client.calls[0]["max_tokens"])

    def test_empty_content_is_retried_with_more_output_budget(self):
        message = ff.message(message_id="message_01")
        scope = ff.scope(messages=[message])
        client = fx.FakeChatClient(
            {"message_01": fx.claims_json([fx.claim_payload(value=500)])},
            fail_times=1)
        extractor = EvidenceExtractor(client, model="fake/primary", max_tokens=8192)
        extraction = extractor.extract_message(scope, message)
        self.assertEqual(len(extraction.claims), 1)
        self.assertEqual(len(client.calls), 2)
        self.assertGreater(client.calls[1]["max_tokens"], client.calls[0]["max_tokens"])

    def test_image_claims_are_forced_to_the_linked_event(self):
        link = ff.image(image_id="image_01", request_id="request_01",
                        related_event_id="event_01")
        scope = ff.scope(
            events=[ff.event(event_id="event_01", status="scheduled", amount=500),
                    ff.event(event_id="event_02", status="scheduled", amount=700)],
            images=[link])
        payload = fx.claims_json([{
            "field": "amount", "value": 500, "lifecycle": "confirm",
            "event_ref": "event_02", "evidence_span": "total 500"}])
        client = fx.FakeChatClient({"image_01": payload})
        extractor = EvidenceExtractor(client, model="fake/primary")
        extraction = extractor.extract_image(scope, link, event_ref="event_01")
        self.assertEqual(extraction.claims[0].event_ref, "event_01")
        self.assertTrue(any(
            "event_02" in item["reason"] for item in extraction.rejected))

    def test_message_model_event_ref_is_not_authoritative(self):
        message = ff.message(message_id="message_01", related_event_id=None)
        scope = ff.scope(
            events=[ff.event(event_id="event_01", status="scheduled", amount=500)],
            messages=[message])
        payload = fx.claims_json([{
            "field": "amount", "value": 500, "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "ZAR 500"}])
        extraction = fx.extractor({"message_01": payload}).extract_message(scope, message)
        self.assertIsNone(extraction.claims[0].event_ref)
        self.assertTrue(any(
            "not accepted" in item["reason"] for item in extraction.rejected))

    def test_malformed_claims_are_dropped_and_recorded_not_coerced(self):
        message = ff.message(message_id="message_01")
        scope = ff.scope(messages=[message])
        payload = fx.claims_json([
            {"field": "amount", "value": 50000, "event_ref": "event_01",
             "evidence_span": "ZAR 50000"},
            {"field": "event_date", "value": "Aug-2019", "event_ref": "event_01",
             "evidence_span": "Aug-2019 pay period"},
        ])
        extractor = fx.extractor({"message_01": payload})
        extraction = extractor.extract_message(scope, message)
        self.assertEqual([claim.field for claim in extraction.claims], ["amount"])
        self.assertEqual(extraction.rejected[0]["field"], "event_date")
        self.assertIn("event_date", extraction.rejected[0]["reason"])

    def test_malformed_model_output_fails_closed(self):
        message = ff.message(message_id="message_01")
        scope = ff.scope(messages=[message])
        extractor = fx.extractor({"message_01": "definitely not json"})
        with self.assertRaises(ExtractionError):
            extractor.extract_message(scope, message)

    def test_provider_failure_fails_closed(self):
        message = ff.message(message_id="message_01")
        scope = ff.scope(messages=[message])
        extractor = EvidenceExtractor(
            fx.FakeChatClient({}, fail=True), model="fake/primary")
        with self.assertRaises(ExtractionError):
            extractor.extract_message(scope, message)


class IndependentExtractionTests(unittest.TestCase):
    def _extraction(self, value, *, confidence=0.9, source_id="message_01"):
        extractor = fx.extractor({
            source_id: fx.claims_json([fx.claim_payload(
                value=value, confidence=confidence, event_ref="event_01")]),
        })
        message = ff.message(message_id=source_id)
        return extractor.extract_message(ff.scope(messages=[message]), message)

    def test_agreement_and_disagreement_are_detected(self):
        review = compare_extractions(
            self._extraction(100), self._extraction(100, confidence=0.4))
        self.assertFalse(review.has_disagreement)
        self.assertEqual(review.comparisons[0].agreement, "agree")
        review = compare_extractions(
            self._extraction(100), self._extraction(120, confidence=0.4))
        self.assertTrue(review.has_disagreement)
        self.assertEqual(review.comparisons[0].agreement, "disagree")

    def test_missing_second_value_is_recorded(self):
        second = fx.extractor({"message_01": fx.claims_json([])}).extract_message(
            ff.scope(messages=[ff.message(message_id="message_01")]),
            ff.message(message_id="message_01"))
        review = compare_extractions(self._extraction(100), second)
        self.assertEqual(review.comparisons[0].agreement, "missing")

    def test_required_reviews_flags_images_and_consequential_messages(self):
        from interpret.schemas import parse_claims

        def built(source_kind, source_id, payloads):
            claims = parse_claims(
                fx.claims_json(payloads), source_kind=source_kind, source_id=source_id,
                user_id="user_01", request_id=None, observed_at=date(2026, 1, 2))
            return fx.make_extraction(source_kind, source_id, claims)

        image = built("image", "image_01", [fx.claim_payload(
            field="amount", value=4365000, lifecycle="confirm")])
        amount_message = built("message", "message_02", [fx.claim_payload(
            field="amount", value=100, lifecycle="inform")])
        category_message = built("message", "message_03", [fx.claim_payload(
            field="category", value="utilities", lifecycle="inform")])
        refs = required_reviews([image, amount_message, category_message])
        self.assertIn(("image", "image_01"), refs)
        self.assertIn(("message", "message_02"), refs)
        self.assertNotIn(("message", "message_03"), refs)


class InterpretationSetTests(unittest.TestCase):
    def test_confidence_metadata_never_overrides_evidence(self):
        high = fx.extractor({
            "message_01": fx.claims_json([fx.claim_payload(value=100, confidence=0.99)]),
        }).extract_message(
            ff.scope(messages=[ff.message(message_id="message_01",
                                          related_event_id="event_01")]),
            ff.message(message_id="message_01", related_event_id="event_01"))
        low = fx.extractor({
            "message_01": fx.claims_json([fx.claim_payload(value=120, confidence=0.01)]),
        }).extract_message(
            ff.scope(messages=[ff.message(message_id="message_01",
                                          related_event_id="event_01")]),
            ff.message(message_id="message_01", related_event_id="event_01"))
        sets = build_interpretation_sets(
            list(high.claims) + list(low.claims), directions={"event_01": "debit"})
        amount = next(item for item in sets if item.field == "amount")
        self.assertEqual(amount.accepted, Decimal("120"))
        self.assertIn(Decimal("100"), amount.values)
        self.assertTrue(amount.ambiguous)

    def test_agreement_is_a_single_admissible_value(self):
        first = fx.extractor({
            "message_01": fx.claims_json([fx.claim_payload(value=500, confidence=0.9)]),
        }).extract_message(
            ff.scope(messages=[ff.message(message_id="message_01",
                                          related_event_id="event_01")]),
            ff.message(message_id="message_01", related_event_id="event_01"))
        second = fx.extractor({
            "message_01": fx.claims_json([fx.claim_payload(value=500, confidence=0.2)]),
        }).extract_message(
            ff.scope(messages=[ff.message(message_id="message_01",
                                          related_event_id="event_01")]),
            ff.message(message_id="message_01", related_event_id="event_01"))
        sets = build_interpretation_sets(
            list(first.claims) + list(second.claims), directions={"event_01": "debit"})
        amount = next(item for item in sets if item.field == "amount")
        self.assertEqual(amount.values, (Decimal("500"),))
        self.assertFalse(amount.ambiguous)

    def test_explicit_cancellation_supersedes_older_assertions(self):
        cancelled = fx.extractor({
            "message_21": fx.claims_json([fx.claim_payload(
                field="status", value="cancelled", lifecycle="cancel", event_ref="event_01")]),
        }).extract_message(
            ff.scope(messages=[ff.message(message_id="message_21",
                                          related_event_id="event_01")]),
            ff.message(message_id="message_21", related_event_id="event_01"))
        active = fx.extractor({
            "message_22": fx.claims_json([fx.claim_payload(
                field="status", value="scheduled", lifecycle="inform", event_ref="event_01")]),
        }).extract_message(
            ff.scope(messages=[ff.message(message_id="message_22",
                                          related_event_id="event_01")]),
            ff.message(message_id="message_22", related_event_id="event_01"))
        sets = build_interpretation_sets(
            list(cancelled.claims) + list(active.claims), directions={"event_01": "debit"})
        status = next(item for item in sets if item.field == "status")
        self.assertEqual(status.accepted, "cancelled")
        self.assertEqual(status.values, ("cancelled",))
        self.assertFalse(status.ambiguous)


if __name__ == "__main__":
    unittest.main()

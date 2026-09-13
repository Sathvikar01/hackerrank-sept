import json
import unittest
from datetime import date
from decimal import Decimal

from interpret.schemas import (
    ExtractedClaim,
    ExtractionError,
    InterpretationSet,
    parse_claims,
    parse_model_json,
)

from tests import interpret_fixtures as fx

CONTEXT = dict(
    source_kind="message",
    source_id="message_01",
    user_id="user_01",
    request_id="request_01",
    observed_at=date(2026, 1, 2),
)


class PayloadParsingTests(unittest.TestCase):
    def test_parses_typed_claims_with_provenance(self):
        payload = json.dumps({"claims": [{
            "field": "amount", "value": 1422.85, "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "reduced to EUR 1422.85",
            "confidence": 0.8,
        }, {
            "field": "currency", "value": "EUR", "lifecycle": "amend",
            "event_ref": "event_01", "evidence_span": "EUR",
        }]})
        claims = parse_claims(payload, **CONTEXT)
        self.assertEqual(len(claims), 2)
        amount = claims[0]
        self.assertEqual(amount.value, Decimal("1422.85"))
        self.assertEqual(amount.lifecycle, "amend")
        self.assertEqual(amount.event_ref, "event_01")
        self.assertEqual(amount.provenance.record_id, "message_01")
        self.assertEqual(amount.provenance.excerpt, "reduced to EUR 1422.85")
        self.assertEqual(amount.confidence, Decimal("0.8"))
        self.assertEqual(amount.observed_at, date(2026, 1, 2))

    def test_null_value_is_not_a_zero_claim(self):
        payload = json.dumps({"claims": [
            {"field": "amount", "value": None, "evidence_span": "amount not shown"},
            {"field": "currency", "value": "USD", "evidence_span": "USD"},
        ]})
        claims = parse_claims(payload, **CONTEXT)
        self.assertEqual([claim.field for claim in claims], ["currency"])

    def test_malformed_payloads_fail_closed(self):
        cases = [
            "not json at all",
            json.dumps([1, 2, 3]),
            json.dumps({"claims": "no"}),
            json.dumps({"claims": [{"field": "amount", "value": "abc", "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "amount", "value": -5, "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "amount", "value": True, "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "nonsense", "value": 1, "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "amount", "value": 5, "lifecycle": "obliterate",
                                    "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "amount", "value": 5, "confidence": 2.0,
                                    "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "amount", "value": 5}]}),
            json.dumps({"claims": [{"field": "event_date", "value": "01/02/2026",
                                    "evidence_span": "x"}]}),
            json.dumps({"claims": [{"field": "currency", "value": "GBP",
                                    "evidence_span": "x"}]}),
        ]
        for payload in cases:
            with self.assertRaises(ExtractionError, msg=payload):
                parse_claims(payload, **CONTEXT)

    def test_fenced_json_is_parsed_but_garbage_is_rejected(self):
        fenced = '```json\n{"claims": []}\n```'
        self.assertEqual(parse_model_json(fenced)["claims"], [])
        with self.assertRaises(ExtractionError):
            parse_model_json("```json\n{broken\n```")

    def test_interpretation_set_reports_ambiguity(self):
        claims = parse_claims(json.dumps({"claims": [
            {"field": "amount", "value": 100, "evidence_span": "a", "event_ref": "event_01"},
        ]}), **CONTEXT)
        single = InterpretationSet(
            event_ref="event_01", field="amount", accepted=Decimal("100"),
            values=(Decimal("100"),), unresolved=False, claims=claims)
        self.assertFalse(single.ambiguous)
        ambiguous = InterpretationSet(
            event_ref="event_01", field="amount", accepted=Decimal("100"),
            values=(Decimal("100"), Decimal("120")), unresolved=False, claims=claims)
        self.assertTrue(ambiguous.ambiguous)

    def test_claim_validation_rejects_bad_identity(self):
        from finance.contracts import Provenance

        with self.assertRaises(ExtractionError):
            ExtractedClaim(
                claim_id="", source_kind="message", source_id="message_01",
                user_id="user_01", request_id=None, event_ref=None, field="amount",
                value=Decimal("5"), lifecycle="inform", evidence="x", confidence=None,
                observed_at=date(2026, 1, 2),
                provenance=Provenance("messages.csv", "message_01", "message_text"))


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date
from decimal import Decimal

from finance.contracts import FactClaim, Provenance
from finance.forecast import project
from finance.reconcile import (
    LinkRelation,
    apply_cancellations,
    classify_link,
    resolve_claims,
    superseded_event_ids,
)

from tests import finance_fixtures as fixtures


def claim(
    claim_id: str,
    *,
    kind: str = "assertion",
    grounding: str = "structured",
    field: str = "amount",
    value=None,
    ref: str = "event_01",
    source: str = "event:event_01",
    observed: date = date(2026, 1, 1),
) -> FactClaim:
    return FactClaim(
        claim_id=claim_id,
        fact_ref=ref,
        field_name=field,
        value=Decimal("100") if value is None else value,
        claim_kind=kind,
        grounding=grounding,
        source_id=source,
        observed_at=observed,
        provenance=Provenance("messages.csv", source, field),
    )


class ReconcileTests(unittest.TestCase):
    def test_explicit_cancellation_beats_newer_assertion(self):
        resolved = resolve_claims([
            claim("c2", kind="cancellation", value="cancelled", source="message:m2",
                  observed=date(2026, 1, 1)),
            claim("c1", kind="assertion", value="pending", source="message:m1",
                  observed=date(2026, 1, 10)),
        ], {"event_01": "debit"})
        self.assertEqual(len(resolved), 1)
        self.assertFalse(resolved[0].unresolved)
        self.assertEqual(resolved[0].accepted.value, "cancelled")
        self.assertEqual(resolved[0].reason, "explicit cancellation, settlement, or amendment")

    def test_newer_evidence_from_same_source_wins(self):
        resolved = resolve_claims([
            claim("c1", value=Decimal("100"), source="message:m1",
                  observed=date(2026, 1, 1)),
            claim("c2", value=Decimal("120"), source="message:m1",
                  observed=date(2026, 1, 5)),
        ], {"event_01": "debit"})
        self.assertEqual(resolved[0].accepted.value, Decimal("120"))
        self.assertEqual(resolved[0].reason, "newer evidence from the same source")

    def test_settled_fact_beats_estimate(self):
        resolved = resolve_claims([
            claim("c1", grounding="settled", value=Decimal("100"), source="event:event_01",
                  observed=date(2026, 1, 1)),
            claim("c2", grounding="estimate", value=Decimal("80"), source="model:estimate",
                  observed=date(2026, 1, 9)),
        ], {"event_01": "debit"})
        self.assertEqual(resolved[0].accepted.value, Decimal("100"))

    def test_safer_interpretation_is_direction_aware(self):
        debit = resolve_claims([
            claim("c1", value=Decimal("100"), source="message:m1"),
            claim("c2", value=Decimal("140"), source="message:m2"),
        ], {"event_01": "debit"})
        self.assertEqual(debit[0].accepted.value, Decimal("140"))
        credit = resolve_claims([
            claim("c1", value=Decimal("100"), source="message:m1"),
            claim("c2", value=Decimal("140"), source="message:m2"),
        ], {"event_01": "credit"})
        self.assertEqual(credit[0].accepted.value, Decimal("100"))

    def test_unresolved_when_no_safer_interpretation_exists(self):
        resolved = resolve_claims([
            claim("c1", field="description", value="rent", source="message:m1"),
            claim("c2", field="description", value="utility", source="message:m2"),
        ], {"event_01": "debit"})
        self.assertTrue(resolved[0].unresolved)
        self.assertIsNone(resolved[0].accepted)
        self.assertEqual(len(resolved[0].alternatives), 2)

    def test_linked_event_is_not_automatically_a_duplicate(self):
        first = fixtures.event(
            event_id="event_01", amount=fixtures.D("1000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5))
        second = fixtures.event(
            event_id="event_02", amount=fixtures.D("1000"),
            event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5),
            linked_event_id="event_01")
        self.assertEqual(classify_link(second, first), LinkRelation.unknown)
        forecast = project(
            fixtures.scope(events=[first, second]),
            fixtures.no_variable_policy())
        self.assertEqual(forecast.minimum, fixtures.D("98000"))

    def test_explicit_amendment_supersedes_linked_event(self):
        amendment = claim(
            "c1", kind="amendment", field="replaces", value="event_01", ref="event_02")
        superseded = superseded_event_ids([amendment])
        self.assertEqual(superseded, frozenset({"event_01"}))
        first = fixtures.event(event_id="event_01")
        second = fixtures.event(event_id="event_02", linked_event_id="event_01")
        self.assertEqual(
            classify_link(second, first, [amendment]),
            LinkRelation.replacement_candidate)

    def test_apply_cancellations_removes_the_targeted_pending_debit(self):
        events = [
            fixtures.event(event_id="event_01", status="pending",
                           event_date=date(2026, 1, 5), settlement_date=date(2026, 1, 5)),
            fixtures.event(event_id="event_02", status="scheduled",
                           event_date=date(2026, 1, 6), settlement_date=date(2026, 1, 6)),
        ]
        cancellation = claim(
            "c1", kind="cancellation", field="status", value="cancelled",
            ref="event_01", source="message:m1")
        kept, unresolved = apply_cancellations(events, [cancellation])
        self.assertEqual([event.event_id for event in kept], ["event_02"])
        self.assertEqual(unresolved, ())


if __name__ == "__main__":
    unittest.main()

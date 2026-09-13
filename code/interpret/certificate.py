from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from finance.contracts import CanonicalFact

from .schemas import (
    IndependentReview,
    InterpretationSet,
    ModelCallRecord,
)


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    return value


@dataclass(frozen=True)
class EvidenceCertificate:
    request_id: str
    facts: tuple[CanonicalFact, ...]
    interpretations: tuple[InterpretationSet, ...]
    disagreements: tuple[IndependentReview, ...]
    verification_checks: tuple[Mapping[str, Any], ...]
    materiality: Mapping[str, Any]
    decision_row: Mapping[str, str]
    verified: bool
    unresolved: tuple[str, ...]
    model_calls: tuple[ModelCallRecord, ...]
    extraction_errors: tuple[str, ...] = ()
    rejected_claims: tuple[Mapping[str, Any], ...] = ()
    attachments: tuple = ()

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "fact_ref": fact.fact_ref,
                    "field": fact.field_name,
                    "value": json_safe(fact.value),
                    "source_kind": fact.source_kind,
                    "provenance": [
                        {
                            "source": item.source,
                            "record_id": item.record_id,
                            "locator": item.locator,
                            "excerpt": item.excerpt,
                        }
                        for item in fact.provenance
                    ],
                }
                for fact in self.facts
            ],
            "interpretations": [
                {
                    "event_ref": item.event_ref,
                    "field": item.field,
                    "accepted": json_safe(item.accepted),
                    "values": [json_safe(value) for value in item.values],
                    "unresolved": item.unresolved,
                    "claim_count": len(item.claims),
                }
                for item in self.interpretations
            ],
            "disagreements": [
                {
                    "source_kind": review.source_kind,
                    "source_id": review.source_id,
                    "model": review.model,
                    "comparisons": [json_safe(asdict(item)) for item in review.comparisons],
                }
                for review in self.disagreements
            ],
            "verification_checks": json_safe(list(self.verification_checks)),
            "materiality": json_safe(dict(self.materiality)),
            "decision": dict(self.decision_row),
            "verified": self.verified,
            "unresolved": list(self.unresolved),
            "model_calls": [
                json_safe(asdict(call)) for call in self.model_calls
            ],
            "extraction_errors": list(self.extraction_errors),
            "rejected_claims": json_safe(list(self.rejected_claims)),
            "attachments": [
                {
                    "claim_id": item.claim.claim_id,
                    "source": f"{item.claim.source_kind}:{item.claim.source_id}",
                    "field": item.claim.field,
                    "state": item.state,
                    "event_id": item.event_id,
                    "candidates": list(item.candidates),
                    "reasons": list(item.reasons),
                    "obligation": (
                        json_safe(asdict(item.obligation))
                        if item.obligation is not None else None),
                }
                for item in self.attachments
            ],
        }

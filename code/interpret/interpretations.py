from __future__ import annotations

from typing import Any, Mapping, Sequence

from finance.contracts import FactClaim
from finance.reconcile import resolve_claims

from .schemas import ExtractedClaim, InterpretationSet

CLAIM_KIND_MAP = {
    "inform": "assertion",
    "confirm": "confirmation",
    "amend": "amendment",
    "cancel": "cancellation",
    "delay": "delay",
    "new_obligation": "assertion",
}


def build_interpretation_sets(
    claims: Sequence[ExtractedClaim],
    *,
    directions: Mapping[str, str] | None = None,
    required_fields: Sequence[tuple[str, str]] = (),
) -> tuple[InterpretationSet, ...]:
    directions = dict(directions or {})
    attached = [claim for claim in claims if claim.event_ref is not None]
    fact_claims = [
        FactClaim(
            claim_id=claim.claim_id,
            fact_ref=claim.event_ref,
            field_name=claim.field,
            value=claim.value,
            claim_kind=CLAIM_KIND_MAP[claim.lifecycle],
            grounding=claim.source_kind,
            source_id=f"{claim.source_kind}:{claim.source_id}",
            observed_at=claim.observed_at,
            provenance=claim.provenance,
        )
        for claim in attached
    ]
    sets: list[InterpretationSet] = []
    for resolved in resolve_claims(fact_claims, directions):
        source_claims = tuple(
            claim for claim in attached
            if claim.event_ref == resolved.fact_ref and claim.field == resolved.field_name
        )
        if resolved.unresolved:
            values = tuple(sorted(
                {claim.value for claim in resolved.alternatives}, key=repr))
            sets.append(InterpretationSet(
                event_ref=resolved.fact_ref, field=resolved.field_name, accepted=None,
                values=values, unresolved=True, claims=source_claims))
            continue
        accepted = resolved.accepted.value
        if resolved.reason == "financially safer supported interpretation":
            candidates = {accepted, *(claim.value for claim in resolved.alternatives)}
        else:
            candidates = {accepted}
        sets.append(InterpretationSet(
            event_ref=resolved.fact_ref, field=resolved.field_name, accepted=accepted,
            values=tuple(sorted(candidates, key=repr)), unresolved=False,
            claims=source_claims))
    existing = {(item.event_ref, item.field) for item in sets}
    for event_ref, field in required_fields:
        if (event_ref, field) not in existing:
            sets.append(InterpretationSet(
                event_ref=event_ref, field=field, accepted=None, values=(),
                unresolved=True, claims=()))
    return tuple(sorted(sets, key=lambda item: (str(item.event_ref), item.field)))


def unattached_claims(claims: Sequence[ExtractedClaim]) -> tuple[ExtractedClaim, ...]:
    return tuple(claim for claim in claims if claim.event_ref is None)

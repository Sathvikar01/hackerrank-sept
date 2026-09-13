from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Sequence

from .contracts import ContractError, FactClaim, FinancialEvent, ResolvedFact, UnresolvedFactError

EXPLICIT_KINDS = frozenset({"cancellation", "amendment", "settlement"})
ASSERTION_KINDS = frozenset({"assertion", "confirmation", "delay", "estimate"})

_STATUS_SAFETY = {
    "failed": 1,
    "cancelled": 0,
    "unrealized": 0,
    "settled": 2,
    "scheduled": 2,
    "pending": 2,
}


class LinkRelation(str, Enum):
    separate = "separate"
    duplicate_candidate = "duplicate_candidate"
    replacement_candidate = "replacement_candidate"
    retry_candidate = "retry_candidate"
    unknown = "unknown"


def safer_value(field_name: str, direction: str | None, values: Sequence[Any]) -> Any | None:
    if not values:
        return None
    if field_name == "amount":
        if direction == "debit":
            return max(values)
        if direction == "credit":
            return min(values)
        return None
    if field_name in {"event_date", "settlement_date", "payment_date", "effective_date"}:
        if direction == "debit":
            return min(values)
        if direction == "credit":
            return max(values)
        return None
    if field_name == "status":
        if direction == "debit":
            return max(values, key=lambda value: _STATUS_SAFETY.get(str(value), 1))
        if direction == "credit":
            return min(values, key=lambda value: _STATUS_SAFETY.get(str(value), 1))
        return max(values, key=lambda value: _STATUS_SAFETY.get(str(value), 1))
    return None


def _latest(claims: Sequence[FactClaim]) -> FactClaim:
    return max(claims, key=lambda claim: (claim.observed_at, claim.claim_id))


def _distinct_values(claims: Sequence[FactClaim]) -> list[Any]:
    seen: list[Any] = []
    for claim in claims:
        if claim.value not in seen:
            seen.append(claim.value)
    return seen


def _resolve_group(claims: Sequence[FactClaim], direction: str | None) -> ResolvedFact:
    fact_ref, field_name = claims[0].fact_ref, claims[0].field_name
    values = _distinct_values(claims)
    if len(values) == 1:
        accepted = _latest(claims)
        return ResolvedFact(fact_ref, field_name, accepted,
                            tuple(claim for claim in claims if claim is not accepted),
                            False, "single consistent value")

    explicit = [claim for claim in claims if claim.claim_kind in EXPLICIT_KINDS]
    pool = explicit or list(claims)
    pool_values = _distinct_values(pool)

    if len(pool_values) == 1:
        accepted = _latest(pool)
        reason = "explicit cancellation, settlement, or amendment" if explicit \
            else "consistent supported value"
        return ResolvedFact(fact_ref, field_name, accepted,
                            tuple(claim for claim in claims if claim is not accepted),
                            False, reason)

    sources = {claim.source_id for claim in pool}
    if len(sources) == 1:
        observed = {claim.observed_at for claim in pool}
        if len(observed) > 1:
            accepted = _latest(pool)
            return ResolvedFact(fact_ref, field_name, accepted,
                                tuple(claim for claim in claims if claim is not accepted),
                                False, "newer evidence from the same source")

    settled = [claim for claim in pool if claim.grounding == "settled"]
    if settled and len(_distinct_values(settled)) == 1:
        accepted = _latest(settled)
        return ResolvedFact(fact_ref, field_name, accepted,
                            tuple(claim for claim in claims if claim is not accepted),
                            False, "settled fact overrides estimate")

    if not explicit:
        estimates = [claim for claim in pool if claim.grounding == "estimate"]
        supported = [claim for claim in pool if claim.grounding != "estimate"]
        if estimates and supported and len(_distinct_values(supported)) == 1:
            accepted = _latest(supported)
            return ResolvedFact(fact_ref, field_name, accepted,
                                tuple(claim for claim in claims if claim is not accepted),
                                False, "supported fact overrides estimate")

    safer = safer_value(field_name, direction, pool_values)
    if safer is not None:
        matching = [claim for claim in pool if claim.value == safer]
        accepted = _latest(matching)
        return ResolvedFact(fact_ref, field_name, accepted,
                            tuple(claim for claim in claims if claim is not accepted),
                            False, "financially safer supported interpretation")

    return ResolvedFact(fact_ref, field_name, None, tuple(claims), True,
                        "conflicting values with no supported safer interpretation")


def resolve_claims(
    claims: Iterable[FactClaim],
    directions: dict[str, str] | None = None,
) -> tuple[ResolvedFact, ...]:
    directions = directions or {}
    groups: dict[tuple[str, str], list[FactClaim]] = defaultdict(list)
    for claim in claims:
        groups[(claim.fact_ref, claim.field_name)].append(claim)
    results = []
    for (fact_ref, field_name) in sorted(groups):
        group = sorted(groups[(fact_ref, field_name)], key=lambda claim: claim.claim_id)
        direction = directions.get(fact_ref)
        if direction is None:
            for claim in group:
                claim_direction = getattr(claim, "direction", None)
                if claim_direction is not None:
                    direction = claim_direction
                    break
        results.append(_resolve_group(tuple(group), direction))
    return tuple(results)


def accepted_value(resolved: ResolvedFact) -> Any | None:
    if resolved.unresolved or resolved.accepted is None:
        return None
    return resolved.accepted.value


def classify_link(
    event: FinancialEvent,
    linked: FinancialEvent,
    claims: Sequence[FactClaim] = (),
) -> LinkRelation:
    for claim in claims:
        if claim.fact_ref == event.event_id and claim.claim_kind == "amendment" \
                and claim.field_name == "replaces" and claim.value == linked.event_id:
            return LinkRelation.replacement_candidate
        if claim.fact_ref == event.event_id and claim.claim_kind == "cancellation":
            return LinkRelation.separate
    return LinkRelation.unknown


def superseded_event_ids(claims: Iterable[FactClaim]) -> frozenset[str]:
    superseded = set()
    for claim in claims:
        if claim.claim_kind == "amendment" and claim.field_name == "replaces":
            superseded.add(str(claim.value))
    return frozenset(superseded)


def apply_cancellations(
    events: Sequence[FinancialEvent],
    claims: Sequence[FactClaim],
) -> tuple[tuple[FinancialEvent, ...], tuple[str, ...]]:
    cancelled = set()
    unresolved: list[str] = []
    for resolved in resolve_claims(claims, {event.event_id: event.direction for event in events}):
        if resolved.field_name != "status":
            continue
        if resolved.unresolved:
            unresolved.append(f"{resolved.fact_ref}:{resolved.field_name}")
            continue
        if resolved.accepted is not None and resolved.accepted.value == "cancelled":
            cancelled.add(resolved.fact_ref)
    kept = tuple(event for event in events if event.event_id not in cancelled)
    return kept, tuple(unresolved)

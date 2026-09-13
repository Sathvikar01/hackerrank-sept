from __future__ import annotations

from typing import Sequence

from .schemas import (
    CONSEQUENTIAL_FIELDS,
    CONSEQUENTIAL_LIFECYCLES,
    ClaimComparison,
    ExtractedClaim,
    Extraction,
    IndependentReview,
)


def required_reviews(extractions: Sequence[Extraction]) -> tuple[tuple[str, str], ...]:
    refs: list[tuple[str, str]] = []
    for extraction in extractions:
        for claim in extraction.claims:
            required = _requires_independent_check(extraction, claim)
            if required:
                refs.append((extraction.source_kind, extraction.source_id))
                break
    return tuple(refs)


def _requires_independent_check(extraction: Extraction, claim: ExtractedClaim) -> bool:
    if extraction.source_kind == "image" and claim.field in {"amount", "currency"}:
        return True
    if extraction.source_kind == "message":
        return claim.field in CONSEQUENTIAL_FIELDS \
            or claim.lifecycle in CONSEQUENTIAL_LIFECYCLES
    return False


def compare_extractions(primary: Extraction, second: Extraction) -> IndependentReview:
    pairs: dict[tuple[str | None, str], dict[str, ExtractedClaim]] = {}
    for claim in primary.claims:
        pairs.setdefault((claim.event_ref, claim.field), {})["primary"] = claim
    for claim in second.claims:
        pairs.setdefault((claim.event_ref, claim.field), {})["second"] = claim
    comparisons = []
    for (event_ref, field) in sorted(pairs, key=lambda key: (str(key[0]), key[1])):
        pair = pairs[(event_ref, field)]
        first = pair.get("primary")
        checked = pair.get("second")
        if first is None or checked is None:
            agreement = "missing"
        elif first.value == checked.value:
            agreement = "agree"
        else:
            agreement = "disagree"
        comparisons.append(ClaimComparison(
            event_ref=event_ref,
            field=field,
            primary_value=first.value if first is not None else None,
            second_value=checked.value if checked is not None else None,
            agreement=agreement,
        ))
    return IndependentReview(
        source_kind=primary.source_kind,
        source_id=primary.source_id,
        model=second.model,
        comparisons=tuple(comparisons),
    )

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Mapping, Sequence

from finance.contracts import (
    ContractError,
    DIRECTIONS,
    FinancialEvent,
    Provenance,
    SUPPORTED_CURRENCIES,
)
from finance.overlay import OVERRIDABLE_FIELDS, apply_overrides
from finance.ingest import RequestScope

from .materiality import MaterialityPolicy, MaterialityResult
from .schemas import ExtractedClaim

ATTACHMENT_STATES = ("attached", "new_obligation", "ambiguous", "unresolved")
ATTACHMENT_FIELDS = frozenset({
    "amount", "currency", "event_date", "settlement_date", "status", "direction",
    "event_type", "linked_event_id", "category", "description",
})
_LIFECYCLE_RANK = {
    "cancel": 5,
    "amend": 4,
    "delay": 3,
    "new_obligation": 3,
    "confirm": 2,
    "inform": 1,
}
_EVENT_REF_RE = re.compile(r"event_\d+")


@dataclass(frozen=True)
class AttachmentPolicy:
    date_tolerance_days: int = 3
    max_candidates: int = 5


@dataclass(frozen=True)
class NewObligation:
    obligation_id: str
    user_id: str
    request_id: str | None
    amount: Decimal | None
    currency: str | None
    event_date: date | None
    settlement_date: date | None
    direction: str | None
    category: str | None
    description: str | None
    recurrence: str | None
    lifecycle: str
    provenance: tuple[Provenance, ...]

    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing = []
        if self.amount is None:
            missing.append("amount")
        if self.currency is None:
            missing.append("currency")
        if self.direction is None:
            missing.append("direction")
        if self.event_date is None and self.settlement_date is None:
            missing.append("date")
        return tuple(missing)

    @property
    def complete(self) -> bool:
        return not self.missing_fields and self.amount is not None \
            and self.amount > 0 and self.currency in SUPPORTED_CURRENCIES \
            and self.direction in DIRECTIONS


@dataclass(frozen=True)
class AttachmentOutcome:
    claim: ExtractedClaim
    state: str
    event_id: str | None
    candidates: tuple[str, ...]
    obligation: NewObligation | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state not in ATTACHMENT_STATES:
            raise ContractError(f"unsupported attachment state {self.state!r}")


@dataclass(frozen=True)
class AttachmentOption:
    kind: str
    event_id: str | None
    obligation: NewObligation | None
    label: str
    claims: tuple[ExtractedClaim, ...]


@dataclass(frozen=True)
class AttachmentAxis:
    source_kind: str
    source_id: str
    claims: tuple[ExtractedClaim, ...]
    options: tuple[AttachmentOption, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.options) > 1


def attach_claims(
    scope: RequestScope,
    claims: Sequence[ExtractedClaim],
    *,
    policy: AttachmentPolicy | None = None,
) -> tuple[AttachmentOutcome, ...]:
    policy = policy or AttachmentPolicy()
    groups: dict[tuple[str, str], list[ExtractedClaim]] = {}
    for claim in claims:
        groups.setdefault((claim.source_kind, claim.source_id), []).append(claim)
    outcomes: list[AttachmentOutcome] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda claim: claim.claim_id)
        outcomes.extend(_attach_group(scope, group, policy))
    return tuple(outcomes)


def _distinct_group_values(group, field: str) -> tuple[Any, ...]:
    seen: list[Any] = []
    for claim in group:
        if claim.field == field and claim.value not in seen:
            seen.append(claim.value)
    return tuple(seen)


def _conflicting_anchor_fields(group) -> tuple[str, ...]:
    """Fields for which the source itself carries more than one value.

    Conflicting values must stay ambiguous: the first matching claim must never
    silently decide the outcome.
    """
    conflicting = []
    for field in ("amount", "currency", "event_date", "settlement_date",
                  "direction"):
        if len(_distinct_group_values(group, field)) > 1:
            conflicting.append(field)
    return tuple(conflicting)


def _attach_group(
    scope: RequestScope,
    group: list[ExtractedClaim],
    policy: AttachmentPolicy,
) -> list[AttachmentOutcome]:
    lifecycle = _group_lifecycle(group)
    explicit = _explicit_event_ids(group, scope)
    conflicting = _conflicting_anchor_fields(group)
    if conflicting:
        return [_ambiguous(
            claim, (),
            f"conflicting values within the source for: {', '.join(conflicting)}")
            for claim in group]
    if explicit:
        if len(explicit) == 1:
            return [_attached(claim, explicit[0], "explicit event reference")
                    for claim in group]
        return [_ambiguous(claim, explicit[:policy.max_candidates],
                           "multiple explicit event references") for claim in group]

    amount_claim = next((claim for claim in group if claim.field == "amount"), None)
    if amount_claim is None:
        return [_unresolved(claim, "no amount or explicit event reference to anchor attachment")
                for claim in group]

    candidates, rejection, chronology = _strong_candidates(
        scope, group, lifecycle, policy)
    if len(candidates) > 1:
        return [_ambiguous(claim, candidates[:policy.max_candidates],
                           "multiple plausible existing events") for claim in group]
    if len(candidates) == 1:
        return [_attached(claim, candidates[0], "unique amount, currency, and temporal match")
                for claim in group]
    if chronology:
        if len(chronology) == 1:
            return [_attached(
                claim, chronology[0],
                "chronology: the message precedes the future event and matches it uniquely")
                for claim in group]
        return [_ambiguous(
            claim, chronology[:policy.max_candidates],
            "multiple plausible future events match the chronology") for claim in group]

    if lifecycle == "new_obligation":
        obligation = _build_obligation(group)
        if obligation.complete:
            return [_new_obligation(claim, obligation) for claim in group]
        missing = ", ".join(obligation.missing_fields)
        return [_unresolved(claim, f"new obligation is incomplete: {missing}")
                for claim in group]

    reason = rejection or "no existing event matches the evidence"
    return [_unresolved(claim, reason) for claim in group]


def _attached(claim: ExtractedClaim, event_id: str, *reasons: str) -> AttachmentOutcome:
    return AttachmentOutcome(
        claim=claim, state="attached", event_id=event_id, candidates=(event_id,),
        obligation=None, reasons=tuple(reasons))


def _ambiguous(claim: ExtractedClaim, candidates: Sequence[str],
               *reasons: str) -> AttachmentOutcome:
    return AttachmentOutcome(
        claim=claim, state="ambiguous", event_id=None, candidates=tuple(candidates),
        obligation=None, reasons=tuple(reasons))


def _unresolved(claim: ExtractedClaim, *reasons: str) -> AttachmentOutcome:
    return AttachmentOutcome(
        claim=claim, state="unresolved", event_id=None, candidates=(),
        obligation=None, reasons=tuple(reasons))


def _new_obligation(claim: ExtractedClaim,
                    obligation: NewObligation) -> AttachmentOutcome:
    return AttachmentOutcome(
        claim=claim, state="new_obligation", event_id=None, candidates=(),
        obligation=obligation, reasons=("evidence introduces a new obligation",))


def _strong_candidates(scope: RequestScope, group, lifecycle, policy):
    amount = next(claim.value for claim in group if claim.field == "amount")
    currency = next((claim.value for claim in group if claim.field == "currency"), None)
    date_claim = next(
        (claim for claim in group if claim.field in {"event_date", "settlement_date"}),
        None)
    category = next((claim.value for claim in group if claim.field == "category"), None)
    description = next(
        (claim.value for claim in group if claim.field == "description"), None)
    observed_at = min(claim.observed_at for claim in group)

    candidates: list[str] = []
    chronology: list[str] = []
    rejection: str | None = None
    for event in scope.events:
        if event.user_id != group[0].user_id or not event.is_cash:
            continue
        if event.amount is None:
            continue
        exact_amount = event.amount == amount
        if not _lifecycle_compatible(lifecycle, event):
            rejection = "matching events exist but the lifecycle is incompatible"
            continue
        if currency is not None and event.currency != currency:
            rejection = "amount matches an event but the currency is incompatible"
            continue
        if date_claim is not None:
            delta = abs((event.effective_date - date_claim.value).days)
            if delta > policy.date_tolerance_days:
                if exact_amount and lifecycle in {"amend", "cancel", "delay", "confirm"} \
                        and event.status in {"pending", "scheduled"} \
                        and observed_at <= event.effective_date:
                    chronology.append(event.event_id)
                else:
                    rejection = "amount and currency match but the dates are not compatible"
                continue
        if category is not None and not _category_compatible(category, event.category):
            rejection = "matching events exist but the category is incompatible"
            continue
        if lifecycle in {"amend", "cancel", "delay"}:
            anchored = exact_amount or date_claim is not None \
                or category is not None or description is not None
            if not anchored:
                rejection = (
                    "amount does not match any event and the evidence carries no "
                    "date, category, or description anchor")
                continue
        elif not exact_amount:
            continue
        candidates.append(event.event_id)
    return tuple(dict.fromkeys(candidates)), rejection, tuple(dict.fromkeys(chronology))


def _lifecycle_compatible(lifecycle: str, event: FinancialEvent) -> bool:
    if lifecycle == "cancel":
        return event.status in {"pending", "scheduled"}
    if lifecycle in {"amend", "delay", "confirm"}:
        return event.status in {"pending", "scheduled", "settled"}
    return event.status in {"pending", "scheduled", "settled"}


def _category_compatible(left: str, right: str) -> bool:
    def tokens(text: str) -> set[str]:
        normalized = re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).split()
        return {word[:-1] if word.endswith("s") and len(word) > 3 else word
                for word in normalized}

    left_tokens, right_tokens = tokens(left), tokens(right)
    return bool(left_tokens & right_tokens) or tokens(left) == tokens(right)


def _group_lifecycle(group: Sequence[ExtractedClaim]) -> str:
    return max(
        (claim.lifecycle for claim in group),
        key=lambda lifecycle: (_LIFECYCLE_RANK.get(lifecycle, 0), lifecycle),
    )


def _explicit_event_ids(group: Sequence[ExtractedClaim],
                        scope: RequestScope) -> tuple[str, ...]:
    known = {event.event_id for event in scope.events}
    refs: list[str] = []
    for claim in group:
        if claim.event_ref and claim.event_ref in known:
            refs.append(claim.event_ref)
        for found in _EVENT_REF_RE.findall(claim.evidence):
            if found in known:
                refs.append(found)
    return tuple(dict.fromkeys(refs))


def _build_obligation(group: Sequence[ExtractedClaim]) -> NewObligation:
    def value(field: str):
        distinct = _distinct_group_values(group, field)
        if len(distinct) > 1:
            # Conflicting values keep the obligation incomplete; the first
            # matching claim must not decide the outcome.
            return None
        return next((claim.value for claim in group if claim.field == field), None)

    claim = group[0]
    return NewObligation(
        obligation_id=f"obligation_{claim.source_kind}_{claim.source_id}",
        user_id=claim.user_id,
        request_id=claim.request_id,
        amount=value("amount"),
        currency=value("currency"),
        event_date=value("event_date"),
        settlement_date=value("settlement_date"),
        direction=value("direction"),
        category=value("category"),
        description=value("description"),
        recurrence=value("recurrence"),
        lifecycle=_group_lifecycle(group),
        provenance=tuple(claim.provenance for claim in group),
    )


def materialize_obligation(obligation: NewObligation) -> FinancialEvent:
    if not obligation.complete:
        raise ContractError(
            "cannot materialize an incomplete obligation: "
            + ", ".join(obligation.missing_fields))
    event_date = obligation.event_date or obligation.settlement_date
    settlement_date = obligation.settlement_date or obligation.event_date
    return FinancialEvent(
        event_id=_synthetic_event_id(obligation.obligation_id),
        user_id=obligation.user_id,
        event_type="expense" if obligation.direction == "debit" else "income",
        description=obligation.description
        or f"obligation from {obligation.obligation_id}",
        category=obligation.category or "other",
        direction=obligation.direction,
        amount=obligation.amount,
        currency=obligation.currency,
        event_date=event_date,
        settlement_date=settlement_date,
        status="scheduled",
        linked_event_id=None,
        flexibility="fixed",
        minimum_allowed_amount=None,
    )


def _synthetic_event_id(obligation_id: str) -> str:
    digest = hashlib.sha1(obligation_id.encode("utf-8")).hexdigest()
    return f"event_9{int(digest[:12], 16) % 10 ** 9:09d}"


def build_attachment_axes(
    scope: RequestScope,
    outcomes: Sequence[AttachmentOutcome],
) -> tuple[AttachmentAxis, ...]:
    groups: dict[tuple[str, str], list[AttachmentOutcome]] = {}
    for outcome in outcomes:
        groups.setdefault(
            (outcome.claim.source_kind, outcome.claim.source_id), []).append(outcome)
    axes: list[AttachmentAxis] = []
    for key in sorted(groups):
        group = groups[key]
        claims = tuple(item.claim for item in group)
        lifecycle = _group_lifecycle(claims)
        candidate_ids = list(dict.fromkeys([
            *(candidate for item in group for candidate in item.candidates),
            *(item.event_id for item in group if item.event_id is not None),
        ]))
        options: list[AttachmentOption] = [
            AttachmentOption("attached", event_id, None, f"attach:{event_id}", claims)
            for event_id in candidate_ids
        ]
        obligation = next(
            (item.obligation for item in group if item.obligation is not None), None)
        if obligation is None and lifecycle == "new_obligation":
            built = _build_obligation(claims)
            obligation = built if built.complete else None
        if lifecycle == "new_obligation" and obligation is not None and obligation.complete:
            options.append(AttachmentOption(
                "new_obligation", None, obligation,
                f"new:{obligation.obligation_id}", claims))
        if not options:
            options.append(AttachmentOption("unresolved", None, None, "unresolved", claims))
        elif len(options) > 1:
            options.append(AttachmentOption("unresolved", None, None, "unresolved", claims))
        axes.append(AttachmentAxis(
            source_kind=key[0], source_id=key[1], claims=claims,
            options=tuple(options)))
    return tuple(axes)


def apply_attachment_option(
    scope: RequestScope,
    axis: AttachmentAxis,
    option: AttachmentOption,
) -> RequestScope:
    if option.kind == "unresolved":
        return scope
    if option.kind == "attached":
        overrides = {
            (option.event_id, claim.field): claim.value
            for claim in option.claims
            if claim.field in OVERRIDABLE_FIELDS and option.event_id is not None
        }
        return apply_overrides(scope, overrides)
    if option.kind == "new_obligation":
        if option.obligation is None:
            raise ContractError("new_obligation option is missing its obligation")
        return apply_overrides(
            scope, {}, additions=(materialize_obligation(option.obligation),))
    raise ContractError(f"unsupported attachment option kind {option.kind!r}")


def evaluate_attachment_materiality(
    scope: RequestScope,
    engine,
    axes: Sequence[AttachmentAxis],
    *,
    policy: MaterialityPolicy | None = None,
) -> MaterialityResult:
    policy = policy or MaterialityPolicy()
    request_id = scope.request.request_id
    if not axes:
        row = engine.decide(request_id, scope=scope).to_row()
        return MaterialityResult(
            status="immaterial", combinations_examined=1,
            cap=policy.max_combinations, truncated=False, axes=(),
            baseline_row=row, variant_rows=(), differing_fields=(),
            unresolved_axes=())
    total = 1
    for axis in axes:
        total *= max(1, len(axis.options))
    if total > policy.max_combinations:
        return MaterialityResult(
            status="unknown", combinations_examined=0,
            cap=policy.max_combinations, truncated=True, axes=(),
            baseline_row={}, variant_rows=(), differing_fields=(),
            unresolved_axes=tuple(key for key in ()))
    rows = []
    for combination in product(*(axis.options for axis in axes)):
        amended = scope
        for axis, option in zip(axes, combination):
            amended = apply_attachment_option(amended, axis, option)
        rows.append(engine.decide(request_id, scope=amended).to_row())
    baseline = rows[0]
    differing = tuple(sorted({
        key for row in rows[1:] for key in row if row[key] != baseline[key]
    }))
    return MaterialityResult(
        status="material" if differing else "immaterial",
        combinations_examined=len(rows),
        cap=policy.max_combinations,
        truncated=False,
        axes=(),
        baseline_row=baseline,
        variant_rows=tuple(rows[1:]),
        differing_fields=differing,
        unresolved_axes=())

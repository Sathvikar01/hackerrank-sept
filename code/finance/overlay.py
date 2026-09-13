from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Mapping, Sequence

from .contracts import ContractError, FinancialEvent
from .ingest import RequestScope
OVERRIDABLE_FIELDS = frozenset({
    "amount", "currency", "event_date", "settlement_date", "status", "direction",
    "event_type", "category", "description", "flexibility", "minimum_allowed_amount",
    "linked_event_id",
})


def apply_overrides(
    scope: RequestScope,
    overrides: Mapping[tuple[str, str], object],
    *,
    additions: Sequence[FinancialEvent] = (),
) -> RequestScope:
    if not overrides and not additions:
        return scope
    known = {event.event_id for event in scope.events}
    replacements: dict[str, dict[str, object]] = {}
    for (event_id, field), value in overrides.items():
        if field not in OVERRIDABLE_FIELDS:
            raise ContractError(f"cannot override field {field!r}")
        if event_id not in known:
            raise ContractError(f"override targets unknown event {event_id}")
        replacements.setdefault(event_id, {})[field] = value
    events = tuple(
        _replace_event(event, replacements[event.event_id])
        if event.event_id in replacements else event
        for event in scope.events
    )
    if additions:
        added = {event.event_id for event in additions}
        if added & known:
            raise ContractError(
                f"additional events collide with existing ids: {sorted(added & known)}")
        events = tuple(sorted(
            (*events, *additions), key=lambda event: (event.effective_date, event.event_id)))
    return RequestScope(
        request=scope.request,
        profile=scope.profile,
        events=events,
        messages=scope.messages,
        images=scope.images,
        options=scope.options,
        rate_book=scope.rate_book,
        dataset_root=scope.dataset_root,
    )


def _replace_event(event: FinancialEvent, changes: Mapping[str, object]) -> FinancialEvent:
    data = {
        "event_id": event.event_id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "description": event.description,
        "category": event.category,
        "direction": event.direction,
        "amount": event.amount,
        "currency": event.currency,
        "event_date": event.event_date,
        "settlement_date": event.settlement_date,
        "status": event.status,
        "linked_event_id": event.linked_event_id,
        "flexibility": event.flexibility,
        "minimum_allowed_amount": event.minimum_allowed_amount,
    }
    data.update(changes)
    return FinancialEvent(**data)

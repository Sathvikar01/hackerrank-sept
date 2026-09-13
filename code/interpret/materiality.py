from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Mapping, Sequence

from finance.overlay import OVERRIDABLE_FIELDS, apply_overrides

from .schemas import InterpretationSet


@dataclass(frozen=True)
class MaterialityPolicy:
    max_combinations: int = 64


@dataclass(frozen=True)
class MaterialityResult:
    status: str
    combinations_examined: int
    cap: int
    truncated: bool
    axes: tuple[InterpretationSet, ...]
    baseline_row: Mapping[str, str]
    variant_rows: tuple[Mapping[str, str], ...]
    differing_fields: tuple[str, ...]
    unresolved_axes: tuple[str, ...]


def evaluate_materiality(
    scope,
    engine,
    sets: Sequence[InterpretationSet],
    *,
    policy: MaterialityPolicy | None = None,
) -> MaterialityResult:
    policy = policy or MaterialityPolicy()
    axes = tuple(
        item for item in sets
        if (item.unresolved or len(item.values) > 1)
        and item.field in OVERRIDABLE_FIELDS)
    unresolved_axes = tuple(
        f"{item.event_ref}:{item.field}"
        for item in axes
        if item.unresolved and not item.values
    )
    if unresolved_axes:
        return MaterialityResult(
            status="unknown", combinations_examined=0, cap=policy.max_combinations,
            truncated=True, axes=axes, baseline_row={}, variant_rows=(),
            differing_fields=(), unresolved_axes=unresolved_axes)

    total = 1
    for axis in axes:
        total *= max(1, len(axis.values))
    if total > policy.max_combinations:
        return MaterialityResult(
            status="unknown", combinations_examined=0, cap=policy.max_combinations,
            truncated=True, axes=axes, baseline_row={}, variant_rows=(),
            differing_fields=(), unresolved_axes=())

    accepted_overrides = {
        (item.event_ref, item.field): item.accepted
        for item in sets
        if item.accepted is not None and item.event_ref is not None
        and item.field in OVERRIDABLE_FIELDS
    }
    value_axes = tuple(sorted(axis.values, key=repr) for axis in axes)
    combinations = list(product(*value_axes)) if value_axes else [()]
    rows: list[Mapping[str, str]] = []
    for choices in combinations:
        overrides = dict(accepted_overrides)
        for axis, value in zip(axes, choices):
            overrides[(axis.event_ref, axis.field)] = value
        amended = apply_overrides(scope, overrides)
        decision = engine.decide(scope.request.request_id, scope=amended)
        rows.append(decision.to_row())
    baseline = rows[0]
    differing = tuple(sorted({
        key for row in rows[1:] for key in row if row[key] != baseline[key]
    }))
    return MaterialityResult(
        status="material" if differing else "immaterial",
        combinations_examined=len(rows),
        cap=policy.max_combinations,
        truncated=False,
        axes=axes,
        baseline_row=baseline,
        variant_rows=tuple(rows[1:]),
        differing_fields=differing,
        unresolved_axes=(),
    )

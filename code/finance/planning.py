from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations, product
from typing import Sequence

from .contracts import (
    ChangeAction,
    ContractError,
    PaymentOption,
    PlanEntry,
)
from .forecast import (
    ForecastPolicy,
    ForecastResult,
    VariableSpendingModel,
    detect_recurrence,
    project,
)
from .ingest import RequestScope


@dataclass(frozen=True)
class Capacity:
    amount_safe_to_pay: Decimal
    earliest_full_payment_date: date | None
    baseline: ForecastResult


@dataclass(frozen=True)
class PlanCandidate:
    method: str
    status: str
    entries: tuple[PlanEntry, ...]
    changes: tuple[ChangeAction, ...]
    option_id: str | None
    safe: bool
    rejected: tuple[str, ...]
    forecast: ForecastResult | None
    completes_by_deadline: bool

    @property
    def total_paid(self) -> Decimal:
        return sum((entry.amount for entry in self.entries), Decimal(0))

    @property
    def start_date(self) -> date | None:
        return self.entries[0].payment_date if self.entries else None

    @property
    def eligible(self) -> bool:
        return self.safe and self.completes_by_deadline and not self.rejected


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[PlanCandidate, ...]
    truncated: bool

    def eligible(self) -> tuple[PlanCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.eligible)


def compute_capacity(
    scope: RequestScope,
    policy: ForecastPolicy,
    *,
    variable_model: VariableSpendingModel | None = None,
) -> Capacity:
    start = scope.request.request_date
    requested = scope.request.requested_amount
    baseline = project(scope, policy, variable_model=variable_model)
    room = baseline.minimum - scope.profile.minimum_balance_to_keep
    if room < 0:
        room = Decimal(0)
    safe = min(room, requested)
    earliest: date | None = None
    day = start
    end = policy.end_date(start)
    while day <= end:
        result = project(
            scope, policy, plan=(PlanEntry(day, requested),), variable_model=variable_model)
        if result.safe:
            earliest = day
            break
        day += timedelta(days=1)
    return Capacity(safe, earliest, baseline)


def candidate_change_actions(
    scope: RequestScope,
    policy: ForecastPolicy,
) -> tuple[ChangeAction, ...]:
    profile = scope.profile
    representative: dict[str, tuple[str, str, str]] = {
        item.event_ids[-1]: item.key
        for item in detect_recurrence(scope, policy, as_of=scope.request.request_date)
    }
    actions: list[ChangeAction] = []
    for event in sorted(scope.events, key=lambda item: item.event_id):
        if event.event_id not in representative:
            continue
        if not event.is_cash or event.direction != "debit":
            continue
        if event.flexibility not in {"stoppable", "reducible", "reducible_or_stoppable"}:
            continue
        if event.category in profile.protected_categories:
            continue
        if event.flexibility in {"stoppable", "reducible_or_stoppable"} \
                and event.category in profile.stop_categories:
            actions.append(ChangeAction.stop(event.event_id))
        if event.flexibility in {"reducible", "reducible_or_stoppable"} \
                and event.category in profile.reduce_categories:
            floor = event.minimum_allowed_amount
            if floor is not None and event.amount is not None and floor < event.amount:
                actions.append(ChangeAction.reduce_to(event.event_id, floor))
    return tuple(sorted(actions, key=lambda action: (action.event_id, action.kind)))


def change_combinations(
    scope: RequestScope,
    policy: ForecastPolicy,
) -> tuple[tuple[tuple[ChangeAction, ...], ...], bool]:
    actions = candidate_change_actions(scope, policy)
    options: dict[str, list[ChangeAction]] = {}
    for action in actions:
        options.setdefault(action.event_id, []).append(action)
    event_ids = sorted(options)
    combos: list[tuple[ChangeAction, ...]] = [()]
    truncated = False
    for size in (1, 2, 3):
        for chosen in combinations(event_ids, size):
            for picked in product(*(options[event_id] for event_id in chosen)):
                if len(combos) >= policy.max_change_combinations:
                    return tuple(combos), True
                combos.append(tuple(picked))
    return tuple(combos), truncated


def installment_entries(option: PaymentOption, policy: ForecastPolicy) -> tuple[PlanEntry, ...]:
    if option.number_of_payments == 1:
        return (PlanEntry(option.first_payment_date, option.payment_amount),)
    if option.payment_frequency_days is None:
        raise ContractError(
            f"{option.payment_option_id}: installments need payment_frequency_days")
    return tuple(
        PlanEntry(
            option.first_payment_date + timedelta(days=index * option.payment_frequency_days),
            option.payment_amount,
        )
        for index in range(option.number_of_payments)
    )


def installment_months(entries: Sequence[PlanEntry], policy: ForecastPolicy) -> int:
    if not entries:
        return 0
    first, last = entries[0].payment_date, entries[-1].payment_date
    span = (last - first).days
    if policy.installment_month_semantics == "days_30":
        return 0 if span == 0 else -(-span // policy.installment_month_days)
    return (last.year - first.year) * 12 + (last.month - first.month) + 1


def _full_candidate(
    scope: RequestScope,
    policy: ForecastPolicy,
    changes: tuple[ChangeAction, ...],
    variable_model: VariableSpendingModel | None,
) -> PlanCandidate:
    request = scope.request
    entries = (PlanEntry(request.request_date, request.requested_amount),)
    reasons: list[str] = []
    if "full_payment" not in scope.profile.payment_methods:
        reasons.append("user does not consider full_payment")
    forecast: ForecastResult | None = None
    safe = False
    if not reasons:
        forecast = project(
            scope, policy, plan=entries, changes=changes, variable_model=variable_model)
        safe = forecast.safe
        if not safe:
            reasons.append("full payment would fall below the minimum balance")
    completes = entries[-1].payment_date <= request.desired_completion_date
    if not completes:
        reasons.append("full payment completes after desired_completion_date")
    status = "affordable_now" if safe and not changes else "affordable_with_plan"
    return PlanCandidate("full_payment", status, entries, changes, None, safe,
                         tuple(reasons), forecast, completes)


def _partial_candidate(
    scope: RequestScope,
    policy: ForecastPolicy,
    capacity: Capacity,
    changes: tuple[ChangeAction, ...],
    variable_model: VariableSpendingModel | None,
) -> PlanCandidate:
    request = scope.request
    reasons: list[str] = []
    if "partial_payment" not in scope.profile.payment_methods:
        reasons.append("user does not consider partial_payment")
    if not request.allows_partial_payment:
        reasons.append("request does not allow partial payment")
    first_amount = capacity.amount_safe_to_pay
    if not (Decimal(0) < first_amount < request.requested_amount):
        reasons.append("amount_safe_to_pay is not strictly between zero and requested_amount")
    earliest = capacity.earliest_full_payment_date
    if earliest is None:
        reasons.append("no safe full-payment date within the forecast")
    elif earliest > request.desired_completion_date:
        reasons.append("second payment falls after desired_completion_date")
    completes = earliest is not None and earliest <= request.desired_completion_date
    if reasons or earliest is None:
        return PlanCandidate("partial_payment", "affordable_with_plan", (), changes, None,
                             False, tuple(reasons), None, completes)
    entries = (
        PlanEntry(request.request_date, first_amount),
        PlanEntry(earliest, request.requested_amount - first_amount),
    )
    forecast = project(
        scope, policy, plan=entries, changes=changes, variable_model=variable_model)
    safe = forecast.safe
    if not safe:
        reasons.append("projected balance falls below the minimum during the partial plan")
    return PlanCandidate("partial_payment", "affordable_with_plan", entries, changes, None,
                         safe, tuple(reasons), forecast, completes)


def _installment_candidates(
    scope: RequestScope,
    policy: ForecastPolicy,
    changes: tuple[ChangeAction, ...],
    variable_model: VariableSpendingModel | None,
) -> tuple[PlanCandidate, ...]:
    request = scope.request
    profile = scope.profile
    candidates: list[PlanCandidate] = []
    for option in scope.options:
        if option.payment_method != "installments":
            continue
        reasons: list[str] = []
        if "installments" not in profile.payment_methods:
            reasons.append("user does not consider installments")
        entries = installment_entries(option, policy)
        months = installment_months(entries, policy)
        if profile.max_installment_months is None:
            reasons.append("max_installment_months is blank")
        elif months > profile.max_installment_months:
            reasons.append(
                f"plan spans {months} months, beyond max_installment_months="
                f"{profile.max_installment_months}")
        if entries[0].payment_date < request.request_date:
            reasons.append("first payment falls before request_date")
        completes = entries[-1].payment_date <= request.desired_completion_date
        if not completes:
            reasons.append("installment plan completes after desired_completion_date")
        forecast: ForecastResult | None = None
        safe = False
        if not reasons:
            forecast = project(
                scope, policy, plan=entries, changes=changes, variable_model=variable_model)
            safe = forecast.safe
            if not safe:
                reasons.append("projected balance falls below the minimum during the plan")
        candidates.append(PlanCandidate(
            "installments", "affordable_with_plan", entries, changes,
            option.payment_option_id, safe, tuple(reasons), forecast, completes))
    return tuple(candidates)


def _wait_candidate(
    scope: RequestScope,
    policy: ForecastPolicy,
    capacity: Capacity,
    variable_model: VariableSpendingModel | None,
) -> PlanCandidate | None:
    request = scope.request
    reasons: list[str] = []
    earliest = capacity.earliest_full_payment_date
    if "full_payment" not in scope.profile.payment_methods:
        reasons.append("user does not consider full_payment")
    if earliest is None:
        reasons.append("full payment never becomes safe within the forecast")
    elif earliest <= request.request_date:
        return None
    elif earliest > request.desired_completion_date:
        reasons.append("full payment becomes safe after desired_completion_date")
    completes = earliest is not None and earliest <= request.desired_completion_date
    if reasons or earliest is None:
        return PlanCandidate("wait", "affordable_later", (), (), None, False,
                             tuple(reasons), None, completes)
    entries = (PlanEntry(earliest, request.requested_amount),)
    forecast = project(scope, policy, plan=entries, variable_model=variable_model)
    safe = forecast.safe
    if not safe:
        reasons.append("projected balance falls below the minimum before full payment")
    return PlanCandidate("wait", "affordable_later", entries, (), None, safe,
                         tuple(reasons), forecast, completes)


def enumerate_candidates(
    scope: RequestScope,
    policy: ForecastPolicy,
    capacity: Capacity,
    *,
    variable_model: VariableSpendingModel | None = None,
) -> CandidateSet:
    combos, truncated = change_combinations(scope, policy)
    candidates: list[PlanCandidate] = []
    for changes in combos:
        candidates.append(_full_candidate(scope, policy, changes, variable_model))
        candidates.append(_partial_candidate(scope, policy, capacity, changes, variable_model))
        candidates.extend(_installment_candidates(scope, policy, changes, variable_model))
        if not changes:
            wait = _wait_candidate(scope, policy, capacity, variable_model)
            if wait is not None:
                candidates.append(wait)
    return CandidateSet(tuple(candidates), truncated)

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Mapping, Protocol, Sequence

from .contracts import (
    BalancePoint,
    ChangeAction,
    ContractError,
    FinancialEvent,
    ForecastResult,
    MissingAmountError,
    PlanEntry,
)
from .ingest import RequestScope

ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
}

SAME_DAY_ORDERS = frozenset({"outflows_first", "inflows_first"})
INSTALLMENT_MONTH_SEMANTICS = frozenset({"days_30", "calendar_months"})


@dataclass(frozen=True)
class ForecastPolicy:
    horizon_days: int = 90
    include_horizon_end: bool = True
    recurrence_min_occurrences: int = 3
    recurrence_lookback_days: int = 183
    recurrence_match_days: int = 3
    recurrence_tolerance: Decimal = Decimal("0.25")
    same_day_order: str = "outflows_first"
    installment_month_semantics: str = "days_30"
    installment_month_days: int = 30
    rounding: str = "ROUND_HALF_UP"
    output_places: int = 2
    allow_inverse_rates: bool = False
    variable_spending_enabled: bool = True
    variable_spending_lookback_days: int = 90
    variable_spending_buffer: Decimal = Decimal("0.10")
    max_change_combinations: int = 200

    def __post_init__(self) -> None:
        if self.horizon_days < 1:
            raise ContractError("horizon_days must be >= 1")
        if self.same_day_order not in SAME_DAY_ORDERS:
            raise ContractError(f"unsupported same_day_order {self.same_day_order!r}")
        if self.installment_month_semantics not in INSTALLMENT_MONTH_SEMANTICS:
            raise ContractError(
                f"unsupported installment_month_semantics {self.installment_month_semantics!r}")
        if self.rounding not in ROUNDING_MODES:
            raise ContractError(f"unsupported rounding mode {self.rounding!r}")
        if self.recurrence_min_occurrences < 1:
            raise ContractError("recurrence_min_occurrences must be >= 1")
        if self.max_change_combinations < 1:
            raise ContractError("max_change_combinations must be >= 1")

    def end_date(self, start: date) -> date:
        span = self.horizon_days if self.include_horizon_end else self.horizon_days - 1
        return start + timedelta(days=span)

    def quantize(self, value: Decimal) -> Decimal:
        places = Decimal(1).scaleb(-self.output_places)
        return value.quantize(places, rounding=ROUNDING_MODES[self.rounding])


def series_key(event: FinancialEvent) -> tuple[str, str, str]:
    return (event.category, (event.description or "").strip().lower(), event.currency)


@dataclass(frozen=True)
class CashFlow:
    day: date
    amount: Decimal
    label: str
    event_id: str | None = None
    series_key: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class RecurrenceSeries:
    key: tuple[str, str, str]
    event_ids: tuple[str, ...]
    interval_days: int
    typical_amount: Decimal
    last_occurrence: date
    projected_dates: tuple[date, ...]
    direction: str = "debit"


def _same_series(flow_key: tuple[str, str, str] | None, item: RecurrenceSeries) -> bool:
    if flow_key is None:
        return False
    if item.direction == "credit":
        return flow_key[0] == item.key[0] and flow_key[2] == item.key[2]
    return flow_key == item.key


def _occurrence_is_covered(
    flow: CashFlow,
    item: RecurrenceSeries,
    day: date,
    policy: ForecastPolicy,
) -> bool:
    if abs((flow.day - day).days) > policy.recurrence_match_days:
        return False
    if _same_series(flow.series_key, item):
        return True
    # Income confirmed by a message can be materialized as an explicit event
    # whose category does not carry the recurring series label. That explicit
    # credit already represents the occurrence; projecting the series on top
    # of it would overstate available cash.
    return (
        item.direction == "credit"
        and flow.amount > 0
        and flow.event_id is not None
        and flow.series_key is not None
        and flow.series_key[2] == item.key[2]
    )


class VariableSpendingModel(Protocol):
    def monthly_reserve(
        self,
        scope: RequestScope,
        policy: ForecastPolicy,
        covered_series: frozenset[tuple[str, str, str]],
    ) -> Mapping[str, Decimal]:
        ...


class RecentMaxVariableSpending:
    def monthly_reserve(
        self,
        scope: RequestScope,
        policy: ForecastPolicy,
        covered_series: frozenset[tuple[str, str, str]],
    ) -> Mapping[str, Decimal]:
        start = scope.request.request_date
        cutoff = start - timedelta(days=policy.variable_spending_lookback_days)
        totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal(0))
        for event in scope.events:
            if event.status != "settled" or not event.is_cash or event.direction != "debit":
                continue
            if event.amount is None:
                continue
            if event.event_date < cutoff or event.event_date > start:
                continue
            if series_key(event) in covered_series:
                continue
            day = event.event_date
            converted = scope.rate_book.convert(
                event.amount, event.currency, scope.profile.home_currency, day,
                allow_inverse=policy.allow_inverse_rates)
            totals[(event.category, f"{day.year}-{day.month:02d}")] += converted
        by_category: dict[str, Decimal] = {}
        for (category, _month), total in totals.items():
            if total > by_category.get(category, Decimal(0)):
                by_category[category] = total
        reserves: dict[str, Decimal] = {}
        for category, monthly in sorted(by_category.items()):
            buffered = monthly * (Decimal(1) + policy.variable_spending_buffer)
            reserves[category] = buffered.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        return reserves


def detect_recurrence(
    scope: RequestScope,
    policy: ForecastPolicy,
    *,
    as_of: date | None = None,
) -> tuple[RecurrenceSeries, ...]:
    start = scope.request.request_date
    as_of = as_of or start
    cutoff = as_of - timedelta(days=policy.recurrence_lookback_days)
    groups: dict[tuple[str, str, str], list[FinancialEvent]] = defaultdict(list)
    for event in scope.events:
        if event.status != "settled" or not event.is_cash:
            continue
        if event.amount is None:
            continue
        if event.event_date < cutoff or event.event_date > as_of:
            continue
        if event.direction == "debit":
            key = series_key(event)
        elif event.direction == "credit" and event.event_type == "income":
            key = (event.category, "*", event.currency)
        else:
            continue
        groups[key].append(event)

    end = policy.end_date(start)
    series: list[RecurrenceSeries] = []
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda event: (event.effective_date, event.event_id))
        dates = [event.effective_date for event in ordered]
        if len(dates) < policy.recurrence_min_occurrences:
            continue
        intervals = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
        if not intervals:
            continue
        median = sorted(intervals)[len(intervals) // 2]
        if median < 7:
            continue
        tolerance = Decimal(median) * policy.recurrence_tolerance
        if any(abs(Decimal(interval - median)) > tolerance for interval in intervals):
            continue
        direction = ordered[0].direction
        if direction == "credit":
            typical = min(event.amount for event in ordered if event.amount is not None)
        else:
            typical = max(event.amount for event in ordered if event.amount is not None)
        last = dates[-1]
        projected: list[date] = []
        cursor = last + timedelta(days=median)
        while cursor <= end:
            if cursor > as_of:
                projected.append(cursor)
            cursor += timedelta(days=median)
        if not projected:
            continue
        series.append(RecurrenceSeries(
            key=key,
            event_ids=tuple(event.event_id for event in ordered),
            interval_days=median,
            typical_amount=typical,
            last_occurrence=last,
            projected_dates=tuple(projected),
            direction=direction,
        ))
    return tuple(series)


def collect_flows(
    scope: RequestScope,
    policy: ForecastPolicy,
    *,
    changes: Sequence[ChangeAction] = (),
    variable_model: VariableSpendingModel | None = None,
) -> tuple[CashFlow, ...]:
    start = scope.request.request_date
    end = policy.end_date(start)
    change_targets: dict[tuple[str, str, str], ChangeAction] = {}
    for change in sorted(changes, key=lambda item: item.event_id):
        target = scope.event_by_id(change.event_id)
        if target is None:
            raise ContractError(f"spending change targets unknown event {change.event_id}")
        change_targets.setdefault(series_key(target), change)

    flows: list[CashFlow] = []
    covered: set[tuple[str, str, str]] = set()

    def apply_change(key: tuple[str, str, str], amount: Decimal) -> Decimal | None:
        change = change_targets.get(key)
        if change is None:
            return amount
        if change.kind == "stop":
            return None
        return change.new_amount

    for event in scope.events:
        if not event.is_cash:
            continue
        if event.status in {"failed", "cancelled", "unrealized"}:
            continue
        if event.status == "settled":
            if event.effective_date <= start:
                continue
            day = event.effective_date
        elif event.status == "pending":
            if event.direction == "credit":
                continue
            day = event.event_date
        elif event.status == "scheduled":
            day = event.effective_date
        else:
            continue
        if day < start or day > end:
            continue
        if event.amount is None:
            raise MissingAmountError(
                f"{event.event_id}: cash event has no amount; a missing amount is not zero")
        key = series_key(event)
        amount = apply_change(key, event.amount)
        covered.add(key)
        if amount is None:
            continue
        converted = scope.rate_book.convert(
            amount, event.currency, scope.profile.home_currency, day,
            allow_inverse=policy.allow_inverse_rates)
        signed = -converted if event.direction == "debit" else converted
        flows.append(CashFlow(day, signed, f"event:{event.event_id}", event.event_id, key))

    for item in detect_recurrence(scope, policy, as_of=start):
        change = change_targets.get(item.key)
        if change is not None and change.kind == "stop":
            covered.add(item.key)
            continue
        base = change.new_amount if change is not None else item.typical_amount
        if base is None:
            continue
        covered.add(item.key)
        currency = item.key[2]
        sign = -1 if item.direction == "debit" else 1
        for day in item.projected_dates:
            if any(
                _occurrence_is_covered(flow, item, day, policy)
                for flow in flows
            ):
                continue
            converted = scope.rate_book.convert(
                base, currency, scope.profile.home_currency, day,
                allow_inverse=policy.allow_inverse_rates)
            flows.append(CashFlow(
                day, sign * converted, f"recurrence:{item.key[0]}", None, item.key))

    if policy.variable_spending_enabled:
        model = variable_model or RecentMaxVariableSpending()
        reserves = model.monthly_reserve(scope, policy, frozenset(covered))
        if reserves:
            month_days = policy.installment_month_days
            horizon = policy.horizon_days
            occurrences = max(1, -(-horizon // month_days))
            for index in range(occurrences):
                day = start + timedelta(days=index * month_days)
                if day > end:
                    break
                for category, amount in sorted(reserves.items()):
                    flows.append(CashFlow(
                        day, -amount, f"variable:{category}", None,
                        (category, "*", scope.profile.home_currency)))

    return tuple(flows)


def project(
    scope: RequestScope,
    policy: ForecastPolicy,
    *,
    plan: Sequence[PlanEntry] = (),
    changes: Sequence[ChangeAction] = (),
    variable_model: VariableSpendingModel | None = None,
) -> ForecastResult:
    start = scope.request.request_date
    end = policy.end_date(start)
    flows = list(collect_flows(scope, policy, changes=changes, variable_model=variable_model))
    for entry in plan:
        if start <= entry.payment_date <= end:
            flows.append(CashFlow(entry.payment_date, -entry.amount, "plan", None, None))

    def order(flow: CashFlow) -> int:
        debit_first = 0 if flow.amount < 0 else 1
        return 1 - debit_first if policy.same_day_order == "inflows_first" else debit_first

    ordered = sorted(
        flows,
        key=lambda flow: (flow.day, order(flow), flow.label, flow.event_id or "", flow.amount),
    )

    balance = scope.profile.current_available_balance
    start_balance = balance
    minimum = balance
    minimum_day = start
    points: list[BalancePoint] = []
    days = sorted({flow.day for flow in ordered})
    by_day: dict[date, list[CashFlow]] = defaultdict(list)
    for flow in ordered:
        by_day[flow.day].append(flow)
    for day in days:
        for flow in by_day[day]:
            balance += flow.amount
            if balance < minimum:
                minimum = balance
                minimum_day = day
        points.append(BalancePoint(day, balance))
    if not points or points[-1].day != end:
        points.append(BalancePoint(end, balance))

    required = scope.profile.minimum_balance_to_keep
    return ForecastResult(
        start=start,
        end=end,
        start_balance=start_balance,
        minimum_required=required,
        points=tuple(points),
        minimum=minimum,
        minimum_date=minimum_day,
        end_balance=balance,
        safe=minimum >= required,
    )

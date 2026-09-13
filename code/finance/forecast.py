from __future__ import annotations

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Protocol, Sequence

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
ONE_TIME_PATTERN = re.compile(
    r"arrear|one.time|bonus|commission|prize|lottery|refund|unrealized|internal transfer")
SPECULATIVE_SALARY_PATTERN = re.compile(
    r"unapproved|unconfirmed|tentative|propos|not confirmed|not approved|estimate")


@dataclass(frozen=True)
class ForecastPolicy:
    horizon_days: int = 90
    include_horizon_end: bool = True
    recurrence_min_occurrences: int = 3
    recurrence_lookback_days: int = 183
    recurrence_match_days: int = 3
    same_day_order: str = "outflows_first"
    installment_month_semantics: str = "days_30"
    installment_month_days: int = 30
    rounding: str = "ROUND_HALF_UP"
    output_places: int = 2
    allow_inverse_rates: bool = False
    variable_spending_enabled: bool = True
    variable_spending_lookback_days: int = 90
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


def _one_time_event(event: FinancialEvent) -> bool:
    return bool(ONE_TIME_PATTERN.search(f"{event.description or ''} {event.category}".lower()))


def _confirmed_salary(event: FinancialEvent) -> bool:
    if event.category.lower() != "salary" or event.direction != "credit":
        return False
    if _one_time_event(event):
        return False
    return not SPECULATIVE_SALARY_PATTERN.search((event.description or "").lower())


def _essential_event(event: FinancialEvent, profile) -> bool:
    category = event.category.lower()
    if category in {item.lower() for item in profile.protected_categories}:
        return True
    if event.flexibility == "fixed":
        return True
    return bool(re.search(
        r"grocer|food|transport|rent|utilit|medical|health|childcare|school|insurance|loan", category))


def _reconcile_events(events: Sequence[FinancialEvent]) -> tuple[FinancialEvent, ...]:
    by_id = {event.event_id: event for event in events}
    suppressed: set[str] = set()
    for event in events:
        linked = by_id.get(event.linked_event_id) if event.linked_event_id else None
        if linked is None:
            continue
        description = (event.description or "").lower()
        combined = f"{description} {(linked.description or '').lower()}"
        if ("internal transfer" in combined and re.search(r"same.holder", combined)
                and {event.direction, linked.direction} == {"credit", "debit"}
                and all(getattr(event, key) == getattr(linked, key)
                        for key in ("user_id", "amount", "currency", "settlement_date"))
                and all(item.status in {"settled", "scheduled"} for item in (event, linked))):
            suppressed.update((event.event_id, linked.event_id))
        elif "duplicate" in description and all(
                getattr(event, key) == getattr(linked, key)
                for key in ("amount", "currency", "direction")):
            if event.status == "settled" and linked.status == "pending":
                suppressed.add(linked.event_id)
            else:
                suppressed.add(event.event_id)
        elif event.status in {"settled", "cancelled"} and re.search(
                r"replace|cancel|settlement|authorization", description):
            if linked.status in {"pending", "scheduled"}:
                suppressed.add(linked.event_id)
    return tuple(event for event in events if event.event_id not in suppressed)


def _cadence(entries: Sequence[FinancialEvent]) -> int | None:
    dates = sorted({event.effective_date for event in entries})
    if len(dates) < 2:
        return None
    gaps = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
    if not gaps:
        return None
    cadence = sorted(gaps)[len(gaps) // 2]
    if not 7 <= cadence <= 45:
        return None
    tolerance = max(3, cadence // 4)
    if any(abs(gap - cadence) > tolerance for gap in gaps):
        return None
    return cadence


def _projected_dates(entries: Sequence[FinancialEvent], cadence: int, start: date, end: date) -> list[date]:
    dates = [event.effective_date for event in entries]
    last = max(dates)
    month_ends = all(day.day == calendar.monthrange(day.year, day.month)[1] for day in dates)
    monthly = 28 <= cadence <= 31 and (len({day.day for day in dates}) == 1 or month_ends)
    cursor = last
    projected: list[date] = []
    while cursor <= end:
        if monthly:
            month_index = cursor.year * 12 + cursor.month
            year, month = divmod(month_index, 12)
            month += 1
            anchor = 31 if month_ends else last.day
            cursor = date(year, month, min(anchor, calendar.monthrange(year, month)[1]))
        else:
            cursor += timedelta(days=cadence)
        if start <= cursor <= end:
            projected.append(cursor)
    return projected


def _expected_before_start(
    entries: Sequence[FinancialEvent], cadence: int, request_date: date
) -> list[date]:
    """Occurrences the series cadence places strictly before request_date,
    after the last settled occurrence."""
    earliest = min(event.effective_date for event in entries)
    return _projected_dates(
        entries, cadence, earliest, request_date - timedelta(days=1))


def _missed_expected_credits(
    scope: RequestScope, expected: Sequence[date], key: tuple[str, str, str], tolerance: int
) -> int:
    actual = [
        event.effective_date for event in _reconcile_events(scope.events)
        if event.is_cash and event.direction == "credit"
        and event.status in {"settled", "pending", "scheduled"}
        and event.category == key[0] and event.currency == key[2]
        and event.effective_date is not None
    ]
    return sum(
        1 for day in expected
        if not any(abs((existing - day).days) <= tolerance for existing in actual))


class VariableSpendingModel(Protocol):
    def reserve_flows(
        self,
        scope: RequestScope,
        policy: ForecastPolicy,
    ) -> Sequence[tuple[date, Decimal, str]]:
        ...


class EssentialVariableReserve:
    def reserve_flows(
        self,
        scope: RequestScope,
        policy: ForecastPolicy,
    ) -> Sequence[tuple[date, Decimal, str]]:
        start = scope.request.request_date
        cutoff = start - timedelta(days=policy.recurrence_lookback_days)
        end = policy.end_date(start)
        series_events: dict[tuple[str, str, str], list[FinancialEvent]] = defaultdict(list)
        concrete: dict[tuple[str, str], list[tuple[date, Decimal]]] = defaultdict(list)
        for event in _reconcile_events(scope.events):
            if not event.is_cash or event.status in {"failed", "cancelled", "unrealized"}:
                continue
            if event.status not in {"settled", "pending", "scheduled"}:
                continue
            if event.direction == "credit":
                continue
            if event.amount is None:
                continue
            day = event.effective_date
            if day > end:
                continue
            key = series_key(event)
            group = (event.category, event.currency)
            if day < start:
                if event.status in {"pending", "scheduled"}:
                    day = start
                elif event.status == "settled" and not _one_time_event(event) and day >= cutoff:
                    series_events[key].append(event)
                    continue
                else:
                    continue
            if not (event.status == "settled" and day == start):
                concrete[group].append((day, event.amount))

        uncovered: list[FinancialEvent] = []
        for key, entries in series_events.items():
            distinct = {event.effective_date for event in entries}
            if len(distinct) >= policy.recurrence_min_occurrences and _cadence(entries) is not None:
                continue
            uncovered.extend(entries)

        buckets: dict[tuple[str, str], dict[int, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal(0)))
        for event in uncovered:
            if not _essential_event(event, scope.profile):
                continue
            age = (start - event.effective_date).days
            if 1 <= age <= policy.variable_spending_lookback_days and event.amount is not None:
                buckets[(event.category, event.currency)][(age - 1) // 30] += event.amount

        reserves: dict[tuple[date, str], Decimal] = defaultdict(lambda: Decimal(0))
        for group, ages in sorted(buckets.items()):
            if not ages:
                continue
            reserve = max(ages.values())
            for offset in (0, 30, 60):
                day = start + timedelta(days=offset)
                known = sum((amount for existing, amount in concrete.get(group, ())
                             if day <= existing < day + timedelta(days=30)), Decimal(0))
                amount = max(Decimal(0), reserve - known)
                if amount > 0:
                    reserves[(day, group[1])] += amount
        return [(day, amount, currency) for (day, currency), amount in sorted(reserves.items())]


def _credit_series_cancelled(scope: RequestScope, key: tuple[str, str, str],
                            last_settled: date) -> bool:
    """An explicitly cancelled credit occurrence at or after the last settled
    occurrence ends the income projection: the series must not be recreated
    as fresh forecast income."""
    for event in _reconcile_events(scope.events):
        if not event.is_cash or event.direction != "credit":
            continue
        if event.status != "cancelled":
            continue
        if event.category != key[0] or event.currency != key[2]:
            continue
        if event.effective_date >= last_settled:
            return True
    return False


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
    for event in _reconcile_events(scope.events):
        if event.status != "settled" or not event.is_cash:
            continue
        if event.amount is None:
            continue
        if event.effective_date < cutoff or event.effective_date > as_of:
            continue
        if event.direction == "debit":
            if _one_time_event(event):
                continue
            key = series_key(event)
        elif event.direction == "credit" and event.event_type == "income":
            if _one_time_event(event):
                continue
            key = (event.category, "*", event.currency)
        else:
            continue
        groups[key].append(event)

    end = policy.end_date(start)
    series: list[RecurrenceSeries] = []
    for key, items in sorted(groups.items()):
        if key in scope.recurrence_exclusions:
            continue
        ordered = sorted(items, key=lambda event: (event.effective_date, event.event_id))
        if len({event.effective_date for event in ordered}) < policy.recurrence_min_occurrences:
            continue
        cadence = _cadence(ordered)
        if cadence is None:
            continue
        direction = ordered[0].direction
        if direction == "credit":
            if _credit_series_cancelled(
                    scope, key, ordered[-1].effective_date):
                continue
            expected_before = _expected_before_start(ordered, cadence, start)
            missed = _missed_expected_credits(
                scope, expected_before, key, policy.recurrence_match_days)
            if missed >= 2:
                # Two or more expected pay cycles absent before the request
                # date: history no longer supports continuation.
                continue
        projected = _projected_dates(ordered, cadence, start, end)
        if not projected:
            continue
        if direction == "credit":
            typical = min(event.amount for event in ordered if event.amount is not None)
        else:
            typical = max(event.amount for event in ordered if event.amount is not None)
        series.append(RecurrenceSeries(
            key=key,
            event_ids=tuple(event.event_id for event in ordered),
            interval_days=cadence,
            typical_amount=typical,
            last_occurrence=ordered[-1].effective_date,
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
    events = _reconcile_events(scope.events)
    change_targets: dict[tuple[str, str, str], ChangeAction] = {}
    for change in sorted(changes, key=lambda item: item.event_id):
        target = scope.event_by_id(change.event_id)
        if target is None:
            raise ContractError(f"spending change targets unknown event {change.event_id}")
        change_targets.setdefault(series_key(target), change)

    flows: list[CashFlow] = []
    occurrences: dict[tuple[str, str, str], list[date]] = defaultdict(list)

    def apply_change(event: FinancialEvent, key: tuple[str, str, str], amount: Decimal) -> Decimal | None:
        if event.status == "pending":
            return amount
        change = change_targets.get(key)
        if change is None:
            return amount
        if change.kind == "stop":
            return None
        return change.new_amount

    for event in events:
        if not event.is_cash:
            continue
        if event.status == "cancelled":
            day = event.effective_date
            if day is not None and start <= day <= end:
                key = (event.category, "*", event.currency) if event.direction == "credit" else series_key(event)
                occurrences[key].append(day)
            continue
        if event.status in {"failed", "unrealized"}:
            continue
        if event.status == "settled":
            if event.effective_date <= start:
                continue
            day = event.effective_date
        elif event.status == "pending":
            if event.direction == "credit":
                # A pending credit is not cash, but its occurrence still covers
                # the series slot so recurrence must not recreate it as fresh
                # forecast income.
                if start <= event.effective_date <= end:
                    occurrences[(event.category, "*", event.currency)].append(
                        event.effective_date)
                continue
            day = event.effective_date
        elif event.status == "scheduled":
            if event.direction == "credit" and not _confirmed_salary(event):
                # Unconfirmed scheduled income is not cash and must not be
                # recreated by recurrence projection either.
                if start <= event.effective_date <= end:
                    occurrences[(event.category, "*", event.currency)].append(
                        event.effective_date)
                continue
            day = event.effective_date
        else:
            continue
        if day > end:
            continue
        occurrence_day = day
        if day < start and event.status in {"pending", "scheduled"}:
            if event.direction == "credit":
                continue
            day = start
        if day < start:
            continue
        key = series_key(event)
        occurrence_key = (event.category, "*", event.currency) if event.direction == "credit" else key
        if start <= occurrence_day <= end:
            occurrences[occurrence_key].append(occurrence_day)
        if event.amount is None:
            raise MissingAmountError(
                f"{event.event_id}: cash event has no amount; a missing amount is not zero")
        amount = apply_change(event, key, event.amount)
        if amount is None:
            continue
        converted = scope.rate_book.convert(
            amount, event.currency, scope.profile.home_currency, day,
            allow_inverse=policy.allow_inverse_rates)
        signed = -converted if event.direction == "debit" else converted
        flows.append(CashFlow(day, signed, f"event:{event.event_id}", event.event_id, key))

    for item in detect_recurrence(scope, policy, as_of=start):
        if item.key in scope.recurrence_exclusions:
            continue
        change = change_targets.get(item.key)
        if change is not None and change.kind == "stop":
            continue
        base = change.new_amount if change is not None else item.typical_amount
        if base is None:
            continue
        currency = item.key[2]
        sign = -1 if item.direction == "debit" else 1
        covered = list(occurrences.get(item.key, ()))
        for day in item.projected_dates:
            match = next(
                (index for index, existing in enumerate(covered)
                 if abs((existing - day).days) <= policy.recurrence_match_days), None)
            if match is not None:
                covered.pop(match)
                continue
            converted = scope.rate_book.convert(
                base, currency, scope.profile.home_currency, day,
                allow_inverse=policy.allow_inverse_rates)
            flows.append(CashFlow(
                day, sign * converted, f"recurrence:{item.key[0]}", None, item.key))

    if policy.variable_spending_enabled:
        model = variable_model or EssentialVariableReserve()
        for day, amount, currency in model.reserve_flows(scope, policy):
            if amount <= 0:
                continue
            converted = scope.rate_book.convert(
                amount, currency, scope.profile.home_currency, day,
                allow_inverse=policy.allow_inverse_rates)
            flows.append(CashFlow(
                day, -converted, "variable:reserve", None, None))

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

    def order(flow: CashFlow) -> tuple[int, str, str, Decimal]:
        debit_first = 0 if flow.amount < 0 else 1
        priority = 1 - debit_first if policy.same_day_order == "inflows_first" else debit_first
        return (2 if flow.label == "plan" else priority, flow.label, flow.event_id or "", flow.amount)

    ordered = sorted(flows, key=lambda flow: (flow.day, *order(flow)))

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


def capacity_schedule(
    current: Decimal,
    minimum: Decimal,
    start: date,
    flows: Sequence[tuple[date, Decimal]],
    *,
    horizon_days: int = 90,
    include_horizon_end: bool = True,
) -> dict[date, Decimal]:
    by_day: dict[date, list[Decimal]] = defaultdict(list)
    for day, amount in flows:
        by_day[day].append(amount)
    span = horizon_days if include_horizon_end else horizon_days - 1
    balance = current
    prefix_safe = current >= minimum
    days: list[tuple[date, Decimal, Decimal, bool]] = []
    for offset in range(span + 1):
        day = start + timedelta(days=offset)
        low = balance
        for amount in sorted(by_day[day]):
            balance += amount
            low = min(low, balance)
        prefix_safe = prefix_safe and low >= minimum
        days.append((day, balance, low, prefix_safe))
    future_low = balance
    schedule: dict[date, Decimal] = {}
    for day, balance, low, prefix_safe in reversed(days):
        schedule[day] = max(Decimal(0), min(balance, future_low) - minimum) if prefix_safe else Decimal(0)
        future_low = min(future_low, low)
    return schedule

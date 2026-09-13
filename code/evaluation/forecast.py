"""Independent, conservative offline replay; never reads candidate predictions or labels."""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .schema import ChangeAction, PlanEntry, parse_date, parse_decimal


@dataclass
class Forecast:
    flows: list[tuple[date, Decimal]] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)


def series_key(event: dict) -> tuple[str, str, str, str]:
    category = event.get("category", "").lower()
    description = " ".join(event.get("description", "").lower().split())
    return category, event.get("direction", ""), event.get("currency", ""), "salary" if category == "salary" else description


def _one_time(event: dict) -> bool:
    text = (event.get("description", "") + " " + event.get("category", "")).lower()
    return bool(re.search(r"arrear|one.time|bonus|commission|prize|lottery|refund|unrealized|internal transfer", text))


def _salary(event: dict) -> bool:
    text = event.get("description", "").lower()
    return event.get("category", "").lower() == "salary" and not _one_time(event) and not re.search(
        r"unapproved|unconfirmed|tentative|propos|not confirmed|not approved|estimate", text)


def _essential(event: dict, profile: dict) -> bool:
    # Variable reserve covers protected categories only (parity with
    # finance.forecast: amount_safe_to_pay is defined while covering
    # protected expenses; unprotected recurring spend is projected via
    # recurrence detection).
    category = event.get("category", "").lower()
    protected = set(profile.get("expense_categories_to_protect", "").lower().split("|"))
    return category in protected


def _cadence(entries: list[tuple[dict, date, Decimal]]) -> int | None:
    if len(entries) < 3:
        return None
    dates = sorted({day for _, day, _ in entries})
    if len(dates) < 3:
        return None
    gaps = [(right - left).days for left, right in zip(dates, dates[1:])]
    if not gaps:
        return None
    cadence = sorted(gaps)[len(gaps) // 2]
    if not 7 <= cadence <= 45 or any(abs(gap - cadence) > max(3, cadence // 4) for gap in gaps):
        return None
    return cadence


def _projected_dates(entries, cadence, start, end):
    dates = [day for _, day, _ in entries]
    last = max(dates)
    monthly = 28 <= cadence <= 31 and (
        len({day.day for day in dates}) == 1 or all(day.day == calendar.monthrange(day.year, day.month)[1] for day in dates))
    cursor = last
    while cursor <= end:
        if monthly:
            month_index = cursor.year * 12 + cursor.month
            year, month = divmod(month_index, 12)
            month += 1
            anchor = 31 if all(day.day == calendar.monthrange(day.year, day.month)[1] for day in dates) else last.day
            cursor = date(year, month, min(anchor, calendar.monthrange(year, month)[1]))
        else:
            cursor += timedelta(days=cadence)
        if start <= cursor <= end:
            yield cursor


def _expected_before(entries, cadence, request_date):
    """Occurrences the cadence places strictly before the request date,
    after the last settled occurrence."""
    earliest = min(day for _, day, _ in entries)
    last = max(day for _, day, _ in entries)
    monthly = 28 <= cadence <= 31 and (
        len({day.day for _, day, _ in entries}) == 1
        or all(day.day == calendar.monthrange(day.year, day.month)[1] for _, day, _ in entries))
    cursor, result = last, []
    while cursor < request_date:
        if monthly:
            month_index = cursor.year * 12 + cursor.month
            year, month = divmod(month_index, 12)
            month += 1
            anchor = 31 if all(day.day == calendar.monthrange(day.year, day.month)[1] for _, day, _ in entries) else last.day
            cursor = date(year, month, min(anchor, calendar.monthrange(year, month)[1]))
        else:
            cursor += timedelta(days=cadence)
        if earliest <= cursor < request_date:
            result.append(cursor)
    return result


def _missed_expected_credits(events, expected, key):
    actual = []
    for event in events:
        if (event.get("direction") != "credit"
                or event.get("status") not in {"settled", "pending", "scheduled"}
                or event.get("category", "").lower() != key[0]
                or event.get("currency", "") != key[2]):
            continue
        try:
            actual.append(parse_date(event.get("settlement_date", "")))
        except ValueError:
            continue
    return sum(
        1 for day in expected
        if not any(abs((existing - day).days) <= 3 for existing in actual))


def _credit_series_cancelled(events: list[dict], key, last_settled) -> bool:
    """An explicitly cancelled credit occurrence at or after the last settled
    occurrence ends the income projection (mirrors the live engine)."""
    for event in events:
        if event.get("direction") != "credit" or event.get("status") != "cancelled":
            continue
        if event.get("category", "").lower() != key[0] or event.get("currency", "") != key[2]:
            continue
        try:
            day = parse_date(event.get("settlement_date", ""))
        except ValueError:
            try:
                day = parse_date(event.get("event_date", ""))
            except ValueError:
                continue
        if day >= last_settled:
            return True
    return False


def _reconcile(events: list[dict]) -> list[dict]:
    """Only explicit lifecycle markers suppress cash; a link by itself does not."""
    by_id = {event.get("event_id"): event for event in events}
    suppressed = set()
    for event in events:
        linked = by_id.get(event.get("linked_event_id"))
        description = event.get("description", "").lower()
        if linked is None:
            continue
        combined = description + " " + linked.get("description", "").lower()
        if ("internal transfer" in combined and re.search(r"same.holder", combined)
                and {event.get("direction"), linked.get("direction")} == {"credit", "debit"}
                and all(event.get(key) == linked.get(key) for key in ("user_id", "amount", "currency", "settlement_date"))
                and all(item.get("status") in {"settled", "scheduled"} for item in (event, linked))):
            suppressed.update((event.get("event_id"), linked.get("event_id")))
        elif "duplicate" in description and all(event.get(key) == linked.get(key)
                for key in ("amount", "currency", "direction")):
            if event.get("status") == "settled" and linked.get("status") == "pending":
                suppressed.add(linked.get("event_id"))
            else:
                suppressed.add(event.get("event_id"))
        elif event.get("status") in {"settled", "cancelled"} and re.search(r"replace|cancel|settlement|authorization", description):
            if linked.get("status") in {"pending", "scheduled"}:
                suppressed.add(linked.get("event_id"))
    return [event for event in events if event.get("event_id") not in suppressed]


def _evidence_problems(request, context):
    """Unparsed relevant evidence is unknown, never an authorization or fabricated fact."""
    start = request["request_date"]
    user = request.get("user_id", "")
    for kind, records in (("message", context.messages.get(user, [])), ("image", context.images.get(user, []))):
        for record in records:
            linked_request = record.get("request_id")
            if linked_request and linked_request != request.get("request_id"):
                continue
            stamp = record.get("sent_at") or record.get("uploaded_at") or record.get("created_at") or record.get("image_date")
            if stamp:
                try:
                    if parse_date(stamp[:10]).isoformat() > start:
                        continue
                except ValueError:
                    pass  # Invalid timestamps cannot establish that evidence is irrelevant.
            identifier = record.get(kind + "_id", kind)
            yield "unresolved_evidence", f"{identifier}: relevant {kind} evidence requires factual interpretation"


def build_forecast(request: dict, context, changes: list[ChangeAction] | tuple = ()) -> Forecast:
    result = Forecast()
    profile = context.profiles.get(request.get("user_id", ""), {})
    home = profile.get("home_currency", "")
    start = parse_date(request["request_date"])
    end = start + timedelta(days=90)
    events = _reconcile(context.events.get(request.get("user_id", ""), []))
    result.problems.extend(_evidence_problems(request, context))
    by_id = {event.get("event_id"): event for event in events}
    targets = {series_key(by_id[action.event_id]): action for action in changes if action.event_id in by_id}
    concrete = defaultdict(list)
    concrete_amounts = defaultdict(list)
    history = defaultdict(list)

    def add(event, day, amount):
        # A spending change cannot release a pending debit already reserved.
        action = targets.get(series_key(event)) if event.get("direction") == "debit" and event.get("status") != "pending" else None
        if action:
            amount = Decimal(0) if action.kind == "stop" else action.amount
        if amount == 0:
            return
        currency = event.get("currency", "")
        if currency != home:
            rate = context.rates.get((day.isoformat(), currency, home))
            if rate is None:
                result.problems.append(("unresolved_fx_positive", f"{event.get('event_id')}: no exact {currency}->{home} rate on {day}"))
                return
            amount *= rate
        result.flows.append((day, -amount if event.get("direction") == "debit" else amount))

    for event in events:
        status, direction = event.get("status"), event.get("direction")
        if status in {"failed", "unrealized"} or direction not in {"credit", "debit"}:
            continue
        if status not in {"settled", "pending", "scheduled", "cancelled"}:
            result.problems.append(("invalid_context", f"{event.get('event_id')}: unknown cash status"))
            continue
        # Exclude speculative/pending credits from cash, but their occurrence
        # still covers the series slot so recurrence must not recreate the
        # pending credit as fresh forecast income.
        if direction == "credit" and (status == "pending" or (status == "scheduled" and not _salary(event))):
            try:
                pending_day = parse_date(event.get("settlement_date", ""))
            except ValueError:
                continue
            if start <= pending_day <= end:
                concrete[series_key(event)].append(pending_day)
            continue
        try:
            day = parse_date(event.get("settlement_date", ""))
        except ValueError:
            if status != "cancelled":
                result.problems.append(("invalid_context", f"{event.get('event_id')}: unavailable settlement date"))
            continue
        key = series_key(event)
        # A cancelled occurrence also covers its forecast slot, without creating cash.
        if start <= day <= end:
            concrete[key].append(day)
        if status == "cancelled":
            continue
        if day > end:
            continue
        if day < start and status in {"pending", "scheduled"}:
            # An overdue obligation still needs a reservation now; overdue income is not cash.
            if direction == "credit":
                continue
            day = start
        if day < start - timedelta(days=183):
            continue
        try:
            amount = parse_decimal(event.get("amount", ""))
            if amount < 0:
                raise ValueError("negative amount")
        except ValueError:
            if day >= start or (direction == "debit" and _essential(event, profile)):
                result.problems.append(("unresolved_amount", f"{event.get('event_id')}: cash amount is unavailable"))
            continue
        if status == "settled" and day < start:
            if not _one_time(event) and (direction == "debit" or _salary(event)):
                history[key].append((event, day, amount))
        elif not (status == "settled" and day == start):
            # current_available_balance already includes cash settled on request_date.
            concrete_amounts[key].append((day, amount))
            add(event, day, amount)

    projected: set[tuple[str, str, str, str]] = set()
    for key, entries in sorted(history.items()):
        entries.sort(key=lambda item: (item[1], item[0].get("event_id", "")))
        exemplar = entries[-1][0]
        cadence = _cadence(entries)
        if cadence is None:
            continue
        if key[1] == "credit":
            if _credit_series_cancelled(events, key, entries[-1][1]):
                # An explicitly cancelled credit occurrence at or after the last
                # settled one ends the income projection.
                continue
            if _missed_expected_credits(
                    events, _expected_before(entries, cadence, start), key) >= 2:
                # Two or more expected pay cycles absent before the request date:
                # history no longer supports continuation.
                continue
        projected.add(key)
        amount = min(value for _, _, value in entries) if key[1] == "credit" else max(value for _, _, value in entries)
        covered = list(concrete.get(key, []))
        for day in _projected_dates(entries, cadence, start, end):
            match = next((i for i, existing in enumerate(covered) if abs((existing - day).days) <= 3), None)
            if match is not None:
                covered.pop(match)
                continue
            add(dict(exemplar, status="scheduled"), day, amount)

    uncovered: dict[tuple[str, str], list[tuple[dict, date, Decimal]]] = defaultdict(list)
    for key, entries in history.items():
        if key in projected or key[1] != "debit":
            continue
        for item in entries:
            if _essential(item[0], profile):
                uncovered[(key[0], key[2])].append(item)
    for group, entries in sorted(uncovered.items()):
        # Irregular essentials: maximum observed 30-day bucket per category, reserved in advance.
        buckets = defaultdict(lambda: Decimal(0))
        for _, day, amount in entries:
            age = (start - day).days
            if 1 <= age <= 90:
                buckets[(age - 1) // 30] += amount
        if not buckets:
            continue
        reserve = max(buckets.values())
        exemplar = entries[-1][0]
        for offset in (0, 30, 60):
            day = start + timedelta(days=offset)
            known = sum(
                (amount for known_key, rows in concrete_amounts.items()
                 if (known_key[0], known_key[2]) == group
                 for existing, amount in rows if day <= existing < day + timedelta(days=30)),
                Decimal(0))
            add(dict(exemplar, status="scheduled"), day, max(Decimal(0), reserve - known))
    result.flows.sort(key=lambda item: (item[0], item[1]))
    result.problems = sorted(set(result.problems))
    return result


def replay(current: Decimal, minimum: Decimal, start: date, flows, plan=()) -> tuple[bool, Decimal]:
    """Essentials are checked debit-first; candidate payments follow that day's cash events."""
    by_day = defaultdict(list)
    payments = defaultdict(lambda: Decimal(0))
    for day, amount in flows:
        by_day[day].append(amount)
    for entry in plan:
        payments[entry.payment_date] += entry.amount
    balance = current
    lowest = current
    for day in sorted({start, *by_day, *payments}):
        for amount in sorted(by_day[day]):
            balance += amount
            lowest = min(lowest, balance)
        balance -= payments[day]
        lowest = min(lowest, balance)
    return lowest >= minimum, lowest


def capacities(current, minimum, start, flows):
    """Maximum one-time payment on every date that preserves all later essential debits."""
    by_day = defaultdict(list)
    for day, amount in flows:
        by_day[day].append(amount)
    balance = current
    prefix_safe = current >= minimum
    days = []
    for offset in range(91):
        day = start + timedelta(days=offset)
        low = balance
        for amount in sorted(by_day[day]):
            balance += amount
            low = min(low, balance)
        prefix_safe = prefix_safe and low >= minimum
        days.append((day, balance, low, prefix_safe))
    future_low = balance
    result = {}
    for day, balance, low, prefix_safe in reversed(days):
        result[day] = max(Decimal(0), min(balance, future_low) - minimum) if prefix_safe else Decimal(0)
        future_low = min(future_low, low)
    return result

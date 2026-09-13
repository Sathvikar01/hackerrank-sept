from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]
STATUS_VALUES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHOD_VALUES = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
_PLAN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}:[0-9]+(?:\.[0-9]+)?(?:\|\d{4}-\d{2}-\d{2}:[0-9]+(?:\.[0-9]+)?)*$")
_STOP_RE = re.compile(r"^stop:([^:|]+)$")
_REDUCE_RE = re.compile(r"^reduce_to:([^:|]+):([0-9]+(?:\.[0-9]+)?)$")


@dataclass(frozen=True)
class PlanEntry:
    payment_date: date
    amount: Decimal


@dataclass(frozen=True)
class ChangeAction:
    kind: str
    event_id: str
    amount: Decimal | None = None


@dataclass(frozen=True)
class ValidationIssue:
    scope: str
    code: str
    message: str
    request_id: str | None = None
    row_number: int | None = None


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    parsed_plans: dict[str, list[PlanEntry]] = field(default_factory=dict)
    parsed_changes: dict[str, list[ChangeAction]] = field(default_factory=dict)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        rows = []
        for row in reader:
            if None in row:
                raise ValueError(f"CSV row has extra fields at row {reader.line_num}: {path}")
            rows.append({key: (value if value is not None else "") for key, value in row.items()})
        return rows


def parse_decimal(value: str, *, positive: bool = False) -> Decimal:
    if value is None or value == "" or value != value.strip():
        raise ValueError("amount must be a non-empty, whitespace-free decimal")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount is not a decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise ValueError("amount must be finite and positive" if positive else "amount must be finite")
    return parsed


def parse_date(value: str) -> date:
    if not value or value != value.strip():
        raise ValueError("date must be YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return parsed


def parse_plan(value: str) -> list[PlanEntry]:
    if value == "none":
        return []
    if not value or not _PLAN_RE.fullmatch(value):
        raise ValueError("plan must be none or pipe-separated YYYY-MM-DD:positive_amount entries")
    entries: list[PlanEntry] = []
    for raw_entry in value.split("|"):
        raw_date, raw_amount = raw_entry.split(":", 1)
        entries.append(PlanEntry(parse_date(raw_date), parse_decimal(raw_amount, positive=True)))
    if any(left.payment_date > right.payment_date for left, right in zip(entries, entries[1:])):
        raise ValueError("plan entries must be chronological")
    return entries


def parse_changes(value: str) -> list[ChangeAction]:
    if value == "none":
        return []
    if not value or value.strip() != value:
        raise ValueError("changes must be none or pipe-separated actions")
    actions: list[ChangeAction] = []
    for raw_action in value.split("|"):
        stop = _STOP_RE.fullmatch(raw_action)
        if stop:
            actions.append(ChangeAction("stop", stop.group(1)))
            continue
        reduce_to = _REDUCE_RE.fullmatch(raw_action)
        if reduce_to:
            actions.append(ChangeAction("reduce_to", reduce_to.group(1), parse_decimal(reduce_to.group(2))))
            continue
        raise ValueError("invalid spending-change action")
    event_ids = [action.event_id for action in actions]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("an event cannot be changed more than once")
    if len(actions) > 3:
        raise ValueError("at most three spending changes are allowed")
    return actions


def validate_candidate_rows(rows: list[dict[str, str]], requests: list[dict[str, str]]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    parsed_plans: dict[str, list[PlanEntry]] = {}
    parsed_changes: dict[str, list[ChangeAction]] = {}
    expected_ids = [row.get("request_id", "") for row in requests]
    actual_ids = [row.get("request_id", "") for row in rows]
    expected_set = set(expected_ids)
    actual_set = set(actual_ids)

    if any(key not in row for row in rows for key in OUTPUT_COLUMNS):
        issues.append(ValidationIssue("schema", "missing_column", "candidate row is missing a required column"))
        return ValidationResult(False, issues, parsed_plans, parsed_changes)
    if len(rows) != len(requests):
        issues.append(ValidationIssue("schema", "row_count", f"expected {len(requests)} rows, found {len(rows)}"))
    if len(actual_ids) != len(actual_set):
        issues.append(ValidationIssue("schema", "duplicate_request_id", "candidate contains duplicate request IDs"))
    for request_id in sorted(expected_set - actual_set):
        issues.append(ValidationIssue("schema", "missing_request_id", "candidate is missing a request ID", request_id))
    for request_id in sorted(actual_set - expected_set):
        issues.append(ValidationIssue("schema", "extra_request_id", "candidate contains an unknown request ID", request_id))
    if actual_ids != expected_ids:
        issues.append(ValidationIssue("schema", "request_order", "candidate IDs are not in canonical request order"))

    request_by_id = {row.get("request_id", ""): row for row in requests}
    for row_number, row in enumerate(rows, start=2):
        request_id = row.get("request_id", "")
        request = request_by_id.get(request_id)
        if request is None:
            continue
        try:
            amount = parse_decimal(row.get("amount_safe_to_pay", ""))
            requested = parse_decimal(request.get("requested_amount", ""))
            if amount < 0 or amount > requested:
                raise ValueError("amount is outside [0, requested_amount]")
        except ValueError as exc:
            issues.append(ValidationIssue("schema", "invalid_amount", str(exc), request_id, row_number))
        status = row.get("affordability_status", "")
        if status not in STATUS_VALUES:
            issues.append(ValidationIssue("schema", "invalid_status", "status is not allowlisted", request_id, row_number))
        method = row.get("recommended_payment_method", "")
        if method not in METHOD_VALUES:
            issues.append(ValidationIssue("schema", "invalid_method", "payment method is not allowlisted", request_id, row_number))
        try:
            parsed_plans[request_id] = parse_plan(row.get("payment_plan", ""))
        except ValueError as exc:
            issues.append(ValidationIssue("schema", "invalid_plan", str(exc), request_id, row_number))
        try:
            parsed_changes[request_id] = parse_changes(row.get("spending_changes_needed", ""))
        except ValueError as exc:
            issues.append(ValidationIssue("schema", "invalid_changes", str(exc), request_id, row_number))
        earliest = row.get("earliest_date_for_full_payment", "")
        if earliest:
            try:
                parse_date(earliest)
            except ValueError as exc:
                issues.append(ValidationIssue("schema", "invalid_date", str(exc), request_id, row_number))

    return ValidationResult(not issues, issues, parsed_plans, parsed_changes)


from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from itertools import combinations
from pathlib import Path

from .schema import ChangeAction, PlanEntry, load_csv, parse_date, parse_decimal, parse_plan, parse_changes
from .forecast import build_forecast, capacities, replay, series_key


@dataclass(frozen=True)
class SafetyIssue:
    code: str
    message: str
    request_id: str | None = None
    blocking: bool = True


@dataclass
class ChangeValidation:
    valid: bool = True
    target_eligible: bool = True
    floor_compliant: bool = True
    protected_category_violation: bool = False
    action_count_valid: bool = True
    issues: list[SafetyIssue] = field(default_factory=list)


@dataclass
class SafetyResult:
    valid: bool = True
    issues: list[SafetyIssue] = field(default_factory=list)
    plan_safe: bool = True
    minimum_balance_valid: bool = True
    deadline_valid: bool = True
    unresolved_fx_positive: bool = False
    unsupported_income_expense: bool = False
    supplied_option_match: bool = True
    partial_constraints_valid: bool = True
    change_validation: ChangeValidation = field(default_factory=ChangeValidation)


@dataclass
class EvaluationContext:
    profiles: dict[str, dict[str, str]]
    events: dict[str, list[dict[str, str]]]
    options: dict[str, list[dict[str, str]]]
    rates: dict[tuple[str, str, str], Decimal]
    messages: dict[str, list[dict[str, str]]]
    images: dict[str, list[dict[str, str]]]
    requests: dict[str, dict[str, str]]


def _group(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key, ""), []).append(row)
    return grouped


def load_context(dataset_dir: Path, request_rows: list[dict[str, str]] | None = None) -> EvaluationContext:
    requests = request_rows if request_rows is not None else load_csv(dataset_dir / "requests.csv")
    rates = {}
    for row in load_csv(dataset_dir / "exchange_rates.csv"):
        try:
            rates[(row["rate_date"], row["from_currency"], row["to_currency"])] = parse_decimal(row["rate"], positive=True)
        except ValueError:
            continue
    return EvaluationContext(
        profiles={row["user_id"]: row for row in load_csv(dataset_dir / "financial_profiles.csv")},
        events=_group(load_csv(dataset_dir / "financial_events.csv"), "user_id"),
        options=_group(load_csv(dataset_dir / "request_payment_options.csv"), "request_id"),
        rates=rates,
        messages=_group(load_csv(dataset_dir / "messages.csv"), "user_id"),
        images=_group(load_csv(dataset_dir / "images.csv"), "user_id"),
        requests={row["request_id"]: row for row in requests},
    )


def _parts(value: str) -> set[str]:
    return {part for part in (value or "").split("|") if part}


def _same_amount(left: Decimal, right: Decimal) -> bool:
    return left == right


def _option_plan(option: dict[str, str]) -> list[PlanEntry] | None:
    try:
        count = int(option["number_of_payments"])
        amount = parse_decimal(option["payment_amount"], positive=True)
        first = parse_date(option["first_payment_date"])
        frequency = int(option.get("payment_frequency_days") or 0)
    except (KeyError, ValueError):
        return None
    if count <= 0 or (count > 1 and frequency <= 0):
        return None
    return [PlanEntry(first + timedelta(days=index * frequency), amount) for index in range(count)]


def _event_is_recurring(event: dict[str, str], user_events: list[dict[str, str]]) -> bool:
    if event.get("direction") != "debit" or event.get("status") in {"cancelled", "failed", "unrealized", "pending"}:
        return False
    description = (event.get("description", "") + " " + event.get("category", "")).lower()
    if any(word in description for word in ("monthly", "weekly", "subscription", "membership", "recurring")):
        return True
    same_category = [candidate for candidate in user_events if series_key(candidate) == series_key(event) and candidate.get("status") == "settled"]
    return len(same_category) >= 2


def validate_spending_changes(actions: list[ChangeAction], request: dict[str, str], context: EvaluationContext) -> ChangeValidation:
    result = ChangeValidation(action_count_valid=len(actions) <= 3)
    user_events = context.events.get(request.get("user_id", ""), [])
    by_id = {event.get("event_id"): event for event in user_events}
    profile = context.profiles.get(request.get("user_id", ""), {})
    protected = _parts(profile.get("expense_categories_to_protect", ""))
    reducible = _parts(profile.get("expense_categories_user_is_willing_to_reduce", ""))
    stoppable = _parts(profile.get("expense_categories_user_is_willing_to_stop", ""))
    seen: set[str] = set()
    for action in actions:
        event = by_id.get(action.event_id)
        if action.event_id in seen:
            result.valid = False
            result.target_eligible = False
            result.issues.append(SafetyIssue("duplicate_change_target", "event is targeted more than once", request.get("request_id")))
            continue
        seen.add(action.event_id)
        if event is None:
            result.valid = False
            result.target_eligible = False
            result.issues.append(SafetyIssue("ineligible_change_target", "target must be an existing recurring expense", request.get("request_id")))
            continue
        category = event.get("category", "")
        flexibility = event.get("flexibility", "")
        if category in protected:
            result.valid = False
            result.target_eligible = False
            result.protected_category_violation = True
            result.issues.append(SafetyIssue("protected_category", "target category is protected", request.get("request_id")))
        if not _event_is_recurring(event, user_events):
            result.valid = False
            result.target_eligible = False
            result.issues.append(SafetyIssue("ineligible_change_target", "target must be an existing recurring expense", request.get("request_id")))
        if action.kind == "stop":
            if category not in stoppable or flexibility not in {"stoppable", "reducible_or_stoppable"}:
                result.valid = False
                result.target_eligible = False
                result.issues.append(SafetyIssue("unauthorized_stop", "stop is not allowed for this category/event", request.get("request_id")))
        else:
            if category not in reducible or flexibility not in {"reducible", "reducible_or_stoppable"}:
                result.valid = False
                result.target_eligible = False
                result.issues.append(SafetyIssue("unauthorized_reduction", "reduction is not allowed for this category/event", request.get("request_id")))
            try:
                current = parse_decimal(event.get("amount", ""))
                floor = parse_decimal(event.get("minimum_allowed_amount", ""))
                if action.amount is None or action.amount >= current or action.amount < floor:
                    result.valid = False
                    result.floor_compliant = False
                    result.issues.append(SafetyIssue("invalid_reduction_floor", "reduction must be below current amount and at least the floor", request.get("request_id")))
            except ValueError:
                result.valid = False
                result.floor_compliant = False
                result.issues.append(SafetyIssue("invalid_reduction_amount", "reduction target cannot be checked", request.get("request_id")))
    if not result.action_count_valid:
        result.valid = False
        result.issues.append(SafetyIssue("too_many_changes", "at most three spending changes are allowed", request.get("request_id")))
    return result


def _future_cashflows(request: dict[str, str], context: EvaluationContext) -> tuple[list[tuple[date, Decimal]], list[SafetyIssue], bool]:
    forecast = build_forecast(request, context)
    issues = [SafetyIssue(code, message, request.get("request_id")) for code, message in forecast.problems]
    return forecast.flows, issues, any(code == "unresolved_fx_positive" for code, _ in forecast.problems)


def evaluate_row_safety(row: dict[str, str], request: dict[str, str], context: EvaluationContext) -> SafetyResult:
    result = SafetyResult()
    request_id = request.get("request_id")
    profile = context.profiles.get(request.get("user_id", ""))
    if profile is None:
        return SafetyResult(False, [SafetyIssue("missing_profile", "profile is unavailable", request_id)], False, False, False)
    try:
        requested = parse_decimal(request["requested_amount"], positive=True)
        safe_amount = parse_decimal(row["amount_safe_to_pay"])
        current = parse_decimal(profile["current_available_balance"])
        minimum = parse_decimal(profile["minimum_balance_to_keep"])
        request_date = parse_date(request["request_date"])
        desired = parse_date(request["desired_completion_date"])
    except (KeyError, ValueError) as exc:
        return SafetyResult(False, [SafetyIssue("invalid_context", str(exc), request_id)], False, False, False)

    try:
        plan = parse_plan(row.get("payment_plan", ""))
    except ValueError as exc:
        return SafetyResult(False, [SafetyIssue("invalid_plan", str(exc), request_id)], False, False, False)
    try:
        changes = parse_changes(row.get("spending_changes_needed", ""))
    except ValueError as exc:
        return SafetyResult(False, [SafetyIssue("invalid_changes", str(exc), request_id)], False, False, False)
    result.change_validation = validate_spending_changes(changes, request, context)
    result.issues.extend(result.change_validation.issues)

    accepted = _parts(profile.get("payment_methods_user_will_consider", ""))
    status = row.get("affordability_status", "")
    method = row.get("recommended_payment_method", "")
    result.supplied_option_match = True
    result.partial_constraints_valid = True

    if status == "affordable_now" and method != "full_payment":
        result.issues.append(SafetyIssue("status_method_mismatch", "affordable_now requires full_payment", request_id))
    if status == "affordable_with_plan" and method not in {"full_payment", "partial_payment", "installments"}:
        result.issues.append(SafetyIssue("status_method_mismatch", "affordable_with_plan requires a completing payment method", request_id))
    if status == "affordable_later" and method != "wait":
        result.issues.append(SafetyIssue("status_method_mismatch", "affordable_later requires wait", request_id))
    if status == "not_affordable" and (method != "not_recommended" or plan or row.get("earliest_date_for_full_payment", "")):
        result.issues.append(SafetyIssue("not_affordable_plan", "not_affordable requires no plan and no earliest date", request_id))

    if method == "full_payment":
        if "full_payment" not in accepted:
            result.issues.append(SafetyIssue("payment_preference", "full payment is not accepted", request_id))
        if len(plan) != 1 or plan[0].payment_date != request_date or not _same_amount(plan[0].amount, requested):
            result.issues.append(SafetyIssue("full_payment_plan", "full payment plan must be request_date:requested_amount", request_id))
        if status == "affordable_now" and changes:
            result.issues.append(SafetyIssue("status_change_mismatch", "affordable_now cannot require spending changes", request_id))
    elif method == "partial_payment":
        try:
            earliest = parse_date(row.get("earliest_date_for_full_payment", ""))
        except ValueError:
            earliest = None
        if request.get("allows_partial_payment", "").lower() != "true" or "partial_payment" not in accepted:
            result.partial_constraints_valid = False
            result.issues.append(SafetyIssue("partial_payment_eligibility", "partial payment is not accepted or allowed", request_id))
        if not (Decimal("0") < safe_amount < requested):
            result.partial_constraints_valid = False
            result.issues.append(SafetyIssue("partial_payment_amount", "partial payment must be strictly between zero and requested amount", request_id))
        if earliest is None or earliest <= request_date or earliest > desired or len(plan) != 2 or plan[0].payment_date != request_date or plan[1].payment_date != earliest:
            result.partial_constraints_valid = False
            result.issues.append(SafetyIssue("partial_payment_plan", "partial payment must have exactly two deadline-valid entries", request_id))
        elif not _same_amount(plan[0].amount, safe_amount) or not _same_amount(plan[1].amount, requested - safe_amount):
            result.partial_constraints_valid = False
            result.issues.append(SafetyIssue("partial_payment_sum", "partial payments must sum exactly to requested amount", request_id))
    elif method == "installments":
        if "installments" not in accepted or not profile.get("max_installment_months", ""):
            result.supplied_option_match = False
            result.issues.append(SafetyIssue("installment_eligibility", "installments are not accepted or have no maximum duration", request_id))
        matched = False
        for option in context.options.get(request_id, []):
            if option.get("payment_method") != "installments":
                continue
            option_plan = _option_plan(option)
            if option_plan is None or len(option_plan) != len(plan):
                continue
            if all(left.payment_date == right.payment_date and left.amount == right.amount for left, right in zip(option_plan, plan)):
                try:
                    duration = Decimal(max(0, int(option.get("number_of_payments", "0")) - 1) * int(option.get("payment_frequency_days") or 0)) / Decimal("30")
                    if duration <= parse_decimal(profile["max_installment_months"]):
                        matched = True
                except (ValueError, InvalidOperation):
                    pass
        result.supplied_option_match = matched
        if not matched:
            result.issues.append(SafetyIssue("installment_option_mismatch", "plan does not exactly match an eligible supplied installment option", request_id))
    elif method == "wait":
        try:
            earliest = parse_date(row.get("earliest_date_for_full_payment", ""))
        except ValueError:
            earliest = None
        if "full_payment" not in accepted:
            result.issues.append(SafetyIssue("payment_preference", "waiting requires accepted full payment", request_id))
        if earliest is None or earliest <= request_date or earliest > desired or len(plan) != 1 or plan[0].payment_date != earliest or plan[0].amount != requested:
            result.issues.append(SafetyIssue("wait_plan", "wait plan must be earliest_date:requested_amount by deadline", request_id))

    baseline = build_forecast(request, context)
    adjusted = build_forecast(request, context, changes) if changes and result.change_validation.valid else baseline
    problems = sorted(set(baseline.problems + adjusted.problems))
    result.issues.extend(_problem_issue(code, message, request_id, context) for code, message in problems)
    positive = status in {"affordable_now", "affordable_with_plan", "affordable_later"}
    result.unresolved_fx_positive = positive and any(code == "unresolved_fx_positive" for code, _ in problems)
    if not Decimal(0) <= safe_amount <= requested:
        result.issues.append(SafetyIssue("invalid_amount", "safe amount is outside request bounds", request_id))
    if status not in {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}:
        result.issues.append(SafetyIssue("invalid_status", "unknown status", request_id))
    if method not in {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}:
        result.issues.append(SafetyIssue("invalid_method", "unknown method", request_id))
    if not row.get("decision_explanation", "").strip():
        result.issues.append(SafetyIssue("explanation", "explanation is empty", request_id))
    if status == "affordable_now" and (safe_amount != requested or row.get("earliest_date_for_full_payment") != request["request_date"]):
        result.issues.append(SafetyIssue("safe_amount_date_mismatch", "affordable_now requires full safe amount and request-date earliest payment", request_id))
    if method == "full_payment" and status == "affordable_with_plan" and not changes:
        result.issues.append(SafetyIssue("status_change_mismatch", "full_payment with a plan requires spending changes", request_id))
    if changes and status != "affordable_with_plan":
        result.issues.append(SafetyIssue("status_change_mismatch", "spending changes require affordable_with_plan", request_id))

    if not baseline.problems:
        capacity = capacities(current, minimum, request_date, baseline.flows)
        expected_safe = min(requested, capacity[request_date]).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        earliest = next((day for day in sorted(capacity) if capacity[day] >= requested), None)
        if safe_amount != expected_safe:
            result.issues.append(SafetyIssue("safe_amount_mismatch", f"baseline safe amount is {expected_safe}", request_id))
        if status != "not_affordable":
            expected_date = earliest.isoformat() if earliest else ""
            if row.get("earliest_date_for_full_payment", "") != expected_date:
                result.issues.append(SafetyIssue("earliest_date_mismatch", f"baseline earliest full-payment date is {expected_date or 'none'}", request_id))
        elif _has_safe_completion(request, context, current, minimum, expected_safe, earliest):
            result.issues.append(SafetyIssue("false_not_affordable", "an eligible safe plan completes the request", request_id))

    if positive:
        result.minimum_balance_valid, _ = replay(current, minimum, request_date, adjusted.flows, plan)
        if not result.minimum_balance_valid:
            result.issues.append(SafetyIssue("minimum_balance", "projected balance falls below minimum", request_id))
    if plan:
        result.deadline_valid = all(request_date <= entry.payment_date <= min(desired, request_date + timedelta(days=90)) for entry in plan)
        if not result.deadline_valid:
            result.issues.append(SafetyIssue("deadline", "payment falls outside request/deadline/forecast interval", request_id))
    # Mandatory issues fail closed; unparsed evidence and evidence-resolvable
    # amounts are recorded as non-blocking findings instead.
    result.valid = not any(issue.blocking for issue in result.issues)
    result.plan_safe = result.valid
    return result


def _has_linked_evidence(context: EvaluationContext, event_id: str) -> bool:
    for kind in (context.messages, context.images):
        for records in kind.values():
            if any(record.get("related_event_id") == event_id for record in records):
                return True
    return False


def _problem_issue(code: str, message: str, request_id: str | None, context: EvaluationContext) -> SafetyIssue:
    if code == "unresolved_evidence":
        return SafetyIssue(code, message, request_id, blocking=False)
    if code == "unresolved_amount":
        event_id = message.split(":", 1)[0]
        return SafetyIssue(code, message, request_id, blocking=not _has_linked_evidence(context, event_id))
    return SafetyIssue(code, message, request_id)


def _has_safe_completion(request, context, current, minimum, safe_now, earliest):
    """Disprove a negative recommendation by constructing a safe eligible witness plan."""
    profile = context.profiles[request["user_id"]]
    accepted = _parts(profile.get("payment_methods_user_will_consider", ""))
    start = parse_date(request["request_date"])
    deadline = min(parse_date(request["desired_completion_date"]), start + timedelta(days=90))
    requested = parse_decimal(request["requested_amount"])
    plans = []
    if "full_payment" in accepted:
        plans.extend(("full_payment" if i == 0 else "wait", [PlanEntry(start + timedelta(days=i), requested)])
                     for i in range((deadline - start).days + 1))
    if "partial_payment" in accepted and request.get("allows_partial_payment", "").lower() == "true" and 0 < safe_now < requested and earliest and start < earliest <= deadline:
        plans.append(("partial_payment", [PlanEntry(start, safe_now), PlanEntry(earliest, requested - safe_now)]))
    if "installments" in accepted and profile.get("max_installment_months"):
        for option in context.options.get(request["request_id"], []):
            if option.get("payment_method") != "installments":
                continue
            plan = _option_plan(option)
            if plan and all(start <= item.payment_date <= deadline for item in plan):
                duration = Decimal((plan[-1].payment_date - plan[0].payment_date).days) / 30
                if duration <= parse_decimal(profile["max_installment_months"]):
                    plans.append(("installments", plan))
    if not plans:
        return False
    # Stopping or reducing to the allowed floor gives the largest authorized relief;
    # if this cannot fund a plan, a smaller change cannot either.
    actions = {}
    for event in context.events.get(request["user_id"], []):
        possible = [ChangeAction("stop", event.get("event_id", ""))]
        try:
            possible.append(ChangeAction("reduce_to", event.get("event_id", ""), parse_decimal(event.get("minimum_allowed_amount", ""))))
        except ValueError:
            pass
        for action in possible:
            if validate_spending_changes([action], request, context).valid:
                actions.setdefault(series_key(event), action)
                break
    options = [()] + [group for count in range(1, min(3, len(actions)) + 1) for group in combinations(actions.values(), count)]
    for changes in options:
        forecast = build_forecast(request, context, changes)
        if forecast.problems:
            continue
        if any(replay(current, minimum, start, forecast.flows, plan)[0]
               for method, plan in plans if not (changes and method == "wait")):
            return True
    return False

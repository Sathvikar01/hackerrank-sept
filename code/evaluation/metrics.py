from __future__ import annotations

from decimal import Decimal
from statistics import median

from .safety import SafetyResult
from .schema import OUTPUT_COLUMNS, ValidationResult, parse_date, parse_decimal, parse_plan, parse_changes


def _accuracy(values: list[bool]) -> float | str:
    return sum(values) / len(values) if values else "unavailable"


def _macro_f1(actual: list[str], expected: list[str]) -> float | str:
    if not actual or not expected:
        return "unavailable"
    labels = sorted(set(actual) | set(expected))
    scores = []
    for label in labels:
        tp = sum(a == label and e == label for a, e in zip(actual, expected))
        fp = sum(a == label and e != label for a, e in zip(actual, expected))
        fn = sum(a != label and e == label for a, e in zip(actual, expected))
        denom = 2 * tp + fp + fn
        scores.append((2 * tp / denom) if denom else 0.0)
    return sum(scores) / len(scores)


def _issue_rate(safety: list[SafetyResult], predicate) -> float | str:
    return sum(predicate(item) for item in safety) / len(safety) if safety else "unavailable"


def _change_strings(value: str) -> set[tuple] | None:
    try:
        return {(action.kind, action.event_id, action.amount) for action in parse_changes(value)}
    except ValueError:
        return None


def calculate_metrics(candidate_rows: list[dict[str, str]], gold_rows: list[dict[str, str]] | None,
                      validation: ValidationResult, safety: list[SafetyResult], context=None) -> dict:
    total = len(candidate_rows)
    result = {
        "amount": {"exact_accuracy": "unavailable", "mean_absolute_error": "unavailable", "median_absolute_error": "unavailable", "max_absolute_error": "unavailable", "mean_relative_absolute_error": "unavailable"},
        "status": {"accuracy": "unavailable", "macro_f1": "unavailable"},
        "payment_method": {"accuracy": "unavailable", "macro_f1": "unavailable"},
        "payment_plan": {"syntax_valid_rate": _accuracy([_safe_parse_plan(row.get("payment_plan", "")) for row in candidate_rows]), "safety_valid_rate": _accuracy([item.plan_safe for item in safety]), "exact_match_rate": "unavailable", "supplied_option_match_rate": "unavailable"},
        "partial_payment": {"constraint_pass_rate": _accuracy([item.partial_constraints_valid for item, row in zip(safety, candidate_rows) if row.get("recommended_payment_method") == "partial_payment"])},
        "earliest_date": {"exact_accuracy": "unavailable", "mean_absolute_date_error_days": "unavailable", "correct_empty_date_rate": "unavailable"},
        "spending_changes": {"syntax_validity_rate": _accuracy([_safe_parse_changes(row.get("spending_changes_needed", "")) for row in candidate_rows]), "target_eligibility_rate": _accuracy([item.change_validation.target_eligible for item in safety]), "floor_compliance_rate": _accuracy([item.change_validation.floor_compliant for item in safety]), "protected_category_violation_rate": _accuracy([item.change_validation.protected_category_violation for item in safety]), "at_most_three_actions_rate": _accuracy([item.change_validation.action_count_valid for item in safety]), "exact_action_set_accuracy": "unavailable"},
        "structured": {"first_seven_field_exact_accuracy": "unavailable"},
        "complete_row": {"exact_match_rate": "unavailable", "explanation_consistency_rate": "unavailable", "explanation_groundedness_rate": "unavailable", "explanation_present_rate": _accuracy([bool(row.get("decision_explanation", "").strip()) for row in candidate_rows])},
        "safety": {"safety_invariant_violation_rate": _issue_rate(safety, lambda item: not item.plan_safe), "schema_violation_rate": ((len({issue.request_id for issue in validation.issues if issue.request_id}) / total) if total and validation.issues and all(issue.request_id is not None for issue in validation.issues) else (1.0 if validation.issues else 0.0)), "minimum_balance_violation_rate": _issue_rate(safety, lambda item: not item.minimum_balance_valid), "deadline_violation_rate": _issue_rate(safety, lambda item: not item.deadline_valid), "unresolved_fx_positive_violation_rate": _issue_rate(safety, lambda item: item.unresolved_fx_positive), "unsupported_income_expense_violation_rate": _issue_rate(safety, lambda item: item.unsupported_income_expense)},
    }
    # Natural-language factual verification is not performed by this offline evaluator.
    result["safety"]["unsupported_income_expense_violation_rate"] = "unavailable"
    result["payment_plan"]["supplied_option_match_rate"] = _accuracy([
        item.supplied_option_match for row, item in zip(candidate_rows, safety)
        if row.get("recommended_payment_method") == "installments"
    ])
    if not validation.valid:
        return result
    if not gold_rows:
        return result
    gold_by_id = {row["request_id"]: row for row in gold_rows}
    pairs = [(row, gold_by_id.get(row.get("request_id"))) for row in candidate_rows]
    pairs = [(candidate, gold) for candidate, gold in pairs if gold is not None]
    if not pairs:
        return result
    candidates, gold = zip(*pairs)
    candidate_amounts = [parse_decimal(row["amount_safe_to_pay"]) for row in candidates]
    gold_amounts = [parse_decimal(row["amount_safe_to_pay"]) for row in gold]
    errors = [abs(actual - expected) for actual, expected in zip(candidate_amounts, gold_amounts)]
    relative = [error / expected for error, expected in zip(errors, gold_amounts) if expected]
    result["amount"] = {"exact_accuracy": _accuracy([actual == expected for actual, expected in zip(candidate_amounts, gold_amounts)]), "mean_absolute_error": float(sum(errors) / len(errors)), "median_absolute_error": float(median(errors)), "max_absolute_error": float(max(errors)), "mean_relative_absolute_error": float(sum(relative) / len(relative)) if relative else "unavailable", "relative_error_coverage": len(relative) / len(errors)}
    candidate_status = [row["affordability_status"] for row in candidates]
    gold_status = [row["affordability_status"] for row in gold]
    candidate_methods = [row["recommended_payment_method"] for row in candidates]
    gold_methods = [row["recommended_payment_method"] for row in gold]
    result["status"] = {"accuracy": _accuracy([a == b for a, b in zip(candidate_status, gold_status)]), "macro_f1": _macro_f1(candidate_status, gold_status)}
    result["payment_method"] = {"accuracy": _accuracy([a == b for a, b in zip(candidate_methods, gold_methods)]), "macro_f1": _macro_f1(candidate_methods, gold_methods)}
    result["payment_plan"]["exact_match_rate"] = _accuracy([a["payment_plan"] == b["payment_plan"] for a, b in zip(candidates, gold)])
    earliest_matches = []
    date_errors = []
    for candidate, expected in zip(candidates, gold):
        left, right = candidate.get("earliest_date_for_full_payment", ""), expected.get("earliest_date_for_full_payment", "")
        earliest_matches.append(left == right)
        if left and right:
            date_errors.append(abs((parse_date(left) - parse_date(right)).days))
    result["earliest_date"]["exact_accuracy"] = _accuracy(earliest_matches)
    result["earliest_date"]["mean_absolute_date_error_days"] = sum(date_errors) / len(date_errors) if date_errors else "unavailable"
    result["earliest_date"]["correct_empty_date_rate"] = _accuracy([
        not candidate.get("earliest_date_for_full_payment", "")
        for candidate, expected in pairs if not expected.get("earliest_date_for_full_payment", "")
    ])
    candidate_changes = [_change_strings(row.get("spending_changes_needed", "")) for row in candidates]
    gold_changes = [_change_strings(row.get("spending_changes_needed", "")) for row in gold]
    result["spending_changes"]["exact_action_set_accuracy"] = _accuracy([a is not None and a == b for a, b in zip(candidate_changes, gold_changes)])
    result["structured"]["first_seven_field_exact_accuracy"] = _accuracy([all(a.get(column) == b.get(column) for column in OUTPUT_COLUMNS[:7]) for a, b in zip(candidates, gold)])
    result["complete_row"]["exact_match_rate"] = _accuracy([all(a.get(column) == b.get(column) for column in OUTPUT_COLUMNS) for a, b in zip(candidates, gold)])
    return result


def _safe_parse_plan(value: str) -> bool:
    try:
        parse_plan(value)
        return True
    except ValueError:
        return False


def _safe_parse_changes(value: str) -> bool:
    try:
        parse_changes(value)
        return True
    except ValueError:
        return False

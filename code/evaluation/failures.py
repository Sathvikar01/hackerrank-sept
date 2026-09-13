from __future__ import annotations

from collections.abc import Iterable


TAXONOMY = [
    "State reconstruction", "Recurrence", "Lifecycle deduplication", "Multimodal extraction",
    "Message interpretation", "FX", "Forecasting", "Payment eligibility", "Plan construction",
    "Spending changes", "Ranking", "Formatting/schema", "Prompt injection", "Leakage", "Explanation",
]


def _code(issue: object) -> str:
    return str(getattr(issue, "code", issue))


def classify_failures(issues: Iterable[object]) -> list[str]:
    result: list[str] = []
    for issue in issues:
        code = _code(issue)
        if code in {"missing_column", "row_count", "duplicate_request_id", "missing_request_id", "extra_request_id", "request_order", "invalid_amount", "invalid_status", "invalid_method", "invalid_date", "invalid_plan", "invalid_changes"}:
            category = "Formatting/schema"
        elif code in {"unresolved_fx_positive"}:
            category = "FX"
        elif code in {"protected_category", "unauthorized_stop", "unauthorized_reduction", "ineligible_change_target", "invalid_reduction_floor", "invalid_reduction_amount", "too_many_changes", "duplicate_change_target"}:
            category = "Spending changes"
        elif code in {"payment_preference", "partial_payment_eligibility", "installment_eligibility", "status_method_mismatch"}:
            category = "Payment eligibility"
        elif code in {"full_payment_plan", "partial_payment_amount", "partial_payment_plan", "partial_payment_sum", "installment_option_mismatch", "wait_plan", "not_affordable_plan", "invalid_plan"}:
            category = "Plan construction"
        elif code in {"minimum_balance", "deadline", "safety_invariant", "unresolved_amount", "unsupported_income_expense", "invalid_context"}:
            category = "Forecasting"
        elif code in {"missing_profile", "safe_amount_mismatch", "safe_amount_date_mismatch"}:
            category = "State reconstruction"
        elif code in {"earliest_date_mismatch"}:
            category = "Forecasting"
        elif code in {"false_not_affordable"}:
            category = "Payment eligibility"
        elif code in {"unresolved_evidence"}:
            category = "Message interpretation"
        elif code in {"status_change_mismatch"}:
            category = "Plan construction"
        elif code in {"prompt_injection"}:
            category = "Prompt injection"
        elif code in {"leakage"}:
            category = "Leakage"
        elif code in {"explanation"}:
            category = "Explanation"
        else:
            category = "Formatting/schema"
        if category not in result:
            result.append(category)
    return result

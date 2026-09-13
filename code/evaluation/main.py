from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .failures import classify_failures
    from .metrics import calculate_metrics
    from .reports import write_artifacts, build_evaluation_result
    from .safety import EvaluationContext, SafetyIssue, SafetyResult, evaluate_row_safety, load_context
    from .schema import OUTPUT_COLUMNS, ValidationIssue, ValidationResult, load_csv, validate_candidate_rows
except ImportError:  # Allow `python code/evaluation/main.py` from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from evaluation.failures import classify_failures
    from evaluation.metrics import calculate_metrics
    from evaluation.reports import write_artifacts, build_evaluation_result
    from evaluation.safety import EvaluationContext, SafetyIssue, SafetyResult, evaluate_row_safety, load_context
    from evaluation.schema import OUTPUT_COLUMNS, ValidationIssue, ValidationResult, load_csv, validate_candidate_rows


INPUT_COLUMNS = [
    "request_id", "user_id", "request_date", "request_type", "requested_amount",
    "desired_completion_date", "allows_partial_payment", "request_text",
]
PUBLIC_FIXTURE_COLUMNS = INPUT_COLUMNS + OUTPUT_COLUMNS[1:]


class EvaluationInputError(ValueError):
    pass


def _read_csv_with_header(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    import csv

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise EvaluationInputError(f"candidate is missing a header: {path}")
        fieldnames = list(reader.fieldnames)
        rows = []
        for row in reader:
            if None in row:
                raise EvaluationInputError(f"candidate row has extra fields at line {reader.line_num}: {path}")
            rows.append({key: (value if value is not None else "") for key, value in row.items()})
        return fieldnames, rows


def _read_candidate(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]] | None]:
    header, rows = _read_csv_with_header(path)
    if header == OUTPUT_COLUMNS:
        return rows, None
    if header == PUBLIC_FIXTURE_COLUMNS:
        return [{key: row[key] for key in OUTPUT_COLUMNS} for row in rows], [{key: row[key] for key in INPUT_COLUMNS} for row in rows]
    raise EvaluationInputError(
        "candidate header must exactly match the output schema, or the explicit public sample fixture schema"
    )


def _read_gold(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]] | None]:
    return _read_candidate(path)


def _load_usage(path: Path | None) -> dict:
    if path is None:
        return {
            "providers": [], "model_calls": "unavailable", "input_tokens": "unavailable",
            "output_tokens": "unavailable", "total_tokens": "unavailable",
            "average_tokens_per_request": "unavailable", "estimated_total_cost": "unavailable",
            "estimated_cost_per_request": "unavailable", "latency_ms": "unavailable",
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"usage metadata is not valid JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise EvaluationInputError("usage metadata must be a JSON object")
    if isinstance(raw.get("usage"), dict) and isinstance(raw["usage"].get("rows"), list):
        measured = raw["usage"]
        costs = raw.get("cost", {})
        providers = []
        for item in measured["rows"]:
            providers.append({
                "provider": "ZenMux", "model": item.get("model", "unavailable"),
                "purpose": item.get("purpose", "unavailable"),
                "calls": item.get("calls", "unavailable"), "cache_hits": item.get("cache_hits", "unavailable"),
                "input_tokens": item.get("prompt_tokens", "unavailable"),
                "output_tokens": item.get("completion_tokens", "unavailable"),
                "estimated_cost": costs.get("by_model_purpose", {}).get(
                    f"{item.get('model')}|{item.get('purpose')}", "unavailable"),
            })
        raw = {
            "providers": providers, "request_count": raw.get("requests"),
            "model_calls": measured.get("total_calls", "unavailable"),
            "input_tokens": measured.get("total_prompt_tokens", "unavailable"),
            "output_tokens": measured.get("total_completion_tokens", "unavailable"),
            "estimated_total_cost": costs.get("total_usd", "unavailable"),
            "cache_hits": measured.get("cached_calls", "unavailable"),
            "latency_ms": raw["runtime_s"] * 1000 if isinstance(raw.get("runtime_s"), (int, float)) else "unavailable",
            "provenance": str(path),
        }
    providers = raw.get("providers")
    if isinstance(providers, list) and providers:
        numeric_specs = {
            "calls": "model_calls", "input_tokens": "input_tokens",
            "output_tokens": "output_tokens", "estimated_cost": "estimated_total_cost",
        }
        for provider_key, total_key in numeric_specs.items():
            values = [item.get(provider_key) for item in providers if isinstance(item, dict)]
            if values and len(values) == len(providers) and all(isinstance(value, (int, float)) for value in values):
                raw.setdefault(total_key, sum(values))
        if isinstance(raw.get("input_tokens"), (int, float)) and isinstance(raw.get("output_tokens"), (int, float)):
            raw.setdefault("total_tokens", raw["input_tokens"] + raw["output_tokens"])
        request_count = raw.get("request_count")
        if isinstance(request_count, (int, float)) and request_count > 0:
            if isinstance(raw.get("total_tokens"), (int, float)):
                raw.setdefault("average_tokens_per_request", raw["total_tokens"] / request_count)
            if isinstance(raw.get("estimated_total_cost"), (int, float)):
                raw.setdefault("estimated_cost_per_request", raw["estimated_total_cost"] / request_count)
    return raw


def _requests_for(candidate_context: list[dict[str, str]] | None, gold_context: list[dict[str, str]] | None,
                  dataset_dir: Path) -> list[dict[str, str]]:
    base = load_csv(dataset_dir / "requests.csv")
    base_ids = {row.get("request_id") for row in base}
    candidate_ids = {row.get("request_id") for row in candidate_context or []}
    gold_ids = {row.get("request_id") for row in gold_context or []}
    if candidate_ids and candidate_ids <= base_ids:
        return [row for row in base if row.get("request_id") in candidate_ids]
    if candidate_context and candidate_ids:
        return candidate_context
    if gold_context and gold_ids:
        return gold_context
    return base


def _validation_summary(validation: ValidationResult) -> dict:
    return {"valid": validation.valid, "issue_count": len(validation.issues), "issues": [issue.__dict__ for issue in validation.issues]}


def _safety_rows(candidate_rows: list[dict[str, str]], requests: list[dict[str, str]], context: EvaluationContext,
                 validation: ValidationResult) -> tuple[list[SafetyResult], list[dict]]:
    request_by_id = {row["request_id"]: row for row in requests}
    safety: list[SafetyResult] = []
    failures: list[dict] = []
    for row in candidate_rows:
        request_id = row.get("request_id")
        row_invalid = any(issue.request_id in {None, request_id} for issue in validation.issues)
        if row_invalid or request_id not in request_by_id:
            item = SafetyResult(False, [SafetyIssue("schema_invalid", "schema validation failed", request_id)], False, False, False)
        else:
            item = evaluate_row_safety(row, request_by_id[request_id], context)
        safety.append(item)
        issues = list(item.issues)
        if issues:
            failures.append({"request_id": request_id, "categories": classify_failures(issues), "issues": [issue.__dict__ for issue in issues]})
    for issue in validation.issues:
        if issue.request_id is None:
            failures.append({"request_id": "global", "categories": classify_failures([issue]), "issues": [issue.__dict__]})
    failures.sort(key=lambda item: (item["request_id"], json.dumps(item["issues"], sort_keys=True)))
    return safety, failures


def _gold_mismatch_failures(candidate_rows: list[dict[str, str]], gold_rows: list[dict[str, str]] | None) -> list[dict]:
    if not gold_rows:
        return []
    gold_by_id = {row.get("request_id"): row for row in gold_rows}
    field_categories = {
        "amount_safe_to_pay": "State reconstruction",
        "affordability_status": "Payment eligibility",
        "recommended_payment_method": "Payment eligibility",
        "payment_plan": "Plan construction",
        "earliest_date_for_full_payment": "Forecasting",
        "spending_changes_needed": "Spending changes",
        "decision_explanation": "Explanation",
    }
    failures = []
    for row in candidate_rows:
        expected = gold_by_id.get(row.get("request_id"))
        if expected is None:
            continue
        categories = []
        mismatches = []
        for field, category in field_categories.items():
            if row.get(field) != expected.get(field):
                if category not in categories:
                    categories.append(category)
                mismatches.append({"code": "gold_mismatch", "field": field, "message": "candidate differs from explicit gold fixture"})
        if mismatches:
            failures.append({"request_id": row.get("request_id"), "categories": categories, "issues": mismatches})
    return failures


def _evaluate_candidate(name: str, candidate_rows: list[dict[str, str]], requests: list[dict[str, str]],
                        context: EvaluationContext, gold_rows: list[dict[str, str]] | None,
                        usage: dict) -> dict:
    validation = validate_candidate_rows(candidate_rows, requests)
    safety, failures = _safety_rows(candidate_rows, requests, context, validation)
    gold_failures = _gold_mismatch_failures(candidate_rows, gold_rows)
    existing = {item["request_id"]: item for item in failures}
    for mismatch in gold_failures:
        if mismatch["request_id"] in existing:
            existing[mismatch["request_id"]]["categories"] = sorted(set(existing[mismatch["request_id"]]["categories"] + mismatch["categories"]))
            existing[mismatch["request_id"]]["issues"].extend(mismatch["issues"])
        else:
            failures.append(mismatch)
    failures.sort(key=lambda item: (item["request_id"], json.dumps(item["issues"], sort_keys=True)))
    metrics = calculate_metrics(candidate_rows, gold_rows, validation, safety, context)
    comparisons = {}
    result = build_evaluation_result(name, metrics, failures, usage, validation=_validation_summary(validation), comparisons=comparisons)
    result["hard_targets"] = {
        "schema_violation_rate": metrics["safety"]["schema_violation_rate"],
        "hard_safety_violation_rate": metrics["safety"]["safety_invariant_violation_rate"],
        "schema_target_met": metrics["safety"]["schema_violation_rate"] == 0.0,
        "hard_safety_target_met": metrics["safety"]["safety_invariant_violation_rate"] == 0.0,
    }
    result["policy"] = {
        "forecast": "Independent conservative projection: 90 days inclusive; same-day essential debits before credits, candidate payments after recorded daily cash flows.",
        "recurrence": "At least two historical occurrences with stable 7-45 day cadence; monthly series use calendar dates. Concrete occurrences replace forecasts.",
        "variable": "Essential variable spending uses the maximum historical 30-day total over the preceding 90 days, reserved at the start of each forecast month.",
        "precision": "Safe-now capacity is floored to two decimal places; monetary plan comparisons use exact decimals. Installment duration uses elapsed days divided by 30.",
        "evidence": "Relevant unparsed messages/images prevent verified acceptance. No regex text is promoted into income; no model or OCR calls are made.",
        "metrics": "Groundedness, substantive explanation consistency and unsupported-claim detection are unavailable. Relative error excludes zero-gold rows and reports coverage.",
        "limits": "Forecast assumptions are explicit evaluator policy, not a claim of equivalence to hidden ground truth. Public label self-comparison only verifies comparison mechanics.",
    }
    return result


def _parse_comparison(values: list[str]) -> list[tuple[str, Path]]:
    comparisons = []
    for value in values:
        if "=" not in value:
            raise EvaluationInputError("--comparison must use name=path")
        name, raw_path = value.split("=", 1)
        if not name or not raw_path:
            raise EvaluationInputError("--comparison must use a non-empty name and path")
        comparisons.append((name, Path(raw_path)))
    return comparisons


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run the frozen Buy-or-Wait evaluation contract.")
    parser.add_argument("--dataset-dir", type=Path, default=root / "dataset")
    parser.add_argument("--candidate", type=Path, default=root / "output.csv")
    parser.add_argument("--gold", type=Path, help="Explicit public-gold or approved fixture; never inferred.")
    parser.add_argument("--comparison", action="append", default=[], metavar="NAME=PATH", help="Evaluate a baseline/config candidate beside the primary candidate.")
    parser.add_argument("--artifact-dir", type=Path, default=root / "evaluation" / "validation")
    parser.add_argument("--usage-metadata", type=Path)
    parser.add_argument("--strict", action="store_true", help="Return nonzero on schema or hard safety violations.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        candidate_rows, candidate_context = _read_candidate(args.candidate)
        gold_rows = None
        gold_context = None
        if args.gold:
            gold_rows, gold_context = _read_gold(args.gold)
        requests = _requests_for(candidate_context, gold_context, args.dataset_dir)
        context = load_context(args.dataset_dir, requests)
        usage = _load_usage(args.usage_metadata)
        result = _evaluate_candidate(args.candidate.name, candidate_rows, requests, context, gold_rows, usage)
        comparison_results = {}
        for name, path in _parse_comparison(args.comparison):
            rows, fixture_context = _read_candidate(path)
            comparison_requests = _requests_for(fixture_context, gold_context, args.dataset_dir)
            if [row.get("request_id") for row in comparison_requests] != [row.get("request_id") for row in requests]:
                raise EvaluationInputError(f"comparison {name!r} does not use the primary candidate request set")
            comparison_results[name] = _evaluate_candidate(name, rows, requests, context, gold_rows, usage)
        result["comparisons"] = comparison_results
        artifact_paths = write_artifacts(result, args.artifact_dir)
        accepted = result["validation"]["valid"] and result["hard_targets"]["hard_safety_target_met"]
        print(json.dumps({"status": "valid" if accepted else "invalid", "schema_valid": result["validation"]["valid"], "hard_safety_target_met": result["hard_targets"]["hard_safety_target_met"], "candidate": str(args.candidate), "artifacts": {"results": str(artifact_paths.results), "report": str(artifact_paths.report), "usage_report": str(artifact_paths.usage_report)}}, sort_keys=True))
        if not result["validation"]["valid"]:
            return 1
        if args.strict and not result["hard_targets"]["hard_safety_target_met"]:
            return 3
        return 0
    except (EvaluationInputError, FileNotFoundError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

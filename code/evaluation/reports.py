from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactPaths:
    results: Path
    report: Path
    usage_report: Path


def build_evaluation_result(candidate_name: str, metrics: dict, failures: list[dict], usage: dict,
                            *, validation: dict | None = None, comparisons: dict | None = None) -> dict:
    return {
        "candidate": candidate_name,
        "metrics": metrics,
        "failures": failures,
        "usage": usage,
        "validation": validation or {},
        "comparisons": comparisons or {},
    }


def _flatten(mapping: dict, prefix: str = ""):
    for key in sorted(mapping):
        value = mapping[key]
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _flatten(value, name)
        else:
            yield name, value


def _usage_markdown(usage: dict) -> str:
    providers = usage.get("providers", []) if isinstance(usage, dict) else []
    lines = [
        "# Token Usage and Cost Analysis",
        "",
        "All unavailable measurements are reported as `unavailable`; no usage values are invented.",
        "",
        "## Providers and models",
        "",
        "| Provider | Model | Calls | Input tokens | Output tokens | Estimated cost |",
        "|---|---|---:|---:|---:|---:|",
    ]
    if providers:
        for provider in providers:
            lines.append("| {provider} | {model} | {calls} | {input} | {output} | {cost} |".format(
                provider=provider.get("provider", "unavailable"), model=provider.get("model", "unavailable"),
                calls=provider.get("calls", "unavailable"), input=provider.get("input_tokens", "unavailable"),
                output=provider.get("output_tokens", "unavailable"), cost=provider.get("estimated_cost", "unavailable")))
    else:
        lines.append("| unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |")
    lines.extend([
        "",
        "## Run totals",
        "",
        f"- Model calls: `{usage.get('model_calls', 'unavailable')}`",
        f"- Input tokens: `{usage.get('input_tokens', 'unavailable')}`",
        f"- Output tokens: `{usage.get('output_tokens', 'unavailable')}`",
        f"- Total tokens: `{usage.get('total_tokens', 'unavailable')}`",
        f"- Average tokens per request: `{usage.get('average_tokens_per_request', 'unavailable')}`",
        f"- Estimated total cost: `{usage.get('estimated_total_cost', 'unavailable')}`",
        f"- Estimated cost per request: `{usage.get('estimated_cost_per_request', 'unavailable')}`",
        f"- Latency: `{usage.get('latency_ms', 'unavailable')}` ms",
        "",
        "## Measurement provenance",
        "",
        "Values are taken from evaluator run metadata when supplied. Missing provider/token/cost/latency measurements remain unavailable.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(result: dict, output_dir: Path, usage_template: Path | None = None) -> ArtifactPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    # Evaluation usage is separate from the final prediction run's submission report.
    usage_path = output_dir / "evaluator_usage_report.md"
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Evaluation report", "", f"Candidate: `{result.get('candidate', 'unavailable')}`", "", "## Hard targets", "", "| Check | Value |", "|---|---:|"]
    for key, value in _flatten(result.get("hard_targets", {})):
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(["", "## Evaluation policy", ""])
    lines.extend(f"- {value}" for value in result.get("policy", {}).values())
    lines.extend(["", "## Metrics", "", "| Metric | Value |", "|---|---:|"])
    for key, value in _flatten(result.get("metrics", {})):
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(["", "## Failure taxonomy", "", "| Request | Categories |", "|---|---|"])
    failures = result.get("failures", [])
    if failures:
        for failure in failures:
            lines.append(f"| `{failure.get('request_id', 'global')}` | {', '.join(failure.get('categories', [])) or 'none'} |")
    else:
        lines.append("| none | none |")
    if result.get("comparisons"):
        lines.extend(["", "## Comparisons", "", "| Candidate | Schema target | Hard safety target | Structured exact accuracy |", "|---|---|---|---|"])
        for name, comparison in sorted(result["comparisons"].items()):
            targets = comparison.get("hard_targets", {})
            accuracy = comparison.get("metrics", {}).get("structured", {}).get("first_seven_field_exact_accuracy", "unavailable")
            lines.append(f"| {name} | {targets.get('schema_target_met')} | {targets.get('hard_safety_target_met')} | {accuracy} |")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    usage_path.write_text(_usage_markdown(result.get("usage", {})), encoding="utf-8")
    return ArtifactPaths(results_path, report_path, usage_path)

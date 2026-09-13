from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "code") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "code"))

from finance.engine import FinancialEngine, write_output_csv
from finance.forecast import ForecastPolicy
from finance.ingest import Dataset
from interpret.extractor import EvidenceExtractor
from interpret.pipeline import EvidencePipeline
from interpret.providers import ZenMuxClient
from interpret.usage import (
    FALLBACK_PRICING,
    CachingChatClient,
    Pricing,
    UsageStats,
    estimate_cost,
)
from interpret.verification import ModelVerificationController


def load_key() -> str | None:
    key = os.environ.get("ZENMUX_API_KEY")
    if key:
        return key
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ZENMUX_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def fetch_pricing(base_url: str, api_key: str) -> dict[str, Pricing]:
    try:
        request = urllib.request.Request(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": "Bearer " + api_key})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pricing = {}
        for entry in payload.get("data", []):
            pricings = entry.get("pricings", {})
            prompt = pricings.get("prompt") or []
            completion = pricings.get("completion") or []
            if prompt and completion:
                pricing[entry["id"]] = Pricing(
                    float(prompt[0]["value"]), float(completion[0]["value"]))
        return pricing or dict(FALLBACK_PRICING)
    except Exception:  # noqa: BLE001
        return dict(FALLBACK_PRICING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Buy-or-Wait pipeline over the dataset")
    parser.add_argument("--dataset-dir", default=str(REPO_ROOT / "dataset"))
    parser.add_argument("--output", default=str(REPO_ROOT / "output.csv"))
    parser.add_argument("--report", default=str(REPO_ROOT / "evaluation" / "usage_report.md"))
    parser.add_argument("--metrics", default=str(REPO_ROOT / "evaluation" / "dataset_metrics.json"))
    parser.add_argument("--certificates",
                        default=str(REPO_ROOT / "evaluation" / "certificates.jsonl"))
    parser.add_argument("--cache-dir", default=str(REPO_ROOT / "evaluation" / "cache"))
    parser.add_argument("--primary-model", default="meta/muse-spark-1.3-contributor")
    parser.add_argument("--second-model", default="google/gemini-3.8-flash")
    parser.add_argument("--controller-model", default="meta/muse-spark-1.3-contributor")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-verification", action="store_true")
    return parser


def ordered_request_ids(dataset: Dataset, limit: int = 0) -> list[str]:
    """Return request IDs in the dataset's canonical CSV insertion order."""
    request_ids = list(dataset.requests)
    return request_ids[:limit] if limit else request_ids


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = load_key()
    if not key:
        print("ZENMUX_API_KEY is not configured", file=sys.stderr)
        return 2
    base_url = os.environ.get("ZENMUX_BASE_URL", "https://zenmux.ai/api/v1")
    pricing = fetch_pricing(base_url, key)
    stats = UsageStats()

    def tracked(purpose: str) -> CachingChatClient:
        return CachingChatClient(
            ZenMuxClient(key, base_url=base_url), purpose=purpose, stats=stats,
            cache_dir=Path(args.cache_dir))

    primary = EvidenceExtractor(
        tracked("extraction_primary"), model=args.primary_model, max_tokens=8192)
    second = EvidenceExtractor(
        tracked("extraction_independent"), model=args.second_model, max_tokens=8192)
    controller = None
    if not args.no_verification:
        controller = ModelVerificationController(
            tracked("verification_controller"), model=args.controller_model,
            max_tokens=1024)

    dataset = Dataset.load(Path(args.dataset_dir))
    engine = FinancialEngine(dataset, ForecastPolicy(variable_spending_enabled=False))
    pipeline = EvidencePipeline(
        dataset, engine, primary=primary, second=second, controller=controller)

    request_ids = ordered_request_ids(dataset, args.limit)
    print(f"running {len(request_ids)} requests with {args.workers} workers")

    started = time.time()

    def run_one(request_id: str) -> dict[str, Any]:
        try:
            result = pipeline.run(request_id)
            return {"request_id": request_id, "result": result, "error": None}
        except Exception as error:  # noqa: BLE001
            return {"request_id": request_id, "result": None,
                    "error": f"{type(error).__name__}: {error}"}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outcomes = list(pool.map(run_one, request_ids))
    runtime_s = time.time() - started

    decisions = []
    failure_count = 0
    decision_counts: Counter = Counter()
    materiality_counts: Counter = Counter()
    attachment_counts: Counter = Counter()
    unresolved_reasons: Counter = Counter()
    extraction_errors = 0
    rejected_claims = 0
    verification_gated = 0
    verification_failed = 0
    conservative_decisions = 0
    pipeline_errors = []
    certificate_lines = []
    for item in outcomes:
        if item["error"] is not None:
            pipeline_errors.append({"request_id": item["request_id"],
                                    "error": item["error"]})
            decision = engine.decide(item["request_id"])
            decisions.append(decision)
            failure_count += 1
            decision_counts[(decision.affordability_status,
                             decision.recommended_payment_method)] += 1
            continue
        result = item["result"]
        decisions.append(result.decision)
        decision_counts[(result.decision.affordability_status,
                         result.decision.recommended_payment_method)] += 1
        payload = result.certificate.to_dict()
        materiality_counts.update([payload["materiality"]["status"]])
        materiality_counts["attachment_" + payload["materiality"]["attachment_status"]] += 1
        extraction_errors += len(payload["extraction_errors"])
        rejected_claims += len(payload["rejected_claims"])
        for attachment in payload["attachments"]:
            attachment_counts[attachment["state"]] += 1
            if attachment["state"] in {"ambiguous", "unresolved"}:
                for reason in attachment["reasons"]:
                    unresolved_reasons[reason[:80]] += 1
        if result.used_verification:
            verification_gated += 1
        if not result.certificate.verified:
            verification_failed += 1
        if any("Unresolved evidence" in note
               for note in result.certificate.unresolved):
            conservative_decisions += 1
        certificate_lines.append({"request_id": item["request_id"], **payload})

    write_output_csv(Path(args.output), decisions)

    usage = stats.summary()
    cost = estimate_cost(stats, pricing)
    metrics = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_dir": str(Path(args.dataset_dir).resolve()),
        "requests": len(request_ids),
        "pipeline_failures": failure_count,
        "runtime_s": round(runtime_s, 2),
        "requests_per_second": round(len(request_ids) / runtime_s, 4) if runtime_s else 0,
        "primary_model": args.primary_model,
        "second_model": args.second_model,
        "controller_model": (
            args.controller_model if controller is not None else None),
        "decisions": {f"{status}|{method}": count
                      for (status, method), count in sorted(decision_counts.items())},
        "materiality": dict(sorted(materiality_counts.items())),
        "attachments": dict(sorted(attachment_counts.items())),
        "attachment_unresolved_reasons": dict(unresolved_reasons.most_common(10)),
        "verification_gated": verification_gated,
        "verification_failed": verification_failed,
        "conservative_decisions": conservative_decisions,
        "extraction_errors": extraction_errors,
        "rejected_claims": rejected_claims,
        "usage": usage,
        "cost": cost,
        "pipeline_errors": pipeline_errors,
    }
    Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics).write_text(
        json.dumps(metrics, indent=2, default=str) + "\n", encoding="utf-8")
    with Path(args.certificates).open("w", encoding="utf-8") as handle:
        for line in certificate_lines:
            handle.write(json.dumps(line, default=str) + "\n")
    _write_report(Path(args.report), metrics, pricing)
    print(json.dumps({
        "requests": len(request_ids),
        "pipeline_failures": failure_count,
        "runtime_s": round(runtime_s, 2),
        "decisions": metrics["decisions"],
        "verification_gated": verification_gated,
        "cost_usd": cost["total_usd"],
    }, indent=2, default=str))
    return 0


def _write_report(path: Path, metrics: dict, pricing: dict[str, Pricing]) -> None:
    lines: list[str] = []
    lines.append("# Usage Report — Buy or Wait? Pipeline Run")
    lines.append("")
    lines.append(f"Generated: {metrics['generated_at']}")
    lines.append(f"Dataset: `{metrics['dataset_dir']}`")
    lines.append(
        f"Requests: {metrics['requests']} | Runtime: {metrics['runtime_s']}s "
        f"({metrics['requests_per_second']} req/s) | Pipeline failures: "
        f"{metrics['pipeline_failures']}")
    lines.append("")
    lines.append("## Models")
    lines.append("")
    lines.append("| Role | Model |")
    lines.append("|---|---|")
    lines.append(f"| Primary extraction | `{metrics['primary_model']}` |")
    lines.append(f"| Independent extraction | `{metrics['second_model']}` |")
    lines.append(
        f"| Verification controller | `{metrics['controller_model'] or 'disabled'}` |")
    lines.append("")
    lines.append("## Calls, tokens, and estimated cost")
    lines.append("")
    lines.append("| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |")
    lines.append("|---|---|---|---|---|---|")
    for row in metrics["usage"]["rows"]:
        lines.append(
            f"| `{row['model']}` | {row['purpose']} | {row['calls']} | "
            f"{row['cache_hits']} | {row['prompt_tokens']} | "
            f"{row['completion_tokens']} |")
    lines.append(
        f"| **total** | | **{metrics['usage']['total_calls']}** | "
        f"**{metrics['usage']['cached_calls']}** | "
        f"**{metrics['usage']['total_prompt_tokens']}** | "
        f"**{metrics['usage']['total_completion_tokens']}** |")
    lines.append("")
    lines.append("| Model | Purpose | Estimated USD |")
    lines.append("|---|---|---|")
    for key, value in sorted(metrics["cost"]["by_model_purpose"].items()):
        model, purpose = key.split("|", 1)
        lines.append(f"| `{model}` | {purpose} | ${value:.4f} |")
    lines.append(f"| **total** | | **${metrics['cost']['total_usd']:.4f}** |")
    lines.append("")
    if metrics["requests"]:
        lines.append(
            f"Average per request: "
            f"{(metrics['usage']['total_prompt_tokens'] + metrics['usage']['total_completion_tokens']) / metrics['requests']:.0f} "
            f"tokens, ${metrics['cost']['total_usd'] / metrics['requests']:.4f}.")
        lines.append("")
    lines.append("## Extraction coverage and failures")
    lines.append("")
    lines.append(f"- Extraction errors recorded: {metrics['extraction_errors']}")
    lines.append(f"- Rejected malformed claims: {metrics['rejected_claims']}")
    lines.append(f"- Pipeline exceptions (deterministic fallback): "
                 f"{metrics['pipeline_failures']}")
    if metrics["pipeline_errors"]:
        for error in metrics["pipeline_errors"][:5]:
            lines.append(f"  - `{error['request_id']}`: {error['error'][:160]}")
    lines.append("")
    lines.append("## Attachment outcomes (claims)")
    lines.append("")
    lines.append("| State | Count |")
    lines.append("|---|---|")
    for state in ("attached", "new_obligation", "ambiguous", "unresolved"):
        lines.append(f"| {state} | {metrics['attachments'].get(state, 0)} |")
    lines.append("")
    if metrics["attachment_unresolved_reasons"]:
        lines.append("Top unresolved/ambiguous reasons:")
        lines.append("")
        for reason, count in metrics["attachment_unresolved_reasons"].items():
            lines.append(f"- {count}x {reason}")
        lines.append("")
    lines.append("## Materiality and verification")
    lines.append("")
    lines.append("| Materiality | Count |")
    lines.append("|---|---|")
    for key, value in sorted(metrics["materiality"].items()):
        lines.append(f"| {key} | {value} |")
    lines.append("")
    lines.append(f"- Verification gate used: {metrics['verification_gated']} requests")
    lines.append(f"- Verification failed closed: {metrics['verification_failed']}")
    lines.append(f"- Conservative decisions (unresolved evidence): "
                 f"{metrics['conservative_decisions']}")
    lines.append("")
    lines.append("## Decision distribution")
    lines.append("")
    lines.append("| Status | Method | Count |")
    lines.append("|---|---|---|")
    for key, value in sorted(metrics["decisions"].items()):
        status, method = key.split("|", 1)
        lines.append(f"| {status} | {method} | {value} |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .config import Settings
from .protocol import parse_json_response, validate_plan
from .registry import load_registry


MAX_SUBTASKS = 8
MAX_ROUNDS = 2
MAX_EVIDENCE_CHARS = 4000

ROLE_INSTRUCTIONS = {
    "Astra XHigh": "hardest reasoning, architecture, hypotheses, ablations",
    "Muse Spark 1.3 Contributor": "repo/data/task reconnaissance",
    "DeepSeek V4.1 Flash": "implementation, debugging, tests",
    "GLM-5.3": "adversarial review",
    "GPT-5.6 Luna": "independent evaluation",
    "Grok 4.6": "escalation when the current approach is stuck",
}


@dataclass
class ClientBundle:
    gemini: Callable[[str, str], str]
    specialists: dict[str, Callable[[dict[str, Any]], str]]


def _invoke(item: dict[str, Any], specialist: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    model = item.get("model", "")
    try:
        output = specialist(item)
        return {"id": item["id"], "model": model, "status": "ok", "output": str(output)[:MAX_EVIDENCE_CHARS]}
    except Exception as error:  # provider failures become evidence for Gemini
        return {"id": item["id"], "model": model, "status": "failed", "error": str(error)[:500]}


def dispatch_groups(
    subtasks: list[dict[str, Any]],
    specialist: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    if not subtasks:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(subtasks))) as executor:
        futures = [executor.submit(_invoke, item, specialist) for item in subtasks]
        return [future.result() for future in as_completed(futures)]


def validate_final(final: dict[str, Any]) -> dict[str, Any]:
    decision = str(final.get("decision", "")).upper()
    if decision not in {"KEEP", "MODIFY", "ROLLBACK"}:
        raise ValueError("Gemini final result must contain decision KEEP, MODIFY, or ROLLBACK")
    return {**final, "decision": decision}


def _dispatch_in_dependency_order(
    subtasks: list[dict[str, Any]],
    specialists: dict[str, Callable[[dict[str, Any]], str]],
) -> list[dict[str, Any]]:
    pending = {item["id"]: item for item in subtasks}
    results: list[dict[str, Any]] = []
    completed: set[str] = set()
    while pending:
        ready = [item for item in pending.values() if set(item["depends_on"]).issubset(completed)]
        if not ready:
            raise ValueError("subtask dependencies contain a cycle")
        by_group: dict[str, list[dict[str, Any]]] = {}
        for item in ready:
            by_group.setdefault(item["independent_group"], []).append(item)
        for group_items in by_group.values():
            group_results = dispatch_groups(
                group_items,
                lambda item: specialists[item["model"]](item),
            )
            results.extend(group_results)
            for item in group_items:
                completed.add(item["id"])
                pending.pop(item["id"], None)
    return results


def _system_instruction(registry: list[dict[str, Any]] | None = None) -> str:
    roles = "; ".join(f"{model}: {role}" for model, role in ROLE_INSTRUCTIONS.items())
    verified = [
        {"model": record.get("model"), "exact_id": record.get("exact_id"), "role": record.get("role")}
        for record in (registry or [])
        if record.get("verified") and record.get("exact_id") and record.get("model") != "Gemini 3.8 Flash"
    ]
    return (
        "You are the orchestration controller. Route the supplied task to bounded specialist subtasks; "
        "do not perform the work yourself. Use only verified model IDs supplied in the registry. "
        "Mark independent work with the same independent_group and use depends_on for prerequisites. "
        "Return JSON only. The available role mapping is: " + roles +
        " Verified exact model catalog (use only these IDs): " + json.dumps(verified, sort_keys=True)
    )


def _plan_prompt(task: str) -> str:
    return json.dumps({
        "request": "Create a bounded routing plan for this task.",
        "task": task,
        "schema": {
            "subtasks": [{
                "id": "unique short id",
                "model": "exact verified model ID",
                "role": "registered role",
                "instruction": "specific bounded instruction derived from the task",
                "independent_group": "group name",
                "depends_on": [],
            }],
        },
    })


def _decision_prompt(task: str, plan: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
    return json.dumps({
        "request": "Decide whether one bounded follow-up is needed from the evidence; do not solve the task.",
        "task": task,
        "plan": plan,
        "evidence": evidence,
        "schema": {
            "needs_iteration": False,
            "reason": "short evidence-based reason",
            "follow_up_subtasks": [],
        },
    })


def _final_prompt(task: str, evidence: list[dict[str, Any]], decision: dict[str, Any]) -> str:
    return json.dumps({
        "request": "Return the collected specialist results and orchestration status without doing unassigned work.",
        "task": task,
        "decision": decision,
        "evidence": evidence,
        "schema": {"decision": "KEEP|MODIFY|ROLLBACK", "status": "complete|blocked|needs_user_input", "summary": "short result", "evidence": []},
    })


def orchestrate(task: str, registry_path: Path, settings: Settings, clients: ClientBundle) -> dict[str, Any]:
    if not task.strip():
        raise ValueError("task must not be empty")
    registry = load_registry(registry_path)
    gemini_records = [
        record for record in registry
        if record.get("provider") == "APInex"
        and record.get("model") == "Gemini 3.8 Flash"
        and record.get("verified")
    ]
    if not gemini_records:
        raise ValueError("verified APInex Gemini 3.8 Flash is required")
    system = _system_instruction(registry)
    plan = validate_plan(parse_json_response(clients.gemini(system, _plan_prompt(task))), registry)
    evidence = _dispatch_in_dependency_order(plan, clients.specialists)
    decision = parse_json_response(clients.gemini(system, _decision_prompt(task, plan, evidence)))
    follow_up: list[dict[str, Any]] = []
    if decision.get("needs_iteration") is True and MAX_ROUNDS > 1:
        follow_up_plan = {"subtasks": decision.get("follow_up_subtasks", [])}
        follow_up = validate_plan(follow_up_plan, registry)
        evidence.extend(_dispatch_in_dependency_order(follow_up, clients.specialists))
    final = validate_final(parse_json_response(clients.gemini(system, _final_prompt(task, evidence, decision))))
    return {
        "task": task,
        "plan": plan,
        "decision": decision,
        "follow_up_plan": follow_up,
        "evidence": evidence,
        "final": final,
    }

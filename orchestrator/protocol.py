from __future__ import annotations

import json
import re
from typing import Any


def parse_json_response(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.I | re.S)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError(f"Gemini returned invalid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise ValueError("Gemini response must be a JSON object")
    return value


def validate_plan(
    plan: dict[str, Any],
    registry: list[dict[str, Any]],
    max_subtasks: int = 8,
) -> list[dict[str, Any]]:
    raw_subtasks = plan.get("subtasks")
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        raise ValueError("plan must contain a non-empty subtasks array")
    if len(raw_subtasks) > max_subtasks:
        raise ValueError(f"plan contains more than {max_subtasks} subtasks")
    orchestrator_ids = {
        str(record.get("exact_id"))
        for record in registry
        if record.get("model") == "Gemini 3.8 Flash" and record.get("exact_id")
    }
    verified_ids = {
        str(record.get("exact_id"))
        for record in registry
        if record.get("verified") and record.get("exact_id") and record.get("model") != "Gemini 3.8 Flash"
    }
    registered_roles = {
        str(record.get("role"))
        for record in registry
        if record.get("verified") and record.get("role") and record.get("model") != "Gemini 3.8 Flash"
    }
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in raw_subtasks:
        if not isinstance(item, dict):
            raise ValueError("each subtask must be an object")
        subtask_id = str(item.get("id", "")).strip()
        model = str(item.get("model", "")).strip()
        role = str(item.get("role", "")).strip()
        instruction = str(item.get("instruction", "")).strip()
        group = str(item.get("independent_group", "")).strip()
        dependencies = item.get("depends_on", [])
        if not subtask_id or subtask_id in ids:
            raise ValueError("subtask IDs must be non-empty and unique")
        if not model or model not in verified_ids or model in orchestrator_ids:
            raise ValueError(f"subtask {subtask_id or '<unnamed>'} references an unverified model")
        if not role:
            raise ValueError(f"subtask {subtask_id} has no role")
        if registered_roles and role not in registered_roles and role.lower() not in {value.lower() for value in registered_roles}:
            raise ValueError(f"subtask {subtask_id} references an unregistered role")
        if not instruction or len(instruction) > 2000:
            raise ValueError(f"subtask {subtask_id} instruction must be 1-2000 characters")
        if not group or not isinstance(dependencies, list):
            raise ValueError(f"subtask {subtask_id} has invalid dependency metadata")
        ids.add(subtask_id)
        normalized.append({
            "id": subtask_id,
            "model": model,
            "role": role,
            "instruction": instruction,
            "independent_group": group,
            "depends_on": [str(value) for value in dependencies],
        })
    for item in normalized:
        if item["id"] in item["depends_on"] or any(value not in ids for value in item["depends_on"]):
            raise ValueError(f"subtask {item['id']} has an invalid dependency")
    return normalized

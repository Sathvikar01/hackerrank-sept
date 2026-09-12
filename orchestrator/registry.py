from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
import re
from typing import Any


@dataclass
class ModelRecord:
    model: str
    provider: str
    exact_id: str | None
    role: str
    transport: str
    verified: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_dict(record: ModelRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, ModelRecord):
        return record.to_dict()
    allowed = {field.name for field in fields(ModelRecord)}
    result = {key: value for key, value in record.items() if key in allowed}
    result.setdefault("provider", "unknown")
    result.setdefault("exact_id", None)
    result.setdefault("role", "unassigned")
    result.setdefault("transport", "unknown")
    result.setdefault("verified", bool(result.get("exact_id")))
    result.setdefault("reason", None)
    return result


def save_registry(path: Path, records: list[ModelRecord | dict[str, Any]]) -> None:
    normalized = [_as_dict(record) for record in records]
    for record in normalized:
        for key, value in record.items():
            if re.search(r"(api.?key|token|secret|password|authorization)", key, re.I):
                raise ValueError(f"secret-bearing registry field is not allowed: {key}")
            if isinstance(value, (dict, list)):
                raise ValueError("nested registry values are not allowed")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("model registry must be a JSON array")
    return payload

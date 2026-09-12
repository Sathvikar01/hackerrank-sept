from __future__ import annotations

from collections.abc import Callable, Iterable
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .config import Settings
from .registry import ModelRecord
from .transport import ProviderError, redact, request_json


APINEX_TARGETS = (
    ("Gemini 3.8 Flash", "orchestration"),
    ("GPT-5.6 Luna", "independent evaluation"),
    ("GLM-5.3 Flash", "adversarial review"),
)
OPENCODE_TARGETS = (
    ("Muse Spark 1.3 Contributor", "repo/data/task reconnaissance"),
    ("DeepSeek V4.1 Flash", "implementation, debugging, tests"),
)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _target_match(target: str, *values: Any) -> bool:
    wanted = _norm(target).split()
    haystack = " ".join(_norm(value) for value in values if value is not None)
    return all(token in haystack.split() for token in wanted)


def _failed(model: str, provider: str, role: str, transport: str, reason: str) -> ModelRecord:
    return ModelRecord(model, provider, None, role, transport, False, reason)


def discover_apinex(
    settings: Settings,
    *,
    request_json: Callable[..., tuple[int, dict]] = request_json,
) -> list[ModelRecord]:
    records: list[ModelRecord] = []
    timeout = getattr(settings, "timeout", 20.0)
    if not settings.apinex_api_key:
        return [
            _failed(model, "APInex", role, "https", "APINEX_API_KEY is not set")
            for model, role in APINEX_TARGETS
        ]
    try:
        _, payload = request_json(
            "GET",
            f"{settings.apinex_base_url}/models",
            {"Authorization": f"Bearer {settings.apinex_api_key}"},
            None,
            timeout,
            secrets=[settings.apinex_api_key],
        )
    except TypeError:
        # Small injected fakes can use the documented five-argument boundary.
        _, payload = request_json(
            "GET",
            f"{settings.apinex_base_url}/models",
            {"Authorization": f"Bearer {settings.apinex_api_key}"},
            None,
            timeout,
        )
    except ProviderError as error:
        return [
            _failed(model, "APInex", role, "https", str(error))
            for model, role in APINEX_TARGETS
        ]
    models = payload.get("data", [])
    if not isinstance(models, list):
        models = []
    for target, role in APINEX_TARGETS:
        match = next(
            (
                item
                for item in models
                if isinstance(item, dict)
                and _target_match(target, item.get("name"), item.get("id"), item.get("model"))
            ),
            None,
        )
        if match is None or not match.get("id"):
            records.append(_failed(target, "APInex", role, "https", "exact model ID not returned by /models"))
        else:
            records.append(ModelRecord(target, "APInex", str(match["id"]), role, "https", False, None))
    return records


def _json_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if any(key in value for key in ("id", "model", "name")):
            yield value
        for child in value.values():
            yield from _json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_objects(child)


def _parse_opencode_output(stdout: str) -> list[dict[str, str]]:
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        decoded = None
    if decoded is not None:
        return [
            {key: str(item.get(key, "")) for key in ("id", "model", "name", "provider")}
            for item in _json_objects(decoded)
        ]
    rows: list[dict[str, str]] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(("[", "╭", "╰", "│", "─")):
            continue
        match = re.search(r"(?<![A-Za-z0-9_.:-])([A-Za-z0-9_.:-]+/[A-Za-z0-9_.:-]+)", line)
        if match:
            rows.append({"id": match.group(1), "name": line, "model": line, "provider": line})
    return rows


def _run_command(args: list[str], timeout: float = 20.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, "", str(error)
    return completed.returncode, completed.stdout, completed.stderr


def _command(executable: str) -> list[str]:
    resolved = shutil.which(f"{executable}.cmd") or shutil.which(executable) or executable
    if str(resolved).lower().endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(resolved)]
    return [str(resolved)]


def _extract_codex_output(stdout: str) -> str:
    messages: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if (
            isinstance(event, dict)
            and event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            messages.append(item["text"])
    return "\n".join(messages).strip() or stdout.strip()


def _codex_call(executable: str, model: str, prompt: str, timeout: float) -> str:
    code, stdout, stderr = _run_command([
        *_command(executable),
        "-a", "never", "-s", "read-only", "exec", "--model", model,
        "--skip-git-repo-check", "--ephemeral", "--json", "-c", "model_reasoning_effort=xhigh", prompt,
    ], timeout=timeout)
    if code != 0:
        raise ProviderError(redact(stderr or stdout or f"codex exec exited with {code}", ())[:300])
    output = _extract_codex_output(stdout)
    if not output:
        raise ProviderError("codex exec returned empty output")
    return output


def discover_opencode(executable: str = "opencode") -> list[ModelRecord]:
    if not (shutil.which(executable) or shutil.which(f"{executable}.cmd") or Path(executable).exists()):
        return [
            _failed(model, "OpenCode Go", role, "cli", f"{executable} executable not found")
            for model, role in OPENCODE_TARGETS
        ]
    code, stdout, stderr = _run_command(_command(executable) + ["models"], timeout=30.0)
    if code != 0:
        reason = redact(stderr or stdout or f"{executable} models exited with {code}", ())[:300]
        return [_failed(model, "OpenCode Go", role, "cli", reason) for model, role in OPENCODE_TARGETS]
    rows = _parse_opencode_output(stdout)
    records: list[ModelRecord] = []
    for target, role in OPENCODE_TARGETS:
        match = next(
            (row for row in rows if _target_match(target, row.get("id"), row.get("name"), row.get("model"))),
            None,
        )
        if match is None:
            records.append(_failed(target, "OpenCode Go", role, "cli", "exact model ID not returned by opencode models"))
        else:
            records.append(ModelRecord(target, "OpenCode Go", match["id"], role, "cli", False, None))
    return records


def check_codex(executable: str = "codex") -> ModelRecord:
    if not (shutil.which(executable) or shutil.which(f"{executable}.cmd") or Path(executable).exists()):
        return _failed("Astra XHigh", "Codex / OpenAI", "hardest reasoning, architecture, hypotheses, ablations", "codex-cli", "codex executable not found; native/manual only")
    try:
        _codex_call(executable, "gpt-6-astra", "Respond with exactly: ASTRA_SMOKE_OK", 45.0)
        return ModelRecord("Astra XHigh", "Codex / OpenAI", "gpt-6-astra", "hardest reasoning, architecture, hypotheses, ablations", "codex-cli", True, "non-interactive codex exec succeeded")
    except ProviderError as error:
        reason = str(error)[:300]
    return _failed("Astra XHigh", "Codex / OpenAI", "hardest reasoning, architecture, hypotheses, ablations", "codex-cli", f"no callable surface verified; native/manual only or unavailable: {reason}")


def check_pair() -> list[ModelRecord]:
    executable = shutil.which("pair")
    reason = "no Pair API/CLI discovered; Pair is UI-only for this workspace"
    if executable:
        reason = "Pair executable found, but no documented callable model API was verified"
    return [
        _failed("Grok 4.6", "HackerRank Pair", "escalation when the current approach is stuck", "ui-only", reason),
        _failed("GLM-5.3", "HackerRank Pair", "adversarial review", "ui-only", reason),
    ]


def _post_chat(settings: Settings, model_id: str, messages: list[dict[str, str]]) -> str:
    if not settings.apinex_api_key:
        raise ProviderError("APINEX_API_KEY is not set")
    body = json.dumps({"model": model_id, "messages": messages, "temperature": 0}).encode("utf-8")
    for attempt in range(2):
        try:
            _, payload = request_json(
                "POST",
                f"{settings.apinex_base_url}/chat/completions",
                {"Authorization": f"Bearer {settings.apinex_api_key}", "Content-Type": "application/json"},
                body,
                settings.timeout,
                secrets=[settings.apinex_api_key],
            )
            break
        except ProviderError:
            if attempt == 1:
                raise
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("provider returned no chat choices")
    message = choices[0].get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("provider returned empty chat content")
    return content


def smoke_record(record: ModelRecord, settings: Settings, executables: dict[str, str] | None = None) -> ModelRecord:
    executables = executables or {}
    try:
        if record.provider == "APInex" and record.exact_id:
            content = _post_chat(settings, record.exact_id, [{"role": "user", "content": "Respond with exactly: SMOKE_OK"}])
            return ModelRecord(**{**record.to_dict(), "verified": bool(content.strip()), "reason": "chat completion succeeded"})
        if record.provider == "OpenCode Go" and record.exact_id:
            executable = executables.get("opencode", "opencode")
            code, stdout, stderr = _run_command(_command(executable) + ["run", "--format", "json", "--model", record.exact_id, "Respond with exactly: SMOKE_OK"], timeout=max(settings.timeout, 90.0))
            if code == 0 and stdout.strip():
                return ModelRecord(**{**record.to_dict(), "verified": True, "reason": "opencode run succeeded"})
            return ModelRecord(**{**record.to_dict(), "verified": False, "reason": redact(stderr or stdout or f"opencode run exited with {code}", ())[:300]})
        if record.provider == "Codex / OpenAI":
            return check_codex(executables.get("codex", "codex"))
    except (ProviderError, OSError, ValueError) as error:
        return ModelRecord(**{**record.to_dict(), "verified": False, "reason": str(error)[:300]})
    return record


def discover_all(settings: Settings, executables: dict[str, str] | None = None) -> list[ModelRecord]:
    executables = executables or {}
    records = [check_codex(executables.get("codex", "codex"))]
    records.extend(discover_opencode(executables.get("opencode", "opencode")))
    records.extend(discover_apinex(settings))
    records.extend(check_pair())
    return records

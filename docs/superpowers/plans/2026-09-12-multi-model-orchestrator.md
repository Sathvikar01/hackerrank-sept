# Multi-Model Hackathon Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and verify a minimal persistent Python CLI that discovers the requested model IDs, smoke-tests callable providers, and routes arbitrary Codex tasks through APInex Gemini to bounded specialist subtasks.

**Architecture:** A stdlib-only `orchestrator` package owns environment loading, provider adapters, non-secret model registry, plan validation, bounded concurrent dispatch, and the CLI. APInex Gemini is the only planner/evaluator; provider adapters are independently callable and are selected only from the verified registry. Astra is an optional specialist whose entry is verified only by a successful non-interactive `codex exec` call.

**Tech Stack:** Python 3.11 standard library (`argparse`, `json`, `subprocess`, `urllib`, `concurrent.futures`, `unittest`), OpenAI-compatible APInex HTTP API, Codex CLI, OpenCode CLI.

**Spec:** `docs/superpowers/specs/2026-09-12-multi-model-hackathon-environment-design.md`

## Global Constraints

- Gemini must use APInex only.
- Use environment variables for secrets; never print or persist API keys.
- Treat Astra as programmatically available only after a real successful non-interactive Codex/OpenAI call.
- Discover exact OpenCode and APInex IDs live; do not guess IDs from display names.
- Do not create hackathon-specific phases or task prompts.
- Keep one orchestration layer and a finite bounded iteration loop.
- Pair receives no invented integration if no real API/CLI exists.
- All CLI commands emit JSON on stdout and diagnostics on stderr.

---

### Task 1: Create the safe configuration and provider transport boundaries

**Files:**
- Create: `orchestrator/__init__.py`
- Create: `orchestrator/config.py`
- Create: `orchestrator/transport.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config_transport.py`

**Interfaces:**
- `config.load_settings(workdir: Path) -> Settings` reads process environment first and `.env` second, accepting `APINEX_API_KEY`/`APINEX_BASE_URL` and the existing lowercase aliases. `Settings.secret(name) -> str | None` is never included in repr/JSON.
- `transport.request_json(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, dict]` performs one HTTP request with `urllib`, returns decoded JSON, and raises `ProviderError` with redacted diagnostics.
- `transport.redact(text: str, secrets: Iterable[str]) -> str` removes secret values from error strings.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
import tempfile
import unittest

from orchestrator.config import load_settings
from orchestrator.transport import redact


class ConfigTransportTests(unittest.TestCase):
    def test_process_environment_wins_over_dotenv_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "apinex_api_key=file-secret\napinex_base_url=https://file.example/v1\n",
                encoding="utf-8",
            )
            old = __import__("os").environ.get("APINEX_API_KEY")
            __import__("os").environ["APINEX_API_KEY"] = "process-secret"
            try:
                settings = load_settings(Path(directory))
                self.assertEqual(settings.apinex_api_key, "process-secret")
                self.assertNotIn("process-secret", repr(settings))
            finally:
                if old is None:
                    __import__("os").environ.pop("APINEX_API_KEY", None)
                else:
                    __import__("os").environ["APINEX_API_KEY"] = old

    def test_redact_removes_secret_from_provider_error(self):
        self.assertEqual(redact("token=abc body=abc", ["abc"]), "token=[REDACTED] body=[REDACTED]")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_config_transport -v`
Expected: FAIL because `orchestrator.config` and `orchestrator.transport` do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement a frozen `Settings` dataclass whose repr replaces the key with `[REDACTED]`, a two-source dotenv parser that ignores comments/blank lines and does not mutate `os.environ`, and a `ProviderError`. Use `urllib.request.Request` and `urlopen`; decode only JSON responses and redact the URL/body text with all non-empty secrets before raising.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_config_transport -v`
Expected: PASS with 2 tests and no secret value in output.

- [ ] **Step 5: Run a mutation check**

Temporarily change precedence so `.env` wins, run the focused test, and confirm it fails; restore the implementation and rerun the focused test to confirm it passes.

---

### Task 2: Add live discovery, registry persistence, and smoke-test adapters

**Files:**
- Create: `orchestrator/registry.py`
- Create: `orchestrator/providers.py`
- Create: `orchestrator/models.json`
- Create: `tests/test_registry_providers.py`

**Interfaces:**
- `registry.ModelRecord` has `model`, `provider`, `exact_id`, `role`, `transport`, `verified`, and optional `reason` fields; `save_registry(path, records)` writes deterministic JSON and rejects secret-looking values.
- `providers.discover_apinex(settings) -> list[ModelRecord]` calls `/models` and matches the requested display names against returned IDs/names, preserving the exact returned ID.
- `providers.discover_opencode(executable="opencode") -> list[ModelRecord]` calls the model inventory command and matches names from its real output; no guessed fallback IDs.
- `providers.check_codex(executable="codex") -> ModelRecord` runs a non-interactive `codex exec` smoke command with `gpt-6-astra` and `xhigh`; failure is a failed/manual-only record, not a fabricated HTTP adapter.
- `providers.check_pair() -> list[ModelRecord]` reports unavailable/UI-only when no real local API/CLI is found and creates no callable Pair client.
- `providers.smoke_record(record, settings, executables) -> ModelRecord` performs one simple provider-specific call and returns updated verification status.

- [ ] **Step 1: Write the failing tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.providers import discover_apinex
from orchestrator.registry import save_registry


class FakeSettings:
    apinex_api_key = "secret"
    apinex_base_url = "http://127.0.0.1:9/v1"


class RegistryProviderTests(unittest.TestCase):
    def test_apinex_keeps_exact_live_id_from_models_payload(self):
        # The test uses the provider's injected HTTP function; its hand-written payload
        # is deliberately different from any guessed display-name slug.
        payload = {"data": [
            {"id": "gemini-3.8-flash-live-2026", "name": "Gemini 3.8 Flash"},
            {"id": "gpt-5.6-luna-live", "name": "GPT-5.6 Luna"},
            {"id": "glm-5.3-flash-live", "name": "GLM-5.3 Flash"},
        ]}
        records = discover_apinex(FakeSettings(), request_json=lambda *args, **kwargs: (200, payload))
        self.assertEqual(
            {record.exact_id for record in records},
            {"gemini-3.8-flash-live-2026", "gpt-5.6-luna-live", "glm-5.3-flash-live"},
        )

    def test_registry_serialization_contains_no_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "models.json")
            save_registry(path, [{"model": "Gemini 3.8 Flash", "exact_id": "gemini-live", "reason": "ok"}])
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", raw)
            self.assertEqual(json.loads(raw)[0]["exact_id"], "gemini-live")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_registry_providers -v`
Expected: FAIL because the provider and registry functions do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement requested display-name mappings only for the three APInex targets, Astra, Muse, DeepSeek, GLM, Luna, and optional Grok roles. Match case-insensitive normalized `name`/`id`/provider text and return a failed record when a target is absent. Parse OpenCode’s actual `models` output as JSON when available and as lines/table data otherwise; retain the complete provider/model identifier used by `opencode run`. Persist `models.json` as an array with sorted keys and no credentials. For Pair, check `Get-Command`/`shutil.which` and return a UI-only reason if absent.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_registry_providers -v`
Expected: PASS with 2 tests.

- [ ] **Step 5: Run a mutation check**

Temporarily replace the exact APInex ID with a display-name slug in the adapter, run the focused tests, and confirm the exact-ID assertion fails; restore and rerun.

---

### Task 3: Implement the generic Gemini routing protocol and bounded specialist runner

**Files:**
- Create: `orchestrator/protocol.py`
- Create: `orchestrator/runner.py`
- Create: `tests/test_runner.py`

**Interfaces:**
- `protocol.parse_json_response(text: str) -> dict` accepts plain or fenced JSON and rejects non-object JSON.
- `protocol.validate_plan(plan: dict, registry: list[dict], max_subtasks: int = 8) -> list[dict]` validates unique IDs, non-empty bounded instructions, verified model references, role references, and dependency IDs.
- `runner.orchestrate(task: str, registry_path: Path, settings: Settings, clients: ClientBundle) -> dict` performs plan, grouped parallel dispatch, one Gemini iteration decision, optional one follow-up batch, and final Gemini result.
- `runner.ClientBundle` carries injected `gemini`, `specialists`, and optional clock/executor hooks so tests do not contact live providers.

- [ ] **Step 1: Write the failing tests**

```python
import unittest
from orchestrator.protocol import parse_json_response, validate_plan
from orchestrator.runner import dispatch_groups


class RunnerTests(unittest.TestCase):
    def test_validator_rejects_unverified_model_reference(self):
        with self.assertRaises(ValueError):
            validate_plan({"subtasks": [{
                "id": "one", "model": "missing", "role": "review",
                "instruction": "inspect the supplied input", "independent_group": "a",
                "depends_on": [],
            }]}, [{"exact_id": "verified", "verified": True}])

    def test_independent_group_dispatches_concurrently_and_collects_results(self):
        calls = []
        def specialist(subtask):
            calls.append(subtask["id"])
            return {"id": subtask["id"], "status": "ok"}
        result = dispatch_groups([
            {"id": "a", "independent_group": "parallel", "depends_on": []},
            {"id": "b", "independent_group": "parallel", "depends_on": []},
        ], specialist)
        self.assertEqual({item["id"] for item in result}, {"a", "b"})
        self.assertEqual(set(calls), {"a", "b"})

    def test_parser_accepts_fenced_json_without_executing_embedded_text(self):
        self.assertEqual(parse_json_response("```json\n{\"needs_iteration\": false}\n```"), {"needs_iteration": False})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_runner -v`
Expected: FAIL because protocol and runner modules do not exist.

- [ ] **Step 3: Write minimal implementation**

Define one generic system instruction containing only the specialist role mapping and JSON schemas. The user task is passed verbatim as data. Ask Gemini for a bounded plan, validate it, run each independent group via `ThreadPoolExecutor`, and preserve dependency order for later groups. Send capped specialist results to Gemini for an iteration decision. If `needs_iteration` is true, validate and run only the returned follow-up subtasks, then ask Gemini for a final structured result. Enforce maximum 8 subtasks per round, maximum 2 rounds, 20-second provider call timeout, and bounded output truncation. Do not add any task-specific phase or prompt text.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_runner -v`
Expected: PASS with 3 tests.

- [ ] **Step 5: Run a mutation check**

Temporarily remove the verified-model check, run the focused tests with an unverified reference, and confirm the test fails; restore and rerun.

---

### Task 4: Wire the CLI, real clients, and local test suite

**Files:**
- Create: `orchestrator/__main__.py`
- Modify: `orchestrator/providers.py`
- Modify: `orchestrator/runner.py`
- Create: `tests/test_cli.py`
- Create: `.env.example`
- Create: `.gitignore`

**Interfaces:**
- `python -m orchestrator discover` discovers all provider records and writes `orchestrator/models.json`.
- `python -m orchestrator smoke-test` loads/discovers the registry and smoke-tests every callable record.
- `python -m orchestrator run "task"` requires a verified APInex Gemini record and prints the structured orchestration result.

- [ ] **Step 1: Write the failing tests**

```python
import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_help_is_json_safe_and_does_not_print_environment_values(self):
        completed = subprocess.run([sys.executable, "-m", "orchestrator", "--help"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("discover", completed.stdout)
        self.assertNotIn("APINEX_API_KEY=", completed.stdout)

    def test_invalid_command_returns_nonzero_json_error(self):
        completed = subprocess.run([sys.executable, "-m", "orchestrator", "unknown"], capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["status"], "error")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cli -v`
Expected: FAIL because `orchestrator.__main__` does not exist.

- [ ] **Step 3: Write minimal implementation**

Use `argparse` with the three subcommands, JSON stdout, stderr diagnostics, and nonzero errors. Implement APInex chat-completions using the exact discovered ID and bearer key. Implement Codex smoke invocation with `codex exec --model gpt-6-astra -c model_reasoning_effort=xhigh --ask-for-approval never --sandbox read-only`; success requires exit code 0 and non-empty output. Implement OpenCode smoke invocation using the exact discovered `provider/model` ID and `opencode run --model ... --prompt ... --no-replay`. Each live response is reduced to status and a short redacted reason, never persisted.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -v`
Expected: PASS for all local tests.

- [ ] **Step 5: Run a mutation check**

Temporarily make the invalid command return exit code 0, run `python -m unittest tests.test_cli -v`, confirm failure, restore, and rerun the full suite.

---

### Task 5: Execute live discovery, smoke tests, Pair capability check, and orchestration dry-run

**Files:**
- Modify: `orchestrator/models.json`

**Interfaces:**
- No new public interface; this task uses the CLI from Task 4 and records only the resulting non-secret registry.

- [ ] **Step 1: Run live discovery**

Run: `python -m orchestrator discover`
Expected: JSON records for Astra, Muse, DeepSeek, Gemini, Luna, GLM, and Pair, with exact IDs only where the live provider returned them.

- [ ] **Step 2: Run live smoke tests**

Run: `python -m orchestrator smoke-test`
Expected: one status per programmatic target; Astra is verified only if non-interactive `codex exec` exits 0; Pair remains UI-only if no real API/CLI is available.

- [ ] **Step 3: Run one simple generic orchestration dry-run**

Run: `python -m orchestrator run "Return a one-sentence acknowledgement and identify which specialist roles would be useful."`
Expected: APInex Gemini produces a bounded routing plan, available specialists are called, and a structured result is returned without a phase prompt or secret value.

- [ ] **Step 4: Verify requirements from fresh evidence**

Run: `python -m unittest discover -v` and inspect `orchestrator/models.json` with a secret scan. Confirm each requested connection has a live status, exact ID where discoverable, and an honest blocker where unavailable. Do not claim a provider is connected based only on CLI presence or model display text.


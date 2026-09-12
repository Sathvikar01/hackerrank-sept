# Multi-Model Hackathon Environment Design

## Goal

Create a minimal, persistent command-line environment that verifies the requested model connections and lets Codex submit arbitrary future tasks to one Gemini-backed orchestration layer.

## Scope

The workspace starts empty except for a local `.env`. The implementation will add one small Python package and its tests. It will not add hackathon phases, phase names, task-specific prompts, a web server, a database, or a second orchestration service.

## Architecture

The `orchestrator` package exposes one CLI with three operational actions: `discover`, `smoke-test`, and `run`. Discovery resolves live model IDs and writes only non-secret model metadata. Smoke testing exercises each programmatic connection. `run` accepts the user’s arbitrary task, asks APInex Gemini to produce a bounded routing plan, dispatches the assigned specialists concurrently where the plan marks work independent, and asks Gemini to decide whether one follow-up round is warranted.

Gemini is the sole orchestration layer and is always called through APInex. It does not replace the specialists: specialist outputs are collected and returned as the evidence used for the final decision. The orchestrator enforces a finite subtask and iteration budget so a malformed or over-ambitious model response cannot create an unbounded loop.

## Provider boundaries

### Codex / OpenAI

Use the existing Codex authentication through the locally available Codex CLI. Verify `gpt-6-astra` with `xhigh` reasoning using a minimal smoke prompt. The adapter must not require or read an OpenAI API key.

### OpenCode Go

Use the locally available OpenCode Go CLI and its existing authentication. Discover the exact live IDs by querying the CLI’s model inventory, matching the displayed names for Muse Spark 1.3 Contributor and DeepSeek V4.1 Flash, then smoke-test each exact ID through the CLI. The discovered IDs are stored as metadata, never guessed or hardcoded from a display name.

### APInex / API Next

Use `APINEX_API_KEY` and `APINEX_BASE_URL` from the environment. For this workspace, the supplied base URL is `https://api.apinex.bond/v1`; the existing lowercase `.env` names may be accepted as a local compatibility fallback without printing their values. Query `<base>/models`, match the exact live IDs for Gemini 3.8 Flash, GPT-5.6 Luna, and GLM-5.3 Flash, and smoke-test each through the OpenAI-compatible chat-completions endpoint. Gemini calls in both smoke tests and orchestration must use APInex only.

### HackerRank Pair

Inspect the installed command-line surface and publicly documented Pair surface for a real API or CLI that exposes Grok 4.6 and GLM-5.3. If no authenticated programmatic surface exists, record Pair as UI-only/unavailable and do not create an adapter or fabricate model IDs. A UI-only result is a reported blocker, not a failed connection caused by the orchestrator.

## Persistent metadata

`orchestrator/models.json` is the generated, non-secret registry. Each verified entry records provider, exact model ID, display name when known, role, transport, and verification status. It must never contain API keys, bearer tokens, response bodies, or full environment values. Re-running discovery replaces only the registry entries it owns.

The committed `.env` remains user-owned. Add `.env.example` only with variable names and the supplied APInex base URL, and ensure `.gitignore` excludes `.env` and other secret-bearing local files if a git repository is later initialized.

## CLI contract

```text
python -m orchestrator discover
python -m orchestrator smoke-test
python -m orchestrator run "<arbitrary user task>"
```

All commands emit JSON to stdout for machine use and concise diagnostics to stderr. Secrets are redacted from diagnostics and error messages. `run` returns the original task, the Gemini routing plan, specialist results, any bounded follow-up results, and Gemini’s final orchestration decision. It does not silently execute a task itself when a specialist is unavailable; it returns a structured failure for that subtask and lets Gemini decide whether the remaining evidence is sufficient.

The generic Gemini orchestration instruction defines only the routing schema and the supplied specialist role mapping. It must not contain hackathon-specific phases, hidden task prompts, or domain assumptions. Gemini’s plan is validated before dispatch: every model must be in the verified registry, every subtask must have bounded text and a unique ID, and parallel groups may contain only explicitly independent subtasks.

## Specialist role mapping

| Exact model label | Provider/transport | Role |
|---|---|---|
| Astra XHigh | Codex / OpenAI authentication | Hardest reasoning, architecture, hypotheses, ablations |
| Muse Spark 1.3 Contributor | OpenCode Go | Repo/data/task reconnaissance |
| DeepSeek V4.1 Flash | OpenCode Go | Implementation, debugging, tests |
| GLM-5.3 | APInex, exact discovered GLM-5.3 Flash ID | Adversarial review |
| GPT-5.6 Luna | APInex | Independent evaluation |
| Grok 4.6 | HackerRank Pair if a real programmatic surface exists | Escalation when the current approach is stuck |

The display labels above are routing roles. The runtime uses exact IDs discovered from each provider and refuses to route to an unresolved or unverified entry.

## Data flow

```text
Codex task
   -> APInex Gemini: bounded routing plan
   -> validate plan against verified registry
   -> concurrent specialist calls for independent subtasks
   -> APInex Gemini: evidence + iteration decision
   -> optional one-round follow-up specialists
   -> APInex Gemini: final structured result
   -> Codex
```

The first Gemini response must be structured JSON. The orchestrator must tolerate a fenced JSON response but reject malformed or schema-invalid content. Specialist outputs are size-limited before they are sent back to Gemini. Provider calls use bounded timeouts and a small, explicit retry policy only for transient transport failures; authentication, model-not-found, and schema errors fail immediately.

## Testing and verification

Local tests use an in-process fake HTTP server and fake executable scripts to test request paths, exact model selection, registry safety, plan validation, concurrent dispatch, bounded follow-up behavior, and secret redaction without contacting live providers. The tests must be written and observed failing before production code is added.

Live verification runs after implementation:

1. Codex authentication smoke test for GPT-6 Astra.
2. OpenCode Go discovery and smoke tests for both requested models.
3. APInex `/v1/models` discovery and smoke tests for all three requested models.
4. Pair API/CLI capability check, with UI-only reported explicitly if applicable.
5. One simple `run` dry-run using APInex Gemini plus available specialists, with no hackathon-specific task prompt and no secret output.

The final report uses exactly the requested columns:

```text
MODEL | PROVIDER | EXACT ID | ROLE | VERIFIED/FAILED
```

After the table, report only blockers.

## Self-review

- No hackathon phase or hidden task prompt is introduced.
- Gemini is the only orchestration layer and uses APInex exclusively.
- OpenCode and APInex IDs are discovered live rather than guessed.
- Pair is not integrated unless an actual API/CLI is found.
- Secrets remain environment-only and are redacted from output and metadata.
- The orchestration loop is finite and testable.
- The CLI is reusable for arbitrary future user tasks.

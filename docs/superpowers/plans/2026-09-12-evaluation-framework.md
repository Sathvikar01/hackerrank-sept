# Evaluation Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen Buy-or-Wait evaluation specification as a deterministic, runnable Python evaluator without changing the decision policy or implementing the agent.

**Architecture:** A small standard-library Python package under `code/evaluation/` will load CSV fixtures, validate candidate rows, replay only evaluator-observable ledger facts for safety checks, calculate the frozen metric set, classify failures using the frozen taxonomy, and write deterministic JSON/Markdown artifacts. The CLI will support one candidate or named baseline/config candidates, explicit public-gold comparison, and usage metadata supplied by the runner or marked unavailable.

**Tech Stack:** Python 3 standard library, `unittest`, CSV/JSON/Markdown artifacts.

**Spec:** `Codex_evaluation_specification.md`

## Global Constraints

- Required output columns remain exactly `request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation`.
- Public `sample_requests.csv` labels are used only for explicit public-gold validation and never to alter evaluation-request results.
- Malformed candidate output is reported as invalid; it is never silently repaired.
- Safety/schema failures fail closed and hard safety/schema rates are reported explicitly.
- Results use canonical request order and stable JSON/Markdown ordering.
- No LLM calls, external financial data, live FX, Buy-or-Wait agent logic, extraction, orchestration, UI, or Docker changes.

---

### Task 1: Define evaluator data loading and schema validation

**Files:**
- Create: `code/evaluation/__init__.py`
- Create: `code/evaluation/schema.py`
- Test: `tests/test_evaluation_schema.py`

**Interfaces:**
- `load_csv(path: Path) -> list[dict[str, str]]`
- `validate_candidate(path: Path, requests: list[dict[str, str]]) -> ValidationResult`
- `parse_plan(value: str) -> list[PlanEntry]`
- `parse_changes(value: str) -> list[ChangeAction]`

- [x] **Step 1: Write failing tests** for exact columns/order, duplicate/missing/extra IDs, finite bounded amounts, dates/enums, plan grammar, and spending-change grammar.
- [x] **Step 2: Run `python -m unittest tests.test_evaluation_schema -v` and confirm the missing-module failure.**
- [x] **Step 3: Implement the loader and validator with explicit row errors and no repair.**
- [x] **Step 4: Run the focused tests and confirm they pass.**

### Task 2: Implement deterministic safety and eligibility checks

**Files:**
- Create: `code/evaluation/safety.py`
- Test: `tests/test_evaluation_safety.py`

**Interfaces:**
- `load_context(dataset_dir: Path) -> EvaluationContext`
- `evaluate_row_safety(row, context) -> SafetyResult`
- `validate_spending_changes(actions, request, context) -> ChangeValidation`

- [x] **Step 1: Write failing tests** for minimum-balance breaches, deadline breaches, exact supplied installment matching, partial-payment constraints, and flexible/protected spending targets.
- [x] **Step 2: Run the focused tests and verify failures are caused by missing evaluator behavior.**
- [x] **Step 3: Implement conservative, fail-closed checks from structured participant-facing data, including status/lifecycle exclusions and exact option matching; unresolved required FX or amount evidence produces an explicit safety failure.**
- [x] **Step 4: Run the focused tests and confirm they pass.**

### Task 3: Implement frozen metrics and failure classification

**Files:**
- Create: `code/evaluation/metrics.py`
- Create: `code/evaluation/failures.py`
- Test: `tests/test_evaluation_metrics.py`
- Test: `tests/test_evaluation_failures.py`

**Interfaces:**
- `calculate_metrics(candidate_rows, gold_rows, validation, safety) -> dict`
- `classify_failures(row_result) -> list[str]`

- [x] **Step 1: Write failing tests** for amount aggregates, accuracy/macro-F1, plan/change metrics, first-seven-field exactness, explanation consistency/groundedness, safety/schema rates, and taxonomy labels.
- [x] **Step 2: Run the focused tests and confirm the expected missing implementation failures.**
- [x] **Step 3: Implement exactly the metrics listed in specification section H and taxonomy labels listed in section G, representing unavailable gold/usage measurements as unavailable rather than invented values.**
- [x] **Step 4: Run the focused tests and confirm they pass.**

### Task 4: Implement deterministic aggregation and report generation

**Files:**
- Create: `code/evaluation/reports.py`
- Test: `tests/test_evaluation_reports.py`

**Interfaces:**
- `build_evaluation_result(...) -> dict`
- `write_artifacts(result, output_dir: Path, usage_template: Path) -> ArtifactPaths`

- [x] **Step 1: Write failing tests** for stable JSON output, human-readable Markdown output, usage-report placeholders, comparison tables, and reproducibility.
- [x] **Step 2: Run the focused tests and verify they fail before report implementation.**
- [x] **Step 3: Implement stable artifact generation for `results.json`, `report.md`, and the required `usage_report.md` structure, preserving unavailable values as `unavailable`.**
- [x] **Step 4: Run the focused tests and confirm they pass.**

### Task 5: Implement the executable CLI and approved-fixture run

**Files:**
- Modify: `code/evaluation/main.py`
- Modify: `code/evaluation/usage_report.md`
- Test: `tests/test_evaluation_cli.py`

**Interfaces:**
- `main(argv: list[str] | None = None) -> int`
- CLI flags: `--dataset-dir`, `--candidate`, repeated `--comparison name=path`, `--gold`, `--artifact-dir`, `--usage-metadata`, and `--strict`.

- [x] **Step 1: Write failing tests** for successful public-gold evaluation, malformed candidate nonzero exit, safety-failure nonzero exit in strict mode, comparison execution, and generated artifacts.
- [x] **Step 2: Run the focused tests and confirm the CLI is not yet implemented.**
- [x] **Step 3: Implement CLI orchestration with deterministic ordering and appropriate exit codes; default the candidate to root `output.csv` and allow explicit `dataset/sample_requests.csv` public-gold execution.**
- [x] **Step 4: Run the focused CLI tests and confirm they pass.**
- [x] **Step 5: Execute unit tests and run the evaluator on the approved public fixture, then inspect generated artifacts.**

### Task 6: Final verification

**Files:**
- Verify: all files above plus generated artifacts.

- [x] **Step 1: Run `python -m unittest discover -s tests -v`.**
- [x] **Step 2: Run the executable evaluator on `dataset/sample_requests.csv` with explicit public gold and a temporary artifact directory.**
- [x] **Step 3: Re-run the same command and compare JSON artifacts byte-for-byte.**
- [x] **Step 4: Check `git diff --check`, generated artifact contents, and that no unrelated files changed.**

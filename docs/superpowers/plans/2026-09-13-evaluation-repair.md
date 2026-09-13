# Evaluation framework repair plan

**Goal:** Repair the nine findings in `evaluation/framework_review/review.md` and verify their counterexamples.

**Architecture:** Keep the evaluator independent of the candidate engine. Extract the evaluator's conservative cash-flow construction into `code/evaluation/forecast.py`, retain row eligibility in `safety.py`, and aggregate every mandatory validation failure at the CLI gate. Unknown evidence and unavailable semantic metrics must be reported honestly.

**Tech stack:** Python standard library and the existing unittest/pytest suite.

**Spec:** `AGENTS.md`, `problem_statement.md`, `Codex_evaluation_specification.md`, and the review above. Execute inline in this existing checkout; preserve unrelated uncommitted work.

## Tasks

1. Add failing regression tests in `tests/test_evaluation_regressions.py` for missing plans, invalid options, unresolved debits, speculative credits, recurring essentials, duplicate salary, future messages, valid changes, semantic fields, metrics, report preservation, and strict CLI exit codes. Run `python -m unittest tests.test_evaluation_regressions -v` to establish the failures.
2. Implement `forecast.py` with `build_forecast(request, context, changes=())`: reconcile explicit lifecycle representations, admit settled credits and confirmed scheduled salary, reserve debits, infer supported recurrence without duplicating concrete occurrences, conservatively reserve variable essentials, and convert only exact dated FX. Never turn free-text imperatives into cash; unresolved relevant evidence is a validation failure.
3. Update `safety.py` to replay baseline and changed plans separately, verify safe-now capacity and earliest full-payment date, enforce every plan/eligibility constraint, and fail closed on unresolved required evidence. Declare forecast assumptions in reports rather than suggesting equivalence to hidden labels.
4. Correct `metrics.py`: align by request ID, compare candidate empty dates, compute option validity without gold, report groundedness/unsupported-claim detection as unavailable when not measured, and use an explicit zero-denominator policy for relative error.
5. Update `main.py`, `reports.py`, and `failures.py`: strict failure uses all mandatory issues; machine status distinguishes schema and semantic results; preserve existing usage reports and keep evaluator artifacts separate from final-run usage; retain deterministic output.
6. Run the regression and existing evaluation tests. Correct public self-comparison tests so they establish schema/comparison validity without equating identical labels with independently established financial safety. Add lifecycle, cancellation, FX, monthly recurrence, and evidence-boundary tests for newly implemented behavior.
7. Run the broader offline suite, rerun public/current-output checks into a dedicated artifact folder, document the new command and limitations in README, and append the required log entry. No prediction rewrite or live provider calls are needed to repair the evaluator.

## Acceptance examples

```python
assert not evaluate_row_safety(missing_payment, request, context).valid
assert not result['hard_targets']['hard_safety_target_met']
assert evaluate_row_safety(valid_changed_plan, request, context).valid
assert metrics['earliest_date']['correct_empty_date_rate'] == 0.0
assert final_usage_report.read_bytes() == before
```

Regression fixtures provide literal expected amounts, dates and balances rather than deriving expected values from the candidate engine. A positive fixture with complete evidence must pass; rejecting everything is not a fix.

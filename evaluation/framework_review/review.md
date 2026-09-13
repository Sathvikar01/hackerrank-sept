# Evaluation framework verification

Reviewed September 13, 2026, against the current working tree, `AGENTS.md`, `problem_statement.md`, and `Codex_evaluation_specification.md`.

**Verdict: not correctly implemented as a release gate.** The schema checks and basic reporting work, but strict mode accepts invalid plans, the cash-flow replay can approve unsafe payments or reject safe spending-change plans, and several reported metrics do not measure their advertised properties.

This was a verification review. Production code, dataset files, predictions, and existing usage reports were not modified. Review artifacts and the required session log were written. No live model or financial-data calls were made.

## Verified findings

### 1. [P1] Strict mode ignores recorded eligibility and unresolved-amount failures

Location: `code/evaluation/safety.py:416`, `code/evaluation/metrics.py:71`, `code/evaluation/main.py:247`.

`SafetyResult.valid` incorporates all issues, but `plan_safe` only considers minimum balance, deadline, and unresolved FX. The hard safety metric uses `plan_safe`; the CLI's `validation.valid` is only schema validation. Consequently, an absent full-payment plan, an installment schedule absent from the supplied options, and an unresolved future debit each produce issues while both hard targets remain satisfied. The actual CLI returned exit **0** and `status=valid` for an affordable-now full-payment candidate with `payment_plan=none`, even with `--strict`.

Expected: all mandatory eligibility, plan construction, spending-change and unresolved-required-evidence failures must prevent acceptance. Preserve the distinction between conservative rejection and a positive recommendation whose safety is unknown.

Probes: `missing_full_payment`, `unmatched_installments`, `unknown_debit`, `strict_cli_missing_payment`.

### 2. [P1] Scheduled speculative credits are counted as available cash

Location: `code/evaluation/safety.py:212`.

The replay excludes pending credits but adds every scheduled credit, without requiring confirmed salary or settlement for bonuses/refunds/etc. Starting at a balance equal to the protected minimum, a scheduled unapproved USD 1,000 bonus allowed a USD 50 wait recommendation to pass with no issues. The governing contract excludes speculative proceeds until settlement.

Expected: classify the credit's cash state and evidence before adding it to the forecast; a scheduled status alone does not establish confirmed salary.

Probe: `scheduled_unconfirmed_bonus`.

### 3. [P1] Essential variable spending is omitted from the safety forecast

Location: `code/evaluation/safety.py:250`.

Historical non-salary recurrence is limited to protected categories with a small list of fixed-expense words. Three weekly USD 30 grocery expenses, explicitly in the protected groceries category, produce no projected spending. With USD 100 current balance and USD 50 minimum, paying USD 50 now is accepted despite leaving nothing for that essential spending over the forecast.

Expected: conservatively forecast essential variable spending from supported history. The exact estimator may remain experimental; excluding the entire obligation is not a conservative check.

Probe: `essential_variable_spending_ignored`.

### 4. [P1] Concrete salary and forecast recurrence can be counted twice

Location: `code/evaluation/safety.py:270` through `289`, following concrete cash-flow insertion at line 215.

Recurring salary is appended without reconciling already scheduled/settled occurrences. Two historic fortnightly USD 100 salary payments plus a confirmed USD 100 salary scheduled for January 1 produce two credits for that date. A January 2 USD 150 payment then passes from a USD 50 balance with a USD 50 minimum, although the one actual salary supports only USD 100 of spending at that point.

Expected: a concrete occurrence should replace its forecast occurrence; reconciliation must not sum both representations.

Probe: `forecast_and_concrete_salary_double_counted`.

### 5. [P1] Message overlays promote unsupported or future text into salary

Location: `code/evaluation/safety.py:235` through `248`.

The overlay parser searches for salary keywords, a currency amount and a date. It does not validate `sent_at`, source, confirmation/cancellation semantics, or applicable request/event linkage. A message dated 2027 saying an **unapproved** salary proposal is USD 1,000 starting January 2026 increases a January 2026 salary forecast and makes an otherwise unaffordable payment pass.

Expected: apply evidence available at the request date, with explicit confirmation/amendment semantics and conflict precedence. Imperative text cannot provide that authority. The evaluator also loads image metadata but never consumes images or validated extracted evidence; required blank debit amounts therefore remain unresolved.

Probe: `future_unconfirmed_message_promoted_to_salary`. The experiment establishes unsupported factual promotion, not execution of the embedded imperative.

### 6. [P1] Valid spending changes are never applied to the balance replay

Location: `code/evaluation/safety.py:390` through `407`.

Changes are checked for eligibility, then the original unmodified cash flows are replayed. With USD 100 balance, USD 50 minimum, a scheduled USD 20 stoppable streaming subscription, and permission to stop streaming, the valid plan to stop that subscription and pay USD 50 is rejected for minimum-balance violation. The reported pre-change safe amount is correctly USD 30 in this probe.

Expected: calculate safe-now capacity on the baseline forecast and validate the selected plan on the forecast after applying permitted changes, with their effective dates and recurrence scope.

Probe: `valid_spending_change_not_applied`.

### 7. [P2] Safe-now and earliest-full-payment assertions are not verified

Location: `code/evaluation/safety.py:301` and `335` through `341`; date syntax only at `code/evaluation/schema.py:185`.

An otherwise valid affordable-now USD 50 full payment passes with `amount_safe_to_pay=0` and `earliest_date_for_full_payment=2027-01-01`, despite the request date being January 1, 2026. There is no requirement in that branch that the safe amount equal the requested amount or that the earliest date equal the request date. More generally, earliest-date optimality and safe capacity are not recomputed; even a universally negative candidate can pass without an eligibility search.

Expected: enforce direct status/field invariants and verify safe capacity and earliest full-payment date against a trustworthy baseline projection. Keep this independent from preferred payment method.

Probe: `false_safe_amount_and_earliest`.

### 8. [P2] Empty-date, groundedness and other metrics are misleading

Locations: `code/evaluation/metrics.py:70`, `75`, `86`, `94` through `108`; `code/evaluation/safety.py:37`.

- `correct_empty_date_rate` filters gold rows with empty dates and then checks those same gold rows for emptiness. It reports 1.0 even when every corresponding candidate date is nonempty. Compare candidate values at those IDs.
- Explanation groundedness only checks whether text is nonempty. An invented guaranteed USD 1,000,000 lottery win receives groundedness and consistency scores of 1.0. Evaluate claims against evidence or mark substantive groundedness unavailable; text presence is a separate metric.
- `unsupported_income_expense` is initialized to False and never assigned by the evaluator. Its reported zero violation rate is not evidence of detection coverage.
- Supplied-option match rate is calculated only after the no-gold early return, although it needs options rather than labels. It remains unavailable in ordinary evaluation runs. Its positional indexing also becomes incorrect if gold covers only a subset of candidates.
- Relative error is forced to zero when the expected safe amount is zero, even for a nonzero prediction. Use an explicit documented zero-denominator policy rather than implying perfect relative accuracy.

Probes: `wrong_empty_date`, `fabricated_explanation`, `unsupported_income_metric`; remaining points verified by tracing the metric code.

### 9. [P1] Running evaluation can overwrite the required final-run usage report

Location: `code/evaluation/reports.py:96`; defaults at `code/evaluation/main.py:216` and `code/evaluation/dataset_run.py:71`.

The dataset runner and evaluator both default to `evaluation/usage_report.md`. The evaluator unconditionally replaces that file with its own report, including all-`unavailable` content when no usage metadata is supplied. A normal evaluation after a measured dataset run therefore destroys the report required for submission. The temporary-file probe reproduced this replacement. The root report currently contains unavailable values, while `code/evaluation/usage_report.md` contains a separate cache-run account; that observation alone does not establish how the root report was overwritten.

Expected: preserve the final run's measured usage, or generate evaluator artifacts in a distinct directory. Adapt runner metadata explicitly if importing it: the runner's nested `usage`/`cost` structure differs from the evaluator's expected `providers` format.

Probe: `usage_report_overwrite`.

## Verification and limits

- Ran all six existing evaluation test modules: **17 passed**, with one unrelated dependency deprecation warning.
- Ran the public fixture against itself: 25 rows, structured exact accuracy 1.0, and both hard targets reported as met. Three rows nevertheless recorded unresolved evidence issues. This checks ingestion and comparison with identical data; it does not establish that the decision engine reproduces the public answers.
- Evaluated current root `output.csv`: 250 rows, schema passes, hard safety target reported as met, and 26 rows contain recorded issues. Some issues are on negative recommendations and are not themselves proof of unsafe output. The independent positive counterexamples above demonstrate why the reported pass is insufficient.
- Ran an actual strict CLI counterexample: missing payment was accepted with exit 0.
- Ran isolated probes for the other findings, including a valid spending-change plan incorrectly rejected.
- Existing evaluation tests have only three direct safety tests and two metric tests. They do not establish the specified lifecycle, amendment, image, injection, leakage-removal, ranking, or complete forecast behavior. Testing elsewhere in the finance/interpretation packages does not establish equivalent coverage for this separate evaluator implementation.
- No hidden ground truth was available or used. This review does not claim the current 250 predictions are financially correct, and does not assess live provider quality.

Reproduce the observations from the repository root:

```text
python evaluation/framework_review/probes.py
python -m pytest tests/test_evaluation_cli.py tests/test_evaluation_failures.py tests/test_evaluation_metrics.py tests/test_evaluation_reports.py tests/test_evaluation_safety.py tests/test_evaluation_schema.py -q
```

The probe script writes only temporary CLI fixtures, prints diagnostic JSON, and does not call model providers. `observations.json` preserves the results observed during this review. Exit zero from the probe script means the diagnostic script ran; its JSON contains the expected/actual mismatches.

Repair order: correct the acceptance gate first, then fix and independently test cash-state/evidence reconciliation and forecasting, apply spending changes to the plan replay, verify safe-amount/date semantics, correct the metrics, and protect final-run usage provenance. Add regression tests for the counterexamples before relying on the gate.

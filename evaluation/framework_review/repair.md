# Evaluation framework repair

The acceptance gate, financial replay, metrics, and report handling identified in
`review.md` have been repaired. The original review and observations are retained
as the record of behavior before the repair.

## Changes

- Strict acceptance now requires every mandatory row check to pass. Machine output
  reports semantic validity separately from schema validity. Missing plans, unknown
  debit amounts, invalid options, protected changes and inconsistent fields fail.
- An independent evaluator forecast excludes speculative scheduled credits, reserves
  essential spending, reconciles supported recurrence against concrete occurrences,
  handles explicit duplicates/replacements/transfers, and preserves calendar month ends.
- Future evidence cannot affect current decisions. Free-text salary regex overlays
  were removed. Relevant evidence that needs interpretation is explicitly unresolved.
- Safe-now capacity is checked before changes; eligible changes are applied to the
  recommended plan. Earliest full-payment dates are checked against the baseline.
  Negative recommendations are checked for a safe eligible completion witness.
- Empty-date accuracy uses candidate values. Option matching works without gold
  and with partial gold. Equivalent decimal action amounts compare numerically.
  Zero-gold relative errors are excluded with coverage reported. Unmeasured
  substantive explanation/unsupported-claim metrics are marked unavailable.
- Evaluator usage goes to `evaluator_usage_report.md`; existing final-run reports
  are preserved. The runner's measured JSON can be imported via `--usage-metadata`.

## Current output validation

The fresh strict run over the existing 250-row `output.csv` passes schema validation
but fails mandatory validation for **235 rows**. Issue counts overlap:

| Issue | Count |
|---|---:|
| Unresolved message/image evidence | 209 |
| Projected minimum-balance failure | 103 |
| Safe-now amount mismatch | 35 |
| Earliest full-payment date mismatch | 24 |
| Unresolved cash amount | 11 |

The public fixture self-comparison retains structured exact accuracy of 1.0 but
does not pass the independent safety gate. The evaluator does not perform OCR or
general natural-language interpretation. Its explicit conservative forecast
assumptions can also differ from the public labels. These results do **not** prove
that 235 predictions are wrong; they mean this offline evaluator cannot establish
acceptance for those rows under its stated policy.

See `after/current/results.json` and `after/current/report.md` for per-request
details, and `after/public/` for the separate public comparison. Existing output
and both pre-existing usage reports were checked by SHA-256 and remain unchanged.

## Verification

Final offline test run: **205 passed** (including **50 evaluation tests**), with
one pre-existing LangChain deprecation warning. Live model tests were excluded.

New tests cover the review counterexamples and additional lifecycle, FX,
month-boundary, capacity-replay, valid partial-payment, and exact-installment cases.
The original public CLI test was corrected: comparing labels to themselves is no
longer treated as proof of independent financial safety. Its schema and exact-match
assertions remain, while strict rejection of unresolved evidence is now required.

No live provider calls or prediction regeneration were needed for this repair.

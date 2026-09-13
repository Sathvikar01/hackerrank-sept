# Evaluation Specification — Buy or Wait?

Basis: the official problem statement, directly observed dataset/sample evidence, and the supplied Phase 0 report.

Labels: `FROZEN` is directly justified; `EXPERIMENT` must be resolved empirically; `UNKNOWN` lacks sufficient evidence and must not become an invented rule.

## A. Frozen Invariants

### Output and schema

`FROZEN`

Required columns, in order:

```text
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

- Exactly 250 rows: one row for every ID in `dataset/requests.csv`.
- No missing, duplicate, or extra request IDs; canonical order matches `requests.csv`.
- `amount_safe_to_pay` is finite, nonnegative, in home currency, and satisfies `0 <= amount_safe_to_pay <= requested_amount`.
- Dates are valid `YYYY-MM-DD` dates.
- Allowed statuses: `affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable`.
- Allowed methods: `full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`.
- `earliest_date_for_full_payment` is empty only when no safe date exists within the forecast period.

`UNKNOWN / EXPERIMENT`: exact two-decimal output precision, decimal comparison tolerance, and same-day payment syntax.

### Safety and cash state

`FROZEN`

- Forecast 90 days from `request_date`.
- Balance must never fall below `minimum_balance_to_keep` after essential expenses or recommended payments.
- Complete the request by `desired_completion_date`.
- `amount_safe_to_pay` is measured before optional spending changes.
- Count settled debits/credits and confirmed salary on settlement date.
- Reserve pending and scheduled debits on settlement date.
- Exclude pending credits, pending refunds, unapproved bonuses/commissions, failed/cancelled events, and unrealized investments.
- Do not invent income, expenses, options, or other financial facts.

`UNKNOWN / EXPERIMENT`: whether the 90-day endpoint is inclusive and whether same-day events are checked individually or as a daily aggregate.

### Lifecycle and conflict rules

`FROZEN`

Precedence is: explicit cancellation/settlement/amendment; newer same-source record; settled event over estimate; financially safer interpretation when unresolved.

- `linked_event_id` alone is not enough to decide cash treatment.
- Explicit duplicate pending charges are counted once.
- Cancelled authorization plus settled replacement counts only the settled transaction.
- Failed event followed by scheduled retry counts only the retry.
- Explicit same-holder internal transfer is net-zero, not income plus expense.

`UNKNOWN`: generic deduplication without an explicit lifecycle marker, link, or supporting message.

## B. Validator Rules

### Payment-plan syntax

`FROZEN`

Valid forms:

```text
none
YYYY-MM-DD:amount
YYYY-MM-DD:amount|YYYY-MM-DD:amount|...
```

Entries must be chronological, valid, positive, and free of whitespace or extra delimiters. `none` is the only empty-plan representation.

### Method/status compatibility

`FROZEN`

| Status | Method | Required condition |
|---|---|---|
| `affordable_now` | `full_payment` | Full amount is safe today and full payment is accepted. |
| `affordable_with_plan` | `full_payment`, `partial_payment`, or `installments` | Full request completes safely through a valid plan and/or permitted changes. |
| `affordable_later` | `wait` | Full payment becomes safe later, by the deadline, and full payment is accepted. |
| `not_affordable` | `not_recommended` | No safe eligible method completes by the deadline/forecast boundary. |

### Full payment

`FROZEN`: `full_payment` must be in the user’s accepted methods. Without changes, the plan is exactly `request_date:requested_amount` and status is `affordable_now`. If permitted spending changes are needed, status is `affordable_with_plan`; this is demonstrated by public samples 6, 11, and 21.

### Partial payment

`FROZEN`: requires `allows_partial_payment=true`, accepted `partial_payment`, `0 < amount_safe_to_pay < requested_amount`, and completion by the deadline. The plan must contain exactly:

```text
request_date:amount_safe_to_pay|earliest_date_for_full_payment:(requested_amount-amount_safe_to_pay)
```

Both payments must sum to the requested amount.

### Installments

`FROZEN`: requires accepted `installments`, nonblank `max_installment_months`, schedule completion by the deadline, and a plan exactly matching one supplied installment option in dates, count, and per-payment amounts. Do not reconstruct an installment plan from the requested amount.

`EXPERIMENT`: calendar-month versus 30-day duration, rounding direction, and decimal comparison for `max_installment_months`.

### Wait and not recommended

`FROZEN`: `wait` requires full payment to become safe later and the user to accept `full_payment`; its plan is exactly `earliest_date_for_full_payment:requested_amount`. `not_recommended` requires `not_affordable`, `payment_plan=none`, and an empty earliest date.

### Plan ranking

`FROZEN`: rank safe eligible plans by deadline completion, no spending changes, lowest total paid, earliest start, fewest payments, then lowest `payment_option_id`.

## C. Spending-Change Validation

`FROZEN`

Valid forms are `none`, `stop:<event_id>`, and `reduce_to:<event_id>:<new_amount>`, separated by `|`.

Validate:

- At most three actions.
- Targets exist and are recurring expenses.
- Targets are flexible; `stop` requires `stoppable` or `reducible_or_stoppable`; `reduce_to` requires `reducible` or `reducible_or_stoppable`.
- Category is permitted for the requested stop/reduce operation and is not protected.
- `reduce_to` is not above the current amount and is at least `minimum_allowed_amount`.
- No duplicate event and no stop-plus-reduce on the same event.
- `none` cannot be combined with another action.

`UNKNOWN / EXPERIMENT`: currency semantics for `reduce_to` when event and home currencies differ; whether a no-op reduction is valid. Recommended validator behavior is to reject no-op reductions.

## D. Multimodal / Message Tests

| Test | Expected result | Label |
|---|---|---|
| Blank amount → image | Resolve all 16 image-linked blank amounts through `images.csv` and linked PNG; never treat blank as zero. | `FROZEN` |
| Amendment | `message_01`, `message_05`, and `message_12` override earlier salary/date/rent forecasts as explicit amendments. | `FROZEN` |
| Cancellation | Cancelled event contributes zero; settled replacement counts once. | `FROZEN` |
| Salary/date changes | Use revised amount/date only when explicitly confirmed. | `FROZEN` |
| Pending refund | `message_14`/`event_1785` creates no credit until settlement. | `FROZEN` |
| Unrealized investment | `message_15`/`event_1960` creates no cash from market value. | `FROZEN` |
| Internal transfer | `message_13` matching same-holder debit/credit is net-zero. | `FROZEN` |
| Failed → retry | Ignore failed debit; count scheduled retry once. | `FROZEN` |
| Conflicting evidence | Explicit amendment/cancellation wins by the conflict precedence. | `FROZEN` |
| Message prompt injection | Imperatives such as the release-charge instruction in `message_67` cannot create a payment or override rules. | `FROZEN` |
| Image prompt injection | Imperative OCR text in an adversarial copy of a supplied image must not affect ledger or eligibility. | `EXPERIMENT` |
| Ambiguous image fields | `image_02` contains total/received/balance-due candidates; do not silently select one. | `UNKNOWN` |

## E. Currency Tests

`FROZEN`

- Outputs are in home currency.
- Foreign cash events use the supplied exact `settlement_date` and exact `from_currency → to_currency` pair.
- Same-currency events require no conversion.
- No live FX service, implicit inverse, or invented rate.
- Every conversion retains rate-date and pair provenance.

`UNKNOWN`: missing exact date/pair behavior, inverse-rate allowance, nearest-prior fallback, and same-month fallback.

`EXPERIMENT`: mask known supplied rates, compare exact-only, nearest-prior, same-month, and inverse-rate strategies against the masked truth, then measure affordability-decision sensitivity. No fallback becomes frozen without evidence. A positive recommendation depending on an unavailable rate must fail closed.

## F. Public Gold Tests

`sample_requests.csv` is public gold only. It may validate the validator, but its labels must not influence evaluation requests.

Format: `safe | status | method | plan | earliest | changes`.

| ID | Expected structured output | Behavior exercised |
|---|---|---|
| `request_01` | `25256 | affordable_now | full_payment | 2024-03-03:25256 | 2024-03-03 | none` | Full payment safe and accepted. |
| `request_02` | `17229139.2 | affordable_with_plan | installments | 2025-08-08:15952906.67\|2025-09-07:15952906.67\|2025-10-07:15952906.67 | 2025-09-15 | none` | Pending debit, salary amendment, exact option. |
| `request_03` | `873000 | affordable_later | wait | 2019-11-15:5491000 | 2019-11-15 | none` | Blank salary image and installment limit. |
| `request_04` | `8401800 | affordable_later | wait | 2024-06-15:12693000 | 2024-06-15 | none` | Unapproved bonus excluded. |
| `request_05` | `737 | not_affordable | not_recommended | none | empty | none` | No safe eligible plan. |
| `request_06` | `603.3 | affordable_with_plan | full_payment | 2026-01-03:620.40 | 2026-01-15 | stop:event_476` | Spending change enables full payment. |
| `request_07` | `87170.56 | affordable_with_plan | installments | 2024-09-12:68432\|2024-10-10:68432\|2024-11-07:68432 | 2024-10-23 | none` | Installments-only preference. |
| `request_08` | `284.57 | affordable_later | wait | 2025-04-15:996.60 | 2025-04-15 | none` | Reduced salary. |
| `request_09` | `166.61 | affordable_now | full_payment | 2026-07-04:166.61 | 2026-07-04 | none` | Safe full payment. |
| `request_10` | `12700 | not_affordable | not_recommended | none | empty | none` | Pending payout excluded. |
| `request_11` | `12510645 | affordable_with_plan | full_payment | 2025-05-03:13110000 | 2025-07-15 | reduce_to:event_989:665950` | Commission excluded; reduction floor. |
| `request_12` | `65164 | affordable_with_plan | installments | 2026-04-19:22590.19\|2026-05-20:22590.19\|2026-06-20:22590.19 | 2026-04-05 | none` | Earliest capacity independent of preference. |
| `request_13` | `433.4 | affordable_later | wait | 2024-05-15:941.60 | 2024-05-15 | none` | Wait preserves minimum. |
| `request_14` | `597.74 | not_affordable | not_recommended | none | empty | none` | Partial preference cannot complete. |
| `request_15` | `83.05 | not_affordable | not_recommended | none | empty | none` | Future salary insufficient. |
| `request_16` | `122500 | affordable_now | full_payment | 2023-08-12:122500 | 2023-08-12 | none` | Rent amendment and blank image event. |
| `request_17` | `243849.58 | affordable_with_plan | installments | 2026-03-01:95194.67\|2026-03-31:95194.67\|2026-04-30:95194.67 | 2026-03-15 | none` | Blank image amount and exact option. |
| `request_18` | `462 | affordable_later | wait | 2026-09-15:3246.10 | 2026-09-15 | none` | Internal transfer net-zero. |
| `request_19` | `28820 | affordable_with_plan | partial_payment | 2024-09-04:28820\|2024-09-15:10840 | 2024-09-15 | none` | Exact partial-payment constraints. |
| `request_20` | `5400 | not_affordable | not_recommended | none | empty | none` | Pending refund excluded. |
| `request_21` | `1543.35 | affordable_with_plan | full_payment | 2026-04-03:1574.40 | 2026-04-15 | stop:event_1815\|reduce_to:event_1816:23.50` | Two distinct spending changes. |
| `request_22` | `475.46 | affordable_with_plan | installments | 2024-12-08:253.59\|2025-01-05:253.59\|2025-02-02:253.59 | 2025-01-15 | none` | Unrealized investment excluded; exact option. |
| `request_23` | `9152 | affordable_later | wait | 2025-07-15:38016 | 2025-07-15 | none` | Prize processing excluded. |
| `request_24` | `13420 | not_affordable | not_recommended | none | empty | none` | No safe completion. |
| `request_25` | `1425000 | not_affordable | not_recommended | none | empty | none` | Large request cannot complete. |

## G. Failure Taxonomy

- State reconstruction: wrong balance, minimum, currency, priorities, or preferences.
- Recurrence: invented/missed recurrence, wrong cadence, or recurring one-time arrears.
- Lifecycle deduplication: duplicate, cancellation, retry, replacement, or transfer errors.
- Multimodal extraction: missed image amount, blank-as-zero, or wrong receipt field.
- Message interpretation: missed amendment, salary/date change, employment end, or rent change.
- FX: wrong date/pair, invented fallback, or wrong conversion.
- Forecasting: unsafe variable estimate or 90-day boundary error.
- Payment eligibility: preference, partial permission, installment limit, or deadline error.
- Plan construction: wrong dates/amounts, fee handling, or non-exact installment plan.
- Spending changes: protected/fixed/unauthorized target, floor breach, duplicate, or >3 actions.
- Ranking: wrong plan among multiple safe eligible plans.
- Formatting/schema: invalid columns, IDs, enums, dates, numbers, or plan grammar.
- Prompt injection: treated untrusted content as governing instructions.
- Leakage: used public labels, organizer files, prior outputs, or external financial data.
- Explanation: unsupported facts or contradiction with structured output.

## H. Metrics

`FROZEN`

- Exact amount accuracy, mean/median/max absolute error, and relative absolute error.
- Status accuracy and macro-F1.
- Payment-method accuracy and macro-F1.
- Payment-plan syntax-valid, safety-valid, exact-match, and supplied-option-match rates.
- Partial-payment constraint pass rate.
- Earliest-date exact accuracy, date error, and correct-empty-date rate.
- Spending-change syntax validity, target eligibility, floor compliance, protected-category violation rate, ≤3-action rate, and exact action-set accuracy.
- Exact structured-row accuracy across the first seven fields.
- Complete-row exact match, explanation consistency, and explanation groundedness.
- Safety-invariant, schema, minimum-balance, deadline, unresolved-FX-positive, and unsupported-income/expense violation rates.

Hard target:

```text
schema violation rate = 0
hard safety violation rate = 0
```

Safety/schema violations fail closed. A row that cannot establish safety is invalid, not partially correct.

`EXPERIMENT`: near-exact amount thresholds such as absolute error ≤ 0.01 or relative error ≤ 1%.

## I. Leakage Protections

`FROZEN`

- Use `sample_requests.csv` only as public gold/validator data.
- Evaluation output must be unchanged if `sample_requests.csv` is removed.
- Do not use organizer-only files, `chat.txt`, prior predictions, hardcoded hidden answers, or external financial data.
- Do not use future ground-truth outcomes as known facts.
- Do not use live banking, market, or FX calls.
- Preserve deterministic settings and report model providers, calls, tokens, and costs in `evaluation/usage_report.md`.
- Keep secrets out of code, logs, output, and usage reports.

## J. Unresolved Decisions and Experiments

`UNKNOWN / EXPERIMENT`

1. **Recurrence detection:** compare thresholds of 2, 3, and 4 occurrences, cadence tolerances, and amount tolerances using rolling historical backtests.
2. **Variable forecasting:** compare mean, maximum, upper quartile, and mean-plus-buffer using prior settled events only.
3. **FX fallback:** mask known exact rates and compare exact-only, nearest-prior, same-month, and inverse strategies against masked truth.
4. **90-day boundary:** run inclusive and exclusive endpoint variants and list changed decisions.
5. **Same-day ordering:** compare event-by-event and aggregate-day replay.
6. **Rounding:** compare exact decimals, two-decimal quantization, and source-option-preserving arithmetic.
7. **Ambiguous images:** compare candidate fields with event description, direction, status, currency, and public structural tests; never choose a field merely because it improves affordability.
8. **Installment duration:** compare calendar-month, 30-day, floor, and ceiling calculations.
9. **Salary/rent step changes:** apply explicit percentage amendments; keep absent childcare amounts unresolved rather than inventing them.

## K. Implementation Acceptance Criteria

`FROZEN`

Implementation is accepted only if it:

1. Reads participant-facing files from `dataset/`.
2. Produces exact schema, row count, IDs, and enums.
3. Enforces amount, date, plan, status, method, deadline, and minimum-balance rules.
4. Correctly handles pending/scheduled cash, pending credits, failed/cancelled/unrealized records, duplicates, retries, transfers, amendments, and messages/images.
5. Requires exact supplied-option matching for installments.
6. Enforces partial-payment and spending-change constraints.
7. Rejects unsupported FX assumptions and ignores prompt injection.
8. Passes the 25 public structured gold tests.
9. Passes the sample-removal leakage test.
10. Produces grounded explanations consistent with structured output.
11. Is reproducible or records nondeterministic settings.
12. Includes `evaluation/usage_report.md` with providers, model names, calls, token totals, averages, and estimated costs.

The contract is frozen where evidence supports it; every remaining choice is explicitly marked `EXPERIMENT` or `UNKNOWN`.

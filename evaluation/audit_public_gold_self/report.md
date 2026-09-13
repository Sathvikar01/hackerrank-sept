# Evaluation report

Candidate: `sample_requests.csv`

## Hard targets

| Check | Value |
|---|---:|
| `hard_safety_target_met` | `False` |
| `hard_safety_violation_rate` | `1.0` |
| `schema_target_met` | `True` |
| `schema_violation_rate` | `0.0` |

## Evaluation policy

- Independent conservative projection: 90 days inclusive; same-day essential debits before credits, candidate payments after recorded daily cash flows.
- At least two historical occurrences with stable 7-45 day cadence; monthly series use calendar dates. Concrete occurrences replace forecasts.
- Essential variable spending uses the maximum historical 30-day total over the preceding 90 days, reserved at the start of each forecast month.
- Safe-now capacity is floored to two decimal places; monetary plan comparisons use exact decimals. Installment duration uses elapsed days divided by 30.
- Relevant unparsed messages/images prevent verified acceptance. No regex text is promoted into income; no model or OCR calls are made.
- Groundedness, substantive explanation consistency and unsupported-claim detection are unavailable. Relative error excludes zero-gold rows and reports coverage.
- Forecast assumptions are explicit evaluator policy, not a claim of equivalence to hidden ground truth. Public label self-comparison only verifies comparison mechanics.

## Metrics

| Metric | Value |
|---|---:|
| `amount.exact_accuracy` | `1.0` |
| `amount.max_absolute_error` | `0.0` |
| `amount.mean_absolute_error` | `0.0` |
| `amount.mean_relative_absolute_error` | `0.0` |
| `amount.median_absolute_error` | `0.0` |
| `amount.relative_error_coverage` | `1.0` |
| `complete_row.exact_match_rate` | `1.0` |
| `complete_row.explanation_consistency_rate` | `unavailable` |
| `complete_row.explanation_groundedness_rate` | `unavailable` |
| `complete_row.explanation_present_rate` | `1.0` |
| `earliest_date.correct_empty_date_rate` | `1.0` |
| `earliest_date.exact_accuracy` | `1.0` |
| `earliest_date.mean_absolute_date_error_days` | `0.0` |
| `partial_payment.constraint_pass_rate` | `1.0` |
| `payment_method.accuracy` | `1.0` |
| `payment_method.macro_f1` | `1.0` |
| `payment_plan.exact_match_rate` | `1.0` |
| `payment_plan.safety_valid_rate` | `0.0` |
| `payment_plan.supplied_option_match_rate` | `1.0` |
| `payment_plan.syntax_valid_rate` | `1.0` |
| `safety.deadline_violation_rate` | `0.0` |
| `safety.minimum_balance_violation_rate` | `0.68` |
| `safety.safety_invariant_violation_rate` | `1.0` |
| `safety.schema_violation_rate` | `0.0` |
| `safety.unresolved_fx_positive_violation_rate` | `0.0` |
| `safety.unsupported_income_expense_violation_rate` | `unavailable` |
| `spending_changes.at_most_three_actions_rate` | `1.0` |
| `spending_changes.exact_action_set_accuracy` | `1.0` |
| `spending_changes.floor_compliance_rate` | `1.0` |
| `spending_changes.protected_category_violation_rate` | `0.0` |
| `spending_changes.syntax_validity_rate` | `1.0` |
| `spending_changes.target_eligibility_rate` | `1.0` |
| `status.accuracy` | `1.0` |
| `status.macro_f1` | `1.0` |
| `structured.first_seven_field_exact_accuracy` | `1.0` |

## Failure taxonomy

| Request | Categories |
|---|---|
| `request_01` | State reconstruction, Forecasting |
| `request_02` | Message interpretation, Forecasting |
| `request_03` | Message interpretation, Forecasting |
| `request_04` | Message interpretation, Forecasting |
| `request_05` | State reconstruction, Payment eligibility |
| `request_06` | Message interpretation, Forecasting |
| `request_07` | Message interpretation, Forecasting |
| `request_08` | Message interpretation, Forecasting |
| `request_09` | State reconstruction, Forecasting |
| `request_10` | Message interpretation |
| `request_11` | Message interpretation, Forecasting |
| `request_12` | Message interpretation |
| `request_13` | State reconstruction, Forecasting |
| `request_14` | Message interpretation |
| `request_15` | Message interpretation |
| `request_16` | Forecasting, Message interpretation |
| `request_17` | Forecasting, Message interpretation |
| `request_18` | Message interpretation, Forecasting |
| `request_19` | Forecasting, Message interpretation |
| `request_20` | Forecasting, Message interpretation |
| `request_21` | State reconstruction, Forecasting |
| `request_22` | Message interpretation, Forecasting |
| `request_23` | Message interpretation, Forecasting |
| `request_24` | Message interpretation |
| `request_25` | State reconstruction |

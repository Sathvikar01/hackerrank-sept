# Evaluation report

Candidate: `output.csv`

## Metrics

| Metric | Value |
|---|---:|
| `amount.exact_accuracy` | `unavailable` |
| `amount.max_absolute_error` | `unavailable` |
| `amount.mean_absolute_error` | `unavailable` |
| `amount.mean_relative_absolute_error` | `unavailable` |
| `amount.median_absolute_error` | `unavailable` |
| `complete_row.exact_match_rate` | `unavailable` |
| `complete_row.explanation_consistency_rate` | `0.228` |
| `complete_row.explanation_groundedness_rate` | `1.0` |
| `earliest_date.correct_empty_date_rate` | `unavailable` |
| `earliest_date.exact_accuracy` | `unavailable` |
| `earliest_date.mean_absolute_date_error_days` | `unavailable` |
| `partial_payment.constraint_pass_rate` | `1.0` |
| `payment_method.accuracy` | `unavailable` |
| `payment_method.macro_f1` | `unavailable` |
| `payment_plan.exact_match_rate` | `unavailable` |
| `payment_plan.safety_valid_rate` | `1.0` |
| `payment_plan.supplied_option_match_rate` | `unavailable` |
| `payment_plan.syntax_valid_rate` | `1.0` |
| `safety.deadline_violation_rate` | `0.0` |
| `safety.minimum_balance_violation_rate` | `0.0` |
| `safety.safety_invariant_violation_rate` | `0.0` |
| `safety.schema_violation_rate` | `0.0` |
| `safety.unresolved_fx_positive_violation_rate` | `0.1` |
| `safety.unsupported_income_expense_violation_rate` | `0.0` |
| `spending_changes.at_most_three_actions_rate` | `1.0` |
| `spending_changes.exact_action_set_accuracy` | `unavailable` |
| `spending_changes.floor_compliance_rate` | `1.0` |
| `spending_changes.protected_category_violation_rate` | `0.0` |
| `spending_changes.syntax_validity_rate` | `1.0` |
| `spending_changes.target_eligibility_rate` | `1.0` |
| `status.accuracy` | `unavailable` |
| `status.macro_f1` | `unavailable` |
| `structured.first_seven_field_exact_accuracy` | `unavailable` |

## Failure taxonomy

| Request | Categories |
|---|---|
| `request_109` | FX |
| `request_113` | FX |
| `request_125` | FX |
| `request_153` | FX |
| `request_169` | FX |
| `request_173` | FX |
| `request_183` | FX |
| `request_184` | FX |
| `request_214` | FX |
| `request_235` | FX |
| `request_245` | FX |
| `request_257` | FX |
| `request_260` | FX |
| `request_263` | FX |
| `request_267` | FX |
| `request_274` | FX |
| `request_39` | FX |
| `request_41` | FX |
| `request_48` | FX |
| `request_63` | FX |
| `request_64` | Forecasting, FX |
| `request_71` | FX |
| `request_73` | Forecasting |
| `request_79` | FX |
| `request_84` | FX |
| `request_98` | FX |

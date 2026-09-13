# Evaluation report

Candidate: `sample_requests.csv`

## Metrics

| Metric | Value |
|---|---:|
| `amount.exact_accuracy` | `1.0` |
| `amount.max_absolute_error` | `0.0` |
| `amount.mean_absolute_error` | `0.0` |
| `amount.mean_relative_absolute_error` | `0.0` |
| `amount.median_absolute_error` | `0.0` |
| `complete_row.exact_match_rate` | `1.0` |
| `complete_row.explanation_consistency_rate` | `1.0` |
| `complete_row.explanation_groundedness_rate` | `1.0` |
| `earliest_date.correct_empty_date_rate` | `1.0` |
| `earliest_date.exact_accuracy` | `1.0` |
| `earliest_date.mean_absolute_date_error_days` | `0.0` |
| `partial_payment.constraint_pass_rate` | `1.0` |
| `payment_method.accuracy` | `1.0` |
| `payment_method.macro_f1` | `1.0` |
| `payment_plan.exact_match_rate` | `1.0` |
| `payment_plan.safety_valid_rate` | `1.0` |
| `payment_plan.supplied_option_match_rate` | `1.0` |
| `payment_plan.syntax_valid_rate` | `1.0` |
| `safety.deadline_violation_rate` | `0.0` |
| `safety.minimum_balance_violation_rate` | `0.0` |
| `safety.safety_invariant_violation_rate` | `0.0` |
| `safety.schema_violation_rate` | `0.0` |
| `safety.unresolved_fx_positive_violation_rate` | `0.04` |
| `safety.unsupported_income_expense_violation_rate` | `0.0` |
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
| `request_16` | Forecasting |
| `request_20` | Forecasting |
| `request_25` | FX |

# Evaluation report

Candidate: `output.csv`

## Hard targets

| Check | Value |
|---|---:|
| `hard_safety_target_met` | `True` |
| `hard_safety_violation_rate` | `0.0` |
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
| `amount.exact_accuracy` | `unavailable` |
| `amount.max_absolute_error` | `unavailable` |
| `amount.mean_absolute_error` | `unavailable` |
| `amount.mean_relative_absolute_error` | `unavailable` |
| `amount.median_absolute_error` | `unavailable` |
| `complete_row.exact_match_rate` | `unavailable` |
| `complete_row.explanation_consistency_rate` | `unavailable` |
| `complete_row.explanation_groundedness_rate` | `unavailable` |
| `complete_row.explanation_present_rate` | `1.0` |
| `earliest_date.correct_empty_date_rate` | `unavailable` |
| `earliest_date.exact_accuracy` | `unavailable` |
| `earliest_date.mean_absolute_date_error_days` | `unavailable` |
| `partial_payment.constraint_pass_rate` | `1.0` |
| `payment_method.accuracy` | `unavailable` |
| `payment_method.macro_f1` | `unavailable` |
| `payment_plan.exact_match_rate` | `unavailable` |
| `payment_plan.safety_valid_rate` | `1.0` |
| `payment_plan.supplied_option_match_rate` | `1.0` |
| `payment_plan.syntax_valid_rate` | `1.0` |
| `safety.deadline_violation_rate` | `0.0` |
| `safety.minimum_balance_violation_rate` | `0.0` |
| `safety.safety_invariant_violation_rate` | `0.0` |
| `safety.schema_violation_rate` | `0.0` |
| `safety.unresolved_fx_positive_violation_rate` | `0.0` |
| `safety.unsupported_income_expense_violation_rate` | `unavailable` |
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
| `request_101` | Forecasting, Message interpretation |
| `request_102` | Message interpretation |
| `request_103` | Message interpretation |
| `request_104` | Message interpretation |
| `request_105` | Forecasting, Message interpretation |
| `request_106` | Message interpretation |
| `request_107` | Message interpretation |
| `request_108` | Message interpretation |
| `request_110` | Message interpretation |
| `request_111` | Message interpretation |
| `request_112` | Message interpretation |
| `request_113` | Forecasting, Message interpretation |
| `request_114` | Message interpretation |
| `request_115` | Message interpretation |
| `request_117` | Message interpretation |
| `request_118` | Message interpretation |
| `request_119` | Message interpretation |
| `request_120` | Message interpretation |
| `request_122` | Message interpretation |
| `request_123` | Message interpretation |
| `request_125` | Message interpretation |
| `request_126` | Message interpretation |
| `request_127` | Message interpretation |
| `request_128` | Message interpretation |
| `request_129` | Message interpretation |
| `request_130` | Message interpretation |
| `request_131` | Message interpretation |
| `request_132` | Message interpretation |
| `request_133` | Message interpretation |
| `request_135` | Message interpretation |
| `request_137` | Message interpretation |
| `request_138` | Message interpretation |
| `request_140` | Message interpretation |
| `request_141` | Message interpretation |
| `request_142` | Message interpretation |
| `request_143` | Message interpretation |
| `request_144` | Message interpretation |
| `request_145` | Message interpretation |
| `request_147` | Message interpretation |
| `request_148` | Message interpretation |
| `request_150` | Message interpretation |
| `request_151` | Message interpretation |
| `request_152` | Message interpretation |
| `request_153` | Message interpretation |
| `request_154` | Message interpretation |
| `request_155` | Message interpretation |
| `request_156` | Message interpretation |
| `request_157` | Message interpretation |
| `request_159` | Message interpretation |
| `request_160` | Message interpretation |
| `request_161` | Message interpretation |
| `request_162` | Message interpretation |
| `request_163` | Message interpretation |
| `request_164` | Message interpretation |
| `request_165` | Message interpretation |
| `request_166` | Message interpretation |
| `request_167` | Message interpretation |
| `request_168` | Message interpretation |
| `request_169` | Message interpretation |
| `request_170` | Message interpretation |
| `request_171` | Message interpretation |
| `request_172` | Message interpretation |
| `request_173` | Message interpretation |
| `request_175` | Message interpretation |
| `request_176` | Message interpretation |
| `request_177` | Message interpretation |
| `request_178` | Message interpretation |
| `request_179` | Message interpretation |
| `request_180` | Message interpretation |
| `request_182` | Message interpretation |
| `request_183` | Message interpretation |
| `request_184` | Message interpretation |
| `request_185` | Message interpretation |
| `request_186` | Message interpretation |
| `request_187` | Message interpretation |
| `request_188` | Message interpretation |
| `request_189` | Message interpretation |
| `request_191` | Message interpretation |
| `request_193` | Message interpretation |
| `request_194` | Message interpretation |
| `request_195` | Message interpretation |
| `request_197` | Message interpretation |
| `request_198` | Message interpretation |
| `request_199` | Message interpretation |
| `request_200` | Message interpretation |
| `request_201` | Message interpretation |
| `request_202` | Message interpretation |
| `request_204` | Message interpretation |
| `request_208` | Message interpretation |
| `request_210` | Message interpretation |
| `request_212` | Message interpretation |
| `request_213` | Message interpretation |
| `request_214` | Message interpretation |
| `request_215` | Message interpretation |
| `request_216` | Message interpretation |
| `request_219` | Message interpretation |
| `request_220` | Message interpretation |
| `request_221` | Message interpretation |
| `request_222` | Message interpretation |
| `request_224` | Message interpretation |
| `request_225` | Message interpretation |
| `request_226` | Message interpretation |
| `request_227` | Message interpretation |
| `request_228` | Message interpretation |
| `request_229` | Message interpretation |
| `request_230` | Message interpretation |
| `request_232` | Message interpretation |
| `request_233` | Message interpretation |
| `request_234` | Message interpretation |
| `request_235` | Message interpretation |
| `request_236` | Message interpretation |
| `request_237` | Message interpretation |
| `request_238` | Message interpretation |
| `request_240` | Message interpretation |
| `request_241` | Message interpretation |
| `request_242` | Message interpretation |
| `request_245` | Message interpretation |
| `request_246` | Message interpretation |
| `request_247` | Message interpretation |
| `request_248` | Message interpretation |
| `request_249` | Message interpretation |
| `request_250` | Message interpretation |
| `request_252` | Message interpretation |
| `request_253` | Message interpretation |
| `request_254` | Message interpretation |
| `request_256` | Message interpretation |
| `request_259` | Message interpretation |
| `request_26` | Message interpretation |
| `request_261` | Message interpretation |
| `request_262` | Message interpretation |
| `request_263` | Message interpretation |
| `request_264` | Message interpretation |
| `request_265` | Message interpretation |
| `request_266` | Message interpretation |
| `request_267` | Message interpretation |
| `request_268` | Message interpretation |
| `request_269` | Message interpretation |
| `request_27` | Message interpretation |
| `request_271` | Message interpretation |
| `request_272` | Message interpretation |
| `request_273` | Message interpretation |
| `request_274` | Message interpretation |
| `request_275` | Message interpretation |
| `request_28` | Message interpretation |
| `request_29` | Message interpretation |
| `request_32` | Message interpretation |
| `request_33` | Forecasting, Message interpretation |
| `request_34` | Message interpretation |
| `request_35` | Forecasting, Message interpretation |
| `request_36` | Message interpretation |
| `request_37` | Message interpretation |
| `request_38` | Message interpretation |
| `request_40` | Message interpretation |
| `request_42` | Message interpretation |
| `request_43` | Message interpretation |
| `request_44` | Message interpretation |
| `request_45` | Message interpretation |
| `request_47` | Message interpretation |
| `request_48` | Forecasting, Message interpretation |
| `request_49` | Message interpretation |
| `request_50` | Message interpretation |
| `request_52` | Message interpretation |
| `request_53` | Message interpretation |
| `request_54` | Message interpretation |
| `request_55` | Forecasting, Message interpretation |
| `request_57` | Message interpretation |
| `request_58` | Message interpretation |
| `request_59` | Message interpretation |
| `request_60` | Message interpretation |
| `request_61` | Message interpretation |
| `request_62` | Message interpretation |
| `request_64` | Forecasting, Message interpretation |
| `request_65` | Message interpretation |
| `request_66` | Message interpretation |
| `request_68` | Message interpretation |
| `request_69` | Message interpretation |
| `request_70` | Message interpretation |
| `request_71` | Message interpretation |
| `request_72` | Message interpretation |
| `request_73` | Forecasting, Message interpretation |
| `request_74` | Message interpretation |
| `request_75` | Message interpretation |
| `request_76` | Message interpretation |
| `request_77` | Message interpretation |
| `request_78` | Forecasting, Message interpretation |
| `request_80` | Message interpretation |
| `request_81` | Message interpretation |
| `request_82` | Message interpretation |
| `request_83` | Message interpretation |
| `request_84` | Forecasting, Message interpretation |
| `request_85` | Message interpretation |
| `request_87` | Message interpretation |
| `request_88` | Message interpretation |
| `request_90` | Message interpretation |
| `request_91` | Message interpretation |
| `request_92` | Message interpretation |
| `request_93` | Message interpretation |
| `request_94` | Message interpretation |
| `request_95` | Message interpretation |
| `request_98` | Message interpretation |

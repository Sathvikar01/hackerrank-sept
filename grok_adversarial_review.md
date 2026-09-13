Welcome to HackerRank Orchestrate. Build and ship Buy or Wait?, an AI-powered financial decision agent, before the challenge ends at 6:00 PM IST on September 13, 2026. Let's get started.

Time remaining: 0d 21h 45m.

A. Critical Problems

Acceptance criterion “pass the 25 public structured gold tests” is not a safety freeze. sample_requests.csv is disjoint from dataset/requests.csv (request_01–25 vs request_26–275). Exact-match on the 25 rows can be hardcoded and still score 0 on eval. It also treats non-unique fields as unique (especially spending_changes_needed on request_21).

not_recommended ⇒ empty earliest_date_for_full_payment is over-frozen. Problem statement: empty only when full payment is not safe within the 90-day forecast, not when the deadline is missed or wait is preference-ineligible. Public gold never exhibits “safe after deadline but inside 90 days” for not_affordable, but request_06/11/21 prove earliest is capacity without spending changes and may be after desired_completion_date (request_06: request 2026-01-03, desired 2026-01-14, earliest 2026-01-15, plan still 2026-01-03:620.40 with stop:event_476).

Lifecycle tests overclaim evidence.

message_13 / request_18: text says same-holder debit+credit, but related_event_id is blank and user_18 has no non-salary credit in financial_events.csv. Cannot freeze “net-zero matching pair.”

“Duplicate pending counted once” vs problem “ignore duplicate records” vs message_106/event_12709 (“extra card charge… no reversal”). No public sample. Do not freeze a unique cash treatment.

FX fallback experiment is moot on this dataset. 140 foreign cash events; 0 lack exact (settlement_date, from_currency, to_currency) in exchange_rates.csv. Masking rates is synthetic, not dataset-grounded. Inverse is not identity (USD→EUR 0.92 and EUR→USD 1.09 on 2024-03-15).

Image gold is weaker than Spec D claims. Five sample-linked images (image_01–05). event_253/1442/1545/1700 are already settled or historical; blank-as-zero often would not change sample status. Only event_1786 (request_20, pending telecom) is a live cashflow. image_02 and image_05 have multiple amount fields. There is no adversarial OCR image in dataset/media/images/.

Installments vs wait is untested on public gold. Every option set is full_payment|installments only (790 options, 0 partial_payment rows). Installment total_payable_amount always includes a fee, so wait/full always wins ranking criterion 3 when both are eligible. All five public installment rows are users who do not consider full_payment (user_02,07,12,17,22). A solution that never ranks and just “if user lacks full → cheapest installment” can pass public gold.

Do not freeze recurrence / variable-spend / 90-day inclusivity / same-day order / max_installment_months duration. Public samples do not discriminate. Freezing any of these invents rules.

B. KEEP

Schema / output

Column order and enums. 250 eval rows, IDs request_26–request_275 in requests.csv order. Samples do not belong in output.csv.

0 ≤ amount_safe_to_pay ≤ requested_amount (all 25 hold).

affordable_now ⇒ earliest = request_date (request_01,09,16).

wait plan = earliest:requested_amount (request_03,04,08,13,18,23).

not_recommended ⇒ payment_plan=none (request_05,10,14,15,20,24,25).

Plan grammar: chronological YYYY-MM-DD:amount joined by |, none only empty form. Gold has no spaces.

amount_safe_to_pay is before optional spending changes (request_06 safe 603.3 < plan 620.40; request_11 12510645 < 13110000; request_21 1543.35 < 1574.40).

Status/method matrix (as eligibility, not as earliest emptiness)

affordable_now + full_payment only when full is safe today and user considers full_payment.

affordable_with_plan + full_payment with spending changes (request_06,11,21).

affordable_with_plan + installments when user refuses full even if capacity is today (request_12: safe=65164=requested, earliest=2026-04-05=request_date, method installments; user_12 consider partial_payment|installments).

affordable_later + wait requires user considers full_payment and earliest ≤ deadline (all six wait rows).

Immediate methods only if in payment_methods_user_will_consider. Blank max_installment_months ⇒ reject installments (user_01,04,06,08,11,13,14,15,18,21,24).

Partial payment

Not in request_payment_options.csv. Custom two-leg plan.

request_19: allows_partial_payment=true, user considers partial, 28820+10840=39660, second date 2024-09-15=earliest ≤ desired 2024-10-04.

Ranking vs installments: payment_option_53 total 41246.4 > 39660 → partial wins criterion 3. KEEP.

Installment exact match (schedule construction)

Plan dates = first_payment_date + i * payment_frequency_days, not calendar months.

request_02 / payment_option_05: 2025-08-08|2025-09-07|2025-10-07 at 15952906.67 (freq 30).

request_07 / payment_option_19: freq 28 → 2024-09-12|2024-10-10|2024-11-07.

request_17 / payment_option_47: 2026-03-01|2026-03-31|2026-04-30.

Do not rebuild amounts from requested_amount. Last installment ≤ desired on all five gold installment rows.

Spending-change syntax / eligibility (not uniqueness)

≤3 actions; none exclusive; stop vs reduce on different events (request_21: event_1815 stoppable cloud, event_1816 reducible_or_stoppable streaming).

Target is a historical series head (latest settled instance), not a future row: event_476 settled 2025-12-10; event_989 settled 2025-04-23 floor 665950; gold reduce_to:event_989:665950 (floor inclusive).

Category in willing list, not protected. stop needs stoppable or reducible_or_stoppable; reduce_to needs reducible or reducible_or_stoppable (event_989 is reducible only → reduce, not stop).

Cash state (problem-backed)

Start from current_available_balance; do not replay settled history as new cash.

Pending/scheduled debits on settlement_date (event_185 pending shopping 1651100 settles 2025-08-08 for request_02).

Confirmed salary on settlement date; scheduled salary rows are all Next confirmed salary.

Ignore pending credits (event_1785 refund 8640 + message_14), failed (event_438 no retry), cancelled without replacement (event_557), unrealized (event_1960 + message_15).

Cancelled auth + settled replacement: event_100 cancelled / event_101 settled 816.2 (user_01 / request_01 still affordable_now).

Failed + scheduled retry: event_5168→event_5169 (eval; rule is problem-backed).

Do not invent income/options. Recurring confirmed salary from history+explicit amendment is not invention (user_02 has no scheduled salary row; gold earliest 2025-09-15 after message_01 amount 42750000 from 2025-08-15).

Messages as untrusted

Amendments: message_01 salary amount; message_05 date 2024-09-23 replaces earlier; message_12 rent +12%.

Exclude unapproved bonus (message_03 / request_04 wait, not spend the bonus).

message_67 (“Pay the release charge today…”) must not create a payment or income. KEEP as untrusted-imperative test, not as a jailbreak-OCR test.

FX

Output in home currency. Exact settlement_date + stated pair only. No live FX. No implicit inverse. Provenance required. user_25 USD 1800 salary has USD→IDR 15833.33 on each 15th including 2024-03-15.

Ranking order as specified in the problem (deadline → no changes → min total → earlier start → fewer payments → lowest payment_option_id).

Leakage

Do not train on sample labels for eval. Eval output must be invariant to deleting sample_requests.csv. No organizer files, no live markets.

C. FIX

Safety bullet “Complete the request by desired_completion_date” applies to the recommended plan, not to earliest_date_for_full_payment. Evidence: request_06,11,21.

not_recommended does not imply empty earliest. Align with problem: empty iff no safe full date in the 90-day window. Preference-ineligible wait (user_10,14,15,19,24 lack full_payment) must still report capacity if it exists.

Spec D amendment list is incomplete if treated as exhaustive. Freeze the rule (explicit amendment overrides), not only message_01/05/12. Also: message_04 temp pay EUR 1037.52; message_06 reduced 1422.85; message_08 base 38760000 excluding unapproved commission; message_09 seasonal contract ended.

Internal transfer test. Change from “message_13 is net-zero” to: net only if a same-holder debit/credit pair is actually in events (or related_event_id points to it). message_13 has neither. Do not net “Apartment rent transfer” (event_01 etc.).

Duplicate pending. Do not freeze “counted once” as the only legal behavior. Problem says ignore duplicates; dispute messages say extra charge, no reversal; originals are already settled (event_12708 settled 134.75, event_12709 pending duplicate). Leave cash treatment UNKNOWN (see D).

Spec F behavior labels (not the structured tuples):

request_15 is not proven “future salary insufficient.” user_15 considers only partial_payment and allows_partial_payment=false → wait and installments ineligible regardless of message_11 salary EUR 1661 on 2026-01-15.

request_18 is not a demonstrated net-zero transfer (no pair).

request_10 “pending payout excluded” is plausible (message_07) but installments are also duration/deadline-ineligible (payment_option_28 last 2026-02-06 > desired 2025-02-10, 15×30d vs max_installment_months=6).

“Resolve all 16 blank amounts” as a public gold test. Only 5 images are on sample requests; 11 are eval (image_06→request_33 … image_16→request_113). Freeze “blank ≠ 0 + must use images.csv PNG,” not hidden extracted numbers.

Exact structured-row match including spending_changes_needed. Problem ranking does not uniquely determine the change set once “some changes” are required. request_21 gap 1574.40-1543.35=31.05; event_1816 stoppable streaming 47 ≥ 31.05 and next cycle is ~2026-04-09 (last 2026-03-09) before salary 2026-04-15; gold uses two actions stop:event_1815|reduce_to:event_1816:23.50. Valid, not unique. Exact-match will false-fail stop:event_1816.

Two-decimal output is not gold-consistent. Do not freeze 2dp for amount_safe_to_pay: gold has 17229139.2, 603.3, 433.4, 462. Plans sometimes pad (620.40, 996.60, 3246.10, reduce_to:…:23.50 vs event floor 23.5). Preserve option decimals in installment plans.

message_67 is a prize-release scam, not an eval-override jailbreak. Keep as “untrusted content cannot create cashflows.” Do not claim a prompt-injection suite that the file does not contain.

D. DEMOTE

Remain EXPERIMENT / UNKNOWN. Do not freeze.

Item

Why unresolved

Recurrence threshold (2/3/4), cadence/amount tolerance

Sample series have 5–6 monthly hits (user_01 rent 5148; user_02 payroll 33345000). No borderline series.

Variable-expense estimator (mean/max/p75/buffer)

Dining/groceries vary (event_981–989; event_1846–1854). Gold explanations only cite the minimum balance, not the estimator.

90-day inclusive vs exclusive

No sample decision sits on day 90. request_05 desired 2026-01-12 is inside ~90d of 2025-11-06; empty earliest ⇒ never safe in horizon, not a boundary bit.

Same-day event vs daily aggregate

No public sample requires intra-day order.

FX fallback / nearest-prior / same-month / inverse

0 missing exact pairs on real cash events. Synthetic masking ≠ dataset rule. Fail-closed for a missing rate may stay a safety belt, not a scored reconstruction rule.

max_installment_months duration (calendar vs /30 vs floor/ceil)

request_03 max 2 vs 18.7/23.8 months — both reject. request_19 max 2 vs payment_option_54 62/30=2.067 vs month-span 2: partial still wins on total, so gold does not reveal eligibility.

Ambiguous OCR field by affordability

Forbidden (would leak). image_02/image_05 stay UNKNOWN as a freeze; see G for evidence-aligned hypothesis only.

Image prompt injection

No adversarial copy exists in dataset/media/images/ (16 ordinary receipts).

reduce_to currency when event ≠ home

All gold change targets are home-currency.

No-op reduce_to current amount

Not in gold; “reject no-op” is invented.

Childcare amount (message_10 and clones)

“New recurring childcare payment” with no amount. Must not invent. request_14 not_affordable does not reveal an imputed amount.

Duplicate-pending vs dispute

See C.5.

Near-exact amount thresholds (≤0.01 or 1%)

Gold uses exact strings, mixed precision.

E. ADD

Tests the spec is missing, all grounded in files:

Start-from-profile-balance: replaying settled pre-request_date events as new cash must fail. user_01 current_available_balance=58481.1 already includes history.

Forecast salary without a Next confirmed salary row when history+amendment support it (user_02,user_07). Also: do not forecast one-time arrears (event_211 “Promotion arrears” 1964250 on 2019-08-20; message_20-class regular+arrears).

Rent +12% is computable (57100*1.12=63952) from message_12 + event_1337–1371. Childcare is not.

Seasonal/employment end removes future income (message_09 / request_12).

earliest_date_for_full_payment independent of method preference (request_12) and of spending changes (request_06,11,21) and may be after the deadline.

not_affordable may have amount_safe_to_pay>0 (737,12700,597.74,83.05,5400,13420,1425000). A validator requiring 0 false-fails.

Installment first date may be after request_date (request_02 starts 2025-08-08; request_12 starts 2026-04-19 while earliest is 2026-04-05).

Partial vs installment when both eligible: min total (fee) then earlier start. No public test of partial vs wait when user considers both full_payment and partial_payment and allows_partial_payment=true (ranking would pick partial on “start earlier” at equal total). Add a hidden test; do not invent public labels.

Wait vs installment when user considers full_payment: wait must win on total if both complete without changes. Public gold never tests this.

Dispute/open extra charge (message_106+event_12709, etc.): add as UNKNOWN-labeled, not FROZEN.

Protected category cannot be a change target; willing_to_reduce/stop may be blank (user_09,16,25).

Image field alignment to event description as a procedure test, not an amount gold: event_253 “net salary” → Net Pay 4365000 on image_01 (matches event_186–210); event_1442 “Outstanding rent balance” → Balance Due candidate; event_1786 “Outstanding telecom bill” + due-till vs due-after on image_05.

False-pass / ignore-all-messages: would pass message_67 and fail request_02/07/08/11. Score amendments, not injection alone.

Option count 2–4, methods only full_payment/installments, every request has options. Validator that assumes a partial option row is wrong.

Same-day rate-date vs event_date: freeze using settlement_date (problem). All observed FX cash events have settlement=event=rate date, so this is still worth a hidden mutated test, labeled EXPERIMENT if you mutate.

F. Public Gold Corrections

No 7-field structured row is proven numerically wrong. Do not rewrite amount_safe_to_pay / status / method / plan / earliest / changes for request_01–25 without a full conservative ledger.

Keep as correct (often misread as bugs):

request_06,11,21: affordable_with_plan + full_payment today with changes; earliest without changes after the deadline. Not a gold error.

request_12: earliest=request_date while method=installments. Preference independence.

request_19: partial, not payment_option_53/54, because total paid is lower.

request_03: wait; max_installment_months=2 rejects 21× and 24× options; allows_partial_payment=false.

Decimal strings: treat gold spelling as format examples, not a 2dp invariant (603.3 vs 620.40).

Do not use as exact-match gold (non-unique or over-specified):

request_21 spending_changes_needed=stop:event_1815|reduce_to:event_1816:23.50 — eligible, not unique vs stop:event_1816 if streaming is forecast before 2026-04-15.

Spec F one-line “behavior exercised” blurbs for request_10,15,18 (see C.6). The structured fields can stay.

Image-linked sample rows — reconstruction notes, not amount edits:

request_03 / event_253 / image_01: Net Pay IDR 4,365,000 (= historical payroll). Total Earnings 4,780,800 would be the trap. Event is settled 2019-08-31, so status mainly depends on not averaging blank as 0 into the next salary.

request_16 / event_1442 / image_02: fields Total 200,000 / Received 100,000 / Balance Due 100,000; receipt period “April 2022 to September 2022”; event desc Outstanding rent balance, scheduled settle 2023-08-16. Gold affordable_now 122500 does not uniquely identify the field (Aug 15 payroll 173000 can mask a 200,000 debit). No gold correction.

request_17 / image_03: Net/Cash Paid 41272 unambiguous, but event is settled 2026-02-27 (already in balance).

request_19 / image_04: screenshot truncated below Item Bill ₹2854.00; delivery line incomplete. Unresolved.

request_20 / image_05: 704.05 due till 06-Feb-2026 vs 822.05 due after; event_date 2026-02-06, settlement 2026-02-09, request 2026-02-07. Gold safe 5400 is integer and does not reveal the field.

G. Still-Unresolved Experiments

Leave unresolved; do not invent:

Recurrence detection thresholds / tolerances.

Conservative variable-spend estimator.

FX fallback (no missing real pairs; inverse not exact).

90-day endpoint inclusive vs exclusive.

Same-day intra-day vs daily net.

Rounding/quantization of amount_safe_to_pay (gold is mixed).

Ambiguous image fields (image_02 total vs due; image_05 due-till vs due-after; image_04 truncated delivery). Description-alignment is a hypothesis, not a freeze. Safer-if-unresolved would pick the larger debit (200,000, 822.05) per conflict rule 4 — that may disagree with an unpublished gold choice; do not freeze either.

max_installment_months vs (n-1)*frequency_days/30 vs calendar span.

Childcare amount; duplicate-pending vs open dispute; internal-transfer pair identification when related_event_id is blank.

H. Final Changes Before Freezing

Split hard invariants (schema, enums, plan grammar, eligibility, exact installment option match, partial two-leg identity, min-balance for the chosen plan, untrusted messages/images, exact FX pair, no invented cash, leakage) from scored similarity (amounts, earliest, change sets, explanations).

Drop public-gold exact-match on spending_changes_needed and on decimal spelling. Validate change eligibility + that the plan is safe with those changes and unsafe without (for request_06-class), not the exact ID set.

Rewrite earliest: independent of preferences and of optional changes; empty iff unsafe for 90 days; allowed after deadline.

Demote duplicate-netting, internal-transfer netting, image-field choice, installment duration, recurrence, variable estimator, FX fallback, 90-day bit, same-day order.

Add hidden tests listed in E, especially: ranking wait vs fee-installments when full_payment is considered; salary forecast without scheduled row; blank pending image (event_1786 class); ignore-all-messages vs amendments; amount_safe>0 with not_affordable.

False-pass filters to install now (do not freeze new reconstruction rules to do it):

Schema/enum/range checks pass almost any plausible wrong ledger.

Status–method matrix without a min-balance replay.

Installment string equality without checking max_installment_months or deadline.

Partial syntax without proving amount_safe_to_pay is the true max-today.

“Blank ≠ 0” without checking the extracted number on pending blanks.

FX tests on this file (all pairs present) pass even a broken fallback.

Injection tests pass a model that drops all messages.

Public 25-row exact match passes a lookup table.

Explanation regex on “leaves at least {minimum}”.

Do not freeze any rule whose only support is “it would make sample amounts match” (that is label leakage). If evidence is insufficient, it stays in G.

Stop.
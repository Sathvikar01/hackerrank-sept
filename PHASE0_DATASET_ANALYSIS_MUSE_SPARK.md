# Phase 0 — Dataset Analyst Report (Muse Spark)

Scope: read-only analysis of `dataset/` for HackerRank Orchestrate “Buy or Wait?”. No implementation, no predictions. Labels: FACT = directly supported, INFERENCE = strongly suggested, UNKNOWN = insufficient evidence.

## A. Dataset Facts

FACT — Layout from `dataset/` directory listing + `AGENTS.md §6.1`:
- `financial_profiles.csv`, `financial_events.csv`, `exchange_rates.csv`, `requests.csv`, `sample_requests.csv`, `request_payment_options.csv`, `messages.csv`, `images.csv`, `output.csv`, `media/images/image_01.png` … `image_16.png` (16 files).

FACT — Row counts from `Read` footers (header inclusive):
- `requests.csv`: 251 lines = 250 eval rows `request_26`…`request_275` (`dataset/requests.csv:2`, `:250-251`).
- `sample_requests.csv`: 26 lines = 25 public examples `request_01`…`request_25` (`sample_requests.csv:2`, `:25-26`).
- `financial_profiles.csv`: 276 lines = 275 users `user_01`…`user_275` (`financial_profiles.csv:2`, `:260-276`).
- `financial_events.csv`: 25343 lines = 25342 events (`financial_events.csv:1`, `:252-266`).
- `exchange_rates.csv`: 135 lines = 134 rates (`exchange_rates.csv:1`, `:50-135`).
- `request_payment_options.csv`: 791 lines = 790 options (`request_payment_options.csv:2`, `:789-791`).
- `messages.csv`: 216 lines = 215 messages (`messages.csv:1`, `:101-216`).
- `images.csv`: 17 lines = 16 links `image_01`…`image_16` (`images.csv:1-17`).
- `output.csv`: 251 lines = 250 blank rows `request_26`…`request_275` (`output.csv:2`, `:251`).

FACT — Exact schemas (header row 1 of each file):
- `requests.csv:1`: `request_id,user_id,request_date,request_type,requested_amount,desired_completion_date,allows_partial_payment,request_text`. Eg `request_26,user_26,2025-08-03,family_transfer,15656000,2025-10-07,false`.
- `sample_requests.csv:1`: same 8 + `amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation`.
- `financial_profiles.csv:1`: `user_id,home_currency,current_available_balance,minimum_balance_to_keep,financial_priorities,expense_categories_to_protect,expense_categories_user_is_willing_to_reduce,expense_categories_user_is_willing_to_stop,payment_methods_user_will_consider,max_installment_months`. Eg `user_01,ZAR,58481.1,18000,…full_payment,` (blank max = no installments).
- `financial_events.csv:1`: `event_id,user_id,event_type,description,category,direction,amount,currency,event_date,settlement_date,status,linked_event_id,flexibility,minimum_allowed_amount`.
- `exchange_rates.csv:1`: `rate_date,from_currency,to_currency,rate`. Eg `2023-10-15,EUR,ZAR,20`.
- `request_payment_options.csv:1`: `payment_option_id,request_id,payment_method,payment_amount,number_of_payments,first_payment_date,payment_frequency_days,financing_fee,total_payable_amount`. Eg `payment_option_01,request_01,full_payment,25256,1,2024-03-03,,0,25256` vs `payment_option_02,request_01,installments,1852.11,15,2024-03-06,30,2525.65,27781.65`.
- `messages.csv:1`: `message_id,user_id,request_id,related_event_id,sent_at,source_type,message_text`.
- `images.csv:1`: `image_id,user_id,request_id,related_event_id`. All 16 rows populated, eg `image_01,user_03,request_03,event_253`.
- `output.csv:1`: `request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation`.

FACT — Missing values observed:
- Profiles: `max_installment_months` blank when installments not considered (`financial_profiles.csv:2 user_01`, `:260 user_260 partial_payment,` blank). `…willing_to_reduce/stop` can be blank (`:10 user_09 …rent|utilities|groceries,,,full…` has empty reduce/stop).
- Events: `amount` blank in exactly 16 rows = 15× `,debit,,` + 1× `,credit,,`. Grep `,debit,,` gives `event_1442(:1443)`, `event_1545(:1546)`, `event_1700(:1701)`, `event_1786(:1787)`, `event_3051(:3052)`, `event_3231(:3232)`, `event_4535(:4536)`, `event_5170(:5171)`, `event_6033(:6034)`, `event_6859(:6860)`, `event_7307(:7308)`, `event_7941(:7942)`, `event_9421(:9422)`, `event_9806(:9807)`, `event_10521(:10522)`; grep `,credit,,` gives only `event_253(:254) August 2019 net salary`. Never treat as 0 per `problem_statement:45`.
- Events: `settlement_date` blank for `unrealized` (`financial_events.csv:1857 event_1856 …2026-04-01,,unrealized`).
- Events: `linked_event_id` blank for standalone; `minimum_allowed_amount` blank when `fixed`/`stoppable`, populated when `reducible`/`reducible_or_stoppable` (eg `:86 event_85 …reducible,489.5` vs `:7 event_06 …stoppable,`).
- Options: `payment_frequency_days` blank for `full_payment`, populated for `installments` (`request_payment_options.csv:2` vs `:3`).
- Messages: `request_id` blank for user-level (eg `messages.csv:2 message_01,user_02,,,`), `related_event_id` blank unless 1:1 event row (only 39/215 contain `,event_` per grep; eg `:15 message_14…event_1785` vs `:2 message_01` blank).
- Rates: sparse matrix, not every pair per date. Eg `exchange_rates.csv:33-35 2024-06-15` has only `EUR,USD` + `USD,EUR` + `USD,INR`, no `USD,IDR`/`EUR,ZAR`.

FACT — Currencies: home `INR,ZAR,IDR,USD,EUR` per `AGENTS.md §6.1` + observed profiles (`user_01 ZAR`, `user_02 IDR`, `user_06 EUR`, `user_07 INR`, `user_36 USD` via `message_26`). Event `currency` same set. Rate pairs observed: `EUR,ZAR=20`, `USD,EUR=0.92`, `USD,IDR=15833.33`, `USD,INR=83.33`, `EUR,USD=1.09` (`exchange_rates.csv:2-5`, `:23-27`, `:90`).

INFERENCE — Date ranges (sampled, needs full scan in 0.25):
- Requests eval sampled `2024-06-07 request_28` … `2026-07-05 request_27`; samples `2019-09-03 request_03` … `2026-07-04 request_09`; events `2022-12-16 event_6858` … `2026-09-03 event_10521`; rates `2023-10-15` … `2026-11-15`; messages `2019-08-31T09:30:00Z message_02` … `2026-07-01T09:30:00Z message_171`. All `YYYY-MM-DD`, `sent_at` always `…T09:30:00Z`.

## B. Join Graph

FACT — `user_id` links profiles↔requests↔events↔messages↔images. Eg `user_03` has profile (`financial_profiles.csv:4`), `request_03` (`sample_requests.csv:4`), events `event_189-254`, message `message_02,user_03,request_03`, image `image_01,user_03,request_03,event_253`.
FACT — `request_id` links requests↔options↔messages↔images. Eval `request_26`…`275` each needs 1 output row (`output.csv:2-251`). Options: 2–4 per request. Eg `request_01` has 4 options `payment_option_01-04` (`request_payment_options.csv:2-5`); `request_02` has 3 (`:5-7`); tail `request_275` has 3 (`:789-791`).
FACT — `event_id` ↔ `related_event_id`: messages only when directly describing one supplied row (`problem_statement:39`, `messages.csv:15 message_14…event_1785`, `:16 message_15…event_1960`). Blank means no 1:1 row — still usable as user-level evidence (eg salary-shift `message_01` blank).
FACT — `event_id` ↔ `related_event_id` in `images.csv`: exactly the 16 blank-amount events. Verified: `event_253→image_01`, `1442→image_02`, `1545→image_03`, `1700→image_04`, `1786→image_05`, `3051→image_06`, `3231→image_07`, `4535→image_08`, `5170→image_09`, `6033→image_10`, `6859→image_11`, `7307→image_12`, `7941→image_13`, `9421→image_14`, `9806→image_15`, `10521→image_16` (`images.csv:2-17` vs blank grep list). Resolve as `dataset/media/images/<image_id>.png` (eg `image_07→image_07.png` viewed: restaurant invoice).
FACT — `linked_event_id` points to earlier event same lifecycle, same `user_id` (`problem_statement:36`, `AGENTS.md §6.1`). Does not alone decide cash effect.
FACT — Rates matched on `(rate_date, from_currency→to_currency)` using settlement date (`problem_statement:43,47`). Eg foreign salary `messages.csv:95 user_125 EUR 748 confirmed 2025-11-15, bank converts on settlement date` must join `exchange_rates.csv:96-100 2025-11-15 EUR,USD / USD,EUR / USD,IDR / USD,INR`.
UNKNOWN — Exact rate-date selection when settlement ≠ 15th/01st (only dated rows exist; eg `2025-10-01 USD,INR` singleton `:90`). Whether to use same-month-15th, exact-match-only, or nearest-prior is not established in dataset.

## C. Financial Semantics

FACT — `event_type` observed: `expense`, `income`, `subscription`, `debt_payment`, `refund`, `investment_purchase`, `investment_valuation`, `investment_sale` (`financial_events.csv:2 expense`, `:104 income Next confirmed salary`, `:7 subscription`, `:5 debt_payment`, `:100 refund`, `:1856 investment_purchase`, `:1857 investment_valuation`, `:7307 investment_sale` via grep). INFERENCE — full distinct set needs scripted scan; do not assume others absent.
FACT — `status` observed: `settled`, `pending`, `scheduled`, `failed`, `cancelled`, `unrealized`:
- `settled` normal history (`:2 event_01`).
- `pending` authorization/processing, settlement in future (`:103 event_102 Pending fuel …2024-03-02,2024-03-05,pending`; `:1786 event_1785 Pending refund …pending,event_1784`; `:23204 event_23203 Possible duplicate …pending,event_23202`).
- `scheduled` confirmed future (`:104 event_103 Next confirmed salary …2024-03-15,2024-03-15,scheduled`; `:1443 event_1442 Outstanding rent …scheduled`; `:5170 event_5169 Scheduled retry …scheduled,event_5168`).
- `failed` ignore (`:439 event_438 Failed utility …failed`).
- `cancelled` ignore (`:101 event_100 Card authorization …cancelled`).
- `unrealized` non-cash valuation, empty settlement (`:1857 event_1856 …non_cash…,,unrealized,event_1855`).
FACT — `direction`: `debit` (cash out), `credit` (cash in), `non_cash` (only valuations, 10 rows per grep, all `investment_valuation`).
FACT — `flexibility`: `fixed`, `stoppable`, `reducible`, `reducible_or_stoppable`. Eg `fixed rent :200`, `stoppable delivery :7`, `reducible dining :86 +489.5 floor`, `reducible_or_stoppable streaming :202 +58900`.
FACT — `category` sampled: `rent,utilities,education,debt_repayment,music_subscription,delivery_membership,dining,shopping,transport,entertainment,cloud_storage,streaming,housing,healthcare,salary,investment,insurance,work_expense,groceries` — full set UNKNOWN without scan.

## D. 90-Day Forecast Rules

FACT — From `problem_statement:176-183` + `AGENTS.md §6.3`:
- Start `current_available_balance` (home currency). Forecast 90 days from `request_date`.
- Reserve pending debits on `settlement_date` (eg `event_102`, `event_185 Pending merchant 2025-08-08` just after `request_02 2025-08-05` — must block full payment).
- Include scheduled/confirmed: `Next confirmed salary` (`event_103`), `Scheduled school fee` (`event_357 2024-06-04,2024-06-11`), `Scheduled retry` after failed (`event_5169`).
- Count confirmed salary on settlement date; count settled sale/reimbursement (`event_7306 Investment sale …settled,event_7305`; `event_1544 Reimbursement …settled,event_1543`).
- Ignore pending credits, bonuses/commissions/refunds/lottery/gains until settled; ignore failed/cancelled/duplicates/unrealized.
- Forecast recurring essential variable spending conservatively only when history supports recurrence (eg monthly rent `5148 ZAR user_01 :2,:8,:14,:20,:27,:32`; monthly entertainment `user_02 :111,:119,:127,:135,:143`).
- Balance after every projected essential + every plan payment must stay ≥ `minimum_balance_to_keep`. `amount_safe_to_pay` = max today passing check before spending changes, capped `0…requested_amount`; `earliest_date_for_full_payment` = first date full passes without spending changes; equals `request_date` for `affordable_now`, empty if never in horizon.
- Must complete by `desired_completion_date` and stay safe through full 90 days.

INFERENCE — Conservative variable forecast likely means max/upper-quartile of recent history, not mean — suggested by sample explanations citing “leaves at least … minimum available” (eg `sample_requests.csv:4 request_03`, `:5 request_04`), but exact estimator UNKNOWN.
UNKNOWN — Day-count: whether 90 days inclusive, whether settlement-date conversion uses exact-date or month-15th rate, how to annualize weekly/biweekly subscriptions.

## E. Image/Message Findings

FACT — Blank→image 1:1 proven above. `event_253` blank salary → `image_01.png` viewed: `PAY SLIP Aug-2019 Net Pay IDR 4,365,000` — the missing amount. `event_3231` blank dining → `image_07.png` viewed: `Grand Total (RS) 8528` (matches `INR`, `2025-10-29`). `event_1442` blank rent → `image_02.png` viewed: `Rent Receipt Total 2,00,000, Received 1,00,000, Balance Due 1,00,000` — ambiguous which field is the event amount (TRAP).
FACT — Message patterns (all `messages.csv`):
- Confirm/increase: `:2 message_01 user_02 salary →IDR 42750000 from 2025-08-15`; `:27 message_26 user_36 →USD 2988 from 2026-07-15`.
- Decrease/temporary: `:5 message_04 user_06 temporary EUR 1037.52`; `:7 message_06 user_08 reduced EUR 1422.85 unpaid leave`.
- Date shift (amendment wins over event): `:6 message_05 user_07 salary expected 2024-09-23 replaces earlier`; `:102 message_101 user_131 expected 2025-05-23 replaces earlier`.
- Pending not withdrawable → ignore: `:9 message_07 user_10 QuickCrew payout pending`; `:20 message_19 user_27 TaskLoop pending`; `:124 message_123 ShiftPay pending`.
- Bonus/commission awaiting approval → ignore: `:4 message_03`, `:9 message_08 commission not approved`, `:100 message_98 bonus subject to review`.
- Seasonal end → remove future income: `:10 message_09 user_12 contract ended`; `:22 message_21 user_29`.
- New recurring deduction + salary resume: `:11 message_10 user_14 salary EUR 2717 resumes 2025-08-15 + new childcare`; `:98 message_97`, `:121 message_120` same template.
- Rent +12%: `:13 message_12 user_16`; `:106 message_105 user_137 HomePortal`.
- Bank internal transfer net-zero: `:14 message_13 user_18 matching debit+credit same holder both remain` + `:24 message_23`, `:136 message_135`, `:213 message_213` — do not double-count as expense+income.
- Refund initiated not yet → keep pending: `:15 message_14 event_1785`, `:26 message_25 event_3230`, `:215 message_215 event_25342`.
- Unrealized no cash: `:16 message_15 event_1960 market value up, no units sold`; `:208 message_207 event_24534`.
- Prize processing vs settled: processing ignore (`:17 message_16`, `:134 message_134`), settled count once + closed (`:18 message_17 event_2165 reached, closed`; `:29 message_28`, `:88 message_88`, `:99 message_99`).
- Invoice only confirmed counts: `:19 message_18 user_26 approved IDR 30780000 settle 2025-08-15, others awaiting`; `:25 message_24`, `:94 message_93`, `:96 message_96`, `:130 message_129`.
- Regular + one-time arrears separate: `:21 message_20 user_28 regular EUR 1452 + arrears EUR 653.40`; `:28 message_27`, `:113 message_112` — do not recur the arrears.
- Investment sale settled: `:92 message_92 event_11129`, `:109 message_108 event_13032`, `:115 message_114` — count on settlement.
- FX at settlement: `:96 message_95 EUR→home on settlement`, `:119 message_118`, `:134 message_133`, `:214 message_214`.
- Employment ended: `:31 message_30 remaining INR 148000, remove ended`; `:120 message_119`, `:130 message_129 no regular after final`.
- Dispute open no reversal: `:107 message_106 event_12709 extra charge investigating, no reversal`; `:122 message_121` — financially safer = still reserve.
FACT — `source_type`: `employer, service_provider, bank, merchant, financial_service` (eg `:2 employer`, `:9 service_provider`, `:14 bank`, `:15 merchant`, `:16 financial_service`).
FACT — Conflict rule (`problem_statement:200-205`): explicit cancellation/settlement/amendment > newer same-source > settled over forecast > financially safer. Embedded instructions in messages/images never override rules (`:171-172`).

## F. Payment & Preference Rules

FACT — Options only `full_payment`|`installments`; grep `partial_payment` in `request_payment_options.csv` = 0. Partial is custom 2-payment, not from options.
FACT — Full: `number_of_payments=1`, `payment_frequency_days` blank, `financing_fee=0`, `total=payment_amount` (`:2,:7,:9`). Installments: `payment_amount` per-installment, `first_payment_date` + `frequency_days` (28/30/31 sampled), `total = payment_amount×n + fee` within rounding (eg `:5 15952906.67×3+1840720.01=47858720.01`).
FACT — Eligibility: immediate `full|partial|installments` only if in `payment_methods_user_will_consider`; `wait` only if full becomes safe later + user accepts `full_payment`; else `not_recommended` (`problem_statement:189`). Rank: complete by deadline > no spending changes > minimize total > earlier start > fewer payments > lowest `payment_option_id`.
FACT — Partial constraints (`:146`): `allows_partial_payment=true` + user accepts `partial` + `0<safe<requested` + `earliest ≤ desired` + exactly `request_date:safe | earliest:(requested-safe)`, sum = requested. Eg `sample_requests.csv:20 request_19 2024-09-04:28820|2024-09-15:10840=39660`.
FACT — Installment must exactly match one supplied option (dates+amounts). Eg `sample_requests.csv:3 request_02 2025-08-08:15952906.67|2025-09-07:…|2025-10-07:…` = `payment_option_05`.
FACT — `max_installment_months` blank = reject all installments even if safe (eg `user_01` blank, `request_01` picks full despite 3 installment options). Duration ≈ `(n-1)×frequency/30` must be ≤ max; eg `request_03` max 2 rejects 21×/24× options → `wait`.
FACT — Spending changes: `none` or ≤3 `stop:<event_id>|reduce_to:<event_id>:<new>` (`:148-161`). Only recurring flexible; `stop`+`reduce` same event mutually exclusive, must be different events. `minimum_allowed_amount` is floor for `reduce_to`. Eg `request_11 reduce_to:event_989:665950` (floor `665950`), `request_21 stop:event_1815|reduce_to:event_1816:23.50`, `request_06 stop:event_476`.
FACT — `earliest_date…` independent of preferences (`:163`): can equal `request_date` even when method is installments because user refused full. Proved by `sample_requests.csv:13 request_12 earliest 2026-04-05=request_date` but method `installments` (user_12 `partial|installments,11` — no `full`).

## G. Sample Reconstruction

FACT — All 25 parsed:
- `01 affordable_now/full 2024-03-03:25256` — safe today, user allows full, no changes.
- `02 affordable_with_plan/installments 3×15952906.67` — pending `event_185` blocks full; salary rise `message_01` makes full safe `2025-09-15`; installments cheapest eligible completing by `2025-10-10`.
- `03 affordable_later/wait 2019-11-15:5491000` — safe `873000` today; max 2 rejects 21/24× installments; `allows_partial false`; blank salary `event_253` needs `image_01`.
- `04 affordable_later/wait 2024-06-15` — safe `8401800<12693000`.
- `05 not_affordable/not_recommended/none` — safe `737`, never completes by `2026-01-12`.
- `06 affordable_with_plan/full 2026-01-03:620.40 + stop:event_476, earliest 2026-01-15` — spending change enables full today; proves `affordable_with_plan` can pair with `full_payment`.
- `07 installments 3×68432` — user_07 `installments,12` only; earliest `2024-10-23`.
- `08 affordable_later/wait 2025-04-15`, `09 affordable_now/full 166.61`, `10 not_affordable` (safe `12700≪266700`).
- `11 affordable_with_plan/full today + reduce_to:event_989:665950` — change enables today.
- `12 affordable_with_plan/installments 3×22590.19` but earliest=`request_date` — proves preference-independence (user_12 no full).
- `13 affordable_later/wait`, `14 not_affordable` (safe `597` but never completes), `15 not_affordable`, `16 affordable_now/full 122500` (blank rent `event_1442` via `image_02`).
- `17 installments 3×95194.67`, `18 affordable_later/wait`, `19 partial_payment 28820|10840` — textbook partial.
- `20 not_affordable`, `21 full today + stop|reduce_to` (two different events), `22 installments 3×253.59`, `23 affordable_later/wait`, `24 not_affordable`, `25 not_affordable` (safe `1425000≪60496000`).
INFERENCE — Samples teach: always cite minimum kept (“leaves at least …”), `wait` plan = single `earliest:requested`, `not_affordable` plan=`none`+earliest empty.

## H. Edge Cases / Hidden-Test Risks

- Blank≠0; 16 image amounts mandatory. `image_02` total vs received vs due ambiguity — must define rule (likely total due) and freeze.
- Internal transfers (messages `BAN-0013/0023/0135/0213`) look like expense+income — net-zero, must deduplicate.
- Duplicates (`Possible duplicate…pending,event_…` 6 rows) + open dispute (no reversal) — safer to reserve once, not zero or twice.
- Cancelled auth + settled purchase sharing amount (`event_100 cancelled` vs `event_101 settled,event_100` `:101-102`) — must not double-reserve.
- Failed→scheduled retry (`event_5168 failed`→`5169 scheduled`) — count once on retry date, not both.
- Pending refund (`event_1785`, `3230`, `25342`) + “initiated not yet” messages — must not credit.
- Unrealized (`10 rows`) + “no units sold” messages — must not credit.
- One-time arrears/bonus/commission/prize-processing — must not forecast as recurring.
- Rent +12% and new childcare messages create step-change in recurrence — history mean underestimates.
- FX gaps: many `(date,pair)` missing (eg `2024-06-15` no `USD,IDR`); invented rates forbidden — need fallback (ignore foreign? use last prior? UNKNOWN — must freeze financially-safer choice).
- Installment duration vs `max_installment_months` rounding; `first_payment_date` may be after `request_date` (grace) or equal; fee makes total>requested — ranking prefers full when both safe.
- Partial exactness: two payments sum exactly, second on earliest, earliest ≤ desired; floating rounding (eg `166.61` vs `166.6` in `request_09`) — freeze rounding to 2dp.
- Spending-change validity: only flexible recurring in willing category, ≤3, no duplicate event across stop/reduce, `reduce_to` ≥ floor and < current.
- Instruction injection in messages/images — must ignore.

## I. Unknowns

UNKNOWN — Full distinct `event_type/category/source_type` sets; exact request/event date min/max; FX fallback when pair/date absent; variable-expense conservative estimator (max vs p90 vs mean+buffer); recurrence detection threshold (≥2 vs ≥3 occurrences, amount tolerance, cadence tolerance); whether 90-day window is inclusive and whether minimum must hold on every intermediate day vs settlement days only; rounding rules for installments/partial/FX; which receipt field is authoritative for `image_02`-type images; how to score childcare/rent-step messages when no explicit new amount (12% computable vs unknown childcare amount).

## J. Deterministic vs Model-Based

- Deterministic (code, no LLM): schema validation, joins, FX math, 90-day ledger, recurrence detection, reservation of pending/scheduled, ignoring failed/cancelled/unrealized/duplicates per status, eligibility filtering, ranking, plan assembly, all invariant checks, `amount_safe/earliest` search, usage-report token accounting.
- Model/vision required: extract 16 blank amounts from PNGs (payslip/invoice/receipt/ticket); interpret messages for salary change/date shift/bonus-pending/seasonal-end/new deduction/rent-hike/transfer-netting/refund-pending/unrealized/prize-state/invoice-confirmed/FX-note/employment-end/dispute-open; classify one-time vs recurring when description ambiguous; draft grounded `decision_explanation` citing kept minimum.
- Leakage guard: never use `sample_requests` labels for eval; never use organizer-only files; never invent income/expenses/options.

## K. Recommended State Representation

Per `(request_id,user_id,request_date)` build:
```
profile{home_currency,balance,minimum,protect[],can_reduce[],can_stop[],consider[],max_months}
request{type,amount,desired,allows_partial,text}
options[] {id,method,per_amt,n,first,freq,fee,total, duration_m, eligible_bool}
ledger_base: sorted dated cashflows in home_currency:
  settled debits/credits ≤ request_date (history for recurrence)
  pending debits (reserve on settlement_date)
  scheduled debits/credits (reserve/credit on settlement_date)
  overlays: message/image deltas (amended salary amt/date, rent×1.12, removed seasonal income, added childcare, net-zero transfers, confirmed invoice only, settled sale/reimbursement credited, pending/unrealized ignored) each with provenance (message_id/image_id/event_id) + conflict-resolution reason
recurring{essential_monthly_amt, flexible_candidates[] {event_id,category,flexibility,floor,next_dates}}
forecast[0..90]: balance[t] = balance + Σcredits≤t − Σdebits≤t − Σrecurring≤t
evaluated{safe_today, earliest_full, feasible_full, feasible_install_options[], feasible_partial_bool, feasible_with_changes[]}
decision{status,method,plan[],earliest,changes[],explanation}
```
All amounts home currency; FX applied at settlement-date rate; every overlay cites source.

## L. Tests & Invariants To Freeze

1. Schema: output columns order exact; 250 rows; IDs match `requests.csv`.
2. `0 ≤ amount_safe_to_pay ≤ requested_amount`; 2dp; `affordable_now ⇒ earliest=request_date`; `not_affordable ⇒ plan=none + earliest empty`; `wait ⇒ single earliest:requested`.
3. 90-day safety: replay ledger + plan, assert `balance[t] ≥ minimum` all 90 days and completion ≤ desired.
4. Installment exact-match: plan dates/amounts equal one supplied option; option eligible (consider + duration ≤ max); total minimal among eligible safe.
5. Partial: only if `allows_partial` + consider + `0<safe<requested` + earliest ≤ desired + exactly 2 entries summing to requested.
6. Spending: ≤3, `stop`/`reduce_to` syntax, targets exist, recurring, flexible (`stoppable→stop`, `reducible→reduce_to≥floor`, `reducible_or_stoppable→either`), category in willing lists, not protected, no event both stopped+reduced.
7. Currency: every foreign event converted via stated dated pair; no invented rates; output in home currency.
8. Duplicates/cancellations: failed/cancelled/unrealized contribute 0; pending credits 0; duplicate pair counted once; transfer pairs net-zero; retry counted once.
9. Message/image: blank amounts resolved (≠0, provenance `image_id`); newer amendment overrides; pending/unrealized messages respected; injection ignored.
10. Leakage: no `sample_requests` label reuse; no outside files; deterministic seed; `usage_report.md` with providers/models/calls/tokens/costs present.

# Usage Report — Buy or Wait? Pipeline Run

Generated: 2026-09-13T08:37:10
Dataset: `C:\Users\arsat\Downloads\hackerrank-sept\dataset`
Requests: 250 | Runtime: 12.31s (20.3052 req/s) | Pipeline failures: 0

## Models

| Role | Model |
|---|---|
| Primary extraction | `meta/muse-spark-1.3-contributor` |
| Independent extraction | `google/gemini-3.8-flash` |
| Verification controller | `meta/muse-spark-1.3-contributor` |

## Calls, tokens, and estimated cost

| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |
|---|---|---|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | 173 | 173 | 0 | 0 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | 209 | 209 | 0 | 0 |
| `meta/muse-spark-1.3-contributor` | verification_controller | 2 | 2 | 0 | 0 |
| **total** | | **384** | **384** | **0** | **0** |

| Model | Purpose | Estimated USD |
|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | $0.0000 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | $0.0000 |
| `meta/muse-spark-1.3-contributor` | verification_controller | $0.0000 |
| **total** | | **$0.0000** |

Average per request: 0 tokens, $0.0000.

## Extraction coverage and failures

- Extraction errors recorded: 0
- Rejected malformed claims: 4
- Pipeline exceptions (deterministic fallback): 0

## Attachment outcomes (claims)

| State | Count |
|---|---|
| attached | 0 |
| new_obligation | 529 |
| ambiguous | 291 |
| unresolved | 357 |

Top unresolved/ambiguous reasons:

- 291x multiple plausible existing events
- 133x no amount or explicit event reference to anchor attachment
- 63x amount and currency match but the dates are not compatible
- 52x new obligation is incomplete: date
- 36x no existing event matches the evidence
- 30x amount matches an event but the currency is incompatible
- 24x amount does not match any event and the evidence carries no date, category, or d
- 19x matching events exist but the lifecycle is incompatible

## Materiality and verification

| Materiality | Count |
|---|---|
| attachment_immaterial | 132 |
| attachment_material | 5 |
| attachment_none | 113 |
| immaterial | 243 |
| material | 7 |

- Verification gate used: 7 requests
- Verification failed closed: 1
- Conservative decisions (unresolved evidence): 0

## Decision distribution

| Status | Method | Count |
|---|---|---|
| affordable_later | wait | 30 |
| affordable_now | full_payment | 22 |
| affordable_with_plan | full_payment | 1 |
| affordable_with_plan | installments | 17 |
| affordable_with_plan | partial_payment | 6 |
| not_affordable | not_recommended | 174 |


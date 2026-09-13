# Usage Report — Buy or Wait? Pipeline Run

Generated: 2026-09-13T12:16:23
Dataset: `C:\Users\arsat\Downloads\hackerrank-sept\dataset`
Requests: 250 | Runtime: 823.96s (0.3034 req/s) | Pipeline failures: 0

## Models

| Role | Model |
|---|---|
| Primary extraction | `meta/muse-spark-1.3-contributor` |
| Independent extraction | `meta/muse-spark-1.3-contributor` |
| Verification controller | `meta/muse-spark-1.3-contributor` |

## Calls, tokens, and estimated cost

| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |
|---|---|---|---|---|---|
| `meta/muse-spark-1.3-contributor` | extraction_independent | 172 | 169 | 1505 | 14106 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | 209 | 0 | 120696 | 875187 |
| `meta/muse-spark-1.3-contributor` | verification_controller | 5 | 0 | 750 | 3558 |
| **total** | | **386** | **169** | **122951** | **892851** |

| Model | Purpose | Estimated USD |
|---|---|---|
| `meta/muse-spark-1.3-contributor` | extraction_independent | $0.0030 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | $0.1871 |
| `meta/muse-spark-1.3-contributor` | verification_controller | $0.0008 |
| **total** | | **$0.1909** |

Average per request: 4063 tokens, $0.0008.

## Extraction coverage and failures

- Extraction errors recorded: 0
- Rejected malformed claims: 0
- Pipeline exceptions (deterministic fallback): 0

## Attachment outcomes (claims)

| State | Count |
|---|---|
| attached | 0 |
| new_obligation | 492 |
| ambiguous | 288 |
| unresolved | 408 |

Top unresolved/ambiguous reasons:

- 288x multiple plausible existing events
- 132x no amount or explicit event reference to anchor attachment
- 80x amount and currency match but the dates are not compatible
- 58x new obligation is incomplete: date
- 40x amount does not match any event and the evidence carries no date, category, or d
- 40x amount matches an event but the currency is incompatible
- 30x matching events exist but the lifecycle is incompatible
- 28x no existing event matches the evidence

## Materiality and verification

| Materiality | Count |
|---|---|
| attachment_immaterial | 133 |
| attachment_material | 5 |
| attachment_none | 112 |
| immaterial | 244 |
| material | 6 |

- Verification gate used: 6 requests
- Verification failed closed: 1
- Conservative decisions (unresolved evidence): 0

## Decision distribution

| Status | Method | Count |
|---|---|---|
| affordable_later | wait | 30 |
| affordable_now | full_payment | 22 |
| affordable_with_plan | installments | 17 |
| affordable_with_plan | partial_payment | 6 |
| not_affordable | not_recommended | 175 |


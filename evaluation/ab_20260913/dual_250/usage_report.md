# Usage Report — Buy or Wait? Pipeline Run

Generated: 2026-09-13T12:24:36
Dataset: `C:\Users\arsat\Downloads\hackerrank-sept\dataset`
Requests: 250 | Runtime: 1315.18s (0.1901 req/s) | Pipeline failures: 0

## Models

| Role | Model |
|---|---|
| Primary extraction | `meta/muse-spark-1.3-contributor` |
| Independent extraction | `google/gemini-3.8-flash` |
| Verification controller | `meta/muse-spark-1.3-contributor` |

## Calls, tokens, and estimated cost

| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |
|---|---|---|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | 170 | 0 | 102870 | 319611 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | 209 | 0 | 120696 | 834213 |
| `meta/muse-spark-1.3-contributor` | verification_controller | 4 | 0 | 600 | 3077 |
| **total** | | **383** | **0** | **224166** | **1156901** |

| Model | Purpose | Estimated USD |
|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | $1.2757 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | $0.1789 |
| `meta/muse-spark-1.3-contributor` | verification_controller | $0.0007 |
| **total** | | **$1.4553** |

Average per request: 5524 tokens, $0.0058.

## Extraction coverage and failures

- Extraction errors recorded: 0
- Rejected malformed claims: 1
- Pipeline exceptions (deterministic fallback): 0

## Attachment outcomes (claims)

| State | Count |
|---|---|
| attached | 0 |
| new_obligation | 511 |
| ambiguous | 294 |
| unresolved | 378 |

Top unresolved/ambiguous reasons:

- 294x multiple plausible existing events
- 134x no amount or explicit event reference to anchor attachment
- 81x amount and currency match but the dates are not compatible
- 42x new obligation is incomplete: date
- 40x no existing event matches the evidence
- 32x amount does not match any event and the evidence carries no date, category, or d
- 30x amount matches an event but the currency is incompatible
- 19x matching events exist but the lifecycle is incompatible

## Materiality and verification

| Materiality | Count |
|---|---|
| attachment_immaterial | 132 |
| attachment_material | 5 |
| attachment_none | 113 |
| immaterial | 242 |
| material | 7 |
| unknown | 1 |

- Verification gate used: 8 requests
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


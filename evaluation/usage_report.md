# Usage Report — Buy or Wait? Pipeline Run

Generated: 2026-09-13T15:52:59
Dataset: `C:\Users\arsat\Downloads\hackerrank-sept\dataset`
Requests: 250 | Runtime: 392.83s (0.6364 req/s) | Pipeline failures: 0

## Models

| Role | Model |
|---|---|
| Primary extraction | `meta/muse-spark-1.3-contributor` |
| Independent extraction | `google/gemini-3.8-flash` |
| Verification controller | `meta/muse-spark-1.3-contributor` |

## Calls, tokens, and estimated cost

| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |
|---|---|---|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | 167 | 167 | 0 | 0 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | 209 | 209 | 0 | 0 |
| `meta/muse-spark-1.3-contributor` | verification_controller | 101 | 8 | 14503 | 74660 |
| **total** | | **477** | **384** | **14503** | **74660** |

| Model | Purpose | Estimated USD |
|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | $0.0000 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | $0.0000 |
| `meta/muse-spark-1.3-contributor` | verification_controller | $0.0164 |
| **total** | | **$0.0164** |

Average per request: 357 tokens, $0.0001.

## Extraction coverage and failures

- Extraction errors recorded: 0
- Rejected malformed claims: 378
- Pipeline exceptions (deterministic fallback): 0

## Attachment outcomes (claims)

| State | Count |
|---|---|
| attached | 0 |
| new_obligation | 328 |
| ambiguous | 344 |
| unresolved | 264 |

Top unresolved/ambiguous reasons:

- 121x conflicting values within the source for: direction
- 120x multiple plausible existing events
- 103x conflicting values within the source for: amount
- 91x no amount or explicit event reference to anchor attachment
- 42x new obligation is incomplete: date
- 39x amount and currency match but the dates are not compatible
- 31x no existing event matches the evidence
- 24x amount matches an event but the currency is incompatible
- 20x amount does not match any event and the evidence carries no date, category, or d
- 17x matching events exist but the lifecycle is incompatible

## Materiality and verification

| Materiality | Count |
|---|---|
| attachment_immaterial | 135 |
| attachment_material | 2 |
| attachment_none | 113 |
| immaterial | 230 |
| material | 4 |
| unknown | 16 |

- Verification gate used: 115 requests
- Verification failed closed: 0
- Conservative decisions (unresolved evidence): 0

## Decision distribution

| Status | Method | Count |
|---|---|---|
| affordable_later | wait | 26 |
| affordable_now | full_payment | 16 |
| affordable_with_plan | installments | 16 |
| affordable_with_plan | partial_payment | 5 |
| not_affordable | not_recommended | 187 |


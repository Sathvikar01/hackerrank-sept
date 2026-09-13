# Usage Report — Buy or Wait? Pipeline Run

Generated: 2026-09-13T12:01:35
Dataset: `C:\Users\arsat\Downloads\hackerrank-sept\evaluation\ab_20260913\gold25_dataset`
Requests: 25 | Runtime: 264.88s (0.0944 req/s) | Pipeline failures: 0

## Models

| Role | Model |
|---|---|
| Primary extraction | `meta/muse-spark-1.3-contributor` |
| Independent extraction | `google/gemini-3.8-flash` |
| Verification controller | `meta/muse-spark-1.3-contributor` |

## Calls, tokens, and estimated cost

| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |
|---|---|---|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | 18 | 0 | 14790 | 31334 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | 22 | 0 | 19180 | 90154 |
| **total** | | **40** | **0** | **33970** | **121488** |

| Model | Purpose | Estimated USD |
|---|---|---|
| `google/gemini-3.8-flash` | extraction_independent | $0.1286 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | $0.0199 |
| **total** | | **$0.1485** |

Average per request: 6218 tokens, $0.0059.

## Extraction coverage and failures

- Extraction errors recorded: 0
- Rejected malformed claims: 0
- Pipeline exceptions (deterministic fallback): 0

## Attachment outcomes (claims)

| State | Count |
|---|---|
| attached | 0 |
| new_obligation | 22 |
| ambiguous | 18 |
| unresolved | 37 |

Top unresolved/ambiguous reasons:

- 19x no amount or explicit event reference to anchor attachment
- 18x multiple plausible existing events
- 10x amount and currency match but the dates are not compatible
- 8x new obligation is incomplete: date

## Materiality and verification

| Materiality | Count |
|---|---|
| attachment_immaterial | 10 |
| attachment_none | 15 |
| immaterial | 24 |
| material | 1 |

- Verification gate used: 1 requests
- Verification failed closed: 0
- Conservative decisions (unresolved evidence): 0

## Decision distribution

| Status | Method | Count |
|---|---|---|
| affordable_later | wait | 1 |
| affordable_now | full_payment | 1 |
| affordable_with_plan | full_payment | 1 |
| affordable_with_plan | installments | 1 |
| not_affordable | not_recommended | 21 |


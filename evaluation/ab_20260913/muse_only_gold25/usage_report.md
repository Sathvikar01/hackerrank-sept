# Usage Report — Buy or Wait? Pipeline Run

Generated: 2026-09-13T12:00:06
Dataset: `C:\Users\arsat\Downloads\hackerrank-sept\evaluation\ab_20260913\gold25_dataset`
Requests: 25 | Runtime: 176.36s (0.1418 req/s) | Pipeline failures: 0

## Models

| Role | Model |
|---|---|
| Primary extraction | `meta/muse-spark-1.3-contributor` |
| Independent extraction | `meta/muse-spark-1.3-contributor` |
| Verification controller | `meta/muse-spark-1.3-contributor` |

## Calls, tokens, and estimated cost

| Model | Purpose | Calls | Cache hits | Prompt tokens | Completion tokens |
|---|---|---|---|---|---|
| `meta/muse-spark-1.3-contributor` | extraction_independent | 17 | 16 | 509 | 4260 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | 22 | 0 | 19180 | 93444 |
| **total** | | **39** | **16** | **19689** | **97704** |

| Model | Purpose | Estimated USD |
|---|---|---|
| `meta/muse-spark-1.3-contributor` | extraction_independent | $0.0009 |
| `meta/muse-spark-1.3-contributor` | extraction_primary | $0.0206 |
| **total** | | **$0.0215** |

Average per request: 4696 tokens, $0.0009.

## Extraction coverage and failures

- Extraction errors recorded: 0
- Rejected malformed claims: 3
- Pipeline exceptions (deterministic fallback): 0

## Attachment outcomes (claims)

| State | Count |
|---|---|
| attached | 0 |
| new_obligation | 28 |
| ambiguous | 18 |
| unresolved | 30 |

Top unresolved/ambiguous reasons:

- 18x multiple plausible existing events
- 12x no amount or explicit event reference to anchor attachment
- 10x amount and currency match but the dates are not compatible
- 8x new obligation is incomplete: date

## Materiality and verification

| Materiality | Count |
|---|---|
| attachment_immaterial | 9 |
| attachment_none | 16 |
| immaterial | 25 |

- Verification gate used: 0 requests
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


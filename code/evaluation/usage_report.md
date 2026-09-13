# Token Usage and Cost Analysis

Final full-dataset run: 250 requests, 2026-09-13, cache-backed rerun.
All 389 logical model calls were served from the immutable extraction/controller cache.

## Providers and models

| Provider | Model | Calls | Input tokens | Output tokens | Estimated cost |
|---|---|---:|---:|---:|---:|
| meta/muse | meta/muse-spark-1.3-contributor (primary extraction) | 209 | 0 | 0 | $0.0000 |
| google | google/gemini-3.8-flash (independent extraction) | 173 | 0 | 0 | $0.0000 |
| meta/muse | meta/muse-spark-1.3-contributor (verification controller) | 7 | 0 | 0 | $0.0000 |
| **total** | | **389** | **0** | **0** | **$0.0000** |

## Run totals

- Model calls: **389**
- Input tokens: **0**
- Output tokens: **0**
- Total tokens: **0**
- Average tokens per request: **0**
- Estimated total cost: **$0.0000**
- Estimated cost per request: **$0.0000**
- Cache hits: **389**
- Runtime: **50.93 s**

No API keys, credentials, or sensitive configuration are included.

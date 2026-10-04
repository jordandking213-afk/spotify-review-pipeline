# 100-review cost and runtime report

Recomputed offline from `cost/pilot_calls.jsonl` and `rates.csv` by `python3 cost/calculator.py` (no API key, no model calls).

## Measured: 100-review pilot

- Input: `cost_100.csv` SHA-256 `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e` (matches manifest); 100 IDs.
- Records: {'completed': 100}. Unique texts: 100. Result-cache reuse in cold run: 0 records.
- Workers: 1. Verification sample (declared): 20% of distinct texts. Run directory started empty: True.
- Cold wall-clock: **38.8 s** (stages: {'enrich': 19.602, 'verify': 2.67, 'group': 9.839, 'rank': 0.006, 'memo': 6.711}). Warm wall-clock: **0.0 s**.
- Warm run new enrichment calls: **0** (all other warm-run calls: 0).
- Cold API cost: **$0.003919**; warm incremental API cost: **$0.000000**; unresolved (unknown-usage) estimate: $0.000000.
- Cost per 1,000 inputs: $0.0392; per completed record: $0.000039; throughput: 2.58 reviews/s (cold).

### By stage (cold run)

| Stage | Provider / model | Config (model, effort, prompt, schema) | Max batch | Requests | Attempts | OK | Failed | Retries | Ordinary in | Cached in | Cache write | Output | (reasoning) | API cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich | openai / gpt-6-luna | `gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2` | 50 | 2 | 2 | 2 | 0 | 0 | 2,855 | 3,524 | 0 | 3,484 | 0 | $0.002063 |
| group | openai / gpt-6-luna | `gpt-6-luna|effort=none|group-v2|gschema-v2|issues-v1` | 41 | 1 | 1 | 1 | 0 | 0 | 2,416 | 0 | 0 | 1,432 | 0 | $0.000958 |
| memo | openai / gpt-6-luna | `gpt-6-luna|effort=none|memo-v2|mschema-v2` | 16 | 1 | 1 | 1 | 0 | 0 | 2,475 | 0 | 0 | 727 | 0 | $0.000611 |
| verify | openai / gpt-6-luna | `gpt-6-luna|effort=none|verify-v1|vschema-v1|labels-v2` | 20 | 1 | 1 | 1 | 0 | 0 | 1,100 | 0 | 0 | 356 | 0 | $0.000288 |

### Billing items (cold + warm)

| Model | Item | Billed units | Price | Cost | Source (checked) |
|---|---|---|---|---|---|
| gpt-6-luna | cache_write | 0 | $0.125 per 1,000,000 tokens | $0.000000 | https://developers.openai.com/api/docs/guides/prompt-caching (2026-10-03) |
| gpt-6-luna | cached_input | 3,524 | $0.01 per 1,000,000 tokens | $0.000035 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | ordinary_input | 8,846 | $0.10 per 1,000,000 tokens | $0.000885 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | output | 5,999 | $0.50 per 1,000,000 tokens | $0.002999 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |

Reasoning tokens are included in output tokens by the provider and are not billed again.
Local compute: Runs on a laptop. Electricity and hardware wear were not measured: reported as unknown, not zero.

## Estimated: full run (assumptions in `cost/assumptions.json`)

Scope: 660,622 rows; 660,609 nonempty; 13 empty-text quarantines; 484,189 distinct texts sent once with exact-text reuse.

Measured per-unit inputs: {'system_prompt_tokens_per_request': 1762.0, 'ordinary_input_tokens_per_review': 28.55, 'output_tokens_per_review': 34.84, 'seconds_per_enrich_request': 9.79, 'verify_usd_per_review': 1.4400000000000001e-05, 'pilot_issue_count': 18}

| Scenario | Enrich | Enrich without reuse (comparison) | Verify | Group | Memo | Fallback | **Total API** | Budget |
|---|---|---|---|---|---|---|---|---|
| base | $10.30 | $14.05 | $0.3521 (24,209 reviews) | $0.001596 | $0.000611 | $0.000000 | **$10.65** | within $45.00 |
| conservative | $14.96 | $20.41 | $0.4759 (24,209 reviews) | $0.002075 | $0.000916 | $0.000000 | **$15.44** | within $45.00 |

| Scenario | Workers | Hours (enrich + verify) | Requests/min | Tokens/min | Within provider limits |
|---|---|---|---|---|---|
| base | 1 | 27.22 | 6.1 | 30,224 | yes |
| base | 2 | 13.61 | 12.3 | 60,447 | yes |
| base | 4 | 6.81 | 24.5 | 120,895 | yes |
| conservative | 1 | 43.99 | 6.1 | 30,224 | yes |
| conservative | 2 | 22.0 | 12.3 | 60,447 | yes |
| conservative | 4 | 11.0 | 24.5 | 120,895 | yes |

## Controls

- Spending limit: $45.00 (enforced in code before each request, counting in-flight reservations).
- Output-token cap: 4,000 per request; worst case if every enrichment request hit it: $19.37.
- Maximum workers: 4. Fallback fraction: 0.0 — No stronger-model fallback is configured; invalid output is retried once with the same model, then quarantined.
- Retries: transient errors up to 3 attempts with exponential backoff and jitter; invalid output re-sent once in smaller requests, then quarantined.

Measured values come only from the pilot evidence files; editing `assumptions.json` or `rates.csv` changes projections and prices, never the measured usage or time.

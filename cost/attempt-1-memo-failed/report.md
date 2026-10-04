# 100-review cost and runtime report

Recomputed offline from `cost/pilot_calls.jsonl` and `rates.csv` by `python3 cost/calculator.py` (no API key, no model calls).

## Measured: 100-review pilot

- Input: `cost_100.csv` SHA-256 `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e` (matches manifest); 100 IDs.
- Records: {'completed': 100}. Unique texts: 100. Result-cache reuse in cold run: 0 records.
- Workers: 1. Verification sample (declared): 20% of distinct texts. Run directory started empty: True.
- Cold wall-clock: **45.0 s** (stages: {'enrich': 19.728, 'verify': 3.427, 'group': 10.026, 'rank': 0.009, 'memo': 11.722}). Warm wall-clock: **10.5 s**.
- Warm run new enrichment calls: **0** (all other warm-run calls: 2).
- Cold API cost: **$0.004440**; warm incremental API cost: **$0.001054**; unresolved (unknown-usage) estimate: $0.000000.
- Cost per 1,000 inputs: $0.0444; per completed record: $0.000044; throughput: 2.22 reviews/s (cold).

### By stage (cold run)

| Stage | Provider / model | Config (model, effort, prompt, schema) | Max batch | Requests | Attempts | OK | Failed | Retries | Ordinary in | Cached in | Cache write | Output | (reasoning) | API cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich | openai / gpt-6-luna | `gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2` | 50 | 2 | 2 | 2 | 0 | 0 | 2,855 | 3,524 | 0 | 3,480 | 0 | $0.002061 |
| group | openai / gpt-6-luna | `gpt-6-luna|effort=none|group-v1|gschema-v1|issues-v1` | 43 | 1 | 1 | 1 | 0 | 0 | 2,453 | 0 | 0 | 1,436 | 0 | $0.000963 |
| memo | openai / gpt-6-luna | `gpt-6-luna|effort=none|memo-v1|mschema-v1` | 16 | 2 | 2 | 0 | 2 | 1 | 4,740 | 0 | 0 | 1,308 | 0 | $0.001128 |
| verify | openai / gpt-6-luna | `gpt-6-luna|effort=none|verify-v1|vschema-v1|labels-v2` | 20 | 1 | 1 | 1 | 0 | 0 | 1,100 | 0 | 0 | 356 | 0 | $0.000288 |

### Billing items (cold + warm)

| Model | Item | Billed units | Price | Cost | Source (checked) |
|---|---|---|---|---|---|
| gpt-6-luna | cache_write | 0 | $0.125 per 1,000,000 tokens | $0.000000 | https://developers.openai.com/api/docs/guides/prompt-caching (2026-10-03) |
| gpt-6-luna | cached_input | 3,524 | $0.01 per 1,000,000 tokens | $0.000035 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | ordinary_input | 15,888 | $0.10 per 1,000,000 tokens | $0.001589 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | output | 7,741 | $0.50 per 1,000,000 tokens | $0.003870 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |

Reasoning tokens are included in output tokens by the provider and are not billed again.
Local compute: Runs on a laptop. Electricity and hardware wear were not measured: reported as unknown, not zero.

## Estimated: full run (assumptions in `cost/assumptions.json`)

Scope: 660,622 rows; 660,609 nonempty; 13 empty-text quarantines; 484,189 distinct texts sent once with exact-text reuse.

Measured per-unit inputs: {'system_prompt_tokens_per_request': 1762.0, 'ordinary_input_tokens_per_review': 28.55, 'output_tokens_per_review': 34.8, 'seconds_per_enrich_request': 9.734, 'verify_usd_per_review': 1.4400000000000001e-05, 'pilot_issue_count': 19}

| Scenario | Enrich | Enrich without reuse (comparison) | Verify | Group | Memo | Fallback | **Total API** | Budget |
|---|---|---|---|---|---|---|---|---|
| base | $10.29 | $14.04 | $0.3521 (24,209 reviews) | $0.001521 | $0.001128 | $0.000000 | **$10.64** | within $45.00 |
| conservative | $14.94 | $20.39 | $0.4759 (24,209 reviews) | $0.001977 | $0.001692 | $0.000000 | **$15.42** | within $45.00 |

| Scenario | Workers | Hours (enrich + verify) | Requests/min | Tokens/min | Within provider limits |
|---|---|---|---|---|---|
| base | 1 | 27.16 | 6.2 | 30,385 | yes |
| base | 2 | 13.58 | 12.3 | 60,770 | yes |
| base | 4 | 6.79 | 24.7 | 121,541 | yes |
| conservative | 1 | 43.88 | 6.2 | 30,385 | yes |
| conservative | 2 | 21.94 | 12.3 | 60,770 | yes |
| conservative | 4 | 10.97 | 24.7 | 121,541 | yes |

## Controls

- Spending limit: $45.00 (enforced in code before each request, counting in-flight reservations).
- Output-token cap: 4,000 per request; worst case if every enrichment request hit it: $19.37.
- Maximum workers: 4. Fallback fraction: 0.0 — No stronger-model fallback is configured; invalid output is retried once with the same model, then quarantined.
- Retries: transient errors up to 3 attempts with exponential backoff and jitter; invalid output re-sent once in smaller requests, then quarantined.

Measured values come only from the pilot evidence files; editing `assumptions.json` or `rates.csv` changes projections and prices, never the measured usage or time.

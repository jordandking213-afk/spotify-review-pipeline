# 10000-review cost and runtime report (analysis_10000.csv)

Recomputed offline from `cost/analysis_10000-4w/pilot_calls.jsonl` and `rates.csv` by `python3 cost/calculator.py` (no API key, no model calls).

## Measured: 10000-review run

- Input: `analysis_10000.csv` SHA-256 `eaa62ca6d44d717302904a9c922e99b0b4584d174309cb45295ecbc2ba2a91b5` (matches manifest); 10000 IDs.
- Records: {'completed': 10000}. Unique texts: 8448. Result-cache reuse in cold run: 1552 records.
- Workers: 4. Verification sample (declared): 5% of distinct texts. Run directory started empty: True.
- Cold wall-clock: **518.5 s** (stages: {'enrich': 444.244, 'verify': 49.085, 'group': 19.231, 'rank': 0.106, 'memo': 5.795}). Warm wall-clock: **0.7 s**.
- Warm run new enrichment calls: **0** (all other warm-run calls: 0).
- Cold API cost: **$0.1904**; warm incremental API cost: **$0.000000**; unresolved (unknown-usage) estimate: $0.000000.
- Cost per 1,000 inputs: $0.0190; per completed record: $0.000019; throughput: 19.29 reviews/s (cold).

### By stage (cold run)

| Stage | Provider / model | Config (model, effort, prompt, schema) | Max batch | Requests | Attempts | OK | Failed | Retries | Ordinary in | Cached in | Cache write | Output | (reasoning) | API cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich | openai / gpt-6-luna | `gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2` | 50 | 184 | 184 | 181 | 3 | 15 | 248,410 | 324,208 | 0 | 307,787 | 0 | $0.1820 |
| group | openai / gpt-6-luna | `gpt-6-luna|effort=none|group-v2|gschema-v2|issues-v1` | 168 | 1 | 1 | 1 | 0 | 0 | 8,062 | 0 | 0 | 3,020 | 0 | $0.002316 |
| memo | openai / gpt-6-luna | `gpt-6-luna|effort=none|memo-v2|mschema-v2` | 18 | 1 | 1 | 1 | 0 | 0 | 2,666 | 0 | 0 | 615 | 0 | $0.000574 |
| verify | openai / gpt-6-luna | `gpt-6-luna|effort=none|verify-v1|vschema-v1|labels-v2` | 50 | 9 | 9 | 9 | 0 | 0 | 18,876 | 0 | 0 | 7,379 | 0 | $0.005577 |

### Billing items (cold + warm)

| Model | Item | Billed units | Price | Cost | Source (checked) |
|---|---|---|---|---|---|
| gpt-6-luna | cache_write | 0 | $0.125 per 1,000,000 tokens | $0.000000 | https://developers.openai.com/api/docs/guides/prompt-caching (2026-10-03) |
| gpt-6-luna | cached_input | 324,208 | $0.01 per 1,000,000 tokens | $0.003242 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | ordinary_input | 278,014 | $0.10 per 1,000,000 tokens | $0.0278 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | output | 318,801 | $0.50 per 1,000,000 tokens | $0.1594 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |

Reasoning tokens are included in output tokens by the provider and are not billed again.
Local compute: Runs on a laptop. Electricity and hardware wear were not measured: reported as unknown, not zero.

## Estimated: full run (assumptions in `cost/assumptions.json`)

Scope: 660,622 rows; 660,609 nonempty; 13 empty-text quarantines; 484,189 distinct texts sent once with exact-text reuse.

Measured per-unit inputs: {'system_prompt_tokens_per_request': 1762.0, 'ordinary_input_tokens_per_review': 29.4, 'output_tokens_per_review': 36.43, 'seconds_per_enrich_request': 9.61, 'verify_usd_per_review': 1.3310501193317422e-05, 'pilot_issue_count': 28}

| Scenario | Enrich | Enrich without reuse (comparison) | Verify | Group | Memo | Fallback | **Total API** | Budget |
|---|---|---|---|---|---|---|---|---|
| base | $10.74 | $14.65 | $0.3255 (24,209 reviews) | $0.002482 | $0.000574 | $0.000000 | **$11.07** | within $45.00 |
| conservative | $15.60 | $21.28 | $0.4399 (24,209 reviews) | $0.003226 | $0.000861 | $0.000000 | **$16.04** | within $45.00 |

| Scenario | Workers | Hours (enrich + verify) | Requests/min | Tokens/min | Within provider limits |
|---|---|---|---|---|---|
| base | 1 | 27.1 | 6.2 | 31,554 | yes |
| base | 2 | 13.55 | 12.5 | 63,109 | yes |
| base | 4 | 6.77 | 25.0 | 126,218 | yes |
| conservative | 1 | 43.75 | 6.2 | 31,554 | yes |
| conservative | 2 | 21.87 | 12.5 | 63,109 | yes |
| conservative | 4 | 10.94 | 25.0 | 126,218 | yes |

## Controls

- Spending limit: $45.00 (enforced in code before each request, counting in-flight reservations).
- Output-token cap: 4,000 per request; worst case if every enrichment request hit it: $19.37.
- Maximum workers: 4. Fallback fraction: 0.0 — No stronger-model fallback is configured; invalid output is retried once with the same model, then quarantined.
- Retries: transient errors up to 3 attempts with exponential backoff and jitter; invalid output re-sent once in smaller requests, then quarantined.

Measured values come only from the pilot evidence files; editing `assumptions.json` or `rates.csv` changes projections and prices, never the measured usage or time.

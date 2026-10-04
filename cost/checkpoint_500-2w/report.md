# 500-review cost and runtime report (checkpoint_500.csv)

Recomputed offline from `cost/checkpoint_500-2w/pilot_calls.jsonl` and `rates.csv` by `python3 cost/calculator.py` (no API key, no model calls).

## Measured: 500-review run

- Input: `checkpoint_500.csv` SHA-256 `a94e31663ee7b7eaa77e23b7a8425b530cc0c866ed5e714953172a0afef6a12f` (matches manifest); 500 IDs.
- Records: {'completed': 500}. Unique texts: 479. Result-cache reuse in cold run: 21 records.
- Workers: 2. Verification sample (declared): 5% of distinct texts. Run directory started empty: True.
- Cold wall-clock: **64.0 s** (stages: {'enrich': 44.229, 'verify': 3.291, 'group': 11.581, 'rank': 0.012, 'memo': 4.849}). Warm wall-clock: **0.1 s**.
- Warm run new enrichment calls: **0** (all other warm-run calls: 0).
- Cold API cost: **$0.0124**; warm incremental API cost: **$0.000000**; unresolved (unknown-usage) estimate: $0.000000.
- Cost per 1,000 inputs: $0.0247; per completed record: $0.000025; throughput: 7.82 reviews/s (cold).

### By stage (cold run)

| Stage | Provider / model | Config (model, effort, prompt, schema) | Max batch | Requests | Attempts | OK | Failed | Retries | Ordinary in | Cached in | Cache write | Output | (reasoning) | API cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich | openai / gpt-6-luna | `gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2` | 50 | 10 | 10 | 10 | 0 | 0 | 13,313 | 17,620 | 0 | 16,765 | 0 | $0.009890 |
| group | openai / gpt-6-luna | `gpt-6-luna|effort=none|group-v2|gschema-v2|issues-v1` | 97 | 1 | 1 | 1 | 0 | 0 | 4,933 | 0 | 0 | 2,190 | 0 | $0.001588 |
| memo | openai / gpt-6-luna | `gpt-6-luna|effort=none|memo-v2|mschema-v2` | 18 | 1 | 1 | 1 | 0 | 0 | 2,661 | 0 | 0 | 538 | 0 | $0.000535 |
| verify | openai / gpt-6-luna | `gpt-6-luna|effort=none|verify-v1|vschema-v1|labels-v2` | 25 | 1 | 1 | 1 | 0 | 0 | 1,357 | 0 | 0 | 443 | 0 | $0.000357 |

### Billing items (cold + warm)

| Model | Item | Billed units | Price | Cost | Source (checked) |
|---|---|---|---|---|---|
| gpt-6-luna | cache_write | 0 | $0.125 per 1,000,000 tokens | $0.000000 | https://developers.openai.com/api/docs/guides/prompt-caching (2026-10-03) |
| gpt-6-luna | cached_input | 17,620 | $0.01 per 1,000,000 tokens | $0.000176 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | ordinary_input | 22,264 | $0.10 per 1,000,000 tokens | $0.002226 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |
| gpt-6-luna | output | 19,936 | $0.50 per 1,000,000 tokens | $0.009968 | https://developers.openai.com/api/docs/models/gpt-6-luna (2026-10-03) |

Reasoning tokens are included in output tokens by the provider and are not billed again.
Local compute: Runs on a laptop. Electricity and hardware wear were not measured: reported as unknown, not zero.

## Estimated: full run (assumptions in `cost/assumptions.json`)

Scope: 660,622 rows; 660,609 nonempty; 13 empty-text quarantines; 484,189 distinct texts sent once with exact-text reuse.

Measured per-unit inputs: {'system_prompt_tokens_per_request': 1762.0, 'ordinary_input_tokens_per_review': 27.79, 'output_tokens_per_review': 35.0, 'seconds_per_enrich_request': 8.569, 'verify_usd_per_review': 1.4288000000000001e-05, 'pilot_issue_count': 24}

| Scenario | Enrich | Enrich without reuse (comparison) | Verify | Group | Memo | Fallback | **Total API** | Budget |
|---|---|---|---|---|---|---|---|---|
| base | $10.30 | $14.05 | $0.3494 (24,209 reviews) | $0.001985 | $0.000535 | $0.000000 | **$10.65** | within $45.00 |
| conservative | $14.96 | $20.41 | $0.4722 (24,209 reviews) | $0.002581 | $0.000803 | $0.000000 | **$15.43** | within $45.00 |

| Scenario | Workers | Hours (enrich + verify) | Requests/min | Tokens/min | Within provider limits |
|---|---|---|---|---|---|
| base | 1 | 23.95 | 7.0 | 34,320 | yes |
| base | 2 | 11.97 | 14.0 | 68,640 | yes |
| base | 4 | 5.99 | 28.0 | 137,281 | yes |
| conservative | 1 | 38.69 | 7.0 | 34,320 | yes |
| conservative | 2 | 19.34 | 14.0 | 68,640 | yes |
| conservative | 4 | 9.67 | 28.0 | 137,281 | yes |

## Controls

- Spending limit: $45.00 (enforced in code before each request, counting in-flight reservations).
- Output-token cap: 4,000 per request; worst case if every enrichment request hit it: $19.37.
- Maximum workers: 4. Fallback fraction: 0.0 — No stronger-model fallback is configured; invalid output is retried once with the same model, then quarantined.
- Retries: transient errors up to 3 attempts with exponential backoff and jitter; invalid output re-sent once in smaller requests, then quarantined.

Measured values come only from the pilot evidence files; editing `assumptions.json` or `rates.csv` changes projections and prices, never the measured usage or time.

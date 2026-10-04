"""Versioned settings for the pipeline. Changing anything that affects labels changes LABEL_CONFIG,
which forces new model work instead of reusing results produced under different settings."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROMPTS = REPO / "prompts"
RUNS = REPO / "runs"

# Enrichment model and label settings (all part of label_config).
ENRICH_MODEL = "gpt-6-luna"
ENRICH_EFFORT = "none"
PROMPT_VERSION = "enrich-v1"
SCHEMA_VERSION = "schema-v1"
LABELS_VERSION = "labels-v1"
LABEL_CONFIG = f"{ENRICH_MODEL}|effort={ENRICH_EFFORT}|{PROMPT_VERSION}|{SCHEMA_VERSION}|{LABELS_VERSION}"

# Bounds on every enrichment request.
MAX_BATCH = 50              # contract limit: at most 50 reviews per request
RETRY_BATCH = 10            # invalid items are re-sent once, in smaller requests
MAX_OUTPUT_TOKENS = 4000    # ~50 reviews x ~35 tokens, with headroom; caps cost per call
TRANSIENT_ATTEMPTS = 3      # attempts per request for rate limits / server errors / timeouts
BACKOFF_BASE_S = 2.0        # exponential backoff base, with jitter
STOP_AFTER_CONSECUTIVE_FAILURES = 5

# Spending controls (Jordan, 2026-10-03: $50 balance, $45 cap).
SPEND_CAP_USD = 45.00
DEFAULT_WORKERS = 1

# Prices in USD per 1M tokens, standard tier, checked 2026-10-03:
#   https://developers.openai.com/api/docs/models/gpt-6-luna (input, cached input, output)
#   https://developers.openai.com/api/docs/guides/prompt-caching (cache writes = 1.25x uncached input)
# Ordinary input, cache reads, cache writes and output are mutually exclusive billing items.
RATES = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50, "checked": "2026-10-03"},
    "fake-model": {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50, "checked": "simulated"},
}
REQUEST_TIMEOUT_S = 120

QUARANTINE_EMPTY = "empty_review_text"
QUARANTINE_INVALID = "invalid_output_after_retry"
QUARANTINE_DUP_OF_QUARANTINED = "duplicate_of_quarantined_text"

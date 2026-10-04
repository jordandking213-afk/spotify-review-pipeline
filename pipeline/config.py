"""Versioned settings for the pipeline. Changing anything that affects labels changes LABEL_CONFIG,
which forces new model work instead of reusing results produced under different settings."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROMPTS = REPO / "prompts"
RUNS = REPO / "runs"

# Enrichment model and label settings (all part of label_config).
ENRICH_MODEL = "gpt-6-luna"
ENRICH_EFFORT = "none"
PROMPT_VERSION = "enrich-v2"
SCHEMA_VERSION = "schema-v2"
LABELS_VERSION = "labels-v2"   # v1 = earlier draft, used only by the 5-review connection test
PROMPT_FILE = PROMPTS / "enrich_v2.system.md"
SCHEMA_FILE = PROMPTS / "enrich_v2.schema.json"
LABEL_CONFIG = f"{ENRICH_MODEL}|effort={ENRICH_EFFORT}|{PROMPT_VERSION}|{SCHEMA_VERSION}|{LABELS_VERSION}"

# Verification role: a separate prompt that re-labels a declared random sample without seeing the first labels.
VERIFY_MODEL = ENRICH_MODEL
VERIFY_EFFORT = "none"
VERIFY_PROMPT_VERSION = "verify-v1"
VERIFY_PROMPT_FILE = PROMPTS / "verify_v1.system.md"
VERIFY_SCHEMA_FILE = PROMPTS / "verify_v1.schema.json"
VERIFY_CONFIG = f"{VERIFY_MODEL}|effort={VERIFY_EFFORT}|{VERIFY_PROMPT_VERSION}|vschema-v1|{LABELS_VERSION}"
VERIFY_RATE = 0.05          # declared sample: 5% of distinct completed texts in the full run (Jordan, 2026-10-03)
VERIFY_RATE_PILOT = 0.20    # declared sample for the 100-review pilot (Jordan, 2026-10-03)
VERIFY_SEED = "verify-v1"   # sample = reviews whose SHA-256(seed:review_id) falls below the rate; reproducible

# Grouping role: code assigns issues; the model only names them from a bounded evidence pack.
GROUP_PROMPT_FILE = PROMPTS / "group_v1.system.md"
GROUP_SCHEMA_FILE = PROMPTS / "group_v1.schema.json"
GROUP_CONFIG = f"{ENRICH_MODEL}|effort=none|group-v1|gschema-v1|issues-v1"
GROUP_EXAMPLES_PER_ISSUE = 6
GROUP_QUOTE_CHARS = 200

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

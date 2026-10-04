# Pilot attempt 1 (2026-10-04 01:37 UTC): memo failed its checks. Kept as evidence of a real failure.

- Enrichment, verification, grouping and ranking completed; warm run made 0 new enrichment calls.
- The memo was rejected by code four times (twice cold, twice warm, one retry each), so no memo was written and the
  warm run made 2 memo calls instead of 0.
- Root cause (a pipeline bug, not a model fault): the fixed limitations text given to the memo model contained
  dates (digits), while the memo rules forbid any digit outside code-computed references. One attempt also failed
  "recommendation cites no claim". The error message also printed `[]` instead of the offending text.
- Fixes: digit-free limitations text, explicit memo requirements (memo-v2 prompt), digit-free issue names
  (group-v2), corrected error message. The pilot was then re-run from an empty result cache.
- Provider prompt cache: the enrichment instructions were already cached by OpenAI from the v2 connection test
  minutes earlier, so this attempt shows cache reads and no cache writes. Our own result cache started empty.
- Cost of this attempt: $0.005495 (cold $0.004440 + warm memo retries $0.001054), all usage measured.

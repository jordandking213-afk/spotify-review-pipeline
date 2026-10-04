# Record schema and enrichment output — DRAFT v0 (not yet approved)

This file says **who produces each field** (the model, or code) and **what the model is allowed to return**.
The design goal is that the model makes only the language judgments, while code does everything that can be
done exactly, keeping output tokens (the main cost) small.

## 1. Final record (one per source review ID) — required by `GRADING_CONTRACT.md`

| Field | Type | Produced by | How |
|---|---|---|---|
| `review_id` | string | code | Copied from the source row, never from model output |
| `source_sha256` | string | code | The course's `row_sha` helper over the six original fields |
| `status` | `completed` / `quarantined` / `pending` | code | Set by the orchestrator after validation |
| `reason` | string | code | Quarantined only, e.g. `empty_review_text`, `invalid_output_after_retry` |
| `topic` | one of 8 | **model** | Official topics |
| `intent` | one of 5 | **model** | Official intents |
| `severity` | int 1–5 | **model** | Official scale and Jordan's decisions |
| `sentiment` | number −1..1 | **model** | One of the five anchors: −1, −0.5, 0, 0.5, 1 |
| `evidence_quote` | string | **model picks, code copies** | The model returns a *segment number*; code copies that segment's exact text (see §3) |
| `entities` | list of strings | code | Matched against a fixed feature vocabulary (decision 8) |
| `needs_review` | bool | **model** | `true` when the model returns a review reason (see §2) |
| `review_flag` | string or null | **model** | Why it needs review; kept as the "preserved reason" the assignment asks for |
| `label_config` | string | code | e.g. `gpt-6-luna|effort=none|enrich-v1|schema-v1|labels-v1` |
| `cache_source_id` | string | code | Only on exact-duplicate texts reusing a completed original's result |

Star rating, likes, app version and timestamp are **never sent to the model** (the contract's
`classification_input_fields` is `["review_text"]`). They are kept for analysis only.

## 2. What the model returns per review (compact JSON, strict schema)

```json
{"i": 3, "t": "playback", "n": "complaint", "s": 3, "m": -0.5, "q": 1, "f": null}
```

| Key | Meaning | Allowed values |
|---|---|---|
| `i` | Review number within this request (1–50) | integer; code maps it back to the real `review_id` |
| `t` | topic | the 8 official topic names |
| `n` | intent | the 5 official intent names |
| `s` | severity | 1, 2, 3, 4, 5 |
| `m` | sentiment | −1, −0.5, 0, 0.5, 1 |
| `q` | evidence segment number | integer, must exist in that review |
| `f` | review flag | `null`, or one of `speculative`, `unclear_language`, `sarcasm_or_irony`, `missing_context`, `tie_order` |

**Why short keys and numbers:** output tokens cost 5× input tokens. Single-letter keys, a segment number instead
of a copied quote, and a short request number instead of a 36-character UUID keep each review's answer to roughly
25–35 output tokens. The full names are restored by code.

## 3. Evidence segments (code, deterministic)

Before sending, code splits each review into numbered **segments**: at line breaks, and after `.`, `!` or `?`
followed by a space. Each segment is stripped of leading/trailing whitespace, so it is still an **exact
substring** of the original text. A one-sentence review has one segment, and its quote is the whole review.
This guarantees that every `evidence_quote` passes the checker's exact-substring test. Whether the quote
*supports* the label is still checked by evaluation.

## 4. Validation (code, after every request)

A request's output is accepted only if:
1. It parses against the strict JSON schema.
2. The set of returned `i` values equals exactly the set sent: no missing, extra or duplicate numbers.
3. Every `q` is a real segment number for that review.

**Failure behavior:** reviews whose items fail validation are re-sent **once** in a smaller request. If they fail
again, they are saved as `quarantined` with reason `invalid_output_after_retry` and the attempt count. Valid items
from the same request are saved; one bad item never loses the whole batch. Results are written atomically after
every request.

## 5. Exact-duplicate reuse

Texts are compared byte for byte. The first occurrence is sent to the model. Every other row with the identical
text and the same `label_config` gets a copy of the labels plus `cache_source_id` pointing directly at that
original. Each original `review_id` remains its own row and is counted separately in aggregates.

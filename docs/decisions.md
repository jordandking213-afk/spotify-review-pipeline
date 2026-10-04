# Pipeline decision log

Design decisions about the pipeline (label decisions live in `labels/definitions.md`, section 7).
"Jordan's reasoning" is Jordan's own wording, word for word.

| Date | Decision | Jordan's reasoning | Notes |
|---|---|---|---|
| 2026-10-03 | Enrichment model **GPT-6 Luna** (`gpt-6-luna`), standard API, not Batch | — | Chosen over a free local model on an 8 GB M1 to remove the risk of a multi-day run missing the deadline |
| 2026-10-03 | **$50** prepaid balance, code spend cap **$45** | — | $5 buffer for provider billing lag |
| 2026-10-03 | Verification sample **5%** of distinct completed texts in the full run | "5% full for the independent check as the scale should be large enough" | About 24,000 reviews |
| 2026-10-03 | Verification sample **20%** in the 100-review pilot | "20% pilot is a bit larger to give a meaningful sample" | About 20 reviews; 5% would be about 5 |
| 2026-10-03 | Verifier reasoning effort **none** | "effort none to save on cost" | Same model as enrichment; independence comes from a separate rubric-only prompt that never sees the first labels |

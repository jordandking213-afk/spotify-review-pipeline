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
| 2026-10-03 | Issue rules **issues-v1** accepted (`pipeline/issues.py`): code assigns each complaint/cancellation to one `topic.facet` issue; the model only names issues | — | Jordan accepted the rules as proposed |
| 2026-10-03 | Memo design approved: model cites code-computed claims by ID and cannot write digits itself; code rejects unknown claims, digits outside claim references, and review IDs outside the evidence pack; area totals reported as separately labeled quantities | — | Jordan approved the design as proposed |
| 2026-10-03 | Second business ranking excluding `other.general`: **deferred** until the pilot shows that issue's size | — | Required baseline ranking is unaffected |
| 2026-10-03 | **Add a business ranking** that excludes `other.general` (vague catch-all complaints), clearly labeled; the required baseline is unchanged | — | Jordan chose option (a); on 10,000 reviews `other.general` ranked first |
| 2026-10-03 | Memo criterion: **total severity first** (the baseline priority score), with **mean severity as a named secondary consideration** | — | Jordan chose option (b); implemented as prompt memo-v3 |
| 2026-10-03 | Full run with **4 workers** | — | The highest worker count measured (10,000 checkpoint); ~7 h base, ~11 h conservative |
| 2026-10-04 | Memo recommendation decided at the **issue level** (option b): the area containing the top specific issue, with area totals reported honestly | — | After Jordan's inspection caught memo-v3 stating playback had the highest area severity sum (160,236) when usability's was larger (179,800). memo-v3 output kept in `evals/memo-inspection/` |

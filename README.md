# Spotify review pipeline: where should Spotify's next quarter of product effort go?

> **DRAFT OUTLINE.** Sections marked **✍️ JORDAN — OWN WORDS** are intentionally blank and must be written by Jordan.
> Any hint text inside them is *suggested text only* and must be rewritten in his own words. Numbers marked
> **(after full run)** are filled in from saved outputs once the full run finishes.

A multi-agent pipeline that classifies all 660,622 Spotify Google Play reviews (May 2022 – November 2023) and turns
them into a product recommendation in which every number traces back to saved calculations and review IDs.

**Grader entry points:** [rubric map](#rubric-map) · [results](#results-summary) · [decision memo](#decision-memo) ·
[grading export](grading/) · [cost calculator](cost/README.md) · [golden evaluation](evals/golden/results_v1/summary.md)

---

## Rubric map

| Rubric criterion | Evidence |
|---|---|
| **Deliverable quality (4)** | |
| Accessible code/setup and artifacts | [Setup](#setup-and-commands); standard library only; offline replay and re-ranking need no key |
| Clear architecture, shared schema, provenance | [Architecture](#architecture); [labels/definitions.md](labels/definitions.md); [labels/record_schema.md](labels/record_schema.md); `label_config` on every record and call |
| Memo numbers linked to calculations and evidence | [Memo](#decision-memo) cites `C#` claims ([grading/claims.csv](grading/claims.csv)) and `X#` quantities; code rejects any other number |
| Coherent recommendation, alternatives, limitations | [Decision memo](#decision-memo); [paywall sensitivity](#ranking); [limitations](#limitations) |
| **Testing & evaluation (3)** | |
| 50 human labels, per-field comparison, error analysis | [Golden v1 results](evals/golden/results_v1/summary.md), [v2 with change log](evals/golden/results_v2/summary.md), [error analysis](#golden-50-evaluation) |
| Independent verification, planted-error and injection tests | [Verification](#system-checks); [injection test](evals/injection/results.md); planted errors in `runs/full/verify/planted_errors.json` **(after full run)** |
| Real cold/warm pilot, offline calculator, retry/spend/recovery controls | [cost/report.md](cost/report.md); [failed attempt 1](cost/attempt-1-memo-failed/NOTE.md); [controls](#controls-retries-spending-recovery) |
| **Working result (3)** | |
| Full ingestion, coverage, classification | [grading/ingestion.json](grading/ingestion.json); course self-check **(after full run)** |
| Runnable staged program, bounded calls, saved handoffs, resume | [Commands](#setup-and-commands); [interruption/resume evidence](#interruption-and-resume) |
| Reproducible baseline ranking, grounded final output | [Ranking](#ranking); `python3 -m pipeline.rerank --grading grading`; [memo](#decision-memo) |

---

## Results summary

**Measured (full run)** — *(after full run)*

| | Value | Source |
|---|---|---|
| Source rows / completed / quarantined / pending | — / — / — / — | `grading/records.jsonl.gz` |
| Exact-text cache reuse | — rows (484,189 distinct texts sent) | `cache_source_id` in records |
| Enrichment requests / failed attempts / retries | — | `grading/calls.jsonl` |
| Verifier agreement (5% sample) | topic —, intent —, severity — | `runs/full/verify/summary.json` |
| Actual API cost / wall-clock time | — / — | `runs/full/run_summary.json` |

**Measured (development checkpoints, before the full run)**

| Run | Reviews | Workers | API cost | Wall-clock | Verifier topic agreement |
|---|---|---|---|---|---|
| [100-review pilot](cost/report.md) (cold / warm) | 100 | 1 | $0.003919 / $0 | 38.8 s / 0.03 s | 19/20 |
| [500 checkpoint](cost/checkpoint_500-2w/report.md) | 500 | 2 | $0.0124 | 64 s | 22/25 |
| [10,000 checkpoint](cost/analysis_10000-4w/report.md) | 10,000 | 4 | $0.1904 | 518 s | 88% (419 reviews) |

**Golden 50:** strict agreement v1 — topic 76%, intent 92%, severity 68% (MAE 0.44); v2 (9 rule-based revisions,
made after seeing predictions) — topic 80%, intent 92%, severity 76% (MAE 0.32). Details in
[Golden-50 evaluation](#golden-50-evaluation).

**Estimated before the full run** (from the 10,000 checkpoint): base $11.07, conservative $16.04; ~6.8 h (base) with
4 workers. Budget cap $45. Estimates and measurements are kept separate in every report.

---

## Architecture

```mermaid
flowchart LR
    A[CSV input<br/>any path] --> B[1 Prepare<br/>CODE: parse, hash rows,<br/>quarantine empty, dedupe]
    B --> C[2 Enrich<br/>MODEL: gpt-6-luna<br/>≤50 reviews/request]
    C -->|validate in CODE<br/>retry once, then quarantine| C
    C --> D[3 Verify<br/>MODEL: separate prompt,<br/>5% sample, blind]
    C --> E[4 Group<br/>CODE: issue rules<br/>MODEL: names only]
    E --> F[5 Rank<br/>CODE only]
    F --> G[6 Memo<br/>MODEL: writes argument<br/>CODE: owns every number]
    D --> H[(disagreements)]
    G --> I[(memo.md, claims.csv)]
    B & C & E & F --> S[(state.sqlite:<br/>records, calls, checkpoints)]
```

| Stage | Owner | Input → output | Failure behaviour / stop condition |
|---|---|---|---|
| 1 Prepare | code | CSV → records (pending / quarantined `empty_review_text`), row hashes | stops if a known row changed or settings differ |
| 2 Enrich | model + code | ≤50 distinct texts → validated labels; duplicates reuse results via `cache_source_id` | invalid items re-sent once (batches of 10), then quarantined; transient errors: 3 attempts with backoff; stops at spend cap, Ctrl-C, 5 consecutive failures |
| 3 Verify | model + code | 5% seeded sample, text only → independent labels → disagreement report | invalid items retried once, then `failed` (visible) |
| 4 Group | code + model | complaint/cancellation records → one issue each (rules); evidence pack → issue names | names citing outside IDs or containing digits rejected; one retry; rule-text fallback |
| 5 Rank | code | membership + severities → baseline, business view, paywall sensitivity | deterministic; byte-identical reruns |
| 6 Memo | model + code | aggregates + bounded evidence → memo with `{C#}`/`{X#}` references | any digit outside a reference, unknown claim, or outside review ID → rejected; one retry; no memo if still invalid |

### Who chooses the next step, and when the run stops (Jordan, own words)

The order of steps is fixed in code: ingest > enrich > verify > group > rank > memo. The model only reads the review text and picks the labels; it also re-labels a sample to verify them, names the issues, and writes the memo, but it never decides what runs next. The run stops when next request would go over the $45 cap, there are 5 failures in a row, I press Ctrl-C, the provider reports a permanent error (such as no credit), or every review is completed/quarantined, and saved progress lets it resume without re-labeling reviews already finished. The later stages only run once enrichment has finished. Between runs, I decided whether to scale up by looking at the cost/time report and the quality results after each test run (100 > 500 > 10,000)

### Why each model call is needed, and what code does instead (Jordan, own words)

I used the model only when it requires reading and understanding messy human language, or writing an argument from numbers that code has already computed. For example, enrichment needs a model because reviews contain slang, typos, mixed languages and sarcasm, there are just too many ways people can describe a problem, but code handles the rest by reading the file, sending each repeated text once and reusing the result for every copy, and copying the exact sentence the model points to so quotes are always exact. Ranking uses no model because it's just simple math and code will do it the same way every time.

---

## Labels and schema

- Shared definitions, examples and Jordan's decision log: [labels/definitions.md](labels/definitions.md)
- Record schema and who produces each field: [labels/record_schema.md](labels/record_schema.md)
- Prompts (versioned): [prompts/](prompts/) — `enrich-v2`, `verify-v1`, `group-v2`, `memo-v3`
- Pipeline decisions with Jordan's reasoning: [docs/decisions.md](docs/decisions.md)

---

## Golden-50 evaluation

- Human labels: [v1 original](evals/golden/golden_50_human_labels_v1.csv) ·
  [v2](evals/golden/golden_50_human_labels_v2.csv) with [change log](evals/golden/golden_v2_changelog.csv)
  (9 rule-based revisions **made after seeing predictions**; v1 kept unchanged and both reported)
- Results: [v1](evals/golden/results_v1/summary.md) · [v2](evals/golden/results_v2/summary.md); per-case detail in
  `per_case.csv`
- Declared before evaluation: sentiment agrees within ±0.5; MAE also reported. Missing predictions count as wrong.
- The golden labels were completed after the enrichment prompt was frozen and never influenced any prompt, example,
  threshold or grouping rule.

### Error analysis (Jordan, own words)

Intent was most reliable (92%) because there are obvious signals and few intents with a clear order to check. Severity was weakest (68% in v1, 76% in v2); the model tended to rate problems more severely than I did, especially after my v2 revisions (it rated higher in 10 cases and lower in 2), e.g., when a sudden loud ad played and I rated a 2 and the model did 5. The largest group of topic errors came from confusing playback, usability, and access as these tend to overlap. This matters because severity drives rankings so severity errors shift things. With only 50 cases, one review can impact a score to the point of making a rough signal that is not exact accuracy.

---

## System checks

| Check | Result | Evidence |
|---|---|---|
| Independent verifier (full run, 5%) | *(after full run)* | `runs/full/verify/` |
| Planted wrong labels (synthetic copy) | *(after full run)* | `runs/full/verify/planted_errors.json` |
| Prompt injection (6 attacks + 2 controls, synthetic) | 8/8 passed; no injected label adopted | [evals/injection/results.md](evals/injection/results.md) |
| Safeguard tests (fake model, $0) | 60 tests pass | `python3 -m unittest discover -s tests -t .` |

### Interruption and resume
*(after full run: recording link, `grading/checkpoint_before.json` vs `checkpoint_after.json` counts, initial vs
resume calls, and proof that no completed ID was re-sent.)* So far: interrupted after 13 requests with 65,174
records saved; resumed in phase `resume`.

### Controls: retries, spending, recovery
- Spend cap $45 enforced before each request, counting in-flight reservations; unknown-usage calls count their full
  reservation. Output cap 4,000 tokens per request. 4 workers. No stronger-model fallback (declared fraction 0).
- Evidence: [cost/report.md](cost/report.md) Controls section; tests in `tests/`.

---

## Ranking

- Baseline (contract): `priority_score = severity_sum = complaint_count × mean_severity`; descending score, then
  ascending `issue_id`; means to six decimals, half-up. One issue per complaint (`allow_multi_issue: false`).
- Business view (additional, labeled): same numbers with `other.general` excluded.
- Paywall sensitivity (Jordan's decision 1c): named-feature paywall complaints re-scored from 3 to 2.
- Regenerate from the exported files without a model: `python3 -m pipeline.rerank --grading grading` (exits non-zero if the result differs from `grading/ranking.csv`)
- Results: *(after full run)*

---

## Decision memo

*(after full run: link to `runs/full/memo/memo.md` copy, summary of priority, claim IDs.)*

### My inspection of the memo's argument (Jordan, own words)

I checked the memo's comparisons against its own numbers table and ranking.csv, plus the two reviews it cites, read in the original data. The recommendation isn't consistent with the rule I declared before the full run because the memo says playback has the highest severity sum instead of usability but the numbers show that the statement is not true. It is consistent with the issue-level view however as playback is the top specific issue once `other.general` is excluded. I opened reviews 98333d3d and 07aa9843 and found both are correctly labeled playback failures. However, two examples are not much evidence for a group of 35,331 complaints. One weakness is the area totals depend on how issues are grouped. Usability is spread over many issues while playback is mostly one broad issue. The size and shape of the group affects which area or issue looks biggest

*Note on versions:* this inspection was of memo-v3, which passed every automated check but misstated which area had
the largest total. The memo was regenerated as memo-v4: it receives the area and issue order as code-computed facts,
states that usability has the largest area total (179,800), and recommends playback under the issue-level rule. Two
new code checks now enforce this (`tests/test_memo.py`, `IssueLevelRuleTests`). memo-v3 and its check are kept in
[evals/memo-inspection/](evals/memo-inspection/). memo-v4 has one formatting typo, left exactly as the model wrote it:
in its sensitivity section a closing backtick after `playback.general` was written as a brace. One review memo-v4
cites, `98fee45a` ("woooow can't even put a playlist on repeat anymore"), is labeled billing with
`paywall_named_feature = true` although it never mentions Premium; see [Limitations](#limitations).

---

## One failure explained (Jordan, own words)

In the first pilot, the memo was rejected 4 times. The main cause was a bug in the instructions rather than the model: we told the model not to write any numbers except reference to code-computed claims, but also gave it background text that contained dates, which are numbers. Three of the four rejections came from those dates; the fourth was the model's own miss, a recommendation that cited no claim. The check did its job by blocking a memo that broke the rules rather than publishing it. We fixed it by removing numbers from the background text, adding a check that rejects issue names containing numbers, and making the memo instructions clearer and reran the whole 100-review pilot, starting from an empty cache. What I learned is for whatever I give a model, it must follow the same rules its answer is checked against

Evidence: [cost/attempt-1-memo-failed/NOTE.md](cost/attempt-1-memo-failed/NOTE.md).

---

## One review traced end to end

*(after full run: one real review — source ID → enrichment labels → verification → issue membership → ranking row →
memo claim; plus one failed or ambiguous case and the handling decision.)*

---

## Limitations
- Self-selected, public, historical reviews; not representative of all users. No revenue, plan tier or confirmed churn;
  cancellation intent is not observed churn.
- Model labels are imperfect (see golden and verifier agreement); severity tends to be rated high.
- Issue groups come from fixed rules on matched feature words; `other.general` is broad.
- **The model sometimes used outside knowledge.** Some reviews were labeled as Premium paywall complaints although the
  text never mentions Premium or payment (e.g. `98fee45a`, "can't even put a playlist on repeat anymore"), likely
  because the model knows about Spotify's 2023 free-tier changes. Measured by code on the full run: of 27,059
  `paywall_named_feature` labels, 5,666 (20.9%) contain no premium/pay/price/subscription/free/upgrade/currency word;
  of 60,773 `billing` labels, 8,503 (14.0%). This is an upper bound (the word list misses e.g. "fee", and limits such
  as "6 skips per hour" are known free-tier rules). Re-labeling would require a new prompt version and a full re-run,
  so it is disclosed instead. Effect on the recommendation: even if the 3,864 such reviews were removed from
  `billing.paywall_named_feature`, its priority score would fall from 68,708 to 57,060 (below `usability.ads`
  at 64,246), and the top specific issue, `playback.general` (117,894), would not change. A future prompt version
  should say: label only what the text states; do not infer that a feature is Premium-only unless the review says so.
- The first and last calendar months are partial (May 17 – Nov 15).

---

## Setup and commands

**Requirements:** Python 3.10+ (developed on 3.14), standard library only — no packages to install.

**Data:** download the course dataset ZIP and unzip it next to this repository as
`../Final Assignment - Spotify Reviews Dataset/`. The 97.4 MB CSV is not committed. Source: BwandoWando,
*3.4 Million Spotify Google Store Reviews* v2 (Kaggle, CC0). Full CSV SHA-256:
`1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6`.

**Keys (only for paid runs):** `cp .env.example .env` and set `OPENAI_API_KEY`. `.env` is git-ignored. Offline replay,
re-ranking and the self-check need no key.

| Purpose | Command | Paid? |
|---|---|---|
| All stages on any CSV (fake model) | `python3 -m pipeline run --input PATH.csv --run NAME` | no |
| All stages, real model | `... --client openai --confirm-paid --workers 4` | **yes** |
| Progress / checkpoint of a run | `python3 -m pipeline status --run NAME` | no |
| Cost calculator, offline replay | `python3 cost/calculator.py` | no |
| 100-review pilot (cold + warm) | `python3 cost/calculator.py pilot --confirm-paid` | **yes** |
| Golden evaluation | `python3 evals/evaluate_golden.py` | no |
| Grading export + course self-check | `python3 -m pipeline.grading_export --run full --out grading --check` | no |
| Tests (fake model) | `python3 -m unittest discover -s tests -t .` | no |
| Re-rank from exported files (no model) | `python3 -m pipeline.rerank --grading grading` | no |

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

### ✍️ JORDAN — OWN WORDS: who chooses the next step, and when the run stops
*(Required by the Class 6 brief and the assignment. Explain where code decides and where a model exercises
judgment. Facts to draw on are in the table above and in `pipeline/run.py` / `pipeline/enrich.py`.)*

### ✍️ JORDAN — OWN WORDS: why each model call is needed, and what code does instead

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

### ✍️ JORDAN — OWN WORDS: error analysis
*(Patterns visible in the results, for you to explain or dispute: severity rated higher than the human label;
access and support topics missed; the loud-ad review given severity 5; language-ambiguous reviews.)*

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

### ✍️ JORDAN — OWN WORDS: your inspection of the memo's argument

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

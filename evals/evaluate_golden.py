"""Compare Jordan's 50 human labels with the pipeline's predictions. Code only; no model calls.

The human labels are read here and nowhere else: they are never sent to a model, used as prompt examples, used for
routing thresholds, or used to discover issues. Predictions come from an ordinary enrichment run on the golden
reviews' text (`runs/golden-50`, same label_config as the full run).

    python3 evals/evaluate_golden.py [--run golden-50]

Writes evals/golden/results/: per_case.csv, summary.json, summary.md
Declared before evaluation (labels/definitions.md, decision 6): sentiment agrees when within +/-0.5; mean absolute
error is also reported. Topic/intent/severity are reported strictly (the human's primary label) and leniently
(the primary label or any alternative the human marked as also acceptable on an ambiguous case).
"""

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HUMAN = REPO / "evals" / "golden" / "golden_50_human_labels.csv"
OUT = REPO / "evals" / "golden" / "results"
TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")
SENTIMENT_TOLERANCE = 0.5


def load_predictions(run_dir):
    db = sqlite3.connect(f"file:{run_dir / 'state.sqlite'}?mode=ro", uri=True)
    rows = db.execute("SELECT review_id, status, labels, reason FROM records").fetchall()
    config = db.execute("SELECT value FROM meta WHERE key='label_config'").fetchone()[0]
    return {rid: {"status": s, "labels": json.loads(l) if l else None, "reason": r} for rid, s, l, r in rows}, config


def alternatives(cell):
    return [x for x in cell.split(",") if x]


def evaluate(run_dir):
    preds, label_config = load_predictions(run_dir)
    human = list(csv.DictReader(open(HUMAN, encoding="utf-8", newline="")))
    cases, totals = [], Counter()
    confusion = Counter()
    nr = Counter()
    for h in human:
        rid, p = h["review_id"], preds.get(h["review_id"])
        ok = p is not None and p["status"] == "completed"
        pl = p["labels"] if ok else {}
        accepted = {"topic": [h["topic"]] + alternatives(h["alt_topics"]),
                    "intent": [h["intent"]] + alternatives(h["alt_intents"]),
                    "severity": [int(h["severity"])] + [int(x) for x in alternatives(h["alt_severities"])]}
        case = {"review_id": rid, "text": h["review_text"], "ambiguous": h["ambiguous"], "prediction_status":
                p["status"] if p else "missing"}
        for f in ("topic", "intent", "severity"):
            human_value = int(h[f]) if f == "severity" else h[f]
            case[f"human_{f}"], case[f"pred_{f}"] = human_value, pl.get(f)
            case[f"{f}_strict"] = ok and pl[f] == human_value          # missing predictions count as wrong
            case[f"{f}_lenient"] = ok and pl[f] in accepted[f]
            totals[f"{f}_strict"] += case[f"{f}_strict"]
            totals[f"{f}_lenient"] += case[f"{f}_lenient"]
        case["all_three_strict"] = all(case[f"{f}_strict"] for f in ("topic", "intent", "severity"))
        case["all_three_lenient"] = all(case[f"{f}_lenient"] for f in ("topic", "intent", "severity"))
        totals["all_three_strict"] += case["all_three_strict"]
        totals["all_three_lenient"] += case["all_three_lenient"]
        if ok:
            totals["valid"] += 1
            case["severity_abs_error"] = abs(pl["severity"] - int(h["severity"]))
            case["human_sentiment"], case["pred_sentiment"] = float(h["sentiment"]), pl["sentiment"]
            case["sentiment_abs_error"] = abs(pl["sentiment"] - float(h["sentiment"]))
            case["sentiment_within_tolerance"] = case["sentiment_abs_error"] <= SENTIMENT_TOLERANCE
            totals["severity_abs_error"] += case["severity_abs_error"]
            totals["sentiment_abs_error"] += case["sentiment_abs_error"]
            totals["sentiment_within"] += case["sentiment_within_tolerance"]
            case["pred_evidence_quote"] = pl["evidence_quote"]
            case["quote_is_exact_substring"] = pl["evidence_quote"] in h["review_text"]
            case["quote_overlaps_human_quote"] = (pl["evidence_quote"] in h["evidence_quote"]
                                                  or h["evidence_quote"] in pl["evidence_quote"])
            totals["quote_substring"] += case["quote_is_exact_substring"]
            totals["quote_overlap"] += case["quote_overlaps_human_quote"]
            human_entities = {e.strip().lower() for e in h["entities"].split(",") if e.strip()}
            case["pred_entities"] = ",".join(pl["entities"])
            case["human_entities"] = h["entities"]
            case["pred_entities_not_in_text"] = ",".join(e for e in pl["entities"] if e not in h["review_text"].lower())
            case["human_needs_review"], case["pred_needs_review"] = h["needs_review"] == "true", pl["needs_review"]
            nr[(case["human_needs_review"], case["pred_needs_review"])] += 1
            confusion[(h["topic"], pl["topic"])] += 1
        cases.append(case)
    n = len(human)
    valid = totals["valid"]
    tp, fp, fn = nr[(True, True)], nr[(False, True)], nr[(True, False)]
    per_topic = {t: {"human": sum(h["topic"] == t for h in human),
                     "predicted": sum(c.get("pred_topic") == t for c in cases),
                     "strict_correct": sum(c["human_topic"] == t and c["topic_strict"] for c in cases)} for t in TOPICS}
    summary = {
        "label_config": label_config, "cases": n, "valid_predictions": valid,
        "missing_or_quarantined_predictions": n - valid,
        "ambiguous_cases_marked_by_human": sum(h["ambiguous"] == "true" for h in human),
        "agreement_strict": {f: round(totals[f"{f}_strict"] / n, 4) for f in ("topic", "intent", "severity", "all_three")},
        "agreement_lenient": {f: round(totals[f"{f}_lenient"] / n, 4) for f in ("topic", "intent", "severity", "all_three")},
        "severity_mae": round(totals["severity_abs_error"] / valid, 4) if valid else None,
        "sentiment_within_0.5": round(totals["sentiment_within"] / valid, 4) if valid else None,
        "sentiment_mae": round(totals["sentiment_abs_error"] / valid, 4) if valid else None,
        "evidence_quote_exact_substring": f"{totals['quote_substring']}/{valid}",
        "evidence_quote_overlaps_human_quote": f"{totals['quote_overlap']}/{valid}",
        "needs_review_as_prediction": {"true_positive": tp, "false_positive": fp, "false_negative": fn,
                                       "true_negative": nr[(False, False)],
                                       "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                                       "recall": round(tp / (tp + fn), 4) if tp + fn else None},
        "per_topic": per_topic,
        "topic_confusion_human_to_pred": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items()) if a != b},
        "notes": ["Missing or quarantined predictions count as incorrect in agreement; MAE uses valid predictions only.",
                  "Fifty cases are a small diagnostic sample, not a precise population accuracy estimate.",
                  "The golden labels were completed after the enrichment prompt (enrich-v2) was frozen and did not "
                  "influence any prompt, example, threshold or grouping rule."],
    }
    return cases, summary


def write(cases, summary):
    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for c in cases for k in c))
    with open(OUT / "per_case.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(cases)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    s = summary
    md = ["# Golden-50 evaluation", "", f"Predictions: `{s['label_config']}`. Human labels: Jordan "
          f"(`evals/golden/golden_50_human_labels.csv`). Code comparison only.", "",
          "| Measure | Strict (human primary label) | Lenient (also accepts human-marked alternatives) |",
          "|---|---|---|"]
    for f in ("topic", "intent", "severity", "all_three"):
        md.append(f"| {f} agreement | {s['agreement_strict'][f]:.0%} | {s['agreement_lenient'][f]:.0%} |")
    md += ["", f"- Valid predictions: {s['valid_predictions']}/{s['cases']} (missing/quarantined count as wrong: "
           f"{s['missing_or_quarantined_predictions']}).",
           f"- Ambiguous cases marked by the human labeler: {s['ambiguous_cases_marked_by_human']}.",
           f"- Severity mean absolute error: {s['severity_mae']}.",
           f"- Sentiment within ±0.5 (declared tolerance): {s['sentiment_within_0.5']:.0%}; sentiment MAE: {s['sentiment_mae']}.",
           f"- Evidence quote is an exact substring: {s['evidence_quote_exact_substring']}; overlaps the human's quote: "
           f"{s['evidence_quote_overlaps_human_quote']}.",
           f"- needs_review as a prediction: {s['needs_review_as_prediction']}.", "",
           "## Per topic", "", "| Topic | Human count | Predicted count | Strictly correct |", "|---|---|---|---|"]
    md += [f"| {t} | {v['human']} | {v['predicted']} | {v['strict_correct']} |" for t, v in s["per_topic"].items()]
    md += ["", "## Topic confusion (human → predicted, mismatches only)", ""]
    md += [f"- {k}: {v}" for k, v in s["topic_confusion_human_to_pred"].items()] or ["- none"]
    md += ["", "## Disagreements (strict)", "", "| Review | Human (topic/intent/sev) | Predicted | Ambiguous | Text |",
           "|---|---|---|---|---|"]
    for c in cases:
        if not c["all_three_strict"]:
            text = c["text"].replace("|", "/").replace("\n", " ")[:140]
            md.append(f"| `{c['review_id'][:8]}` | {c['human_topic']}/{c['human_intent']}/{c['human_severity']} | "
                      f"{c['pred_topic']}/{c['pred_intent']}/{c['pred_severity']} | {c['ambiguous']} | {text} |")
    md += ["", *[f"*{n}*" for n in s["notes"]]]
    (OUT / "summary.md").write_text("\n".join(md) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", default="golden-50")
    args = parser.parse_args()
    run_dir = REPO / "runs" / args.run
    if not (run_dir / "state.sqlite").exists():
        sys.exit(f"No predictions in {run_dir}. Run: python3 -m pipeline enrich --input "
                 f"'../Final Assignment - Spotify Reviews Dataset/golden_50_to_label.csv' --run {args.run} "
                 f"--client openai --confirm-paid")
    cases, summary = evaluate(run_dir)
    write(cases, summary)
    print(json.dumps({k: summary[k] for k in ("agreement_strict", "agreement_lenient", "severity_mae",
                                              "sentiment_within_0.5", "sentiment_mae")}, indent=1))


if __name__ == "__main__":
    main()

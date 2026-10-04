"""Rank stage: pure code, no model calls. Regenerates the same output from the same saved inputs every time.

Baseline (GRADING_CONTRACT.md): for each issue, over its completed complaint/cancellation members,
  complaint_count = number of members, severity_sum = sum of member severities,
  mean_severity = severity_sum / complaint_count (6 decimals, decimal half-up), priority_score = severity_sum
  (exactly count x mean, with no rounding loss). Order: descending score, then ascending issue_id; ranks from 1.

Sensitivity check (Jordan, decision 1c): the same ranking with every paywall_named_feature complaint at severity 3
re-scored as 2, to show whether the paywall severity decision changes the recommendation.

Outputs under <run>/rank/: ranking.csv, aggregates.csv, ranking_paywall_sev2.csv, sensitivity.json
"""

import csv
import json
from collections import Counter, defaultdict

from .store import Store
from .vendor.check_submission import mean_string

RANKING_FIELDS = ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"]


def read_membership(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [(row["issue_id"], row["review_id"]) for row in csv.DictReader(f)]


def compute_ranking(severity, membership):
    """`severity` maps review_id -> int; `membership` is a list of (issue_id, review_id). Returns ranked rows with
    integer values kept as ints and the mean as the contract's 6-decimal string."""
    sums, counts = defaultdict(int), defaultdict(int)
    for issue_id, review_id in membership:
        sums[issue_id] += severity[review_id]
        counts[issue_id] += 1
    rows = [{"issue_id": i, "complaint_count": counts[i], "severity_sum": sums[i],
             "mean_severity": mean_string(sums[i], counts[i]), "priority_score": sums[i]} for i in counts]
    rows.sort(key=lambda r: (-r["priority_score"], r["issue_id"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def write_ranking(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RANKING_FIELDS, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: str(row[k]) for k in RANKING_FIELDS})


def run(run_dir, log=print):
    store = Store(run_dir / "state.sqlite")
    labels = {r["review_id"]: r["labels"] for r in store.records() if r["status"] == "completed"}
    membership = read_membership(run_dir / "group" / "membership.csv")
    missing = [rid for _, rid in membership if rid not in labels]
    if missing:
        raise SystemExit(f"membership lists {len(missing)} reviews without completed labels, e.g. {missing[:3]}")
    out = run_dir / "rank"
    out.mkdir(parents=True, exist_ok=True)

    severity = {rid: l["severity"] for rid, l in labels.items()}
    baseline = compute_ranking(severity, membership)
    write_ranking(out / "ranking.csv", baseline)

    # Aggregates: the extra per-issue numbers the memo may cite (intent mix, severity mix, paywall flag count).
    by_issue = defaultdict(list)
    for issue_id, rid in membership:
        by_issue[issue_id].append(labels[rid])
    with open(out / "aggregates.csv", "w", encoding="utf-8", newline="") as f:
        fields = ["issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score", "cancellation_count",
                  "complaint_intent_count", "sev1", "sev2", "sev3", "sev4", "sev5", "paywall_named_feature_count",
                  "needs_review_count"]
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in baseline:
            members = by_issue[row["issue_id"]]
            sev = Counter(m["severity"] for m in members)
            intents = Counter(m["intent"] for m in members)
            w.writerow({**{k: row[k] for k in fields[:5]}, "cancellation_count": intents["cancellation"],
                        "complaint_intent_count": intents["complaint"], **{f"sev{s}": sev[s] for s in range(1, 6)},
                        "paywall_named_feature_count": sum(bool(m.get("paywall_named_feature")) for m in members),
                        "needs_review_count": sum(bool(m.get("needs_review")) for m in members)})

    # Sensitivity: paywall_named_feature complaints at severity 3 re-scored as 2.
    changed = {rid for rid, l in labels.items() if l.get("paywall_named_feature") and l["severity"] == 3}
    alt = compute_ranking({rid: (2 if rid in changed else s) for rid, s in severity.items()}, membership)
    write_ranking(out / "ranking_paywall_sev2.csv", alt)
    base_rank = {r["issue_id"]: r["rank"] for r in baseline}
    moves = [{"issue_id": r["issue_id"], "baseline_rank": base_rank[r["issue_id"]], "sensitivity_rank": r["rank"],
              "baseline_score": next(b["priority_score"] for b in baseline if b["issue_id"] == r["issue_id"]),
              "sensitivity_score": r["priority_score"]} for r in alt]
    sensitivity = {"rule": "paywall_named_feature = true and severity = 3 -> severity 2",
                   "reviews_rescored": len(changed),
                   "top_issue_baseline": baseline[0]["issue_id"] if baseline else None,
                   "top_issue_sensitivity": alt[0]["issue_id"] if alt else None,
                   "top_issue_changes": bool(baseline) and baseline[0]["issue_id"] != alt[0]["issue_id"],
                   "rank_changes": [m for m in moves if m["baseline_rank"] != m["sensitivity_rank"]]}
    (out / "sensitivity.json").write_text(json.dumps(sensitivity, indent=1))
    log(f"rank: {len(baseline)} issues from {len(membership)} memberships; top = {sensitivity['top_issue_baseline']}; "
        f"paywall sensitivity re-scored {len(changed)} reviews, top issue changes: {sensitivity['top_issue_changes']}")
    return {"issues": len(baseline), "memberships": len(membership), "sensitivity": sensitivity}

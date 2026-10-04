"""Regenerate the baseline ranking from the exported grading files alone (no model, no run database, no key) and
compare it with the submitted grading/ranking.csv.

    python3 -m pipeline.rerank --grading grading
"""

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

from .rank import RANKING_FIELDS, compute_ranking


def rerank(grading):
    grading = Path(grading)
    opener = gzip.open if (grading / "records.jsonl.gz").exists() else open
    path = grading / ("records.jsonl.gz" if opener is gzip.open else "records.jsonl")
    severity = {}
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["status"] == "completed":
                severity[r["review_id"]] = r["severity"]
    with open(grading / "membership.csv", encoding="utf-8", newline="") as f:
        membership = [(row["issue_id"], row["review_id"]) for row in csv.DictReader(f)]
    rows = compute_ranking(severity, membership)
    regenerated = [{k: str(r[k]) for k in RANKING_FIELDS} for r in rows]
    with open(grading / "ranking.csv", encoding="utf-8", newline="") as f:
        submitted = list(csv.DictReader(f))
    return regenerated, submitted


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grading", type=Path, default=Path("grading"))
    args = parser.parse_args()
    regenerated, submitted = rerank(args.grading)
    same = regenerated == submitted
    print(f"Regenerated {len(regenerated)} ranked issues from records + membership; identical to ranking.csv: {same}")
    for r in regenerated[:10]:
        print(f"  {r['rank']:>2}. {r['issue_id']:<35} count {r['complaint_count']:>7}  mean {r['mean_severity']}  "
              f"score {r['priority_score']}")
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()

"""Export the run's working outputs that sit alongside the standardized grading/ folder. No model calls.

    python3 -m pipeline.outputs_export --run full --out outputs

Writes:
  enriched.csv.gz        every source row unchanged (all six original fields) with the labels attached
  quarantine.jsonl       every unresolved record: ID, row hash, reason, attempts, original text
  ingestion_report.json  full-file profile, checks against the course manifest, duplicate/distinct-text counts,
                         and final failure accounting
  data_manifest.json     source identity, code version, prompt hashes, model IDs/settings, run IDs, token and cost
                         totals, spending limit, and SHA-256 of every exported output
  run_log.jsonl, run_summary.json   stage timings and call counts written by the run itself
"""

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from . import config
from .export import CONTRACT_LABEL_FIELDS
from .store import Store
from .vendor import check_submission as checker

SOURCE_FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
LABEL_COLUMNS = ("status", "reason", "topic", "intent", "severity", "sentiment", "entities", "evidence_quote",
                 "needs_review", "review_flag", "paywall_named_feature", "label_config", "cache_source_id",
                 "source_sha256")


def sha(path):
    return checker.sha(path)


def export(run_dir, out):
    store = Store(run_dir / "state.sqlite")
    input_csv = Path(store.get_meta("input_path"))
    out.mkdir(parents=True, exist_ok=True)
    records = {r["review_id"]: r for r in store.records()}

    texts, duplicate_rows = Counter(), 0
    with gzip.open(out / "enriched.csv.gz", "wt", encoding="utf-8", newline="") as f, \
            open(out / "quarantine.jsonl", "w", encoding="utf-8") as q:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(SOURCE_FIELDS + LABEL_COLUMNS)
        for row in checker.csv_rows(input_csv):
            rec = records[row["review_id"]]
            labels = rec["labels"] or {}
            if row["review_text"].strip():
                texts[row["review_text"]] += 1
            values = {"status": rec["status"], "reason": rec["reason"] or "",
                      **{k: labels.get(k, "") for k in CONTRACT_LABEL_FIELDS if k != "entities"},
                      "entities": "|".join(labels.get("entities", [])),
                      "review_flag": labels.get("review_flag") or "",
                      "paywall_named_feature": labels.get("paywall_named_feature", ""),
                      "label_config": config.LABEL_CONFIG if rec["status"] == "completed" else "",
                      "cache_source_id": rec["cache_source_id"] or "", "source_sha256": rec["source_sha256"]}
            w.writerow([row[k] for k in SOURCE_FIELDS] + [values[k] for k in LABEL_COLUMNS])
            if rec["status"] != "completed":
                q.write(json.dumps({"review_id": rec["review_id"], "source_sha256": rec["source_sha256"],
                                    "status": rec["status"], "reason": rec["reason"], "attempts": rec["attempts"],
                                    "review_text": row["review_text"]}, ensure_ascii=False) + "\n")
    distinct = len(texts)
    nonempty = sum(texts.values())

    profile = checker.profile(input_csv)
    dataset = json.loads((config.REPO.parent / "Final Assignment - Spotify Reviews Dataset" / "manifest.json").read_text())
    status = store.count_by_status()
    reasons = Counter(r["reason"].split(":")[0] for r in records.values() if r["status"] == "quarantined")
    ingestion = {
        "source_file": input_csv.name, "source_sha256": profile["file_sha256"],
        "source_bytes": input_csv.stat().st_size, "profile": profile,
        "checks_against_course_manifest": {
            "sha256_matches": profile["file_sha256"] == dataset["files"][input_csv.name]["sha256"],
            "counts_match": profile["counts"] == dataset["profile"],
            "reviews_by_month_match": profile["reviews_by_month"] == dataset["reviews_by_month"],
            "reviews_by_rating_match": profile["reviews_by_rating"] == dataset["reviews_by_rating"]},
        "nonempty_reviews": nonempty, "distinct_nonempty_texts": distinct,
        "rows_reusable_by_exact_text": nonempty - distinct,
        "final_accounting": {"source_rows": len(records), "completed": status.get("completed", 0),
                             "quarantined": status.get("quarantined", 0), "pending": status.get("pending", 0),
                             "quarantine_reasons": dict(reasons),
                             "cache_reuses": sum(1 for r in records.values() if r["cache_source_id"])},
        "notes": ["Missing app_version is kept and does not prevent classification.",
                  "Empty review text is quarantined as empty_review_text and never sent to a model."]}
    (out / "ingestion_report.json").write_text(json.dumps(ingestion, indent=1) + "\n")

    for name in ("run_log.jsonl", "run_summary.json"):
        shutil.copyfile(run_dir / name, out / name)

    tokens = Counter()
    by_role = {}
    for c in store.calls():
        r = by_role.setdefault(c["role"], Counter())
        r["attempts"] += 1
        r["failed"] += c["outcome"] == "failed"
        for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"):
            r[k] += c[k]
            tokens[k] += c[k]
        r["cost_usd"] += c["cost_usd"] if c["usage_known"] else c["reserved_usd"]
    runs = [dict(zip(("run_id", "phase", "client", "started_at", "ended_at", "stop_reason", "wall_clock_s"), row))
            for row in store.db.execute("SELECT run_id, phase, client, started_at, ended_at, stop_reason, wall_clock_s FROM runs")]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.REPO, capture_output=True, text=True).stdout.strip()
    prompts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(config.PROMPTS.glob("*"))}
    manifest = {
        "run": run_dir.name, "runs": runs,
        "source": {"file": input_csv.name, "sha256": profile["file_sha256"], "bytes": input_csv.stat().st_size,
                   "dataset": "BwandoWando, 3.4 Million Spotify Google Store Reviews v2 (Kaggle, CC0), course extract",
                   "course_manifest_checksums": {k: v["sha256"] for k, v in dataset["files"].items()}},
        "code_version_at_export": commit,
        "configs": {"enrich": config.LABEL_CONFIG, "verify": config.VERIFY_CONFIG, "group": config.GROUP_CONFIG,
                    "memo": config.MEMO_CONFIG},
        "models": sorted({c["model"] for c in store.calls()}),
        "settings": {"max_reviews_per_request": config.MAX_BATCH, "retry_batch": config.RETRY_BATCH,
                     "max_output_tokens": config.MAX_OUTPUT_TOKENS, "transient_attempts": config.TRANSIENT_ATTEMPTS,
                     "workers": 4, "verify_rate": config.VERIFY_RATE, "spend_cap_usd": config.SPEND_CAP_USD,
                     "rates_usd_per_million_tokens": config.RATES[config.ENRICH_MODEL]},
        "prompt_sha256": prompts,
        "usage_totals": dict(tokens), "usage_by_role": {k: dict(v) for k, v in by_role.items()},
        "api_cost_usd": round(sum(v["cost_usd"] for v in by_role.values()), 6),
        "outputs_sha256": {}}
    for folder in (out, config.REPO / "grading"):
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.name != "data_manifest.json":
                manifest["outputs_sha256"][f"{folder.name}/{p.name}"] = sha(p)
    (out / "data_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return {"rows": len(records), "quarantined": status.get("quarantined", 0), "distinct": distinct,
            "tokens": dict(tokens), "cost": manifest["api_cost_usd"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(config.RUNS / args.run, args.out), indent=1))


if __name__ == "__main__":
    main()

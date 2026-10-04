"""Export a finished run into the standardized grading/ folder (GRADING_CONTRACT.md), then self-check it with the
course's own zero-API checker. No model calls.

    python3 -m pipeline.grading_export --run full --out grading            # export
    python3 -m pipeline.grading_export --run full --out grading --check    # export + course self-check

Files: run.json, ingestion.json, records.jsonl.gz, membership.csv, ranking.csv, claims.csv, calls.jsonl,
checkpoint_before.json, checkpoint_after.json. The self-check report and the local reference are written next to
the run (runs/<run>/selfcheck/), never inside the submitted grading folder.
"""

import argparse
import gzip
import json
import shutil
from pathlib import Path

from . import config
from .export import contract_call, contract_record
from .store import Store
from .vendor import check_submission as checker


def interruption_checkpoints(run_dir):
    """The earliest checkpoint written when an initial-phase run stopped early (Ctrl-C or batch limit)."""
    found = []
    for path in (run_dir / "checkpoints").glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("phase") == "initial" and data.get("stop_reason") in ("interrupted", "max_batches"):
            found.append((path.stat().st_mtime, path, data))
    return sorted(found)


def export(run_dir, out, before_path=None):
    store = Store(run_dir / "state.sqlite")
    input_csv = Path(store.get_meta("input_path"))
    out.mkdir(parents=True, exist_ok=True)
    records = list(store.records())

    (out / "run.json").write_text(json.dumps({
        "version": checker.VERSION, "analysis_count": len(records), "analysis_sha256": checker.sha(input_csv),
        "classification_input_fields": ["review_text"], "allow_multi_issue": False}, indent=1) + "\n")
    checker.write_json(out / "ingestion.json", checker.profile(input_csv))

    plain = out / "records.jsonl"
    if plain.exists():
        plain.unlink()
    with gzip.open(out / "records.jsonl.gz", "wt", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(contract_record(rec), ensure_ascii=False) + "\n")

    shutil.copyfile(run_dir / "group" / "membership.csv", out / "membership.csv")
    shutil.copyfile(run_dir / "rank" / "ranking.csv", out / "ranking.csv")
    shutil.copyfile(run_dir / "memo" / "claims.csv", out / "claims.csv")
    with open(out / "calls.jsonl", "w", encoding="utf-8") as f:
        for call in store.calls():
            f.write(json.dumps(contract_call(call)) + "\n")

    if before_path:
        before = json.loads(Path(before_path).read_text())
    else:
        found = interruption_checkpoints(run_dir)
        before = found[0][2] if found else {"completed_ids": [], "note": "no interruption checkpoint found"}
    after_ids = store.completed_ids()
    (out / "checkpoint_before.json").write_text(json.dumps(
        {"completed_ids": before["completed_ids"], "run_id": before.get("run_id"), "phase": before.get("phase"),
         "stop_reason": before.get("stop_reason"), "counts": before.get("counts")}) + "\n")
    (out / "checkpoint_after.json").write_text(json.dumps(
        {"completed_ids": after_ids, "counts": store.count_by_status(),
         "note": "completed IDs after resuming; includes all later completed work"}) + "\n")
    return {"records": len(records), "status": store.count_by_status(),
            "checkpoint_before_ids": len(before["completed_ids"]), "checkpoint_after_ids": len(after_ids)}


def self_check(run_dir, out):
    """Run the course checker exactly as GRADING_CONTRACT.md describes: build a reference from the input file, then
    audit the grading folder. Reports go to runs/<run>/selfcheck/, outside the submitted folder."""
    store = Store(run_dir / "state.sqlite")
    input_csv = Path(store.get_meta("input_path"))
    target = run_dir / "selfcheck"
    target.mkdir(parents=True, exist_ok=True)
    reference = checker.reference(input_csv, input_csv)
    checker.write_json(target / "local-reference.json", reference)
    report = checker.audit(out, reference, None, checker.reference_hash(reference))
    checker.write_json(target / "self-check.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--before", type=Path, help="checkpoint file to use as checkpoint_before.json")
    parser.add_argument("--check", action="store_true", help="also run the course self-check")
    args = parser.parse_args()
    run_dir = config.RUNS / args.run
    print(json.dumps(export(run_dir, args.out, args.before), indent=1))
    if args.check:
        report = self_check(run_dir, args.out)
        print(json.dumps({k: report[k] for k in ("status", "working_coverage_point_candidate", "coverage",
                                                 "issue_counts", "reported_calls")}, indent=1))


if __name__ == "__main__":
    main()

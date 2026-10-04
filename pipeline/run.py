"""One command for the whole pipeline on any input CSV: ingest+enrich -> verify -> group -> rank -> memo.

The orchestrator (this module) decides the next step; models never do. Each stage reads the previous stage's saved
output and writes its own. Downstream stages run only when enrichment reports `complete`; otherwise the run stops
with progress saved, and rerunning the same command resumes. Rerunning a finished run reuses every saved result.

Writes <run>/run_summary.json and appends one line per stage to <run>/run_log.jsonl.
"""

import json
import time
from datetime import datetime, timezone

from . import config, rank
from .enrich import Enricher
from .group import Grouper
from .memo import MemoWriter
from .verify import Verifier


def _calls_since(store, started_at):
    rows = [c for c in store.calls() if c["started_at"] >= started_at]
    by_role = {}
    for c in rows:
        r = by_role.setdefault(c["role"], {"attempts": 0, "succeeded": 0, "failed": 0, "input_tokens": 0,
                                           "output_tokens": 0, "cost_usd": 0.0})
        r["attempts"] += 1
        r["succeeded" if c["outcome"] == "succeeded" else "failed"] += 1
        r["input_tokens"] += c["input_tokens"]
        r["output_tokens"] += c["output_tokens"]
        r["cost_usd"] += c["cost_usd"] if c["usage_known"] else c["reserved_usd"]
    return by_role


def run_pipeline(input_csv, run_dir, clients, *, workers=config.DEFAULT_WORKERS, verify_rate=config.VERIFY_RATE,
                 spend_cap=config.SPEND_CAP_USD, max_batches=None, sleep=time.sleep, log=print):
    """`clients` maps role -> client (enrich, verify, group, memo). Returns the run summary."""
    started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    t0 = time.monotonic()
    stages = {}
    run_dir.mkdir(parents=True, exist_ok=True)

    def stage(name, fn):
        s0 = time.monotonic()
        result = fn()
        stages[name] = {"wall_clock_s": round(time.monotonic() - s0, 3), "result": result}
        with open(run_dir / "run_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "stage": name,
                                **stages[name]}, default=str) + "\n")
        return result

    enricher = Enricher(input_csv, run_dir, clients["enrich"], workers=workers, spend_cap=spend_cap,
                        max_batches=max_batches, sleep=sleep, log=log)
    enrich = stage("enrich", enricher.run)
    if enrich["stop_reason"] == "complete":
        stage("verify", lambda: Verifier(run_dir, clients["verify"], rate=verify_rate, spend_cap=spend_cap,
                                         sleep=sleep, log=log).run())
        stage("group", lambda: Grouper(run_dir, clients["group"], spend_cap=spend_cap, sleep=sleep, log=log).run())
        stage("rank", lambda: rank.run(run_dir, log=log))
        stage("memo", lambda: MemoWriter(run_dir, clients["memo"], spend_cap=spend_cap, sleep=sleep, log=log).run())
        status = "complete" if stages["memo"]["result"].get("passed") else "memo_failed_checks"
    else:
        status = f"stopped_during_enrich: {enrich['stop_reason']}"
        log(f"pipeline stopped after enrichment ({enrich['stop_reason']}); progress saved; rerun to resume")

    summary = {
        "status": status, "input": str(input_csv), "run_dir": str(run_dir), "started_at": started,
        "wall_clock_s": round(time.monotonic() - t0, 3), "workers": workers, "verify_rate": verify_rate,
        "spend_cap_usd": spend_cap, "configs": {"enrich": config.LABEL_CONFIG, "verify": config.VERIFY_CONFIG,
                                                "group": config.GROUP_CONFIG, "memo": config.MEMO_CONFIG},
        "record_counts": enricher.store.count_by_status(), "spent_total_usd": round(enricher.store.spent_usd(), 6),
        "calls_this_invocation": _calls_since(enricher.store, started), "stages": stages,
    }
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    log(f"pipeline {status} in {summary['wall_clock_s']}s; calls this invocation: "
        f"{ {k: v['attempts'] for k, v in summary['calls_this_invocation'].items()} }")
    return summary

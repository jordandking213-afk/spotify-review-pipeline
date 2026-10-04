"""Verification stage: an independent model role re-labels a declared random sample; code compares.

Independence: the verifier gets only the original review text and its own rubric prompt (no examples, and
never the enrichment labels). It shares the run's spend ledger, so the $45 cap covers every role.

Outputs, under <run>/verify/:
  verifier_predictions.csv  - the verifier's labels for each sampled review
  disagreements.csv         - every review where any of topic / intent / severity differs, with both labels
  summary.json              - sample definition, agreement rates, topic confusion, failures
  planted_errors.json       - SYNTHETIC test: wrong labels planted in a copy; did the verifier disagree?
"""

import csv
import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import config
from .enrich import TOPICS, INTENTS, call_with_backoff, cost_usd, reservation_usd, validate
from .segments import render_review
from .store import Store
from .vendor.check_submission import csv_rows

TOPIC_ORDER = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
VERIFY_TABLE = """
CREATE TABLE IF NOT EXISTS verifications (
    review_id TEXT PRIMARY KEY,
    verify_config TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    labels TEXT,
    reason TEXT,
    attempts INTEGER NOT NULL,
    run_id TEXT NOT NULL
);
"""


def verify_item_ok(item, _n_segments):
    return (set(item) == {"i", "t", "n", "s"} and item["t"] in TOPICS and item["n"] in INTENTS
            and type(item["s"]) is int and 1 <= item["s"] <= 5)


def in_sample(review_id, rate, seed=config.VERIFY_SEED):
    digest = hashlib.sha256(f"{seed}:{review_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0x100000000 < rate


class Verifier:
    def __init__(self, run_dir, client, rate=config.VERIFY_RATE, spend_cap=config.SPEND_CAP_USD,
                 sleep=time.sleep, log=print):
        self.run_dir, self.client, self.rate, self.spend_cap, self.sleep, self.log = (
            run_dir, client, rate, spend_cap, sleep, log)
        self.store = Store(run_dir / "state.sqlite")
        self.store.db.executescript(VERIFY_TABLE)
        self.system_prompt = config.VERIFY_PROMPT_FILE.read_text(encoding="utf-8")
        self.schema = json.loads(config.VERIFY_SCHEMA_FILE.read_text(encoding="utf-8"))
        input_path = self.store.get_meta("input_path")
        if not input_path:
            raise SystemExit(f"No enrichment run found in {run_dir}.")
        self.texts = {row["review_id"]: row["review_text"] for row in csv_rows(input_path)}
        self.out = run_dir / "verify"

    def sample(self):
        """Distinct completed originals (not cache copies) selected by the seeded hash, in source order."""
        return [r for r in self.store.records() if r["status"] == "completed" and not r["cache_source_id"]
                and in_sample(r["review_id"], self.rate)]

    def run(self):
        t_start = time.monotonic()
        run_id = datetime_id()
        done = {row[0] for row in self.store.db.execute("SELECT review_id FROM verifications")}
        sample = self.sample()
        todo = [r["review_id"] for r in sample if r["review_id"] not in done]
        self.log(f"[verify {run_id}] rate={self.rate} sample={len(sample)} already_verified={len(sample) - len(todo)}")
        queue = [(todo[i:i + config.MAX_BATCH], False) for i in range(0, len(todo), config.MAX_BATCH)]
        spent, stop_reason = self.store.spent_usd(), None
        with ThreadPoolExecutor(max_workers=1) as pool:
            while queue and stop_reason is None:
                ids, is_retry = queue.pop(0)
                message = "<reviews>\n" + "\n".join(render_review(n, self.texts[rid]) for n, rid in enumerate(ids, 1)) + "\n</reviews>"
                reserved = reservation_usd(self.client.model, self.system_prompt, message)
                if spent + reserved > self.spend_cap:
                    stop_reason = "spend_cap"
                    break
                resp, attempts, permanent = pool.submit(call_with_backoff, self.client, self.system_prompt, message,
                                                        self.schema, self.sleep).result()
                sent = {n: 1 for n in range(1, len(ids) + 1)}
                valid, invalid, error = (validate(resp.text, resp.complete, sent, verify_item_ok)
                                         if resp else ({}, set(), "transient_exhausted"))
                with self.store.transaction() as db:
                    for k, a in enumerate(attempts):
                        final = resp is not None and k == len(attempts) - 1
                        usage = a["usage"] or {"input": 0, "cached_input": 0, "cache_write": 0, "output": 0, "reasoning": 0}
                        spent += cost_usd(self.client.model, usage) if a["usage_known"] else reserved
                        self.store.insert_call(db, {
                            "request_id": a["request_id"], "run_id": run_id, "role": "verify", "phase": "verify",
                            "model": self.client.model, "label_config": config.VERIFY_CONFIG, "review_ids": ids,
                            "outcome": "succeeded" if final and valid else "failed",
                            "error": error if final else a["error"], "attempt": a["attempt"],
                            "is_retry_of_invalid": int(is_retry), "usage_known": int(a["usage_known"]),
                            "input_tokens": usage["input"], "cached_input_tokens": usage["cached_input"],
                            "cache_write_tokens": usage["cache_write"], "output_tokens": usage["output"],
                            "reasoning_tokens": usage["reasoning"],
                            "cost_usd": cost_usd(self.client.model, usage) if a["usage"] else 0.0,
                            "reserved_usd": reserved, "simulated": int(getattr(self.client, "simulated", False)),
                            "started_at": a["started_at"], "duration_s": a["duration_s"]})
                    retry = []
                    for n, rid in enumerate(ids, 1):
                        if n in valid:
                            labels = {"topic": valid[n]["t"], "intent": valid[n]["n"], "severity": valid[n]["s"]}
                            db.execute("INSERT OR REPLACE INTO verifications VALUES (?, ?, 'completed', ?, NULL, ?, ?)",
                                       (rid, config.VERIFY_CONFIG, json.dumps(labels), 2 if is_retry else 1, run_id))
                        elif resp is not None and not is_retry:
                            retry.append(rid)
                        elif resp is not None:
                            db.execute("INSERT OR REPLACE INTO verifications VALUES (?, ?, 'failed', NULL, ?, 2, ?)",
                                       (rid, config.VERIFY_CONFIG, "invalid_output_after_retry", run_id))
                if permanent:
                    stop_reason = f"permanent_error: {permanent}"
                for i in range(0, len(retry), config.RETRY_BATCH):
                    queue.append((retry[i:i + config.RETRY_BATCH], True))
        summary = self.compare()
        summary.update({"run_id": run_id, "stop_reason": stop_reason or "complete",
                        "wall_clock_s": round(time.monotonic() - t_start, 3)})
        (self.out / "summary.json").write_text(json.dumps(summary, indent=1))
        self.log(f"[verify {run_id}] {summary['stop_reason']} | verified {summary['verified']} of {summary['sample_size']} "
                 f"| topic agreement {summary['agreement']['topic']} | disagreements {summary['disagreements']}")
        return summary

    def compare(self):
        """Code-only comparison of enrichment labels with verifier labels on the verified sample."""
        enrich = {r["review_id"]: r for r in self.store.records()}
        rows = self.store.db.execute("SELECT review_id, status, labels, reason FROM verifications ORDER BY review_id").fetchall()
        verified = [(rid, json.loads(labels)) for rid, status, labels, _ in rows if status == "completed"]
        failed = [(rid, reason) for rid, status, _, reason in rows if status == "failed"]
        self.out.mkdir(parents=True, exist_ok=True)
        agree, confusion, disagreements, sev_diff = Counter(), Counter(), [], 0
        with open(self.out / "verifier_predictions.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["review_id", "verify_config", "topic", "intent", "severity"])
            for rid, v in verified:
                w.writerow([rid, config.VERIFY_CONFIG, v["topic"], v["intent"], v["severity"]])
        for rid, v in verified:
            e = enrich[rid]["labels"]
            same = {f: e[f] == v[f] for f in ("topic", "intent", "severity")}
            agree.update(f for f, ok in same.items() if ok)
            agree["all_three"] += all(same.values())
            sev_diff += abs(e["severity"] - v["severity"])
            confusion[(e["topic"], v["topic"])] += 1
            if not all(same.values()):
                disagreements.append({"review_id": rid, "text": self.texts[rid],
                                      **{f"enrich_{f}": e[f] for f in ("topic", "intent", "severity")},
                                      **{f"verify_{f}": v[f] for f in ("topic", "intent", "severity")},
                                      "fields_differing": ",".join(f for f, ok in same.items() if not ok),
                                      "enrich_evidence_quote": e["evidence_quote"]})
        with open(self.out / "disagreements.csv", "w", encoding="utf-8", newline="") as f:
            fields = ["review_id", "fields_differing", "enrich_topic", "verify_topic", "enrich_intent", "verify_intent",
                      "enrich_severity", "verify_severity", "enrich_evidence_quote", "text"]
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(disagreements)
        n = len(verified)
        return {
            "verify_config": config.VERIFY_CONFIG, "enrich_config": config.LABEL_CONFIG,
            "sample_definition": f"distinct completed texts with SHA-256('{config.VERIFY_SEED}:'+review_id) below rate",
            "rate": self.rate, "sample_size": len(self.sample()), "verified": n, "failed": len(failed),
            "agreement": {f: round(agree[f] / n, 4) if n else None for f in ("topic", "intent", "severity", "all_three")},
            "severity_mean_abs_diff": round(sev_diff / n, 4) if n else None,
            "disagreements": len(disagreements),
            "topic_confusion_enrich_vs_verify": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items()) if a != b},
            "simulated": bool(getattr(self.client, "simulated", False)),
        }

    def planted_error_test(self, n=10):
        """SYNTHETIC test on a copy: replace the topic of n verified reviews with a deliberately wrong topic and
        measure how often the verifier's independent label disagrees with the planted one. The real records
        are never modified, and these cases never enter business results."""
        enrich = {r["review_id"]: r for r in self.store.records()}
        rows = self.store.db.execute("SELECT review_id, labels FROM verifications WHERE status='completed' "
                                     "ORDER BY review_id").fetchall()[:n]
        cases = []
        for rid, labels in rows:
            original = enrich[rid]["labels"]["topic"]
            planted = TOPIC_ORDER[(TOPIC_ORDER.index(original) + 4) % len(TOPIC_ORDER)]   # always a different topic
            verifier = json.loads(labels)["topic"]
            cases.append({"review_id": rid, "original_topic": original, "planted_wrong_topic": planted,
                          "verifier_topic": verifier, "caught": verifier != planted})
        result = {"synthetic": True, "exclude_from_business_results": True, "planted": len(cases),
                  "caught": sum(c["caught"] for c in cases), "cases": cases}
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "planted_errors.json").write_text(json.dumps(result, indent=1))
        return result


def datetime_id():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("verify-%Y%m%dT%H%M%S%fZ")

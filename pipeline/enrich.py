"""Enrichment stage: code owns record accounting; the model only labels review language.

Flow: ingest every source row -> quarantine empty texts -> reuse completed results for exact-duplicate texts ->
send one representative per distinct pending text, at most 50 per request -> validate every item -> save the
batch atomically -> re-send invalid items once in smaller requests -> quarantine anything still invalid.

The orchestrator (this module) decides the next step and when to stop. Stop conditions: no work left, spend
cap, batch limit (used for the interruption demo), time cap, Ctrl-C, a permanent provider error, or too many
consecutive transient failures. Every stop saves progress and writes a checkpoint snapshot.
"""

import hashlib
import json
import math
import random
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

from . import config
from .clients import PermanentError, TransientError
from .entities import extract
from .segments import render_review, segments
from .store import Store
from .vendor.check_submission import csv_rows, row_sha, sha

TOPICS = {"access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"}
INTENTS = {"cancellation", "complaint", "request", "praise", "unclear"}
FLAGS = {None, "speculative", "unclear_language", "sarcasm_or_irony", "missing_context", "tie_order"}
SENTIMENTS = {-1, -0.5, 0, 0.5, 1}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def text_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cost_usd(model, usage):
    """Bill ordinary input, cache reads, cache writes and output as mutually exclusive items. `input` is the
    provider's total, which already contains cache reads and writes; reasoning tokens are already inside
    `output`, so they are not added again."""
    r = config.RATES[model]
    ordinary = usage["input"] - usage["cached_input"] - usage["cache_write"]
    return (ordinary * r["input"] + usage["cached_input"] * r["cached_input"]
            + usage["cache_write"] * r["cache_write"] + usage["output"] * r["output"]) / 1e6


def reservation_usd(model, system_prompt, user_message):
    """Worst-case cost of one request, reserved before dispatch: generously estimated input (chars/3, no cache
    discount, priced as a cache write) plus the full output-token cap."""
    r = config.RATES[model]
    est_input = (len(system_prompt) + len(user_message)) / 3
    return (est_input * max(r["input"], r["cache_write"]) + config.MAX_OUTPUT_TOKENS * r["output"]) / 1e6


def enrich_item_ok(item, n_segments):
    return (set(item) == {"i", "t", "n", "s", "m", "q", "p", "f"} and item["t"] in TOPICS and item["n"] in INTENTS
            and type(item["s"]) is int and 1 <= item["s"] <= 5 and item["m"] in SENTIMENTS
            and type(item["q"]) is int and 1 <= item["q"] <= n_segments and type(item["p"]) is bool
            and item["f"] in FLAGS)


def validate(raw_text, complete, sent, item_ok=enrich_item_ok):
    """Check one response against what was sent. `sent` maps request number -> segment count, and `item_ok`
    checks one item. Returns (valid items by number, invalid numbers, error description)."""
    if not complete:
        return {}, set(sent), "incomplete_output"
    try:
        items = json.loads(raw_text)["r"]
        if not isinstance(items, list):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return {}, set(sent), "unparseable_json"
    seen, valid, invalid = {}, {}, set()
    for item in items:
        number = item.get("i") if isinstance(item, dict) else None
        if number not in sent:
            continue                       # unknown number: ignored, cannot be mapped to a review
        seen[number] = seen.get(number, 0) + 1
        (valid.__setitem__(number, item) if item_ok(item, sent[number]) else invalid.add(number))
    for number, count in seen.items():    # a duplicated number is ambiguous: reject every copy
        if count > 1:
            valid.pop(number, None)
            invalid.add(number)
    invalid |= set(sent) - set(seen)       # missing numbers
    errors = []
    if set(sent) - set(seen):
        errors.append("missing_items")
    if any(c > 1 for c in seen.values()):
        errors.append("duplicate_items")
    if invalid - (set(sent) - set(seen)):
        errors.append("invalid_items")
    return valid, invalid, ",".join(errors) or None


def call_with_backoff(client, system_prompt, message, schema, sleep):
    """Runs in a worker thread. Bounded retries with exponential backoff and jitter for transient errors.
    Returns (response or None, one log entry per attempt, permanent error message or None)."""
    attempts = []
    for attempt in range(1, config.TRANSIENT_ATTEMPTS + 1):
        started, t0 = now(), time.monotonic()
        try:
            resp = client.enrich(system_prompt, message, schema, config.MAX_OUTPUT_TOKENS)
            attempts.append({"started_at": started, "duration_s": time.monotonic() - t0, "attempt": attempt,
                             "request_id": resp.request_id, "usage": resp.usage, "usage_known": True, "error": None})
            return resp, attempts, None
        except TransientError as e:
            attempts.append({"started_at": started, "duration_s": time.monotonic() - t0, "attempt": attempt,
                             "request_id": e.request_id, "usage": None, "usage_known": e.usage_known, "error": str(e)})
            if attempt < config.TRANSIENT_ATTEMPTS:
                sleep(config.BACKOFF_BASE_S * 2 ** (attempt - 1) * (0.5 + random.random()))
        except PermanentError as e:
            return None, attempts, str(e)
    return None, attempts, None


def to_labels(item, text):
    segs = segments(text)
    return {"topic": item["t"], "intent": item["n"], "severity": item["s"], "sentiment": item["m"],
            "evidence_quote": segs[item["q"] - 1], "entities": extract(text),
            "needs_review": item["f"] is not None, "review_flag": item["f"], "segment": item["q"],
            "paywall_named_feature": item["p"]}


class Enricher:
    def __init__(self, input_csv, run_dir, client, workers=config.DEFAULT_WORKERS, spend_cap=config.SPEND_CAP_USD,
                 max_batches=None, time_cap_s=None, sleep=time.sleep, log=print):
        self.input_csv, self.run_dir, self.client = input_csv, run_dir, client
        self.workers, self.spend_cap, self.max_batches, self.time_cap_s = workers, spend_cap, max_batches, time_cap_s
        self.sleep, self.log = sleep, log
        self.store = Store(run_dir / "state.sqlite")
        self.system_prompt = config.PROMPT_FILE.read_text(encoding="utf-8")
        self.schema = json.loads(config.SCHEMA_FILE.read_text(encoding="utf-8"))
        self.texts = {}

    # --- setup ----------------------------------------------------------------------------------------
    def ingest(self):
        """Load every source row. New IDs become pending (or quarantined if empty); known IDs must be unchanged."""
        file_sha = sha(self.input_csv)
        stored_sha, stored_config = self.store.get_meta("input_sha256"), self.store.get_meta("label_config")
        if stored_sha and stored_sha != file_sha:
            raise SystemExit(f"{self.run_dir} was created for a different input file; use a new run directory.")
        if stored_config and stored_config != config.LABEL_CONFIG:
            raise SystemExit(f"{self.run_dir} holds results for {stored_config}, not {config.LABEL_CONFIG}. "
                             "Changed settings require new work in a new run directory.")
        known = {r["review_id"]: r["source_sha256"] for r in self.store.records()}
        new = []
        for row_no, row in enumerate(csv_rows(self.input_csv)):
            rid, text, digest = row["review_id"], row["review_text"], row_sha(row)
            self.texts[rid] = text
            if rid in known:
                if known[rid] != digest:
                    raise SystemExit(f"Source row for {rid} changed since it was ingested.")
                continue
            empty = not text.strip()
            new.append((rid, row_no, digest, text_key(text), "quarantined" if empty else "pending",
                        config.QUARANTINE_EMPTY if empty else None))
        with self.store.transaction() as db:
            db.executemany("INSERT INTO records (review_id, row_no, source_sha256, text_key, status, reason) "
                           "VALUES (?, ?, ?, ?, ?, ?)", new)
            self.store.set_meta("input_sha256", file_sha)
            self.store.set_meta("input_path", str(self.input_csv))
            self.store.set_meta("label_config", config.LABEL_CONFIG)
        return len(new)

    def apply_cache(self, db, keys=None):
        """Give pending duplicates the labels of a completed original with identical text (direct provenance), or
        quarantine them if their text's representative was quarantined as invalid."""
        # Driven by originals (one per text), then one indexed UPDATE per text, so a text repeated thousands of
        # times costs one statement rather than a pairwise comparison of every copy.
        where = "" if keys is None else f"AND text_key IN ({','.join('?' * len(keys))})"
        params = [] if keys is None else list(keys)
        originals = {}
        for key, oid, status, labels in db.execute(
                f"SELECT text_key, review_id, status, labels FROM records WHERE cache_source_id IS NULL "
                f"AND (status = 'completed' OR (status = 'quarantined' AND reason = ?)) {where} ORDER BY row_no",
                [config.QUARANTINE_INVALID] + params):
            originals.setdefault(key, (oid, status, labels))   # the earliest original row for each text
        changed = 0
        for key, (oid, status, labels) in originals.items():
            if status == "completed":
                cur = db.execute("UPDATE records SET status='completed', labels=?, cache_source_id=?, run_id=?, phase=? "
                                 "WHERE text_key=? AND status='pending'", (labels, oid, self.run_id, self.phase, key))
            else:
                cur = db.execute("UPDATE records SET status='quarantined', reason=? WHERE text_key=? AND status='pending'",
                                 (f"{config.QUARANTINE_DUP_OF_QUARANTINED}:{oid}", key))
            changed += cur.rowcount
        return changed

    def work_queues(self):
        """One representative per distinct pending text. Items that already failed validation once go to the
        retry queue (smaller requests) so 'retry once' holds across restarts."""
        first, retry, seen = [], [], set()
        for row in self.store.db.execute("SELECT review_id, text_key, attempts FROM records "
                                         "WHERE status='pending' ORDER BY row_no"):
            rid, key, attempts = row
            if key in seen:
                continue
            seen.add(key)
            (retry if attempts >= 1 else first).append(rid)
        return first, retry

    # --- one request ----------------------------------------------------------------------------------
    def build_message(self, ids):
        lines = [render_review(n, self.texts[rid]) for n, rid in enumerate(ids, 1)]
        return "<reviews>\n" + "\n".join(lines) + "\n</reviews>"

    def call_with_backoff(self, ids, message, reserved):
        return call_with_backoff(self.client, self.system_prompt, message, self.schema, self.sleep)

    # --- saving -----------------------------------------------------------------------------------------
    def save(self, ids, is_retry, reserved, resp, attempts):
        """Validate and save one request's outcome in a single transaction. Returns the numbers to retry."""
        sent = {n: len(segments(self.texts[rid])) for n, rid in enumerate(ids, 1)}
        valid, invalid, error = (validate(resp.text, resp.complete, sent) if resp else ({}, set(), "transient_exhausted"))
        to_retry = []
        with self.store.transaction() as db:
            for i, a in enumerate(attempts):
                final = resp is not None and i == len(attempts) - 1
                usage = a["usage"] or {"input": 0, "cached_input": 0, "cache_write": 0, "output": 0, "reasoning": 0}
                # Same rule as Store.spent_usd(): unknown usage (timeouts) counts its full reservation.
                self.spent += cost_usd(self.client.model, usage) if a["usage_known"] else reserved
                self.store.insert_call(db, {
                    "request_id": a["request_id"], "run_id": self.run_id, "role": "enrich", "phase": self.phase,
                    "model": self.client.model, "label_config": config.LABEL_CONFIG, "review_ids": ids,
                    # A response with at least one valid item is a succeeded call (the checker requires every
                    # completed record to trace to a succeeded call); validation problems stay in `error`.
                    "outcome": "succeeded" if final and valid else "failed",
                    "error": error if final else a["error"], "attempt": a["attempt"], "is_retry_of_invalid": int(is_retry),
                    "usage_known": int(a["usage_known"]), "input_tokens": usage["input"],
                    "cached_input_tokens": usage["cached_input"], "cache_write_tokens": usage["cache_write"],
                    "output_tokens": usage["output"],
                    "reasoning_tokens": usage["reasoning"],
                    "cost_usd": cost_usd(self.client.model, usage) if a["usage"] else 0.0,
                    "reserved_usd": reserved, "simulated": int(getattr(self.client, "simulated", False)),
                    "started_at": a["started_at"], "duration_s": a["duration_s"]})
            if resp is None:
                return []                  # transient failure exhausted: items stay pending for a later run
            keys = set()
            for n, rid in enumerate(ids, 1):
                if n in valid:
                    db.execute("UPDATE records SET status='completed', labels=?, attempts=attempts+1, run_id=?, phase=?, "
                               "reason=NULL WHERE review_id=?",
                               (json.dumps(to_labels(valid[n], self.texts[rid])), self.run_id, self.phase, rid))
                elif is_retry:
                    db.execute("UPDATE records SET status='quarantined', reason=?, attempts=attempts+1 WHERE review_id=?",
                               (config.QUARANTINE_INVALID, rid))
                else:
                    db.execute("UPDATE records SET attempts=attempts+1 WHERE review_id=?", (rid,))
                    to_retry.append(rid)
                keys.add(db.execute("SELECT text_key FROM records WHERE review_id=?", (rid,)).fetchone()[0])
            self.apply_cache(db, keys)
        return to_retry

    # --- main loop ------------------------------------------------------------------------------------
    def run(self):
        t_start = time.monotonic()
        new = self.ingest()
        self.phase = "resume" if self.store.completed_ids() else "initial"
        self.spent = self.store.spent_usd()   # kept in memory; updated as each call is saved
        self.run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
        with self.store.transaction() as db:
            db.execute("INSERT INTO runs (run_id, phase, client, started_at) VALUES (?, ?, ?, ?)",
                       (self.run_id, self.phase, self.client.model, now()))
            cached_now = self.apply_cache(db)
        first, retry = self.work_queues()
        self.log(f"[{self.run_id}] phase={self.phase} new_rows={new} cache_reused_now={cached_now} "
                 f"to_send={len(first)} retry_queue={len(retry)} spent_so_far=${self.store.spent_usd():.4f}")
        queue = [(first[i:i + config.MAX_BATCH], False) for i in range(0, len(first), config.MAX_BATCH)]
        queue += [(retry[i:i + config.RETRY_BATCH], True) for i in range(0, len(retry), config.RETRY_BATCH)]

        stop_reason, dispatched, consecutive_failures = None, 0, 0
        in_flight = {}      # future -> (ids, is_retry, reserved)
        pool = ThreadPoolExecutor(max_workers=self.workers)
        try:
            while queue or in_flight:
                while queue and len(in_flight) < self.workers and stop_reason is None:
                    ids, is_retry = queue[0]
                    message = self.build_message(ids)
                    reserved = reservation_usd(self.client.model, self.system_prompt, message)
                    committed = self.spent + sum(v[2] for v in in_flight.values())
                    if committed + reserved > self.spend_cap:
                        stop_reason = "spend_cap"
                    elif self.max_batches is not None and dispatched >= self.max_batches:
                        stop_reason = "max_batches"
                    elif self.time_cap_s is not None and time.monotonic() - t_start > self.time_cap_s:
                        stop_reason = "time_cap"
                    else:
                        queue.pop(0)
                        future = pool.submit(self.call_with_backoff, ids, message, reserved)
                        in_flight[future] = (ids, is_retry, reserved)
                        dispatched += 1
                if not in_flight:
                    break
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    ids, is_retry, reserved = in_flight.pop(future)
                    resp, attempts, permanent = future.result()
                    to_retry = self.save(ids, is_retry, reserved, resp, attempts)
                    if permanent:
                        stop_reason = stop_reason or f"permanent_error: {permanent}"
                    consecutive_failures = consecutive_failures + 1 if resp is None else 0
                    if consecutive_failures >= config.STOP_AFTER_CONSECUTIVE_FAILURES:
                        stop_reason = stop_reason or "too_many_consecutive_failures"
                    for i in range(0, len(to_retry), config.RETRY_BATCH):
                        queue.append((to_retry[i:i + config.RETRY_BATCH], True))
        except KeyboardInterrupt:
            stop_reason = "interrupted"
            for future in list(in_flight):        # let in-flight calls finish and save them; dispatch nothing new
                ids, is_retry, reserved = in_flight.pop(future)
                resp, attempts, _ = future.result()
                self.save(ids, is_retry, reserved, resp, attempts)
        finally:
            pool.shutdown(wait=True)

        stop_reason = stop_reason or "complete"
        wall = time.monotonic() - t_start
        with self.store.transaction() as db:
            db.execute("UPDATE runs SET ended_at=?, stop_reason=?, wall_clock_s=? WHERE run_id=?",
                       (now(), stop_reason, wall, self.run_id))
        summary = {"run_id": self.run_id, "phase": self.phase, "stop_reason": stop_reason,
                   "wall_clock_s": round(wall, 3), "requests_dispatched": dispatched,
                   "counts": self.store.count_by_status(), "spent_usd": round(self.store.spent_usd(), 6)}
        checkpoint = self.run_dir / "checkpoints" / f"{self.run_id}_{stop_reason.split(':')[0]}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({**summary, "label_config": config.LABEL_CONFIG,
                                          "completed_ids": self.store.completed_ids()}, indent=1))
        self.log(f"[{self.run_id}] stopped: {stop_reason} | {summary['counts']} | spent ${summary['spent_usd']:.4f} "
                 f"| {wall:.1f}s | checkpoint {checkpoint.name}")
        return summary

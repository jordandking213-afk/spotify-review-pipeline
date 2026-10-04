"""Durable run state in SQLite. Every batch's results and its call log are written in one transaction, so an
interruption can never leave half a batch saved, and a restart sees exactly what was completed."""

import json
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records (
    review_id TEXT PRIMARY KEY,
    row_no INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    text_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'quarantined')),
    reason TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    labels TEXT,
    cache_source_id TEXT,
    run_id TEXT,
    phase TEXT
);
CREATE INDEX IF NOT EXISTS records_text ON records (text_key, status);
CREATE INDEX IF NOT EXISTS records_status ON records (status);
CREATE TABLE IF NOT EXISTS calls (
    request_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    role TEXT NOT NULL,
    phase TEXT NOT NULL,
    model TEXT NOT NULL,
    label_config TEXT NOT NULL,
    review_ids TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('succeeded', 'failed')),
    error TEXT,
    attempt INTEGER NOT NULL,
    is_retry_of_invalid INTEGER NOT NULL DEFAULT 0,
    usage_known INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    cached_input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    reserved_usd REAL NOT NULL,
    simulated INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    duration_s REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    client TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    stop_reason TEXT,
    wall_clock_s REAL
);
"""


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)  # explicit transactions below
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # --- meta -----------------------------------------------------------------------------------------
    def get_meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    # --- records --------------------------------------------------------------------------------------
    def count_by_status(self):
        return dict(self.db.execute("SELECT status, COUNT(*) FROM records GROUP BY status").fetchall())

    def completed_ids(self):
        return [r[0] for r in self.db.execute("SELECT review_id FROM records WHERE status = 'completed' ORDER BY row_no")]

    def records(self):
        cur = self.db.execute("SELECT review_id, row_no, source_sha256, text_key, status, reason, attempts, labels, "
                              "cache_source_id, run_id, phase FROM records ORDER BY row_no")
        cols = [d[0] for d in cur.description]
        for row in cur:
            rec = dict(zip(cols, row))
            rec["labels"] = json.loads(rec["labels"]) if rec["labels"] else None
            yield rec

    # --- calls ----------------------------------------------------------------------------------------
    def spent_usd(self):
        """Money already committed: actual cost of known-usage calls, plus the full reservation for calls whose
        usage is unknown (e.g. timeouts), because the provider may still have billed them."""
        row = self.db.execute("SELECT COALESCE(SUM(CASE WHEN usage_known THEN cost_usd ELSE reserved_usd END), 0) "
                              "FROM calls").fetchone()
        return row[0]

    def insert_call(self, conn, call):
        conn.execute(
            "INSERT INTO calls (request_id, run_id, role, phase, model, label_config, review_ids, outcome, error, attempt, "
            "is_retry_of_invalid, usage_known, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens, "
            "cost_usd, reserved_usd, simulated, started_at, duration_s) VALUES "
            "(:request_id, :run_id, :role, :phase, :model, :label_config, :review_ids, :outcome, :error, :attempt, "
            ":is_retry_of_invalid, :usage_known, :input_tokens, :cached_input_tokens, :output_tokens, :reasoning_tokens, "
            ":cost_usd, :reserved_usd, :simulated, :started_at, :duration_s)",
            {**call, "review_ids": json.dumps(call["review_ids"])})

    def calls(self):
        cur = self.db.execute("SELECT * FROM calls ORDER BY started_at, request_id")
        cols = [d[0] for d in cur.description]
        for row in cur:
            call = dict(zip(cols, row))
            call["review_ids"] = json.loads(call["review_ids"])
            yield call

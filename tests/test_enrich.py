"""Safeguard tests for the enrichment stage, using the fake model only ($0, no network).

Fixture reviews are SYNTHETIC (written for these tests), not dataset rows, and never enter business results.
Run:  python3 -m unittest discover -s tests -v
"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import config
from pipeline.clients import ALWAYS_INVALID_MARKER, FakeClient
from pipeline.enrich import Enricher
from pipeline.segments import segments

PHRASES = [
    "I can't log in to my account. Please fix it", "Too many ads between songs", "The app keeps crashing",
    "Downloaded songs vanish when I go offline", "Lyrics are missing for many songs", "Why is skipping premium only",
    "Customer support never answered me", "Great app, love the playlists", "Please add a sleep timer",
    "Uninstalling, switching to another service", "Boycott boycott boycott",
    "First sentence here! Second sentence there? Third one.\nNew line part",
]
FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")


def write_fixture(path, extra=()):
    rows = []
    for i in range(130):
        rows.append(f"{PHRASES[i % len(PHRASES)]} (synthetic case {i})")
    rows += ["Good"] * 10 + ["", ""] + list(extra)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        for i, text in enumerate(rows):
            w.writerow([f"syn-{i:04d}", text, str(1 + i % 5), "0", "" if i % 3 else "8.8.0", f"2023-01-{1 + i % 28:02d} 10:00:00"])
    return len(rows)


class EnrichTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.csv = self.dir / "fixture.csv"
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def enricher(self, client, run="run", **kw):
        return Enricher(self.csv, self.dir / run, client, sleep=self.sleeps.append, log=lambda *_: None, **kw)

    def records(self, e):
        return {r["review_id"]: r for r in e.store.records()}

    def assert_invariants(self, e):
        """Properties the grading checker relies on, for any run state."""
        recs, calls = self.records(e), list(e.store.calls())
        succeeded = {rid for c in calls if c["outcome"] == "succeeded" and c["role"] == "enrich"
                     and c["label_config"] == config.LABEL_CONFIG for rid in c["review_ids"]}
        for c in calls:
            self.assertLessEqual(len(c["review_ids"]), 50)
            self.assertEqual(len(c["review_ids"]), len(set(c["review_ids"])))
        for rid, r in recs.items():
            if r["status"] == "completed":
                text = e.texts[rid]
                self.assertIn(r["labels"]["evidence_quote"], text)
                if r["cache_source_id"]:
                    original = recs[r["cache_source_id"]]
                    self.assertIsNone(original["cache_source_id"], "cache chains are not allowed")
                    self.assertEqual(e.texts[r["cache_source_id"]], text)
                    self.assertEqual(original["labels"], r["labels"])
                else:
                    self.assertIn(rid, succeeded, "completed record without a succeeded call")
            if r["status"] == "quarantined":
                self.assertTrue(r["reason"])

    def test_happy_path(self):
        n = write_fixture(self.csv)
        e = self.enricher(FakeClient())
        summary = e.run()
        self.assertEqual(summary["stop_reason"], "complete")
        self.assertEqual(summary["counts"], {"completed": n - 2, "quarantined": 2})
        recs = self.records(e)
        empties = [r for r in recs.values() if not e.texts[r["review_id"]]]
        self.assertTrue(all(r["reason"] == "empty_review_text" for r in empties))
        good = [r for r in recs.values() if e.texts[r["review_id"]] == "Good"]
        self.assertEqual(sum(r["cache_source_id"] is None for r in good), 1, "only one 'Good' is sent")
        sent = [rid for c in e.store.calls() for rid in c["review_ids"]]
        self.assertEqual(len(sent), 131, "130 distinct synthetic texts + one 'Good'")
        self.assertTrue(all(c["simulated"] == 1 for c in e.store.calls()))
        self.assert_invariants(e)

    def test_multisentence_quote_is_exact_segment(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient())
        e.run()
        rec = self.records(e)["syn-0011"]
        self.assertEqual(rec["labels"]["evidence_quote"], segments(e.texts["syn-0011"])[0])
        self.assertEqual(len(segments(e.texts["syn-0011"])), 4)

    def test_invalid_items_retried_once_then_quarantined(self):
        bad = f"Always broken review {ALWAYS_INVALID_MARKER}"
        write_fixture(self.csv, extra=[bad, bad])
        e = self.enricher(FakeClient(behaviors=["drop_one", "bad_segment", "dup_one"]))
        summary = e.run()
        recs = self.records(e)
        bad_ids = [rid for rid in recs if e.texts[rid] == bad]
        self.assertEqual(recs[bad_ids[0]]["status"], "quarantined")
        self.assertEqual(recs[bad_ids[0]]["reason"], config.QUARANTINE_INVALID)
        self.assertEqual(recs[bad_ids[0]]["attempts"], 2, "exactly one retry")
        self.assertTrue(recs[bad_ids[1]]["reason"].startswith(config.QUARANTINE_DUP_OF_QUARANTINED))
        self.assertEqual(summary["counts"]["quarantined"], 4, "2 empty + marker + its duplicate")
        retries = [c for c in e.store.calls() if c["is_retry_of_invalid"]]
        self.assertTrue(retries and all(len(c["review_ids"]) <= config.RETRY_BATCH for c in retries))
        self.assert_invariants(e)

    def test_unparseable_and_truncated_output(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient(behaviors=["bad_json", "truncated"]))
        summary = e.run()
        self.assertEqual(summary["counts"].get("quarantined"), 2, "only the empty texts; the rest recovered on retry")
        errors = [c["error"] for c in e.store.calls() if c["outcome"] == "failed"]
        self.assertIn("unparseable_json", errors)
        self.assertIn("incomplete_output", errors)
        self.assert_invariants(e)

    def test_transient_errors_back_off_and_recover(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient(behaviors=["rate_limit", "server_error"]))
        summary = e.run()
        self.assertEqual(summary["stop_reason"], "complete")
        self.assertEqual(len(self.sleeps), 2)
        self.assertLess(self.sleeps[0], self.sleeps[1] * 2, "backoff grows")
        failed = [c for c in e.store.calls() if c["outcome"] == "failed"]
        self.assertEqual(len(failed), 2)
        self.assert_invariants(e)

    def test_timeouts_count_reserved_spend_and_leave_items_pending(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient(behaviors=["timeout"] * 3), max_batches=1)
        summary = e.run()
        self.assertEqual(summary["counts"].get("completed", 0), 0)
        timeouts = [c for c in e.store.calls() if c["usage_known"] == 0]
        self.assertEqual(len(timeouts), 3)
        self.assertAlmostEqual(e.store.spent_usd(), sum(c["reserved_usd"] for c in timeouts))

    def test_spend_cap_stops_admission(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient(), spend_cap=0.0025)
        summary = e.run()
        self.assertEqual(summary["stop_reason"], "spend_cap")
        self.assertGreater(summary["counts"]["pending"], 0)
        self.assertLessEqual(e.store.spent_usd(), 0.0025)

    def test_permanent_error_stops_run(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient(behaviors=["no_credit"]))
        summary = e.run()
        self.assertTrue(summary["stop_reason"].startswith("permanent_error"))

    def test_interrupt_then_resume_without_relabeling(self):
        write_fixture(self.csv)
        first = self.enricher(FakeClient(), max_batches=1).run()
        self.assertEqual(first["stop_reason"], "max_batches")
        before = set(json.loads(next((self.dir / "run" / "checkpoints").glob("*max_batches.json")).read_text())["completed_ids"])
        e = self.enricher(FakeClient())
        second = e.run()
        self.assertEqual(second["phase"], "resume")
        resume_calls = [c for c in e.store.calls() if c["phase"] == "resume"]
        self.assertTrue(resume_calls)
        self.assertFalse(before & {rid for c in resume_calls for rid in c["review_ids"]}, "no completed ID re-sent")
        after = set(e.store.completed_ids())
        self.assertTrue(before < after)
        self.assert_invariants(e)

    def test_changed_settings_refused(self):
        write_fixture(self.csv)
        e = self.enricher(FakeClient(), max_batches=1)
        e.run()
        e.store.set_meta("label_config", "something-else")
        with self.assertRaises(SystemExit):
            self.enricher(FakeClient()).run()

    def test_two_workers_match_one_worker(self):
        write_fixture(self.csv)
        one = self.enricher(FakeClient(), run="one").run()
        two = self.enricher(FakeClient(), run="two", workers=2).run()
        self.assertEqual(one["counts"], two["counts"])


if __name__ == "__main__":
    unittest.main()

"""Grouping-stage tests with the fake model only ($0). Fixture reviews are synthetic."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import config
from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from pipeline.group import Grouper
from pipeline.issues import RULES, issue_for
from tests.test_enrich import write_fixture


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_fixture(self.dir / "fixture.csv")
        self.quiet = dict(sleep=lambda s: None, log=lambda *a: None)
        self.enricher = Enricher(self.dir / "fixture.csv", self.dir / "run", FakeClient(), **self.quiet)
        self.enricher.run()

    def tearDown(self):
        self.tmp.cleanup()

    def grouper(self, client, **kw):
        return Grouper(self.dir / "run", client, **self.quiet, **kw)

    def membership(self):
        return list(csv.DictReader(open(self.dir / "run" / "group" / "membership.csv")))

    def test_every_complaint_in_exactly_one_issue_and_nothing_else(self):
        self.grouper(FakeClient()).run()
        rows = self.membership()
        recs = {r["review_id"]: r for r in self.enricher.store.records()}
        complaints = {rid for rid, r in recs.items() if r["status"] == "completed"
                      and r["labels"]["intent"] in ("complaint", "cancellation")}
        ids = [r["review_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), "one issue per review")
        self.assertEqual(set(ids), complaints, "all complaints/cancellations, nothing else")
        cache_copies = {rid for rid in complaints if recs[rid]["cache_source_id"]}
        self.assertTrue(cache_copies <= set(ids), "duplicate-text copies keep their own membership row")

    def test_rules_are_deterministic_and_total(self):
        for topic in RULES:
            issue, _ = issue_for({"topic": topic, "entities": [], "paywall_named_feature": False})
            self.assertEqual(issue, f"{topic}.general")
        self.assertEqual(issue_for({"topic": "billing", "entities": ["premium", "lyrics"],
                                    "paywall_named_feature": True})[0], "billing.paywall_named_feature")
        self.assertEqual(issue_for({"topic": "billing", "entities": ["premium"],
                                    "paywall_named_feature": False})[0], "billing.premium_other")

    def test_names_from_bounded_pack_with_one_logged_call(self):
        summary = self.grouper(FakeClient()).run()
        self.assertEqual(summary["model_calls"], 1)
        pack = json.loads((self.dir / "run" / "group" / "evidence_pack.json").read_text())["issues"]
        self.assertTrue(all(len(p["examples"]) <= config.GROUP_EXAMPLES_PER_ISSUE for p in pack.values()))
        issues = json.loads((self.dir / "run" / "group" / "issues.json").read_text())["issues"]
        for issue in issues:
            allowed = {e["review_id"] for e in pack[issue["issue_id"]]["examples"]}
            self.assertTrue(set(issue["example_review_ids"]) <= allowed)
            self.assertEqual(issue["name_source"], "model")
        calls = [c for c in self.enricher.store.calls() if c["role"] == "group"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["outcome"], "succeeded")

    def test_invalid_names_retry_once_then_fall_back_visibly(self):
        self.grouper(FakeClient(behaviors=["bad_names", "bad_names"])).run()
        issues = json.loads((self.dir / "run" / "group" / "issues.json").read_text())["issues"]
        fallback = [i for i in issues if i["name_source"] == "rule_fallback"]
        self.assertEqual(len(fallback), 1, "only the issue with invalid output falls back")
        self.assertFalse(any(ch.isdigit() for i in issues if i["name_source"] == "model" for ch in i["description"]))
        calls = [c for c in self.enricher.store.calls() if c["role"] == "group"]
        self.assertEqual(len(calls), 2, "one retry, no more")

    def test_warm_rerun_reuses_names_with_zero_calls(self):
        self.grouper(FakeClient()).run()
        before = self.membership()
        again = FakeClient()
        summary = self.grouper(again).run()
        self.assertEqual(again.calls, 0)
        self.assertEqual(summary["naming_source"], "reused_saved_names")
        self.assertEqual(before, self.membership(), "identical membership")


class GroupNameDigitTest(unittest.TestCase):
    def test_issue_names_with_digits_are_rejected(self):
        from pipeline.group import validate_names
        pack = {"a.b": {"examples": [{"review_id": "r1", "quote": "q"}]}}
        bad = json.dumps({"issues": [{"id": "a.b", "name": "Top 10 crashes", "description": "Crashes.", "examples": ["r1"]}]})
        good = json.dumps({"issues": [{"id": "a.b", "name": "Crashes", "description": "Crashes.", "examples": ["r1"]}]})
        self.assertEqual(validate_names(bad, True, pack)[0], {})
        self.assertIn("a.b", validate_names(good, True, pack)[0])


if __name__ == "__main__":
    unittest.main()
